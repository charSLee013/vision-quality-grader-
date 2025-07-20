#!/usr/bin/env python3
"""
VLM图片质量评分 - 批量推理版本
使用50,000并发任务池进行大规模图片质量分析
"""

import os
import argparse
import asyncio
from batch_processing import process_images_batch
from vlm_common import Fore, Style


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='大规模批量分析图片质量 - 批量推理版本')
    parser.add_argument('root_dir', type=str, help='包含图片的根目录')
    parser.add_argument('--force-rerun', action='store_true', help='强制重新处理已存在的结果文件')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--concurrent-limit', type=int, help='并发限制数量 (默认: 50000)')
    args = parser.parse_args()
    
    try:
        print("Batch Image Quality Analysis v1.0")
        print("=" * 40)
        print(f"Target directory: {args.root_dir}")
        print(f"Force rerun: {args.force_rerun}")
        print(f"Debug mode: {args.debug}")

        concurrent_limit = args.concurrent_limit or int(os.getenv('VLM_BATCH_CONCURRENT_LIMIT', '50000'))
        print(f"Concurrent limit: {concurrent_limit}")
        print()
        
        return await process_images_batch(
            root_dir=args.root_dir,
            force_rerun=args.force_rerun,
            debug=args.debug,
            concurrent_limit=concurrent_limit
        )
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return 130
    except Exception as e:
        print(f"ERROR: {e}")
        if args.debug:
            import traceback
            print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
