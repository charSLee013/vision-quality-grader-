#!/usr/bin/env python3
"""
测试图片验证优化效果
比较 imagesize 和 PIL 的性能差异
"""

import time
import os
from vlm_common import quick_validate_image, find_images
from PIL import Image

def test_performance_comparison(image_paths, max_test_images=100):
    """
    比较 imagesize 和 PIL 的性能差异
    
    Args:
        image_paths: 图片路径列表
        max_test_images: 最大测试图片数量
    """
    # 限制测试图片数量
    test_images = image_paths[:max_test_images]
    
    print(f"Testing performance with {len(test_images)} images...")
    print("=" * 60)
    
    # 测试 imagesize 方法（新方法）
    print("Testing imagesize method (optimized)...")
    start_time = time.time()
    imagesize_results = []
    
    for img_path in test_images:
        try:
            result = quick_validate_image(img_path)
            imagesize_results.append(result)
        except Exception as e:
            imagesize_results.append({"valid": False, "reason": f"error: {e}"})
    
    imagesize_time = time.time() - start_time
    
    # 测试 PIL 方法（原方法）
    print("Testing PIL method (original)...")
    start_time = time.time()
    pil_results = []
    
    for img_path in test_images:
        try:
            with Image.open(img_path) as img:
                width, height = img.size
                pil_results.append({
                    "valid": True,
                    "width": width,
                    "height": height,
                    "needs_resize": width > 2000 or height > 2000
                })
        except Exception as e:
            pil_results.append({"valid": False, "reason": f"error: {e}"})
    
    pil_time = time.time() - start_time
    
    # 显示结果
    print("\nPerformance Results:")
    print("=" * 60)
    print(f"Imagesize method: {imagesize_time:.4f} seconds")
    print(f"PIL method:       {pil_time:.4f} seconds")
    print(f"Speed improvement: {pil_time / imagesize_time:.1f}x faster")
    print(f"Time saved:       {pil_time - imagesize_time:.4f} seconds")
    
    # 验证结果一致性
    valid_imagesize = sum(1 for r in imagesize_results if r["valid"])
    valid_pil = sum(1 for r in pil_results if r["valid"])
    
    print(f"\nValidation Results:")
    print(f"Imagesize valid: {valid_imagesize}/{len(test_images)}")
    print(f"PIL valid:       {valid_pil}/{len(test_images)}")
    print(f"Results match:   {'✅' if valid_imagesize == valid_pil else '❌'}")

def main():
    """主测试函数"""
    # 查找测试图片
    test_dir = "./input_images"  # 使用项目中的测试图片
    
    if not os.path.exists(test_dir):
        print(f"Test directory {test_dir} not found!")
        print("Please specify a directory with test images.")
        return
    
    image_paths = find_images(test_dir)
    
    if not image_paths:
        print(f"No images found in {test_dir}")
        return
    
    print(f"Found {len(image_paths)} images in {test_dir}")
    
    # 运行性能测试
    test_performance_comparison(image_paths, max_test_images=50)

if __name__ == "__main__":
    main()
