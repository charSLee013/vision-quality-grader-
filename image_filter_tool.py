#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import json
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from colorama import init, Fore, Style

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
                # 计算目标路径并保持目录结构
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
        logging.error(f"JSON文件格式错误: {json_path}")
        return 'error', json_path
    except Exception as e:
        logging.error(f"处理 {img_path} 时发生未知错误: {e}")
        return 'error', img_path

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
    parser.add_argument('--workers', type=int, default=os.cpu_count(), help='并行处理的工作线程数 (默认: 系统CPU核心数)。')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行，只打印操作信息而不实际复制文件。')
    parser.add_argument('--log-file', type=str, default='filter_log.txt', help='指定日志文件的路径 (默认: filter_log.txt)。')
    
    return parser

def main():
    """主函数，编排整个筛选和复制流程"""
    parser = setup_parser()
    args = parser.parse_args()
    
    # 打印参数
    print(f"{Fore.CYAN}--- 配置参数 ---{Style.RESET_ALL}")
    for key, value in vars(args).items():
        print(f"  {key:<15}: {Fore.YELLOW}{value}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}------------------{Style.RESET_ALL}\n")

    # 配置日志
    setup_logging(args.log_file)

    # 检查是否有任何筛选条件
    if not any([args.score, args.is_ai, args.has_watermark]):
        print(f"{Fore.YELLOW}⚠️ 警告: 未指定任何筛选条件，将不会有文件被复制。{Style.RESET_ALL}")
        # 可以选择在这里退出，或者继续执行一个空操作
        # return

    if args.dry_run:
        print(f"{Fore.MAGENTA}*** 模拟运行模式已激活 ***{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}将只显示操作信息，不会实际复制任何文件。{Style.RESET_ALL}\n")

    # 查找文件对
    image_pairs = find_image_json_pairs(args.source)
    if not image_pairs:
        print(f"{Fore.YELLOW}⚠️ 在源目录中未找到任何有效的图片-JSON文件对。程序退出。{Style.RESET_ALL}")
        return

    # 并行处理
    results = {'copied': 0, 'skipped': 0, 'error': 0}
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # 创建future任务列表
        futures = {executor.submit(process_image, img_path, json_path, args): (img_path, json_path)
                   for img_path, json_path in image_pairs}
        
        # 使用tqdm显示进度条
        pbar = tqdm(as_completed(futures), total=len(image_pairs), desc=f"{Fore.GREEN}筛选进度{Style.RESET_ALL}")
        for future in pbar:
            try:
                status, path = future.result()
                results[status] += 1
                pbar.set_postfix_str(f"状态: {status}, 文件: {os.path.basename(path)}")
            except Exception as e:
                results['error'] += 1
                logging.error(f"一个工作线程发生严重错误: {e}")

    # 打印最终报告
    print(f"\n{Fore.CYAN}--- 处理完成 ---{Style.RESET_ALL}")
    print(f"  ✅ {Fore.GREEN}成功复制: {results['copied']} 个文件对{Style.RESET_ALL}")
    print(f"  ⏭️ {Fore.BLUE}跳过处理: {results['skipped']} 个文件对{Style.RESET_ALL}")
    print(f"  ❌ {Fore.RED}发生错误: {results['error']} 个文件对{Style.RESET_ALL}")
    print(f"  📝 详细日志已保存到: {args.log_file}")
    if args.dry_run:
        print(f"{Fore.MAGENTA}\n*** 模拟运行结束 ***{Style.RESET_ALL}")

if __name__ == "__main__":
    main() 