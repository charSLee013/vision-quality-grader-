#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import json
import argparse
import logging
import hashlib
import asyncio
import aiofiles
from typing import AsyncGenerator, Tuple, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm.asyncio import tqdm
from colorama import init, Fore, Style

# 导入批处理任务池
try:
    from batch_task_pool import BatchTaskPool
except ImportError:
    # 如果找不到BatchTaskPool，创建一个简化版本
    class BatchTaskPool:
        """简化版任务池，用于并发处理"""
        def __init__(self, max_concurrent=8192):
            self.semaphore = asyncio.Semaphore(max_concurrent)
            self.active_tasks = {}
            self.task_counter = 0
            self.completed_count = 0
            self.failed_count = 0

        async def submit_task(self, coro, task_data):
            await self.semaphore.acquire()
            task_id = f"task_{self.task_counter}"
            self.task_counter += 1

            task = asyncio.create_task(self._execute_task(coro, task_id))
            self.active_tasks[task_id] = task
            return task_id, task

        async def _execute_task(self, coro, task_id):
            try:
                result = await coro
                self.completed_count += 1
                return result
            except Exception as e:
                self.failed_count += 1
                return {"status": "error", "error": str(e)}
            finally:
                self.semaphore.release()
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]

        def get_stats(self):
            total = self.completed_count + self.failed_count
            success_rate = (self.completed_count / total * 100) if total > 0 else 0
            return {
                "total_submitted": self.task_counter,
                "completed": self.completed_count,
                "failed": self.failed_count,
                "success_rate": success_rate
            }

# 初始化colorama
init(autoreset=True)

# 支持的图片文件扩展名
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif', '.tiff', '.tif')

def find_image_json_pairs(source_dir):
    """
    递归扫描源目录，查找图片文件及其对应的JSON文件。
    
    Args:
        source_dir (str): 要扫描的源目录。
        
    Returns:
        list: 包含(图片路径, JSON路径)元组的列表。
    """
    pairs = []
    print(f"{Fore.BLUE}🔍 正在扫描源目录: {source_dir}...{Style.RESET_ALL}")
    
    all_files = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            all_files.append(os.path.join(root, file))

    image_files = [f for f in all_files if f.lower().endswith(IMAGE_EXTENSIONS)]
    
    print(f"{Fore.GREEN}🖼️  发现 {len(image_files)} 张图片。正在匹配JSON文件...{Style.RESET_ALL}")

    for img_path in image_files:
        json_path = os.path.splitext(img_path)[0] + '.json'
        if os.path.exists(json_path):
            pairs.append((img_path, json_path))
        else:
            logging.warning(f"图片 {img_path} 缺少对应的JSON文件，已跳过。")
            
    print(f"{Fore.GREEN}✅ 找到 {len(pairs)} 个有效的图片-JSON文件对。{Style.RESET_ALL}\n")
    return pairs

async def discover_image_json_pairs_streaming(source_dir: str) -> AsyncGenerator[Tuple[str, str], None]:
    """
    流式发现图片-JSON文件对，单次文件系统遍历

    优化特性:
    - 单次os.walk遍历同时识别图片和JSON文件
    - 实时yield有效文件对，支持流式处理
    - 避免构建大型文件列表，减少内存使用

    Args:
        source_dir: 要扫描的源目录

    Yields:
        Tuple[str, str]: (图片路径, JSON路径)
    """
    # 图片扩展名集合（包含大小写变体）
    image_extensions = set()
    for ext in IMAGE_EXTENSIONS:
        image_extensions.add(ext.lower())
        image_extensions.add(ext.upper())

    discovered_count = 0

    try:
        # 使用os.walk进行高效递归遍历
        for root, dirs, files in os.walk(source_dir):
            # 在当前目录中查找图片-JSON文件对
            image_files = set()
            json_files = set()

            # 分类文件
            for file in files:
                file_path = os.path.join(root, file)
                _, ext = os.path.splitext(file)

                if ext in image_extensions:
                    image_files.add(os.path.splitext(file)[0])  # 不带扩展名的基础名
                elif ext.lower() == '.json':
                    json_files.add(os.path.splitext(file)[0])   # 不带扩展名的基础名

            # 找到匹配的图片-JSON对
            matching_pairs = image_files.intersection(json_files)

            for base_name in matching_pairs:
                img_path = None
                json_path = os.path.join(root, base_name + '.json')

                # 找到对应的图片文件（可能有不同扩展名）
                for file in files:
                    if os.path.splitext(file)[0] == base_name and os.path.splitext(file)[1] in image_extensions:
                        img_path = os.path.join(root, file)
                        break

                if img_path:
                    discovered_count += 1
                    yield img_path, json_path

                    # 每发现100个文件就让出控制权，保持响应性
                    if discovered_count % 100 == 0:
                        await asyncio.sleep(0)

    except (PermissionError, OSError) as e:
        logging.warning(f"扫描目录时遇到错误: {e}")

def get_file_sha256(file_path):
    """计算文件的SHA256哈希值，适用于大文件。"""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while True:
                # 读取1MB的数据块
                data = f.read(1024 * 1024)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()
    except IOError:
        logging.error(f"无法读取文件进行哈希计算: {file_path}")
        return None

async def get_file_sha256_async(file_path: str) -> str:
    """异步计算文件的SHA256哈希值，适用于大文件。"""
    sha256 = hashlib.sha256()
    try:
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                # 读取1MB的数据块
                data = await f.read(1024 * 1024)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()
    except IOError:
        logging.error(f"无法读取文件进行哈希计算: {file_path}")
        return None

def evaluate_conditions(data, args):
    """
    根据传入的参数评估单个数据对象是否满足所有筛选条件。
    
    Args:
        data (dict): 从JSON文件读取的数据。
        args (argparse.Namespace): 解析后的命令行参数。
        
    Returns:
        bool: 如果满足条件则返回True，否则返回False。
    """
    conditions = []
    
    # 1. 分数条件
    if args.score:
        try:
            score_val = float(data.get('score', -1))
            if score_val == -1:
                raise KeyError
                
            parts = args.score.replace(' ', '').split(':')
            op = parts[0]
            
            if op == 'between':
                min_val, max_val = float(parts[1]), float(parts[2])
                conditions.append(min_val <= score_val <= max_val)
            else:
                val = float(parts[1])
                if op == '>': conditions.append(score_val > val)
                elif op == '<': conditions.append(score_val < val)
                elif op == '==': conditions.append(score_val == val)
                elif op == '>=': conditions.append(score_val >= val)
                elif op == '<=': conditions.append(score_val <= val)
        except (ValueError, IndexError):
            logging.error(f"无效的分数参数格式: {args.score}。已跳过此条件。")
            conditions.append(False)
        except KeyError:
            logging.warning(f"JSON数据中缺少 'score' 字段。已跳过此文件。")
            return False # 直接判定失败

    # 2. AI生成条件
    if args.is_ai is not None:
        try:
            ai_val = bool(data['is_ai_generated'])
            expected_val = args.is_ai == 'true'
            conditions.append(ai_val == expected_val)
        except KeyError:
            logging.warning(f"JSON数据中缺少 'is_ai_generated' 字段。已跳过此文件。")
            return False

    # 3. 水印条件
    if args.has_watermark is not None:
        try:
            watermark_val = bool(data['watermark_present'])
            expected_val = args.has_watermark == 'true'
            conditions.append(watermark_val == expected_val)
        except KeyError:
            logging.warning(f"JSON数据中缺少 'watermark_present' 字段。已跳过此文件。")
            return False

    if not conditions:
        return False # 如果没有任何筛选条件，则默认不匹配

    if args.logic == 'AND':
        return all(conditions)
    else: # OR
        return any(conditions)

def process_image(img_path, json_path, args):
    """
    处理单个图片-JSON文件对。
    
    Args:
        img_path (str): 图片文件路径。
        json_path (str): JSON文件路径。
        args (argparse.Namespace): 命令行参数。
        
    Returns:
        tuple: (状态, 文件路径)
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if evaluate_conditions(data, args):
            if not args.dry_run:
                if args.flat_output:
                    # 平铺输出模式：使用SHA256重命名并复制到根目录
                    img_hash = get_file_sha256(img_path)
                    if not img_hash:
                        return 'error', img_path # 哈希计算失败

                    _, img_ext = os.path.splitext(img_path)
                    
                    dest_img_path = os.path.join(args.dest, f"{img_hash}{img_ext}")
                    dest_json_path = os.path.join(args.dest, f"{img_hash}.json")
                    
                    # 仅创建目标根目录
                    os.makedirs(args.dest, exist_ok=True)
                    
                    # 复制文件
                    shutil.copy2(img_path, dest_img_path)
                    shutil.copy2(json_path, dest_json_path)

                else:
                    # 默认模式：保持目录结构
                    relative_path = os.path.relpath(img_path, args.source)
                    dest_img_path = os.path.join(args.dest, relative_path)
                    dest_json_path = os.path.splitext(dest_img_path)[0] + '.json'
                    
                    # 创建目标目录
                    os.makedirs(os.path.dirname(dest_img_path), exist_ok=True)
                    
                    # 复制文件
                    shutil.copy2(img_path, dest_img_path)
                    shutil.copy2(json_path, dest_json_path)

            return 'copied', img_path
        else:
            return 'skipped', img_path
            
    except json.JSONDecodeError:
        return 'error', json_path
    except Exception as e:
        logging.error(f"处理 {img_path} 时发生未知错误: {e}")
        return 'error', img_path

async def process_image_async(img_path: str, json_path: str, args) -> Dict[str, Any]:
    """
    异步处理单个图片-JSON文件对

    Args:
        img_path: 图片文件路径
        json_path: JSON文件路径
        args: 命令行参数

    Returns:
        Dict: 处理结果 {"status": str, "path": str, "details": str}
    """
    try:
        # 使用aiofiles异步读取JSON文件
        async with aiofiles.open(json_path, 'r', encoding='utf-8') as f:
            content = await f.read()
            data = json.loads(content)

        if evaluate_conditions(data, args):
            if not args.dry_run:
                if args.flat_output:
                    # 平铺输出模式：使用SHA256重命名并复制到根目录
                    img_hash = await get_file_sha256_async(img_path)
                    if not img_hash:
                        return {"status": "error", "path": img_path, "details": "哈希计算失败"}

                    _, img_ext = os.path.splitext(img_path)

                    dest_img_path = os.path.join(args.dest, f"{img_hash}{img_ext}")
                    dest_json_path = os.path.join(args.dest, f"{img_hash}.json")

                    # 仅创建目标根目录
                    os.makedirs(args.dest, exist_ok=True)

                    # 异步复制文件
                    await asyncio.gather(
                        copy_file_async(img_path, dest_img_path),
                        copy_file_async(json_path, dest_json_path)
                    )

                else:
                    # 默认模式：保持目录结构
                    relative_path = os.path.relpath(img_path, args.source)
                    dest_img_path = os.path.join(args.dest, relative_path)
                    dest_json_path = os.path.splitext(dest_img_path)[0] + '.json'

                    # 创建目标目录
                    os.makedirs(os.path.dirname(dest_img_path), exist_ok=True)

                    # 异步复制文件
                    await asyncio.gather(
                        copy_file_async(img_path, dest_img_path),
                        copy_file_async(json_path, dest_json_path)
                    )

            return {"status": "copied", "path": img_path, "details": "成功复制"}
        else:
            return {"status": "skipped", "path": img_path, "details": "不满足筛选条件"}

    except json.JSONDecodeError:
        return {"status": "error", "path": json_path, "details": "JSON格式错误"}
    except Exception as e:
        logging.error(f"处理 {img_path} 时发生未知错误: {e}")
        return {"status": "error", "path": img_path, "details": str(e)}

async def copy_file_async(src_path: str, dest_path: str):
    """异步复制文件"""
    try:
        async with aiofiles.open(src_path, 'rb') as src:
            async with aiofiles.open(dest_path, 'wb') as dest:
                while True:
                    chunk = await src.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    await dest.write(chunk)
    except Exception as e:
        logging.error(f"复制文件失败 {src_path} -> {dest_path}: {e}")
        raise

def setup_logging(log_file):
    """配置日志记录"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename=log_file,
        filemode='w'
    )
    # 添加一个控制台处理器，用于显示警告和错误
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

def setup_parser():
    """设置和配置命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description='根据JSON分析结果筛选图片并复制文件。',
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
使用示例:
  - 筛选分数大于8.5分的非AI、无水印图片:
    python %(prog)s --source ./images --dest ./high_quality --score '>:8.5' --is-ai false --has-watermark false

  - 筛选分数在7到8之间，或者是AI生成的图片:
    python %(prog)s --source ./images --dest ./filtered --score 'between:7:8' --is-ai true --logic OR
    
  - 模拟运行，查看将要复制的文件:
    python %(prog)s --source ./images --dest ./filtered --score '<:5' --dry-run
"""
    )
    
    # 必需参数
    parser.add_argument('--source', type=str, required=True, help='包含图片和JSON文件的源目录路径。')
    parser.add_argument('--dest', type=str, required=True, help='用于存放筛选后文件的目标目录路径。')
    
    # 可选筛选参数
    parser.add_argument('--score', type=str, help="分数筛选条件。格式: 'OP:VALUE' 或 'between:MIN:MAX'。\n有效OP: '>', '<', '==', '>=', '<='。示例: --score '>:8.5'")
    parser.add_argument('--is-ai', type=str, choices=['true', 'false'], help="AI生成状态筛选。'true' 或 'false'。")
    parser.add_argument('--has-watermark', type=str, choices=['true', 'false'], help="水印状态筛选。'true' 或 'false'。")
    
    # 控制参数
    parser.add_argument('--logic', type=str, choices=['AND', 'OR'], default='AND', help="多个筛选条件之间的逻辑关系 (默认: AND)。")
    parser.add_argument('--workers', type=int, default=os.cpu_count(), help='并行处理的协程数量 (默认: 系统CPU核心数)。')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行，只打印操作信息而不实际复制文件。')
    parser.add_argument('--flat-output', action='store_true', help='将所有文件复制到目标目录的根级别，并以SHA256重命名。')
    parser.add_argument('--log-file', type=str, default='filter_log.txt', help='指定日志文件的路径 (默认: filter_log.txt)。')
    
    return parser

async def process_images_concurrent(
    image_pairs: List[Tuple[str, str]],
    args,
    max_concurrent: int = 8192
) -> Dict[str, int]:
    """
    并发处理图片文件对

    Args:
        image_pairs: 图片-JSON文件对列表
        args: 命令行参数
        max_concurrent: 最大并发数

    Returns:
        Dict[str, int]: 处理结果统计
    """
    if not image_pairs:
        return {'copied': 0, 'skipped': 0, 'error': 0}

    # 初始化任务池
    task_pool = BatchTaskPool(max_concurrent=max_concurrent)
    results = []
    pending_tasks = {}

    print(f"ASYNC: {max_concurrent} coroutines")

    # 初始化计数器
    success_count = 0
    skip_count = 0
    error_count = 0

    # 使用tqdm显示处理进度
    with tqdm(total=len(image_pairs), desc="PROCESS", unit="pairs", ncols=80) as pbar:

        # 提交所有任务
        for img_path, json_path in image_pairs:
            coro = process_image_async(img_path, json_path, args)
            task_data = {"path": img_path}

            task_id, task = await task_pool.submit_task(coro, task_data)
            pending_tasks[task_id] = {"task": task, "data": task_data}

        # 收集完成的任务
        while pending_tasks:
            completed_task_ids = []

            for task_id, task_info in pending_tasks.items():
                if task_info["task"].done():
                    try:
                        result = await task_info["task"]
                        results.append(result)

                        # 更新进度条
                        pbar.update(1)

                        # 更新计数器并显示聚合统计
                        status = result.get("status", "unknown")
                        if status == "copied":
                            success_count += 1
                        elif status == "skipped":
                            skip_count += 1
                        else:
                            error_count += 1

                        # 显示聚合统计
                        pbar.set_postfix_str(f"成功={success_count}，跳过={skip_count}，失败={error_count}")

                    except Exception as e:
                        # 处理任务异常
                        error_result = {
                            "status": "error",
                            "path": task_info["data"]["path"],
                            "details": f"任务执行错误: {str(e)}"
                        }
                        results.append(error_result)
                        pbar.update(1)

                        # 更新错误计数器并显示聚合统计
                        error_count += 1
                        pbar.set_postfix_str(f"成功={success_count}，跳过={skip_count}，失败={error_count}")

                    completed_task_ids.append(task_id)

            # 移除已完成的任务
            for task_id in completed_task_ids:
                pending_tasks.pop(task_id)

            # 如果还有未完成的任务，短暂等待
            if pending_tasks:
                await asyncio.sleep(0.1)

    # 统计结果
    result_counts = {'copied': 0, 'skipped': 0, 'error': 0}
    for result in results:
        status = result.get("status", "error")
        if status in result_counts:
            result_counts[status] += 1
        else:
            result_counts['error'] += 1

    # 显示任务池统计
    stats = task_pool.get_stats()
    print(f"STATS: {stats['success_rate']:.1f}% success ({stats['completed']}/{stats['total_submitted']})")

    return result_counts

async def main_async():
    """异步主函数，实现流式进度条和并发处理"""
    parser = setup_parser()
    args = parser.parse_args()
    
    # 获取实际的并发配置
    max_concurrent = int(os.getenv('IMAGE_FILTER_CONCURRENT_LIMIT', '8192'))

    # DOS风格配置显示
    print("=" * 60)
    print("IMAGE FILTER v2.0 - ASYNC EDITION")
    print("=" * 60)
    print(f"SOURCE: {args.source}")
    print(f"DEST  : {args.dest}")
    print(f"FILTER: {args.score or 'NONE'} | AI:{args.is_ai or 'ANY'} | WM:{args.has_watermark or 'ANY'}")
    print(f"ASYNC : {max_concurrent} COROUTINES")
    if args.dry_run:
        print("MODE  : DRY RUN (SIMULATION)")
    print("=" * 60)

    # 配置日志
    setup_logging(args.log_file)

    # 检查筛选条件
    if not any([args.score, args.is_ai, args.has_watermark]):
        print("WARNING: No filter conditions specified!")
        return

    # 文件发现阶段
    print("\nSCANNING...")
    image_pairs = []
    discovered_count = 0

    # 使用流式发现并显示实时进度
    with tqdm(desc="DISCOVER", unit="pairs", ncols=80) as discovery_pbar:
        async for img_path, json_path in discover_image_json_pairs_streaming(args.source):
            image_pairs.append((img_path, json_path))
            discovered_count += 1
            discovery_pbar.update(1)

            # 每发现1000个文件就让出控制权
            if discovered_count % 1000 == 0:
                await asyncio.sleep(0)

    if not image_pairs:
        print("ERROR: No image-JSON pairs found!")
        return

    print(f"FOUND: {len(image_pairs)} pairs")

    # 处理阶段
    print("PROCESSING...")
    results = await process_images_concurrent(
        image_pairs,
        args,
        max_concurrent=max_concurrent
    )

    # 结果统计
    print("\n" + "=" * 60)
    print("RESULTS:")
    print(f"COPIED : {results['copied']}")
    print(f"SKIPPED: {results['skipped']}")
    print(f"ERRORS : {results['error']}")
    print(f"LOG    : {args.log_file}")
    if args.dry_run:
        print("STATUS : SIMULATION COMPLETE")
    else:
        print("STATUS : OPERATION COMPLETE")
    print("=" * 60)

def main():
    """同步入口点，调用异步主函数"""
    return asyncio.run(main_async())

if __name__ == "__main__":
    main()