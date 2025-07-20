#!/usr/bin/env python3
"""
BatchTaskPool - 高性能任务池管理器
支持50,000并发任务，72小时超时，自动故障恢复
"""

import asyncio
import traceback
import time
from typing import Dict, Any, Tuple, Optional


class BatchTaskPool:
    """
    批量任务池管理器
    
    特性:
    - 支持最大50,000并发任务
    - 72小时任务超时
    - 自动故障恢复和槽位释放
    - 线程安全的任务管理
    """
    
    def __init__(self, max_concurrent: int = 50000):
        """
        初始化任务池
        
        Args:
            max_concurrent: 最大并发任务数，默认50,000
        """
        self.max_concurrent = max_concurrent
        self.task_timeout = 72 * 3600  # 72小时超时
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.task_semaphore = asyncio.Semaphore(max_concurrent)
        self.task_counter = 0
        self.completed_count = 0
        self.failed_count = 0
        self.timeout_count = 0
        self.lock = asyncio.Lock()
        
    async def submit_task(self, coro, task_data: Dict[str, Any]) -> Tuple[str, asyncio.Task]:
        """
        提交任务到池中，如果池满则等待空闲槽位
        
        Args:
            coro: 要执行的协程
            task_data: 任务相关数据，必须包含'path'字段
            
        Returns:
            Tuple[task_id, asyncio.Task]: 任务ID和Task对象
        """
        # 等待空闲槽位
        await self.task_semaphore.acquire()
        
        # 生成唯一任务ID
        task_id = f"task_{self.task_counter}"
        self.task_counter += 1
        
        # 包装任务以处理超时和异常
        wrapped_task = asyncio.create_task(
            self._execute_with_timeout(coro, task_id, task_data)
        )
        
        # 线程安全地添加到活跃任务列表
        async with self.lock:
            self.active_tasks[task_id] = wrapped_task
            
        return task_id, wrapped_task
    
    async def _execute_with_timeout(self, coro, task_id: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行任务并处理超时和异常，确保槽位释放
        
        Args:
            coro: 要执行的协程
            task_id: 任务ID
            task_data: 任务数据
            
        Returns:
            Dict: 任务执行结果
        """
        try:
            # 设置72小时超时执行任务
            result = await asyncio.wait_for(coro, timeout=self.task_timeout)
            self.completed_count += 1
            return result
            
        except asyncio.TimeoutError:
            self.timeout_count += 1
            self.failed_count += 1
            return {
                "status": "timeout_error",
                "path": task_data.get("path", "unknown"),
                "error": f"任务超时 (超过 {self.task_timeout} 秒)",
                "task_id": task_id
            }
            
        except Exception as e:
            self.failed_count += 1
            return {
                "status": "task_error",
                "path": task_data.get("path", "unknown"),
                "error": str(e),
                "traceback": traceback.format_exc(),
                "task_id": task_id
            }
            
        finally:
            # 确保清理任务并释放槽位
            await self._cleanup_task(task_id)
    
    async def _cleanup_task(self, task_id: str):
        """
        清理任务并释放槽位
        
        Args:
            task_id: 要清理的任务ID
        """
        # 线程安全地从活跃任务中移除
        async with self.lock:
            self.active_tasks.pop(task_id, None)
        
        # 释放信号量槽位
        self.task_semaphore.release()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取任务池统计信息
        
        Returns:
            Dict: 包含各种统计数据的字典
        """
        return {
            "max_concurrent": self.max_concurrent,
            "active_tasks": len(self.active_tasks),
            "available_slots": self.task_semaphore._value,
            "total_submitted": self.task_counter,
            "completed": self.completed_count,
            "failed": self.failed_count,
            "timeout": self.timeout_count,
            "success_rate": self.completed_count / max(self.task_counter, 1) * 100
        }
    
    async def wait_for_completion(self, check_interval: float = 60.0):
        """
        等待所有活跃任务完成
        
        Args:
            check_interval: 检查间隔（秒）
        """
        while True:
            async with self.lock:
                active_count = len(self.active_tasks)
            
            if active_count == 0:
                break
                
            print(f"等待 {active_count} 个任务完成...")
            await asyncio.sleep(check_interval)
    
    async def shutdown(self):
        """
        优雅关闭任务池，取消所有活跃任务
        """
        async with self.lock:
            tasks_to_cancel = list(self.active_tasks.values())
        
        if tasks_to_cancel:
            print(f"正在取消 {len(tasks_to_cancel)} 个活跃任务...")
            for task in tasks_to_cancel:
                task.cancel()
            
            # 等待所有任务取消完成
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            
        print("任务池已关闭")
