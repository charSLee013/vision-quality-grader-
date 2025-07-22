
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
from tqdm import tqdm as sync_tqdm
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
    优化的流式发现图片-JSON文件对，消除嵌套循环

    优化特性:
    - 单次os.walk遍历，使用字典映射避免重复搜索
    - 预构建文件映射表，消除嵌套循环
    - 实时yield有效文件对，支持流式处理
    - 大幅减少字符串操作和文件系统访问

    Args:
        source_dir: 要扫描的源目录

    Yields:
        Tuple[str, str]: (图片路径, JSON路径)
    """
    # 预编译图片扩展名集合（包含大小写变体）
    image_extensions = set()
    for ext in IMAGE_EXTENSIONS:
        image_extensions.add(ext.lower())
        image_extensions.add(ext.upper())

    discovered_count = 0

    try:
        # 使用os.walk进行高效递归遍历
        for root, dirs, files in os.walk(source_dir):
            # 构建文件映射表，避免重复的splitext操作
            file_map = {}  # base_name -> (full_path, extension)
            json_bases = set()  # JSON文件的基础名集合
            
            # 单次遍历构建映射表
            for file in files:
                base_name, ext = os.path.splitext(file)
                full_path = os.path.join(root, file)
                
                if ext in image_extensions:
                    # 图片文件：存储到映射表
                    file_map[base_name] = (full_path, ext)
                elif ext.lower() == '.json':
                    # JSON文件：添加到集合并检查是否有对应图片
                    json_bases.add(base_name)
                    if base_name in file_map:
                        # 立即yield找到的配对
                        img_path, _ = file_map[base_name]
                        json_path = full_path
                        discovered_count += 1
                        yield img_path, json_path
                        
                        # 每发现100个文件就让出控制权，保持响应性
                        if discovered_count % 100 == 0:
                            await asyncio.sleep(0)

            # 处理先遇到图片后遇到JSON的情况
            for base_name, (img_path, _) in file_map.items():
                if base_name in json_bases:
                    continue  # 已经处理过
                # 检查是否有对应的JSON文件
                json_path = os.path.join(root, base_name + '.json')
                if base_name + '.json' in [os.path.basename(f) for f in files if f.endswith('.json')]:
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

def process_image_sync(img_path: str, json_path: str, args) -> Dict[str, Any]:
    """
    同步处理单个图片-JSON文件对，优化用于多线程环境
    
    Args:
        img_path: 图片文件路径
        json_path: JSON文件路径
        args: 命令行参数
        
    Returns:
        Dict: 处理结果 {"status": str, "path": str, "details": str}
    """
    try:
        # 同步读取JSON文件
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if evaluate_conditions(data, args):
            if not args.dry_run:
                if args.flat_output:
                    # 平铺输出模式：使用SHA256重命名并复制到根目录
                    img_hash = get_file_sha256(img_path)
                    if not img_hash:
                        return {"status": "error", "path": img_path, "details": "哈希计算失败"}

                    _, img_ext = os.path.splitext(img_path)
                    
                    dest_img_path = os.path.join(args.dest, f"{img_hash}{img_ext}")
                    dest_json_path = os.path.join(args.dest, f"{img_hash}.json")
                    
                    # 仅创建目标根目录（线程安全）
                    os.makedirs(args.dest, exist_ok=True)
                    
                    # 同步复制文件
                    shutil.copy2(img_path, dest_img_path)
                    shutil.copy2(json_path, dest_json_path)

                else:
                    # 默认模式：保持目录结构
                    relative_path = os.path.relpath(img_path, args.source)
                    dest_img_path = os.path.join(args.dest, relative_path)
                    dest_json_path = os.path.splitext(dest_img_path)[0] + '.json'
                    
                    # 创建目标目录（线程安全）
                    dest_dir = os.path.dirname(dest_img_path)
                    if dest_dir:
                        os.makedirs(dest_dir, exist_ok=True)
                    
                    # 同步复制文件
                    shutil.copy2(img_path, dest_img_path)
                    shutil.copy2(json_path, dest_json_path)

            return {"status": "copied", "path": img_path, "details": "成功复制"}
        else:
            return {"status": "skipped", "path": img_path, "details": "不满足筛选条件"}
            
    except json.JSONDecodeError:
        return {"status": "error", "path": json_path, "details": "JSON格式错误"}
    except Exception as e:
        logging.error(f"处理 {img_path} 时发生未知错误: {e}")
        return {"status": "error", "path": img_path, "details": str(e)}

def process_image(img_path, json_path, args):
    """
    处理单个图片-JSON文件对（保持向后兼容）
    
    Args:
        img_path (str): 图片文件路径。
        json_path (str): JSON文件路径。
        args (argparse.Namespace): 命令行参数。
        
    Returns:
        tuple: (状态, 文件路径)
    """
    result = process_image_sync(img_path, json_path, args)
    return result["status"], result["path"]

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
    parser.add_argument('--workers', type=int, default=os.cpu_count() * 4, help='并行处理的线程数量 (默认: CPU核心数*4，最多16384个线程)。')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行，只打印操作信息而不实际复制文件。')
    parser.add_argument('--flat-output', action='store_true', help='将所有文件复制到目标目录的根级别，并以SHA256重命名。')
    parser.add_argument('--log-file', type=str, default='filter_log.txt', help='指定日志文件的路径 (默认: filter_log.txt)。')
    
    return parser

async def process_images_threaded(
    image_pairs: List[Tuple[str, str]],
    args,
    max_workers: int = None
) -> Dict[str, int]:
    """
    使用线程池处理图片文件对，优化I/O密集型操作

    Args:
        image_pairs: 图片-JSON文件对列表
        args: 命令行参数
        max_workers: 最大线程数，默认为CPU核心数*4

    Returns:
        Dict[str, int]: 处理结果统计
    """
    if not image_pairs:
        return {'copied': 0, 'skipped': 0, 'error': 0}

    # 智能设置线程数：I/O密集型操作使用更多线程
    if max_workers is None:
        max_workers = min(os.cpu_count() * 4, 16384)  # 最多16384个线程
    
    print(f"THREADS: {max_workers} workers")

    # 初始化计数器
    success_count = 0
    skip_count = 0
    error_count = 0
    results = []

    # 使用ThreadPoolExecutor处理I/O密集型任务
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_pair = {
            executor.submit(process_image_sync, img_path, json_path, args): (img_path, json_path)
            for img_path, json_path in image_pairs
        }

        # 使用tqdm显示处理进度
        with sync_tqdm(total=len(image_pairs), desc="PROCESS", unit="pairs", ncols=80) as pbar:
            # 使用as_completed获取完成的任务，避免轮询
            for future in as_completed(future_to_pair):
                try:
                    result = future.result()
                    results.append(result)

                    # 更新计数器
                    status = result.get("status", "unknown")
                    if status == "copied":
                        success_count += 1
                    elif status == "skipped":
                        skip_count += 1
                    else:
                        error_count += 1

                    # 更新进度条
                    pbar.update(1)
                    pbar.set_postfix_str(f"成功={success_count}，跳过={skip_count}，失败={error_count}")

                except Exception as e:
                    # 处理任务异常
                    img_path, json_path = future_to_pair[future]
                    error_result = {
                        "status": "error",
                        "path": img_path,
                        "details": f"线程执行错误: {str(e)}"
                    }
                    results.append(error_result)
                    error_count += 1
                    
                    pbar.update(1)
                    pbar.set_postfix_str(f"成功={success_count}，跳过={skip_count}，失败={error_count}")

    # 统计结果
    result_counts = {'copied': 0, 'skipped': 0, 'error': 0}
    for result in results:
        status = result.get("status", "error")
        if status in result_counts:
            result_counts[status] += 1
        else:
            result_counts['error'] += 1

    # 显示处理统计
    total_processed = len(results)
    success_rate = (success_count / total_processed * 100) if total_processed > 0 else 0
    print(f"STATS: {success_rate:.1f}% success ({success_count}/{total_processed})")

    return result_counts

async def process_images_concurrent(
    image_pairs: List[Tuple[str, str]],
    args,
    max_concurrent: int = 8192
) -> Dict[str, int]:
    """
    并发处理图片文件对（保持向后兼容，但推荐使用process_images_threaded）

    Args:
        image_pairs: 图片-JSON文件对列表
        args: 命令行参数
        max_concurrent: 最大并发数

    Returns:
        Dict[str, int]: 处理结果统计
    """
    # 对于大量文件，自动切换到线程池模式
    if len(image_pairs) > 1000:
        print("检测到大量文件，自动切换到优化的线程池模式...")
        return await process_images_threaded(image_pairs, args)
    
    # 小量文件保持原有逻辑（但降低并发数）
    max_concurrent = min(max_concurrent, 200)  # 限制最大并发数
    return await process_images_threaded(image_pairs, args, max_concurrent // 4)

async def main_async():
    """异步主函数，实现流式进度条和并发处理"""
    parser = setup_parser()
    args = parser.parse_args()
    
    # 获取实际的并发配置 - 改为线程数配置
    max_workers = int(os.getenv('IMAGE_FILTER_THREAD_WORKERS', str(os.cpu_count() * 4)))
    max_workers = min(max_workers, 16384)  # 限制最大线程数

    # DOS风格配置显示
    print("=" * 60)
    print("IMAGE FILTER v3.0 - THREADED EDITION")
    print("=" * 60)
    print(f"SOURCE: {args.source}")
    print(f"DEST  : {args.dest}")
    print(f"FILTER: {args.score or 'NONE'} | AI:{args.is_ai or 'ANY'} | WM:{args.has_watermark or 'ANY'}")
    print(f"THREADS: {max_workers} WORKERS")
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
    results = await process_images_threaded(
        image_pairs,
        args,
        max_workers=max_workers
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
