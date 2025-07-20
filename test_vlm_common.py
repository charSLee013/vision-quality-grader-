#!/usr/bin/env python3
"""
vlm_common模块单元测试
测试共享工具函数和CostCalculator类
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import base64
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vlm_common import (
    validate_config, find_images, image_to_base64, 
    extract_xml_result, CostCalculator, USER_PROMPT
)

class TestValidateConfig(unittest.TestCase):
    """测试配置验证功能"""
    
    def setUp(self):
        """设置测试环境"""
        # 备份原始环境变量
        self.original_env = {}
        for key in ['VLM_API_BASE', 'VLM_API_KEY', 'VLM_MODEL_NAME']:
            self.original_env[key] = os.environ.get(key)
    
    def tearDown(self):
        """清理测试环境"""
        # 恢复原始环境变量
        for key, value in self.original_env.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    
    def test_validate_config_success(self):
        """测试有效配置"""
        os.environ['VLM_API_BASE'] = 'https://ark.cn-beijing.volces.com'
        os.environ['VLM_API_KEY'] = 'test_key_12345'
        os.environ['VLM_MODEL_NAME'] = 'doubao-vision-pro-32k'
        
        config = validate_config()
        
        self.assertEqual(config['api_base'], 'https://ark.cn-beijing.volces.com')
        self.assertEqual(config['api_key'], 'test_key_12345')
        self.assertEqual(config['model_name'], 'doubao-vision-pro-32k')
        self.assertEqual(config['max_concurrent'], 5)  # 默认值
    
    def test_validate_config_missing_api_base(self):
        """测试缺少API基础URL"""
        os.environ.pop('VLM_API_BASE', None)
        os.environ['VLM_API_KEY'] = 'test_key'
        os.environ['VLM_MODEL_NAME'] = 'test_model'
        
        with self.assertRaises(ValueError) as cm:
            validate_config()
        self.assertIn('VLM_API_BASE', str(cm.exception))
    
    def test_validate_config_missing_api_key(self):
        """测试缺少API密钥"""
        os.environ['VLM_API_BASE'] = 'https://test.com'
        os.environ.pop('VLM_API_KEY', None)
        os.environ['VLM_MODEL_NAME'] = 'test_model'
        
        with self.assertRaises(ValueError) as cm:
            validate_config()
        self.assertIn('VLM_API_KEY', str(cm.exception))
    
    def test_validate_config_missing_model_name(self):
        """测试缺少模型名称"""
        os.environ['VLM_API_BASE'] = 'https://test.com'
        os.environ['VLM_API_KEY'] = 'test_key'
        os.environ.pop('VLM_MODEL_NAME', None)
        
        with self.assertRaises(ValueError) as cm:
            validate_config()
        self.assertIn('VLM_MODEL_NAME', str(cm.exception))
    
    def test_validate_config_custom_concurrent(self):
        """测试自定义并发数"""
        os.environ['VLM_API_BASE'] = 'https://test.com'
        os.environ['VLM_API_KEY'] = 'test_key'
        os.environ['VLM_MODEL_NAME'] = 'test_model'
        os.environ['VLM_MAX_CONCURRENT'] = '10'
        
        config = validate_config()
        self.assertEqual(config['max_concurrent'], 10)

class TestFindImages(unittest.TestCase):
    """测试图片文件查找功能"""
    
    def setUp(self):
        """创建临时测试目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = [
            'image1.jpg',
            'image2.jpeg',
            'image3.png',
            'image4.gif',
            'image5.bmp',
            'document.txt',  # 非图片文件
            'script.py',     # 非图片文件
        ]
        
        # 创建测试文件
        for filename in self.test_files:
            Path(self.temp_dir, filename).touch()
        
        # 创建子目录
        sub_dir = Path(self.temp_dir, 'subdir')
        sub_dir.mkdir()
        Path(sub_dir, 'image6.jpg').touch()
        Path(sub_dir, 'readme.md').touch()
    
    def tearDown(self):
        """清理临时目录"""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_find_images_basic(self):
        """测试基本图片查找功能"""
        images = find_images(self.temp_dir)
        
        # 应该找到6张图片（包括子目录中的）
        self.assertEqual(len(images), 6)
        
        # 检查是否只包含图片文件
        for img_path in images:
            ext = Path(img_path).suffix.lower()
            self.assertIn(ext, ['.jpg', '.jpeg', '.png', '.gif', '.bmp'])
    
    def test_find_images_empty_directory(self):
        """测试空目录"""
        empty_dir = tempfile.mkdtemp()
        try:
            images = find_images(empty_dir)
            self.assertEqual(len(images), 0)
        finally:
            os.rmdir(empty_dir)
    
    def test_find_images_nonexistent_directory(self):
        """测试不存在的目录"""
        nonexistent = '/path/that/does/not/exist'
        images = find_images(nonexistent)
        self.assertEqual(len(images), 0)

class TestImageToBase64(unittest.TestCase):
    """测试Base64转换功能"""
    
    def setUp(self):
        """创建测试图片文件"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_image = Path(self.temp_dir, 'test.jpg')
        
        # 创建一个简单的测试图片数据
        self.test_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        with open(self.test_image, 'wb') as f:
            f.write(self.test_data)
    
    def tearDown(self):
        """清理临时文件"""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    async def test_image_to_base64_success(self):
        """测试成功转换Base64"""
        result = await image_to_base64(str(self.test_image))
        
        # 验证返回的是有效的Base64字符串
        self.assertIsInstance(result, str)
        
        # 验证可以解码回原始数据
        decoded = base64.b64decode(result)
        self.assertEqual(decoded, self.test_data)
    
    async def test_image_to_base64_nonexistent_file(self):
        """测试转换不存在的文件"""
        nonexistent = '/path/that/does/not/exist.jpg'
        
        with self.assertRaises(FileNotFoundError):
            await image_to_base64(nonexistent)

class TestExtractXmlResult(unittest.TestCase):
    """测试XML结果提取功能"""
    
    def test_extract_xml_result_complete(self):
        """测试完整XML结果提取"""
        xml_content = """
        基于图像分析，我来评估这张图片的质量：
        
        <result>
        <is_ai_generated>false</is_ai_generated>
        <watermark_present>false</watermark_present>
        <watermark_location>none</watermark_location>
        <score>8.5</score>
        <feedback>图片清晰度较好，色彩自然，构图合理。</feedback>
        </result>
        """
        
        result = extract_xml_result(xml_content)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['is_ai_generated'], 'false')
        self.assertEqual(result['watermark_present'], 'false')
        self.assertEqual(result['watermark_location'], 'none')
        self.assertEqual(result['score'], '8.5')
        self.assertEqual(result['feedback'], '图片清晰度较好，色彩自然，构图合理。')
    
    def test_extract_xml_result_markdown_wrapped(self):
        """测试Markdown包装的XML结果"""
        xml_content = """
        ```xml
        <result>
        <is_ai_generated>true</is_ai_generated>
        <watermark_present>true</watermark_present>
        <watermark_location>右下角</watermark_location>
        <score>6.0</score>
        <feedback>图片质量一般，存在水印。</feedback>
        </result>
        ```
        """
        
        result = extract_xml_result(xml_content)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['is_ai_generated'], 'true')
        self.assertEqual(result['watermark_present'], 'true')
        self.assertEqual(result['watermark_location'], '右下角')
        self.assertEqual(result['score'], '6.0')
        self.assertEqual(result['feedback'], '图片质量一般，存在水印。')
    
    def test_extract_xml_result_fallback_extraction(self):
        """测试fallback提取功能"""
        xml_content = """
        这是一个没有完整result标签的响应。
        
        <is_ai_generated>false</is_ai_generated>
        图片看起来很自然。
        <watermark_present>false</watermark_present>
        没有发现水印。
        <score>7.5</score>
        <feedback>整体质量不错。</feedback>
        """
        
        result = extract_xml_result(xml_content)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['is_ai_generated'], 'false')
        self.assertEqual(result['watermark_present'], 'false')
        self.assertEqual(result['score'], '7.5')
        self.assertEqual(result['feedback'], '整体质量不错。')
        self.assertEqual(result['watermark_location'], 'unknown')  # 默认值
    
    def test_extract_xml_result_invalid_xml(self):
        """测试无效XML"""
        xml_content = """
        这是一个完全没有XML标签的响应。
        图片质量看起来还可以。
        """
        
        result = extract_xml_result(xml_content)
        
        # 应该返回默认值的字典
        self.assertIsNotNone(result)
        self.assertEqual(result['is_ai_generated'], 'unknown')
        self.assertEqual(result['watermark_present'], 'unknown')
        self.assertEqual(result['watermark_location'], 'unknown')
        self.assertEqual(result['score'], '0')
        self.assertEqual(result['feedback'], 'XML解析失败')
    
    def test_extract_xml_result_partial_xml(self):
        """测试部分XML标签"""
        xml_content = """
        <result>
        <is_ai_generated>false</is_ai_generated>
        <score>8.0</score>
        </result>
        """
        
        result = extract_xml_result(xml_content)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['is_ai_generated'], 'false')
        self.assertEqual(result['score'], '8.0')
        # 缺失的字段应该有默认值
        self.assertEqual(result['watermark_present'], 'unknown')
        self.assertEqual(result['watermark_location'], 'unknown')
        self.assertEqual(result['feedback'], '无反馈')

class TestCostCalculator(unittest.TestCase):
    """测试成本计算器功能"""
    
    def setUp(self):
        """设置测试用例"""
        self.calculator = CostCalculator()
    
    def test_calculate_cost_basic(self):
        """测试基本成本计算"""
        result = self.calculator.calculate_cost(1000, 500)
        
        self.assertIsInstance(result, dict)
        self.assertIn('prompt_tokens', result)
        self.assertIn('completion_tokens', result)
        self.assertIn('total_tokens', result)
        self.assertIn('prompt_cost', result)
        self.assertIn('completion_cost', result)
        self.assertIn('total_cost', result)
        
        self.assertEqual(result['prompt_tokens'], 1000)
        self.assertEqual(result['completion_tokens'], 500)
        self.assertEqual(result['total_tokens'], 1500)
        
        # 验证成本计算逻辑
        expected_prompt_cost = 1000 / 1000 * self.calculator.prompt_price_per_1k
        expected_completion_cost = 500 / 1000 * self.calculator.completion_price_per_1k
        
        self.assertAlmostEqual(result['prompt_cost'], expected_prompt_cost, places=6)
        self.assertAlmostEqual(result['completion_cost'], expected_completion_cost, places=6)
        self.assertAlmostEqual(
            result['total_cost'], 
            expected_prompt_cost + expected_completion_cost, 
            places=6
        )
    
    def test_calculate_cost_zero_tokens(self):
        """测试零token成本计算"""
        result = self.calculator.calculate_cost(0, 0)
        
        self.assertEqual(result['total_tokens'], 0)
        self.assertEqual(result['total_cost'], 0.0)
    
    def test_format_cost_cny(self):
        """测试人民币格式化"""
        cost_usd = 0.05
        formatted = self.calculator.format_cost(cost_usd)
        
        self.assertIsInstance(formatted, dict)
        self.assertIn('usd', formatted)
        self.assertIn('cny', formatted)
        
        expected_cny = cost_usd * self.calculator.usd_to_cny_rate
        self.assertAlmostEqual(formatted['cny'], expected_cny, places=4)
    
    def test_get_rate_info(self):
        """测试获取汇率信息"""
        rate_info = self.calculator.get_rate_info()
        
        self.assertIsInstance(rate_info, dict)
        self.assertIn('prompt_price_per_1k_usd', rate_info)
        self.assertIn('completion_price_per_1k_usd', rate_info)
        self.assertIn('usd_to_cny_rate', rate_info)

class TestUserPrompt(unittest.TestCase):
    """测试用户提示词"""
    
    def test_user_prompt_exists(self):
        """测试用户提示词是否存在"""
        self.assertIsInstance(USER_PROMPT, str)
        self.assertGreater(len(USER_PROMPT), 0)
    
    def test_user_prompt_contains_xml_format(self):
        """测试用户提示词是否包含XML格式要求"""
        self.assertIn('<result>', USER_PROMPT)
        self.assertIn('</result>', USER_PROMPT)
        self.assertIn('is_ai_generated', USER_PROMPT)
        self.assertIn('watermark_present', USER_PROMPT)
        self.assertIn('score', USER_PROMPT)

def run_tests():
    """运行所有测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加所有测试类
    test_classes = [
        TestValidateConfig,
        TestFindImages,
        TestImageToBase64,
        TestExtractXmlResult,
        TestCostCalculator,
        TestUserPrompt
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1) 