import os
import glob
import json
import re
import base64
import time
import filetype
import xmltodict
import traceback
import aiofiles
from dotenv import load_dotenv
from colorama import init, Fore, Style
from PIL import Image
import io
from typing import Optional, Dict

# 初始化colorama用于彩色输出
init(autoreset=True)

# 加载环境变量
load_dotenv()

# 用户定义的提示词模板
USER_PROMPT = """你是一个专业的图片质量评估专家，具备以下能力：
1. **图像来源分析**：
   - **AI生成检测**：检查图片是否存在以下特征（任一即可判定为AI生成）：
     - 过度平滑的纹理（如皮肤无毛孔、植被无细节）。
     - 不自然的光影（如光源方向矛盾、阴影不符合物理规律）。
     - 异常完美的构图（如完全对称且无拍摄抖动痕迹）。
     - 非现实元素（如人物手指数量异常、物体比例失真）。
   - **真实照片特征**：判断是否符合真实拍摄条件（如存在噪点、轻微模糊、自然景深）。

2. **水印检测**：
   - 分析全图是否存在可见水印（如品牌LOGO、版权文字），描述位置和显著性。

3. **质量评分维度**：
   - **清晰度**：分辨率是否足够，是否存在模糊或压缩伪影。
   - **构图**：画面布局是否美观，主体是否突出。
   - **色彩**：色调是否自然，是否存在过曝或欠曝。
   - **内容相关性**：图片内容是否符合现实逻辑（如人物表情自然、场景无异常）。

4. **综合评分规则**：
   - **基础分**：按权重计算总分（清晰度40%，构图30%，色彩20%，内容10%）。
   - **AI生成惩罚**：若检测为AI生成，总分直接扣除 **2.0分**（最低分保留0分）。
   - **最终等级**：
     - ≥8.5：高质量（真实照片且无明显缺陷）。
     - 7.0-8.4：中等质量（真实照片但有轻微缺陷）。
     - <7.0：低质量（AI生成或严重缺陷）。

5. **输出规范**：
   - 首先用自然语言详细分析图片质量各个维度
   - 最后必须输出纯净的XML格式结果，严格按以下格式：

<result>
<is_ai_generated>true或false</is_ai_generated>
<watermark_present>true或false</watermark_present>
<watermark_location>水印位置描述或无</watermark_location>
<score>数字得分</score>
<feedback>简要评分理由</feedback>
</result>

重要：XML部分必须是纯净格式，不要用markdown代码块包装，不要有额外的格式化符号。
"""

def validate_config():
    """验证必需的环境变量配置"""
    required_vars = ['VLM_API_ENDPOINT', 'VLM_API_TOKEN', 'VLM_MODEL_NAME']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        raise ValueError(f"缺少必需的环境变量: {', '.join(missing_vars)}。请检查 .env 文件配置。")
    
    # 打印配置信息（掩码敏感信息）
    token = os.getenv('VLM_API_TOKEN', '')
    masked_token = token[:8] + '*' * (len(token) - 12) + token[-4:] if len(token) > 12 else '***'
    
    print(f"{Fore.GREEN}✓ 配置加载完成:{Style.RESET_ALL}")
    print(f"  🌐 API端点: {Fore.CYAN}{os.getenv('VLM_API_ENDPOINT')}{Style.RESET_ALL}")
    print(f"  🔑 API令牌: {Fore.YELLOW}{masked_token}{Style.RESET_ALL}")
    print(f"  🤖 模型名称: {Fore.MAGENTA}{os.getenv('VLM_MODEL_NAME')}{Style.RESET_ALL}")
    print(f"  🚀 并发数量: {Fore.BLUE}{os.getenv('CONCURRENT_LIMIT', '3')}{Style.RESET_ALL}")
    
    # 返回配置字典
    return {
        'api_base': os.getenv('VLM_API_ENDPOINT'),
        'api_key': os.getenv('VLM_API_TOKEN'),
        'model_name': os.getenv('VLM_MODEL_NAME'),
        'max_tokens': int(os.getenv('VLM_MAX_TOKENS', '16384')),
        'temperature': float(os.getenv('VLM_TEMPERATURE', '0.3')),
        'timeout': int(os.getenv('VLM_TIMEOUT', '180')),
        'concurrent_limit': int(os.getenv('CONCURRENT_LIMIT', '3'))
    }

def find_images(root_dir, extensions=('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
    """递归查找所有图片文件"""
    all_images = []
    for ext in extensions:
        all_images.extend(glob.glob(os.path.join(root_dir, '**', f'*{ext}'), recursive=True))
        all_images.extend(glob.glob(os.path.join(root_dir, '**', f'*{ext.upper()}'), recursive=True))
    return sorted(list(set(all_images)))  # 去重并排序

async def image_to_base64(image_path):
    """异步将图片转换为Base64编码"""
    async with aiofiles.open(image_path, "rb") as img_file:
        content = await img_file.read()
        return base64.b64encode(content).decode('utf-8')

def get_image_type(image_path: str) -> str:
    """检测图片类型"""
    img_type = 'jpeg'  # 默认
    try:
        kind = filetype.guess(image_path)
        if kind and kind.mime.startswith('image/'):
            img_type = kind.extension
            if img_type == 'jpg':
                img_type = 'jpeg'
    except Exception:
        return 'jpeg' # 默认
    return img_type

def resize_image_if_needed(image_path: str, max_size: int = 2000) -> Optional[bytes]:
    """
    如果图片尺寸超过最大值，则进行等比压缩。

    Args:
        image_path: 图片文件路径。
        max_size: 允许的最大尺寸（宽或高）。

    Returns:
        如果进行了压缩，则返回压缩后的图片二进制数据 (bytes)；否则返回 None。
    """
    try:
        with Image.open(image_path) as img:
            # 检查是否包含有效的图像数据
            try:
                img.verify()
                # 重新打开以进行操作
                img = Image.open(image_path)
            except Exception:
                # 对于损坏的或非标准图像，直接跳过压缩
                return None

            width, height = img.size
            if width > max_size or height > max_size:
                print(f"{Fore.YELLOW}图片尺寸 ({width}x{height}) 超出 {max_size}px，尝试压缩...{Style.RESET_ALL}")
                
                # 计算等比缩放后的尺寸
                if width > height:
                    new_width = max_size
                    new_height = int(max_size * height / width)
                else:
                    new_height = max_size
                    new_width = int(max_size * width / height)
                
                # 使用高质量的LANCZOS采样进行缩放
                resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # 将压缩后的图片保存到内存
                byte_arr = io.BytesIO()
                # 确定原始格式以进行保存
                img_format = img.format if img.format in ['JPEG', 'PNG', 'WEBP'] else 'JPEG'
                resized_img.save(byte_arr, format=img_format)
                
                return byte_arr.getvalue()
    except FileNotFoundError:
        # 文件不存在，无法处理
        return None
    except Exception as e:
        # 捕获所有其他Pillow相关的异常
        print(f"{Fore.RED}处理图片时发生错误: {e}{Style.RESET_ALL}")
        return None
        
    return None

def extract_xml_result(text: str) -> Dict:
    """从模型输出中提取XML内容（增强鲁棒性）"""
    try:
        # 策略1: 提取<result>标签块（最常见）
        xml_patterns = [
            r'<result[^>]*>(.*?)</result>',  # 标准result标签
            r'```xml\s*<result[^>]*>(.*?)</result>\s*```',  # markdown包装的XML
            r'```\s*<result[^>]*>(.*?)</result>\s*```',  # 无xml标识的代码块
            r'<result[^>]*>(.*?)(?=\n\n|\Z)',  # 不完整的result标签
        ]
        
        xml_content = None
        for pattern in xml_patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                xml_content = f"<result>{match.group(1)}</result>"
                break
        
        # 策略2: 如果找不到result标签，尝试提取独立的XML字段
        if not xml_content:
            xml_fields = {}
            field_patterns = {
                'is_ai_generated': r'<is_ai_generated[^>]*>(.*?)</is_ai_generated>',
                'watermark_present': r'<watermark_present[^>]*>(.*?)</watermark_present>',
                'watermark_location': r'<watermark_location[^>]*>(.*?)</watermark_location>',
                'score': r'<score[^>]*>(.*?)</score>',
                'feedback': r'<feedback[^>]*>(.*?)</feedback>'
            }
            
            for field, pattern in field_patterns.items():
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    xml_fields[field] = match.group(1).strip()
            
            if xml_fields:
                # 重建XML
                xml_parts = ['<result>']
                for field, value in xml_fields.items():
                    xml_parts.append(f'<{field}>{value}</{field}>')
                xml_parts.append('</result>')
                xml_content = ''.join(xml_parts)
        
        if not xml_content:
            return {
                "error": "XML_NOT_FOUND",
                "raw_output": text[:500] + "..." if len(text) > 500 else text
            }
        
        # 清理XML内容
        xml_content = re.sub(r'```xml\s*', '', xml_content)
        xml_content = re.sub(r'\s*```', '', xml_content)
        xml_content = xml_content.strip()
        
        # 解析XML
        try:
            result_dict = xmltodict.parse(xml_content, dict_constructor=dict)['result']
        except Exception as parse_error:
            # 如果xmltodict失败，尝试手动解析
            manual_result = {}
            for field in ['is_ai_generated', 'watermark_present', 'watermark_location', 'score', 'feedback']:
                pattern = f'<{field}[^>]*>(.*?)</{field}>'
                match = re.search(pattern, xml_content, re.DOTALL | re.IGNORECASE)
                if match:
                    manual_result[field] = match.group(1).strip()
            
            if manual_result:
                result_dict = manual_result
            else:
                raise parse_error
        
        # 类型转换和验证
        processed = {}
        for key, value in result_dict.items():
            key = key.lower().strip()
            if key in ['is_ai_generated', 'watermark_present']:
                processed[key] = str(value).lower() in ['true', 'yes', '1', 'True']
            elif key == 'score':
                try:
                    if isinstance(value, str):
                        # 提取数字
                        num_match = re.search(r'(\d+\.?\d*)', value)
                        processed[key] = round(float(num_match.group(1)), 1) if num_match else 0.0
                    else:
                        processed[key] = round(float(value), 1)
                    # 确保分数在合理范围内
                    processed[key] = max(0.0, min(10.0, processed[key]))
                except:
                    processed[key] = 0.0
            else:
                processed[key] = str(value).strip() if value else ''
        
        # 确保所有必需字段都存在
        required_fields = {
            'is_ai_generated': False,
            'watermark_present': False,
            'watermark_location': '无',
            'score': 0.0,
            'feedback': '解析成功'
        }
        
        for field, default_value in required_fields.items():
            if field not in processed:
                processed[field] = default_value
        
        return processed
        
    except Exception as e:
        return {
            "error": f"XML_PARSING_ERROR: {str(e)}",
            "raw_output": text[:500] + "..." if len(text) > 500 else text,
            "traceback": traceback.format_exc()
        }

class CostCalculator:
    """API成本计算器"""
    
    def __init__(self):
        # 豆包模型定价（元/百万token）
        self.input_price = 0.15  # 输入token价格
        self.output_price = 1.50  # 输出token价格
        
        # 统计数据
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_reasoning_tokens = 0
        self.total_requests = 0
        self.successful_requests = 0
        
    def add_usage(self, api_usage):
        """添加API使用统计"""
        if not api_usage:
            return
            
        self.total_requests += 1
        self.successful_requests += 1
        
        # 基础token统计
        self.total_prompt_tokens += api_usage.get('prompt_tokens', 0)
        self.total_completion_tokens += api_usage.get('completion_tokens', 0)
        
        # reasoning_tokens统计（属于输出token）
        completion_details = api_usage.get('completion_tokens_details', {})
        reasoning_tokens = completion_details.get('reasoning_tokens', 0)
        self.total_reasoning_tokens += reasoning_tokens
    
    def calculate_cost(self):
        """计算总费用（人民币）"""
        # 输入成本
        input_cost = (self.total_prompt_tokens / 1_000_000) * self.input_price
        
        # 输出成本（包含reasoning_tokens）
        total_output_tokens = self.total_completion_tokens + self.total_reasoning_tokens
        output_cost = (total_output_tokens / 1_000_000) * self.output_price
        
        total_cost = input_cost + output_cost
        
        return {
            'input_tokens': self.total_prompt_tokens,
            'output_tokens': self.total_completion_tokens,
            'reasoning_tokens': self.total_reasoning_tokens,
            'total_output_tokens': total_output_tokens,
            'input_cost': input_cost,
            'output_cost': output_cost,
            'total_cost': total_cost,
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests
        }
    
    def format_cost_report(self, processing_time=0, image_count=0):
        """格式化成本报告"""
        cost_data = self.calculate_cost()
        
        report = f"\n{Fore.CYAN}💰 成本分析报告:{Style.RESET_ALL}\n"
        report += f"{'='*50}\n"
        
        # Token使用统计
        report += f"{Fore.YELLOW}📊 Token使用统计:{Style.RESET_ALL}\n"
        report += f"  🔤 输入Token:     {Fore.GREEN}{cost_data['input_tokens']:,}{Style.RESET_ALL}\n"
        report += f"  📝 输出Token:     {Fore.GREEN}{cost_data['output_tokens']:,}{Style.RESET_ALL}\n"
        if cost_data['reasoning_tokens'] > 0:
            report += f"  🧠 推理Token:     {Fore.BLUE}{cost_data['reasoning_tokens']:,}{Style.RESET_ALL}\n"
        report += f"  📊 总输出Token:   {Fore.MAGENTA}{cost_data['total_output_tokens']:,}{Style.RESET_ALL}\n"
        
        # 费用计算
        report += f"\n{Fore.YELLOW}💳 费用计算:{Style.RESET_ALL}\n"
        report += f"  💵 输入费用:     {Fore.GREEN}¥{cost_data['input_cost']:.4f}{Style.RESET_ALL}\n"
        report += f"  💵 输出费用:     {Fore.GREEN}¥{cost_data['output_cost']:.4f}{Style.RESET_ALL}\n"
        report += f"  💰 总费用:       {Fore.RED}¥{cost_data['total_cost']:.4f}{Style.RESET_ALL}\n"
        
        # 平均成本
        if image_count > 0:
            avg_cost = cost_data['total_cost'] / image_count
            report += f"  📷 单张图片成本: {Fore.CYAN}¥{avg_cost:.4f}{Style.RESET_ALL}\n"
        
        # 请求统计
        report += f"\n{Fore.YELLOW}📈 请求统计:{Style.RESET_ALL}\n"
        report += f"  ✅ 成功请求:     {Fore.GREEN}{cost_data['successful_requests']}{Style.RESET_ALL}\n"
        report += f"  📊 总请求数:     {Fore.BLUE}{cost_data['total_requests']}{Style.RESET_ALL}\n"
        
        # 效率统计
        if processing_time > 0:
            cost_per_second = cost_data['total_cost'] / processing_time
            report += f"  ⏱️  每秒成本:     {Fore.MAGENTA}¥{cost_per_second:.6f}{Style.RESET_ALL}\n"
        
        report += f"{'='*50}\n"
        
        return report, cost_data 