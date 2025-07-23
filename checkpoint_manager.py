#!/usr/bin/env python3
"""
CheckpointManager - 进度跟踪和恢复功能管理器
支持原子文件操作，防止检查点损坏
"""

import os
import json
import time
import asyncio
import aiofiles
from typing import Set, Tuple, Dict, Any, Optional
from colorama import Fore, Style


class CheckpointManager:
    """
    检查点管理器
    
    特性:
    - 原子文件操作防止数据损坏
    - 跟踪已完成和失败的文件
    - 支持进度百分比计算
    - 定期自动保存机制
    """
    
    def __init__(self, checkpoint_file: str, auto_save_interval: int = 100):
        """
        初始化检查点管理器
        
        Args:
            checkpoint_file: 检查点文件路径
            auto_save_interval: 自动保存间隔（处理文件数）
        """
        self.checkpoint_file = checkpoint_file
        self.auto_save_interval = auto_save_interval
        self.completed_files: Set[str] = set()
        self.failed_files: Set[str] = set()
        self.total_files = 0
        self.last_save_count = 0
        self.start_time = time.time()
        self.lock = asyncio.Lock()
        
    async def load_checkpoint(self) -> Tuple[Set[str], Set[str]]:
        """
        从检查点文件加载进度状态
        
        Returns:
            Tuple[Set[str], Set[str]]: (已完成文件集合, 失败文件集合)
        """
        if not os.path.exists(self.checkpoint_file):
            print(f"{Fore.YELLOW}📋 未找到检查点文件，从头开始处理{Style.RESET_ALL}")
            return set(), set()
            
        try:
            async with aiofiles.open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                state = json.loads(content)
                
            self.completed_files = set(state.get('completed', []))
            self.failed_files = set(state.get('failed', []))
            self.total_files = state.get('total_files', 0)
            self.start_time = state.get('start_time', time.time())
            
            completed_count = len(self.completed_files)
            failed_count = len(self.failed_files)
            
            print(f"{Fore.GREEN}📋 检查点加载成功{Style.RESET_ALL}")
            print(f"  已完成: {completed_count:,} 个文件")
            print(f"  失败: {failed_count:,} 个文件")
            if self.total_files > 0:
                progress = (completed_count + failed_count) / self.total_files * 100
                print(f"  进度: {progress:.1f}%")
                
            return self.completed_files.copy(), self.failed_files.copy()
            
        except Exception as e:
            print(f"{Fore.RED}❌ 检查点文件损坏，从头开始: {e}{Style.RESET_ALL}")
            return set(), set()
    
    async def save_checkpoint(self, completed: Set[str], failed: Set[str], total_files: int = None) -> None:
        """
        保存当前进度到检查点文件（原子操作）
        
        Args:
            completed: 已完成文件集合
            failed: 失败文件集合
            total_files: 总文件数（可选）
        """
        async with self.lock:
            self.completed_files = completed.copy()
            self.failed_files = failed.copy()
            if total_files is not None:
                self.total_files = total_files
                
            state = {
                'completed': list(self.completed_files),
                'failed': list(self.failed_files),
                'total_files': self.total_files,
                'start_time': self.start_time,
                'last_update': time.time(),
                'version': '1.0'
            }
            
            # 原子写入：先写临时文件，再重命名
            temp_file = f"{self.checkpoint_file}.tmp"
            try:
                # 确保目录存在
                os.makedirs(os.path.dirname(self.checkpoint_file), exist_ok=True)
                
                async with aiofiles.open(temp_file, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(state, ensure_ascii=False, indent=2))
                
                # 原子重命名（Windows兼容性处理）
                if os.path.exists(self.checkpoint_file):
                    os.remove(self.checkpoint_file)
                os.rename(temp_file, self.checkpoint_file)
                
            except Exception as e:
                # 清理临时文件
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
                raise e
    
    async def update_progress(self, file_path: str, status: str, auto_save: bool = True) -> None:
        """
        更新单个文件的处理状态
        
        Args:
            file_path: 文件路径
            status: 状态 ('completed' 或 'failed')
            auto_save: 是否触发自动保存检查
        """
        async with self.lock:
            if status == 'completed':
                self.completed_files.add(file_path)
                self.failed_files.discard(file_path)  # 从失败列表中移除（如果存在）
            elif status == 'failed':
                self.failed_files.add(file_path)
                self.completed_files.discard(file_path)  # 从完成列表中移除（如果存在）
            
            # 检查是否需要自动保存
            if auto_save:
                current_count = len(self.completed_files) + len(self.failed_files)
                if current_count - self.last_save_count >= self.auto_save_interval:
                    await self.save_checkpoint(self.completed_files, self.failed_files)
                    self.last_save_count = current_count
    
    def get_progress_stats(self) -> Dict[str, Any]:
        """
        获取当前进度统计信息
        
        Returns:
            Dict: 包含进度统计的字典
        """
        completed_count = len(self.completed_files)
        failed_count = len(self.failed_files)
        processed_count = completed_count + failed_count
        
        stats = {
            'completed_count': completed_count,
            'failed_count': failed_count,
            'processed_count': processed_count,
            'total_files': self.total_files,
            'remaining_count': max(0, self.total_files - processed_count),
            'success_rate': (completed_count / processed_count * 100) if processed_count > 0 else 0,
            'progress_percentage': (processed_count / self.total_files * 100) if self.total_files > 0 else 0,
            'elapsed_time': time.time() - self.start_time
        }
        
        # 估算剩余时间
        if processed_count > 0 and stats['remaining_count'] > 0:
            avg_time_per_file = stats['elapsed_time'] / processed_count
            stats['estimated_remaining_time'] = avg_time_per_file * stats['remaining_count']
        else:
            stats['estimated_remaining_time'] = 0
            
        return stats
    
    def should_skip_file(self, file_path: str, force_rerun: bool = False) -> bool:
        """
        检查文件是否应该跳过处理
        
        Args:
            file_path: 文件路径
            force_rerun: 是否强制重新处理
            
        Returns:
            bool: True表示应该跳过
        """
        if force_rerun:
            return False
            
        # 如果文件已经成功处理过，跳过
        return file_path in self.completed_files
    
    async def clear_checkpoint(self) -> None:
        """清除检查点文件"""
        if os.path.exists(self.checkpoint_file):
            try:
                os.remove(self.checkpoint_file)
                print(f"{Fore.YELLOW}🗑️ 检查点文件已清除{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}❌ 清除检查点文件失败: {e}{Style.RESET_ALL}")
        
        # 重置内部状态
        self.completed_files.clear()
        self.failed_files.clear()
        self.total_files = 0
        self.last_save_count = 0
        self.start_time = time.time()
    
    def print_progress_summary(self) -> None:
        """打印进度摘要"""
        stats = self.get_progress_stats()
        
        print(f"\n{Fore.CYAN}📊 处理进度摘要{Style.RESET_ALL}")
        print(f"  ✅ 已完成: {stats['completed_count']:,} 个文件")
        print(f"  ❌ 失败: {stats['failed_count']:,} 个文件")
        print(f"  📈 成功率: {stats['success_rate']:.1f}%")
        print(f"  🎯 总进度: {stats['progress_percentage']:.1f}% ({stats['processed_count']:,}/{stats['total_files']:,})")
        
        if stats['estimated_remaining_time'] > 0:
            remaining_hours = stats['estimated_remaining_time'] / 3600
            if remaining_hours > 1:
                print(f"  ⏱️ 预计剩余时间: {remaining_hours:.1f} 小时")
            else:
                remaining_minutes = stats['estimated_remaining_time'] / 60
                print(f"  ⏱️ 预计剩余时间: {remaining_minutes:.1f} 分钟")
