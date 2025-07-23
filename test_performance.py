#!/usr/bin/env python3
"""
性能测试脚本 - 测试优化后的image_filter_tool.py性能
"""

import os
import time
import asyncio
import tempfile
import json
import shutil
from pathlib import Path

# 导入优化后的函数
from image_filter_tool import discover_image_json_pairs_streaming, process_images_threaded

def create_test_data(num_pairs=1000):
    """创建测试数据"""
    test_dir = tempfile.mkdtemp(prefix="filter_test_")
    print(f"创建测试数据目录: {test_dir}")
    
    # 创建测试图片和JSON文件
    for i in range(num_pairs):
        # 创建假的图片文件
        img_path = os.path.join(test_dir, f"test_{i:06d}.jpg")
        with open(img_path, 'wb') as f:
            f.write(b"fake_image_data" * 100)  # 创建一个小的假图片文件
        
        # 创建对应的JSON文件
        json_path = os.path.join(test_dir, f"test_{i:06d}.json")
        test_data = {
            "analysis_result": {
                "is_ai_generated": "false",
                "watermark_present": "false",
                "score": str(7.5 + (i % 3)),  # 分数在7.5-9.5之间变化
                "feedback": f"Test image {i}"
            }
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(test_data, f, ensure_ascii=False, indent=2)
    
    return test_dir

async def test_file_discovery_performance(test_dir, num_pairs):
    """测试文件发现性能"""
    print(f"\n=== 测试文件发现性能 ({num_pairs} 个文件对) ===")
    
    start_time = time.time()
    discovered_count = 0
    
    async for img_path, json_path in discover_image_json_pairs_streaming(test_dir):
        discovered_count += 1
        if discovered_count % 1000 == 0:
            print(f"已发现: {discovered_count} 个文件对")
    
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"发现 {discovered_count} 个文件对")
    print(f"耗时: {duration:.2f} 秒")
    print(f"速度: {discovered_count / duration:.1f} 对/秒")
    
    return discovered_count

class MockArgs:
    """模拟命令行参数"""
    def __init__(self, source, dest):
        self.source = source
        self.dest = dest
        self.score = '>:8.0'  # 测试筛选条件
        self.is_ai = 'false'
        self.has_watermark = 'false'
        self.logic = 'AND'
        self.dry_run = True  # 使用dry run模式避免实际复制
        self.flat_output = False

async def test_processing_performance(test_dir, num_pairs):
    """测试处理性能"""
    print(f"\n=== 测试处理性能 ({num_pairs} 个文件对) ===")
    
    # 收集所有文件对
    image_pairs = []
    async for img_path, json_path in discover_image_json_pairs_streaming(test_dir):
        image_pairs.append((img_path, json_path))
    
    # 创建模拟参数
    dest_dir = tempfile.mkdtemp(prefix="filter_dest_")
    args = MockArgs(test_dir, dest_dir)
    
    # 测试线程池处理性能
    start_time = time.time()
    results = await process_images_threaded(image_pairs, args, max_workers=16)
    end_time = time.time()
    
    duration = end_time - start_time
    total_processed = sum(results.values())
    
    print(f"处理结果: {results}")
    print(f"总处理数: {total_processed}")
    print(f"耗时: {duration:.2f} 秒")
    print(f"速度: {total_processed / duration:.1f} 对/秒")
    
    # 清理
    shutil.rmtree(dest_dir)
    
    return results

async def main():
    """主测试函数"""
    print("=== IMAGE FILTER 性能测试 ===")
    
    # 测试不同规模的数据
    test_sizes = [100, 1000, 5000]
    
    for size in test_sizes:
        print(f"\n{'='*50}")
        print(f"测试规模: {size} 个文件对")
        print(f"{'='*50}")
        
        # 创建测试数据
        test_dir = create_test_data(size)
        
        try:
            # 测试文件发现性能
            discovered = await test_file_discovery_performance(test_dir, size)
            
            # 测试处理性能
            if discovered > 0:
                await test_processing_performance(test_dir, discovered)
            
        finally:
            # 清理测试数据
            shutil.rmtree(test_dir)
            print(f"清理测试目录: {test_dir}")
    
    print(f"\n{'='*50}")
    print("性能测试完成！")
    print(f"{'='*50}")

if __name__ == "__main__":
    asyncio.run(main())
