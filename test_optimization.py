#!/usr/bin/env python3
"""
测试图片验证优化效果
"""

from vlm_common import find_images, quick_validate_image

def test_optimization():
    """测试优化效果"""
    print("Testing image validation optimization...")
    
    # 查找图片文件
    images = find_images('.')
    print(f"Found {len(images)} images in current directory")
    
    if images:
        # 测试第一张图片
        sample_image = images[0]
        print(f"Testing validation on: {sample_image}")
        
        result = quick_validate_image(sample_image)
        print(f"Validation result: {result}")
        
        if result["valid"]:
            print("✅ Image validation successful!")
        else:
            print(f"❌ Image validation failed: {result['reason']}")
    else:
        print("No images found for testing")
    
    print("Optimization test completed!")

if __name__ == "__main__":
    test_optimization()
