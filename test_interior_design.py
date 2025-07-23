#!/usr/bin/env python3
"""
室内设计图像分析功能的综合测试套件
包含单元测试和集成测试
"""

import unittest
import tempfile
import os
import json
import asyncio
import aiofiles
from unittest.mock import patch, AsyncMock, MagicMock
from typing import Dict, Any

# 导入要测试的模块
from vlm_common import extract_interior_design_result, resize_to_1024px, INTERIOR_DESIGN_PROMPT, convert_score_to_range
from checkpoint_manager import CheckpointManager
from interior_design_analyzer import InteriorDesignAnalyzer


class TestInteriorDesignXMLParser(unittest.TestCase):
    """测试室内设计XML解析功能"""
    
    def test_extract_tags_and_detail_success(self):
        """测试成功提取tags和detail"""
        xml_content = """
        这是一个现代客厅的分析结果：
        
        <tags>photograph, modern, living room, sofa, wooden furniture, plants, natural lighting</tags>
        <detail>A modern living room with comfortable seating arrangement. The space features a grey sofa positioned centrally, wooden coffee table, and large windows providing natural light.</detail>
        
        分析完成。
        """
        
        result = extract_interior_design_result(xml_content)
        
        self.assertNotIn('error', result)
        self.assertIn('tags', result)
        self.assertIn('detail', result)
        self.assertEqual(result['tags'], 'photograph, modern, living room, sofa, wooden furniture, plants, natural lighting')
        self.assertIn('modern living room', result['detail'])
    
    def test_extract_with_markdown_cleanup(self):
        """测试清理markdown标记"""
        xml_content = """
        ```xml
        <tags>bedroom, minimalist, white walls, wooden floor</tags>
        <detail>A minimalist bedroom with clean lines and neutral colors.</detail>
        ```
        """
        
        result = extract_interior_design_result(xml_content)
        
        self.assertNotIn('error', result)
        self.assertEqual(result['tags'], 'bedroom, minimalist, white walls, wooden floor')
        self.assertEqual(result['detail'], 'A minimalist bedroom with clean lines and neutral colors.')
    
    def test_extract_partial_content(self):
        """测试部分内容提取"""
        xml_content = """
        <tags>kitchen, contemporary, stainless steel, granite countertops</tags>
        没有detail标签的内容
        """
        
        result = extract_interior_design_result(xml_content)
        
        self.assertNotIn('error', result)
        self.assertEqual(result['tags'], 'kitchen, contemporary, stainless steel, granite countertops')
        self.assertEqual(result['detail'], '')
    
    def test_extract_no_xml_content(self):
        """测试没有XML内容的情况"""
        xml_content = "这里没有任何XML标签内容"
        
        result = extract_interior_design_result(xml_content)
        
        self.assertIn('error', result)
        self.assertEqual(result['error'], 'XML_TAGS_NOT_FOUND')
    
    def test_extract_malformed_xml(self):
        """测试格式错误的XML"""
        xml_content = "<tags>incomplete tag without closing"

        result = extract_interior_design_result(xml_content)

        # 不完整的标签应该被识别为错误
        self.assertIn('error', result)
        self.assertEqual(result['error'], 'XML_TAGS_NOT_FOUND')


class TestScoreConversion(unittest.TestCase):
    """测试分数转换功能"""

    def test_score_conversion_normal_range(self):
        """测试正常范围内的分数转换"""
        test_cases = [
            (0.0, 1),    # 最小值
            (1.0, 2),    # 低分: (1/10)*8+1 = 1.8 -> 2
            (5.0, 5),    # 中等分数: (5/10)*8+1 = 5
            (8.0, 7),    # 高分: (8/10)*8+1 = 7.4 -> 7
            (10.0, 9),   # 最高分
            (8.5, 8),    # 小数分数: (8.5/10)*8+1 = 7.8 -> 8
        ]

        for input_score, expected_output in test_cases:
            with self.subTest(input_score=input_score):
                result = convert_score_to_range(input_score)
                self.assertEqual(result, expected_output)

    def test_score_conversion_edge_cases(self):
        """测试边界情况"""
        # 超出范围的分数
        self.assertEqual(convert_score_to_range(-1.0), 1)  # 负数
        self.assertEqual(convert_score_to_range(15.0), 9)  # 超过10

        # 字符串输入
        self.assertEqual(convert_score_to_range("8.0"), 7)
        self.assertEqual(convert_score_to_range("invalid"), 5)  # 无效字符串

        # None输入
        self.assertEqual(convert_score_to_range(None), 5)


class TestCheckpointManager(unittest.TestCase):
    """测试检查点管理器功能"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_file = os.path.join(self.temp_dir, 'test_checkpoint.json')
        self.manager = CheckpointManager(self.checkpoint_file, auto_save_interval=5)
    
    def tearDown(self):
        """清理测试环境"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_save_and_load_checkpoint(self):
        """测试保存和加载检查点"""
        async def run_test():
            completed = {'file1.jpg', 'file2.jpg', 'file3.jpg'}
            failed = {'file4.jpg'}
            total_files = 10
            
            # 保存检查点
            await self.manager.save_checkpoint(completed, failed, total_files)
            
            # 验证文件存在
            self.assertTrue(os.path.exists(self.checkpoint_file))
            
            # 创建新管理器实例加载检查点
            new_manager = CheckpointManager(self.checkpoint_file)
            loaded_completed, loaded_failed = await new_manager.load_checkpoint()
            
            self.assertEqual(completed, loaded_completed)
            self.assertEqual(failed, loaded_failed)
            self.assertEqual(new_manager.total_files, total_files)
        
        asyncio.run(run_test())
    
    def test_update_progress(self):
        """测试进度更新"""
        async def run_test():
            # 更新完成状态
            await self.manager.update_progress('file1.jpg', 'completed', auto_save=False)
            await self.manager.update_progress('file2.jpg', 'failed', auto_save=False)
            
            self.assertIn('file1.jpg', self.manager.completed_files)
            self.assertIn('file2.jpg', self.manager.failed_files)
            
            # 测试状态转换
            await self.manager.update_progress('file2.jpg', 'completed', auto_save=False)
            self.assertIn('file2.jpg', self.manager.completed_files)
            self.assertNotIn('file2.jpg', self.manager.failed_files)
        
        asyncio.run(run_test())
    
    def test_should_skip_file(self):
        """测试文件跳过逻辑"""
        # 添加已完成文件
        self.manager.completed_files.add('completed_file.jpg')
        
        # 测试跳过逻辑
        self.assertTrue(self.manager.should_skip_file('completed_file.jpg', force_rerun=False))
        self.assertFalse(self.manager.should_skip_file('completed_file.jpg', force_rerun=True))
        self.assertFalse(self.manager.should_skip_file('new_file.jpg', force_rerun=False))
    
    def test_progress_stats(self):
        """测试进度统计"""
        self.manager.completed_files = {'file1.jpg', 'file2.jpg'}
        self.manager.failed_files = {'file3.jpg'}
        self.manager.total_files = 10
        
        stats = self.manager.get_progress_stats()
        
        self.assertEqual(stats['completed_count'], 2)
        self.assertEqual(stats['failed_count'], 1)
        self.assertEqual(stats['processed_count'], 3)
        self.assertEqual(stats['remaining_count'], 7)
        self.assertAlmostEqual(stats['success_rate'], 66.67, places=1)
        self.assertEqual(stats['progress_percentage'], 30.0)


class TestInteriorDesignAnalyzer(unittest.TestCase):
    """测试室内设计分析器功能"""
    
    def setUp(self):
        """设置测试环境"""
        # 模拟环境变量
        self.env_patcher = patch.dict(os.environ, {
            'VLM_BATCH_API_ENDPOINT': 'https://test-api.example.com/v1/chat/completions',
            'VLM_API_TOKEN': 'test-token-12345',
            'VLM_BATCH_MODEL_NAME': 'test-model',
            'VLM_MAX_TOKENS': '16384',
            'VLM_TEMPERATURE': '0.3'
        })
        self.env_patcher.start()
        
        self.analyzer = InteriorDesignAnalyzer()
    
    def tearDown(self):
        """清理测试环境"""
        self.env_patcher.stop()
    
    def test_analyzer_initialization(self):
        """测试分析器初始化"""
        self.assertEqual(self.analyzer.api_endpoint, 'https://test-api.example.com/v1/chat/completions')
        self.assertEqual(self.analyzer.api_token, 'test-token-12345')
        self.assertEqual(self.analyzer.model_name, 'test-model')
        self.assertEqual(self.analyzer.prompt, INTERIOR_DESIGN_PROMPT)
        self.assertEqual(self.analyzer.max_4xx_retries, 2)
        self.assertEqual(self.analyzer.size_check_range, (500, 2000))
    
    def test_build_payload(self):
        """测试构建API请求负载"""
        base64_image = "test_base64_data"
        img_type = "jpeg"
        
        payload = self.analyzer._build_payload(base64_image, img_type)
        
        self.assertEqual(payload['model'], 'test-model')
        self.assertEqual(payload['max_tokens'], 16384)
        self.assertEqual(payload['temperature'], 0.3)
        self.assertEqual(len(payload['messages']), 1)
        
        message = payload['messages'][0]
        self.assertEqual(message['role'], 'user')
        self.assertEqual(len(message['content']), 2)
        
        # 检查文本内容
        text_content = message['content'][0]
        self.assertEqual(text_content['type'], 'text')
        self.assertEqual(text_content['text'], INTERIOR_DESIGN_PROMPT)
        
        # 检查图片内容
        image_content = message['content'][1]
        self.assertEqual(image_content['type'], 'image_url')
        self.assertEqual(image_content['image_url']['url'], f'data:image/{img_type};base64,{base64_image}')
    
    @patch('interior_design_analyzer.quick_validate_image')
    @patch('interior_design_analyzer.resize_to_1024px')
    def test_handle_4xx_error(self, mock_resize, mock_validate):
        """测试4XX错误处理"""
        # 模拟图片尺寸超出范围
        mock_validate.return_value = {
            'valid': True,
            'width': 3000,
            'height': 2000
        }
        mock_resize.return_value = b'resized_image_data'
        
        result = asyncio.run(self.analyzer._handle_4xx_error('test_image.jpg', 400, 0))

        self.assertEqual(result, b'resized_image_data')
        mock_validate.assert_called_once()
        mock_resize.assert_called_once_with('test_image.jpg')

    @patch('interior_design_analyzer.quick_validate_image')
    def test_handle_4xx_error_no_resize_needed(self, mock_validate):
        """测试4XX错误但不需要调整尺寸的情况"""
        # 模拟图片尺寸在合理范围内
        mock_validate.return_value = {
            'valid': True,
            'width': 1200,
            'height': 800
        }
        
        result = asyncio.run(self.analyzer._handle_4xx_error('test_image.jpg', 400, 0))
        
        self.assertIsNone(result)
        mock_validate.assert_called_once()


class TestIntegrationWorkflow(unittest.TestCase):
    """集成测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp()
        
        # 模拟环境变量
        self.env_patcher = patch.dict(os.environ, {
            'VLM_BATCH_API_ENDPOINT': 'https://test-api.example.com/v1/chat/completions',
            'VLM_API_TOKEN': 'test-token-12345',
            'VLM_BATCH_MODEL_NAME': 'test-model'
        })
        self.env_patcher.start()
    
    def tearDown(self):
        """清理测试环境"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.env_patcher.stop()
    
    def test_txt_output_format(self):
        """测试TXT文件输出格式"""
        async def run_test():
            # 创建测试TXT文件
            txt_file = os.path.join(self.temp_dir, 'test.txt')
            
            tags = "photograph, modern, living room, sofa, wooden furniture"
            detail = "A modern living room with comfortable seating and natural lighting."
            
            content_lines = [tags, detail]
            
            async with aiofiles.open(txt_file, 'w', encoding='utf-8') as f:
                await f.write('\n'.join(content_lines))
            
            # 验证文件内容
            self.assertTrue(os.path.exists(txt_file))
            
            async with aiofiles.open(txt_file, 'r', encoding='utf-8') as f:
                content = await f.read()
            
            lines = content.strip().split('\n')
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0], tags)
            self.assertEqual(lines[1], detail)
        
        asyncio.run(run_test())

    def test_score_integration_with_json(self):
        """测试从JSON文件集成score信息"""
        async def run_test():
            # 创建测试JSON文件
            json_file = os.path.join(self.temp_dir, 'test.json')
            json_data = {
                "is_ai_generated": False,
                "watermark_present": False,
                "watermark_location": "无",
                "score": 8.0,
                "feedback": "高质量图片"
            }

            async with aiofiles.open(json_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(json_data, ensure_ascii=False, indent=2))

            # 模拟score集成逻辑
            from vlm_common import convert_score_to_range

            # 读取JSON并转换score
            async with aiofiles.open(json_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)

            score_value = data['score']
            converted_score = convert_score_to_range(score_value)
            score_prefix = f'score_{converted_score}, '

            # 验证转换结果
            self.assertEqual(score_value, 8.0)
            self.assertEqual(converted_score, 7)  # (8.0/10)*8+1 = 7.4 -> round = 7
            self.assertEqual(score_prefix, 'score_7, ')

            # 测试TXT文件格式（包含score前缀）
            tags = "photograph, modern, living room"
            detail = "The image is a modern living room with comfortable seating."

            final_tags = score_prefix + tags
            content_lines = [final_tags, detail]

            txt_file = os.path.join(self.temp_dir, 'test.txt')
            async with aiofiles.open(txt_file, 'w', encoding='utf-8') as f:
                await f.write('\n'.join(content_lines))

            # 验证最终输出
            async with aiofiles.open(txt_file, 'r', encoding='utf-8') as f:
                result_content = await f.read()

            lines = result_content.strip().split('\n')
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0], 'score_7, photograph, modern, living room')
            self.assertTrue(lines[1].startswith('The image is'))

        asyncio.run(run_test())


def run_tests():
    """运行所有测试"""
    # 创建测试套件
    test_suite = unittest.TestSuite()
    
    # 添加测试类
    test_classes = [
        TestInteriorDesignXMLParser,
        TestScoreConversion,
        TestCheckpointManager,
        TestInteriorDesignAnalyzer,
        TestIntegrationWorkflow
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # 返回测试结果
    return result.wasSuccessful()


if __name__ == '__main__':
    print("🧪 运行室内设计图像分析功能测试套件...")
    print("=" * 60)
    
    success = run_tests()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败，请检查上述错误信息。")
    
    exit(0 if success else 1)
