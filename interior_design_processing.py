#!/usr/bin/env python3
"""
室内设计图像分析批量处理逻辑
集成检查点管理、TXT文件输出和增强错误恢复
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
from interior_design_analyzer import InteriorDesignAnalyzer
from vlm_common import (
    validate_batch_config, find_images, CostCalculator,
    quick_validate_image, Fore, Style, convert_score_to_range
)


async def process_single_interior_design_image(analyzer, session, img_path, force_rerun, debug_mode, cost_calculator):
    """
    处理单个室内设计图片的异步函数
    
    Args:
        analyzer: InteriorDesignAnalyzer实例
        session: aiohttp会话对象
        img_path: 图片文件路径
        force_rerun: 是否强制重新处理
        debug_mode: 是否启用调试模式
        cost_calculator: 成本计算器实例
        
    Returns:
        Dict: 处理结果
    """
    txt_path = os.path.splitext(img_path)[0] + '.txt'

    # 检查是否需要重新处理 - 简单检查TXT文件是否存在且有两行内容
    if not force_rerun and txt_file_exists_with_content(txt_path):
        return {"status": "skipped", "path": img_path}
    
    # 分析图片
    result = await analyzer.analyze_image(session, img_path)
    
    if result and "error" not in result:
        try:
            # 统计API使用成本
            if "api_usage" in result:
                cost_calculator.add_usage(result["api_usage"])
            
            # 构建TXT文件内容
            content_lines = []

            # 第一行：tags（可能包含score前缀）
            tags_content = ''
            if 'tags' in result and result['tags']:
                tags_content = result['tags']

            # 尝试从对应的JSON文件中读取score信息
            score_prefix = ''
            try:
                json_path = os.path.splitext(img_path)[0] + '.json'
                if os.path.exists(json_path):
                    async with aiofiles.open(json_path, 'r', encoding='utf-8') as f:
                        json_content = await f.read()
                        json_data = json.loads(json_content)

                        if 'score' in json_data:
                            score_value = float(json_data['score'])
                            converted_score = convert_score_to_range(score_value)
                            score_prefix = f'score_{converted_score}, '

                            if debug_mode:
                                print(f"{Fore.CYAN}📊 发现评分: {score_value} -> score_{converted_score}{Style.RESET_ALL}")

            except Exception as e:
                # JSON读取失败时静默处理，不影响主流程
                if debug_mode:
                    print(f"{Fore.YELLOW}⚠️ JSON读取失败: {e}{Style.RESET_ALL}")

            # 组合最终的tags内容
            final_tags = score_prefix + tags_content if tags_content else score_prefix.rstrip(', ')
            content_lines.append(final_tags)
                
            # 第二行：detail
            if 'detail' in result and result['detail']:
                content_lines.append(result['detail'])
            else:
                content_lines.append('')  # 空行占位
            
            # 异步保存TXT文件
            os.makedirs(os.path.dirname(txt_path), exist_ok=True)
            async with aiofiles.open(txt_path, 'w', encoding='utf-8') as f:
                await f.write('\n'.join(content_lines))

            return {"status": "success", "path": img_path, "result": result}
            
        except Exception as e:
            return {
                "status": "save_error",
                "path": img_path,
                "error": str(e),
                "result": result
            }
    else:
        # 分析失败，统计请求数
        cost_calculator.total_requests += 1
        return {
            "status": "analysis_error",
            "path": img_path,
            "error": result
        }


def txt_file_exists_with_content(txt_path: str) -> bool:
    """检查TXT文件是否存在且有两行内容"""
    if not os.path.exists(txt_path):
        return False

    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            lines = f.read().strip().split('\n')
            return len(lines) >= 2 and any(line.strip() for line in lines)
    except Exception:
        return False


async def process_images_interior_design(root_dir: str, force_rerun: bool = False, debug: bool = False, concurrent_limit: int = None) -> int:
    """
    批量处理室内设计图片的主函数

    Args:
        root_dir: 图片根目录
        force_rerun: 是否强制重新处理
        debug: 是否启用调试模式
        concurrent_limit: 并发限制数量

    Returns:
        int: 退出代码 (0=成功, 1=失败)
    """
    try:
        start_time = time.time()

        # 验证配置
        validate_batch_config()

        # 获取并发限制
        concurrent_limit = concurrent_limit or int(os.getenv('VLM_BATCH_CONCURRENT_LIMIT', '50000'))

        # 初始化组件
        task_pool = BatchTaskPool(max_concurrent=concurrent_limit)
        analyzer = InteriorDesignAnalyzer()
        cost_calculator = CostCalculator()

        # 查找待处理图片
        all_images = find_images(root_dir)

        # 预过滤：快速验证图片有效性，避免处理无效图片
        valid_images = []
        for img_path in all_images:
            validation = quick_validate_image(img_path, max_size=2000, min_size=100)
            if validation["valid"]:
                valid_images.append(img_path)
            elif debug:
                print(f"Skipping invalid image: {os.path.basename(img_path)} - {validation['reason']}")

        # 过滤已处理的图片
        tasks_to_process = [
            img_path for img_path in valid_images
            if not txt_file_exists_with_content(os.path.splitext(img_path)[0] + '.txt') or force_rerun
        ]

        if not tasks_to_process:
            print("All images already processed.")
            return 0

        print(f"Processing {len(tasks_to_process)} images...")

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



        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 动态提交任务到池中
            pending_tasks = {}

            # 使用tqdm进度条显示完成进度
            with tqdm(total=len(tasks_to_process), desc="Processing") as pbar:

                # 提交所有任务
                for img_path in tasks_to_process:
                    # 创建处理协程
                    coro = process_single_interior_design_image(analyzer, session, img_path, force_rerun, debug, cost_calculator)
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

                    # 短暂等待，避免过度占用CPU
                    if pending_tasks:
                        await asyncio.sleep(0.1)

        # 统计结果
        processing_time = time.time() - start_time
        success_count = sum(1 for r in results if r["status"] == "success")
        skip_count = sum(1 for r in results if r["status"] == "skipped")
        error_count = len(results) - success_count - skip_count

        print(f"\nCompleted {success_count}/{len(tasks_to_process)} images in {processing_time:.1f}s")

        # 显示成本报告
        cost_report, cost_data = cost_calculator.format_cost_report(processing_time, success_count)
        print(cost_report)

        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        if debug:
            import traceback
            print(traceback.format_exc())
        return 1
