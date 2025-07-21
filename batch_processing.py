#!/usr/bin/env python3
"""
批量推理主处理逻辑
集成任务池和分析器，实现高性能批量图片处理
"""

import os
import json
import asyncio
import aiohttp
import aiofiles
import time
import traceback
from typing import List, Dict, Any
from tqdm.asyncio import tqdm

# 导入自定义模块
from batch_task_pool import BatchTaskPool
from batch_image_quality_analyzer import BatchImageQualityAnalyzer
from vlm_common import (
    validate_batch_config, find_images, CostCalculator,
    quick_validate_image, Fore, Style
)


async def process_single_image(analyzer, session, img_path, force_rerun, debug_mode, cost_calculator):
    """
    处理单个图片的异步函数
    保持与在线推理相同的处理逻辑
    
    Args:
        analyzer: BatchImageQualityAnalyzer实例
        session: aiohttp会话对象
        img_path: 图片文件路径
        force_rerun: 是否强制重新处理
        debug_mode: 是否启用调试模式
        cost_calculator: 成本计算器实例
        
    Returns:
        Dict: 处理结果
    """
    json_path = os.path.splitext(img_path)[0] + '.json'
    
    # 检查是否需要重新处理
    if os.path.exists(json_path) and not force_rerun:
        return {"status": "skipped", "path": img_path}
    
    # 分析图片
    result = await analyzer.analyze_image(session, img_path)
    
    if result and "error" not in result:
        try:
            # 统计API使用成本
            if "api_usage" in result:
                cost_calculator.add_usage(result["api_usage"])
            
            # 异步保存结果
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            async with aiofiles.open(json_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(result, ensure_ascii=False, indent=2))
            return {"status": "success", "path": img_path, "result": result}
        except Exception as e:
            return {
                "status": "save_error", 
                "path": img_path, 
                "error": str(e),
                "result": result
            }
    else:
        # 即使失败也要统计请求数
        cost_calculator.total_requests += 1
        return {
            "status": "analysis_error", 
            "path": img_path, 
            "error": result
        }


async def collect_completed_tasks(pending_tasks: Dict[str, Dict], results: List[Dict]):
    """
    收集已完成的任务
    
    Args:
        pending_tasks: 待处理任务字典
        results: 结果列表
    """
    completed_task_ids = []
    for task_id, task_info in pending_tasks.items():
        if task_info["task"].done():
            try:
                result = await task_info["task"]
                results.append(result)
            except Exception as e:
                results.append({
                    "status": "collection_error",
                    "path": task_info["data"]["path"],
                    "error": str(e)
                })
            completed_task_ids.append(task_id)
    
    # 移除已完成的任务
    for task_id in completed_task_ids:
        pending_tasks.pop(task_id)


async def wait_all_tasks(pending_tasks: Dict[str, Dict], results: List[Dict]):
    """
    等待所有剩余任务完成
    
    Args:
        pending_tasks: 待处理任务字典
        results: 结果列表
    """
    if not pending_tasks:
        return
    
    remaining_tasks = [task_info["task"] for task_info in pending_tasks.values()]
    completed_results = await asyncio.gather(*remaining_tasks, return_exceptions=True)
    
    for i, result in enumerate(completed_results):
        if isinstance(result, Exception):
            task_data = list(pending_tasks.values())[i]["data"]
            results.append({
                "status": "gather_error",
                "path": task_data["path"],
                "error": str(result)
            })
        else:
            results.append(result)


async def process_images_batch(root_dir: str, force_rerun: bool = False, debug: bool = False, concurrent_limit: int = None) -> int:
    """
    批量处理图片的主函数
    
    Args:
        root_dir: 图片根目录
        force_rerun: 是否强制重新处理
        debug: 是否启用调试模式
        concurrent_limit: 并发限制数量
        
    Returns:
        int: 退出代码，0表示成功
    """
    try:
        start_time = time.time()
        
        # 验证配置
        validate_batch_config()
        
        # 获取并发限制
        concurrent_limit = concurrent_limit or int(os.getenv('VLM_BATCH_CONCURRENT_LIMIT', '50000'))
        
        # 初始化组件
        task_pool = BatchTaskPool(max_concurrent=concurrent_limit)
        analyzer = BatchImageQualityAnalyzer()
        cost_calculator = CostCalculator()
        
        # 查找待处理图片
        all_images = find_images(root_dir)

        # 预过滤：快速验证图片有效性，避免处理无效图片
        print(f"Found {len(all_images)} images, validating...")
        valid_images = []
        invalid_count = 0
        validation_stats = {"too_small": 0, "invalid_dimensions": 0, "error": 0, "valid": 0}

        for img_path in all_images:
            validation = quick_validate_image(img_path, max_size=2000, min_size=100)
            if validation["valid"]:
                valid_images.append(img_path)
                validation_stats["valid"] += 1
            else:
                invalid_count += 1
                reason = validation["reason"].split(":")[0]  # 提取主要原因
                validation_stats[reason] = validation_stats.get(reason, 0) + 1
                if debug:
                    print(f"{Fore.YELLOW}跳过无效图片: {os.path.basename(img_path)} - {validation['reason']}{Style.RESET_ALL}")

        print(f"Image validation completed:")
        print(f"  Valid: {validation_stats['valid']}")
        print(f"  Invalid: {invalid_count} (too_small: {validation_stats.get('too_small', 0)}, "
              f"invalid_dimensions: {validation_stats.get('invalid_dimensions', 0)}, "
              f"errors: {validation_stats.get('error', 0)})")

        # 过滤已处理的图片
        tasks_to_process = [
            img_path for img_path in valid_images
            if not os.path.exists(os.path.splitext(img_path)[0] + '.json') or force_rerun
        ]

        if not tasks_to_process:
            print("All valid images already processed.")
            return 0

        # 显示处理统计
        print("Processing Statistics:")
        print(f"  Directory: {root_dir}")
        print(f"  Images found: {len(all_images)}")
        print(f"  Valid images: {len(valid_images)}")
        print(f"  Invalid images: {invalid_count}")
        print(f"  To process: {len(tasks_to_process)}")
        print(f"  Concurrent limit: {concurrent_limit}")
        
        # 配置连接池
        connector = aiohttp.TCPConnector(
            limit=0,  # 无限制
            limit_per_host=0,  # 无限制
            keepalive_timeout=3600,  # 1小时保活
            enable_cleanup_closed=True
        )
        timeout = aiohttp.ClientTimeout(total=72*3600, connect=30, sock_read=3600)
        
        results = []
        processed_count = 0
        
        print("\nStarting batch processing...")

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 动态提交任务到池中
            pending_tasks = {}

            # 使用tqdm进度条显示完成进度
            with tqdm(total=len(tasks_to_process), desc="Processing") as pbar:

                # 提交所有任务
                for img_path in tasks_to_process:
                    # 创建处理协程
                    coro = process_single_image(analyzer, session, img_path, force_rerun, debug, cost_calculator)
                    task_data = {"path": img_path, "index": processed_count}

                    # 提交到任务池（如果池满会等待）
                    task_id, task = await task_pool.submit_task(coro, task_data)
                    pending_tasks[task_id] = {"task": task, "data": task_data}

                    processed_count += 1

                # 收集完成的任务并更新进度条
                while pending_tasks:
                    completed_task_ids = []
                    for task_id, task_info in pending_tasks.items():
                        if task_info["task"].done():
                            try:
                                result = await task_info["task"]
                                results.append(result)

                                # 更新进度条
                                pbar.update(1)

                                # 显示当前处理的文件名和状态
                                filename = os.path.basename(result.get("path", "unknown"))
                                if result.get("status") == "success":
                                    pbar.set_postfix_str(f"✓ {filename}")
                                else:
                                    pbar.set_postfix_str(f"✗ {filename}")

                            except Exception as e:
                                results.append({
                                    "status": "collection_error",
                                    "path": task_info["data"]["path"],
                                    "error": str(e)
                                })
                                pbar.update(1)
                                filename = os.path.basename(task_info["data"]["path"])
                                pbar.set_postfix_str(f"✗ {filename}")

                            completed_task_ids.append(task_id)

                    # 移除已完成的任务
                    for task_id in completed_task_ids:
                        pending_tasks.pop(task_id)

                    # 如果还有未完成的任务，短暂等待
                    if pending_tasks:
                        await asyncio.sleep(0.1)
        
        # 统计和报告结果
        end_time = time.time()
        processing_time = end_time - start_time
        
        success_count = sum(1 for r in results if r["status"] == "success")
        error_count = len(results) - success_count
        
        print("\nBatch processing completed.")
        print(f"Success: {success_count}/{len(tasks_to_process)}")
        print(f"Failed: {error_count}")
        print(f"Time: {processing_time:.1f} seconds")

        if processing_time > 0:
            print(f"Speed: {len(tasks_to_process)/processing_time:.1f} images/sec")

        # 显示任务池统计
        pool_stats = task_pool.get_stats()
        print(f"Tasks submitted: {pool_stats['total_submitted']}")
        print(f"Success rate: {pool_stats['success_rate']:.1f}%")
        
        # 显示成本报告
        cost_report, cost_data = cost_calculator.format_cost_report(processing_time, success_count)
        print(cost_report)
        
        # 保存错误日志
        error_log = []
        for result in results:
            if result["status"] in ["analysis_error", "save_error", "collection_error", "gather_error"]:
                error_log.append({
                    "file": result["path"],
                    "error_type": result["status"],
                    "message": result.get("error", "未知错误"),
                    "timestamp": time.time()
                })
        
        if error_log:
            log_file = 'processing_errors_batch.jsonl'
            async with aiofiles.open(log_file, 'w', encoding='utf-8') as f:
                for entry in error_log:
                    await f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            print(f"Error log: {log_file}")
        
        return 0
        
    except ValueError as e:
        print(f"{Fore.RED}❌ 配置错误:{Style.RESET_ALL} {e}")
        print("请确保 .env 文件存在并包含所有必需的配置项。")
        return 1
    except Exception as e:
        print(f"{Fore.RED}❌ 程序执行失败:{Style.RESET_ALL} {e}")
        if debug:
            print(traceback.format_exc())
        return 1
