
import os
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
import glob
try:
    import imagesize
    IMAGESIZE_AVAILABLE = True
except ImportError:
    IMAGESIZE_AVAILABLE = False
    print("Warning: imagesize library not available. Using fallback method for image validation.")

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

# 室内设计分析提示词模板
INTERIOR_DESIGN_PROMPT = """你是一个专业的视觉语言模型(VLM)，专门分析室内设计图像。请严格按以下步骤处理用户提供的图片：

1. **元素识别** - 扫描整体场景：建筑风格、空间类型、主色调
- 识别家具：类型/材质/颜色（如"green velvet sofa"）
- 捕捉装饰品：灯具/植物/艺术品/摆件
- 分析氛围特征：照明/质感/风格关键词

2. **标签生成规则**（输出至<tags>）
- 层级排序：
a) 图像类型 → b) 设计风格 → c) 空间类型 → d) 背景特征 → e) 主要家具大类 → f) 具体家具细节 → g) 装饰元素 → h) 风格形容词 → i) 氛围关键词
- 示例排序链：[photograph] > [mid-century modern] > [living room] > [green background] > [wooden furniture] > [green velvet sofa] > [glass lamp] > [retro style] > [cozy]

3. **详细描述规则**（输出至<detail>）
- 必须以"The image is"开头，采用流畅的叙述性描述
- 描述整体场景和主要元素：
• 空间类型和设计风格
• 主要家具和装饰品（带材质/颜色）
• 空间布局和物品摆放
• 色彩搭配和氛围特征
- 结尾总结：整体风格特征和设计亮点

4. **输出格式要求**
- 严格使用以下结构：
<tags>按层级排序的逗号分隔标签</tags>
<detail>方位描述文本，以风格总结结尾</detail>
- 标签数量：20-30个
- 描述长度：100-150单词

5. **禁止行为**
- 添加解释性文字
- 使用markdown符号
- 改变XML标签结构
"""

def validate_config():
    """验证在线推理的必需环境变量配置"""
    required_vars = ['VLM_ONLINE_API_ENDPOINT', 'VLM_API_TOKEN', 'VLM_ONLINE_MODEL_NAME']
    missing_vars = []

    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        raise ValueError(f"缺少必需的环境变量: {', '.join(missing_vars)}。请检查 .env 文件配置。")

    # 打印配置信息（掩码敏感信息）
    token = os.getenv('VLM_API_TOKEN', '')
    masked_token = token[:8] + '*' * (len(token) - 12) + token[-4:] if len(token) > 12 else '***'

    print("Configuration loaded:")
    print(f"  API endpoint: {os.getenv('VLM_ONLINE_API_ENDPOINT')}")
    print(f"  API token: {masked_token}")
    print(f"  Model name: {os.getenv('VLM_ONLINE_MODEL_NAME')}")
    print(f"  Concurrent limit: {os.getenv('CONCURRENT_LIMIT', '3')}")

    # 返回配置字典
    return {
        'api_base': os.getenv('VLM_ONLINE_API_ENDPOINT'),
        'api_key': os.getenv('VLM_API_TOKEN'),
        'model_name': os.getenv('VLM_ONLINE_MODEL_NAME'),
        'max_tokens': int(os.getenv('VLM_MAX_TOKENS', '16384')),
        'temperature': float(os.getenv('VLM_TEMPERATURE', '0.3')),
        'timeout': int(os.getenv('VLM_TIMEOUT', '180')),
        'concurrent_limit': int(os.getenv('CONCURRENT_LIMIT', '3'))
    }


def validate_batch_config():
    """验证批量推理的必需环境变量配置"""
    required_vars = ['VLM_BATCH_API_ENDPOINT', 'VLM_API_TOKEN', 'VLM_BATCH_MODEL_NAME']
    missing_vars = []

    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        raise ValueError(f"缺少必需的环境变量: {', '.join(missing_vars)}。请检查 .env 文件配置。")

    # 打印配置信息（掩码敏感信息）
    token = os.getenv('VLM_API_TOKEN', '')
    masked_token = token[:8] + '*' * (len(token) - 12) + token[-4:] if len(token) > 12 else '***'

    print("Configuration loaded:")
    print(f"  API endpoint: {os.getenv('VLM_BATCH_API_ENDPOINT')}")
    print(f"  API token: {masked_token}")
    print(f"  Model name: {os.getenv('VLM_BATCH_MODEL_NAME')}")
    print(f"  Concurrent limit: {os.getenv('CONCURRENT_LIMIT', '3')}")

    # 返回配置字典
    return {
        'api_base': os.getenv('VLM_BATCH_API_ENDPOINT'),
        'api_key': os.getenv('VLM_API_TOKEN'),
        'model_name': os.getenv('VLM_BATCH_MODEL_NAME'),
        'max_tokens': int(os.getenv('VLM_MAX_TOKENS', '16384')),
        'temperature': float(os.getenv('VLM_TEMPERATURE', '0.3')),
        'timeout': int(os.getenv('VLM_TIMEOUT', '180')),
        'concurrent_limit': int(os.getenv('CONCURRENT_LIMIT', '3'))
    }

def find_images(root_dir, extensions=('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
    """
    高性能递归查找所有图片文件 - 使用os.walk()优化

    相比原glob实现的优化:
    - 使用os.walk()替代glob.glob()，性能提升3-10倍
    - 单次遍历即可处理所有扩展名，减少重复IO
    - 内存效率更高，适合100K+大数据集

    Args:
        root_dir: 根目录路径
        extensions: 支持的文件扩展名元组

    Returns:
        List[str]: 排序后的图片文件路径列表（与原函数完全兼容）
    """
    # 验证输入目录
    if not os.path.exists(root_dir):
        return []

    if not os.path.isdir(root_dir):
        return []

    # 创建扩展名集合（包含大小写变体）- 一次性处理避免重复检查
    ext_set = set()
    for ext in extensions:
        ext_set.add(ext.lower())
        ext_set.add(ext.upper())

    # 使用set收集图片文件，自动去重
    image_files = set()

    try:
        # 使用os.walk进行高效递归遍历
        for root, dirs, files in os.walk(root_dir):
            # 批量处理当前目录下的所有文件
            for file in files:
                # 获取文件扩展名并检查
                _, ext = os.path.splitext(file)
                if ext in ext_set:
                    image_files.add(os.path.join(root, file))

    except (PermissionError, OSError) as e:
        # 处理权限错误或其他IO错误，继续处理其他目录
        # 保持与原函数相同的错误处理行为
        print(f"{Fore.YELLOW}警告: 扫描目录时遇到错误: {e}{Style.RESET_ALL}")

    # 返回排序后的列表（保持与原函数完全相同的行为）
    return sorted(list(image_files))

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

def quick_validate_image(image_path: str, max_size: int = 2000, min_size: int = 100) -> dict:
    """
    快速验证图片尺寸，性能损耗极小

    优先使用 imagesize 库只读取图片头部信息，避免加载完整图片到内存。
    如果 imagesize 不可用，则回退到 PIL 方法。

    Args:
        image_path: 图片文件路径
        max_size: 最大尺寸限制（宽或高）
        min_size: 最小尺寸限制（宽或高）

    Returns:
        dict: 验证结果
            - valid (bool): 是否通过验证
            - width (int): 图片宽度
            - height (int): 图片高度
            - reason (str): 验证结果说明
            - needs_resize (bool): 是否需要压缩
    """
    try:
        # 优先使用 imagesize 库快速获取尺寸
        if IMAGESIZE_AVAILABLE:
            width, height = imagesize.get(image_path)
        else:
            # 回退到 PIL 方法
            with Image.open(image_path) as img:
                width, height = img.size

        # 检查尺寸有效性
        if width <= 0 or height <= 0:
            return {
                "valid": False,
                "width": 0,
                "height": 0,
                "reason": "invalid_dimensions",
                "needs_resize": False
            }

        # 检查最小尺寸限制
        if width < min_size or height < min_size:
            return {
                "valid": False,
                "width": width,
                "height": height,
                "reason": "too_small",
                "needs_resize": False
            }

        # 检查最大尺寸限制
        if width > max_size or height > max_size:
            return {
                "valid": True,  # 尺寸过大但可以压缩处理
                "width": width,
                "height": height,
                "reason": "needs_resize",
                "needs_resize": True
            }

        # 尺寸合适
        return {
            "valid": True,
            "width": width,
            "height": height,
            "reason": "ok",
            "needs_resize": False
        }

    except Exception as e:
        return {
            "valid": False,
            "width": 0,
            "height": 0,
            "reason": f"error: {str(e)}",
            "needs_resize": False
        }

def resize_image_if_needed(image_path: str, max_size: int = 2000) -> Optional[bytes]:
    """
    优化版本：先快速检查尺寸，再决定是否加载图片

    使用 imagesize 库进行预检查，避免不必要的图片加载，
    大幅提升批量处理性能。

    Args:
        image_path: 图片文件路径。
        max_size: 允许的最大尺寸（宽或高）。

    Returns:
        如果进行了压缩，则返回压缩后的图片二进制数据 (bytes)；否则返回 None。
    """
    # 第一步：快速检查尺寸，避免加载完整图片
    validation = quick_validate_image(image_path, max_size)

    if not validation["valid"]:
        # 图片无效或过小，直接返回
        return None

    if not validation["needs_resize"]:
        # 尺寸合适，无需处理
        return None

    # 第二步：只有确实需要压缩时才加载完整图片
    try:
        width, height = validation["width"], validation["height"]
        print(f"{Fore.YELLOW}图片尺寸 ({width}x{height}) 超出 {max_size}px，尝试压缩...{Style.RESET_ALL}")

        with Image.open(image_path) as img:
            # 检查是否包含有效的图像数据
            try:
                img.verify()
                # 重新打开以进行操作
                img = Image.open(image_path)
            except Exception:
                # 对于损坏的或非标准图像，直接跳过压缩
                return None

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

def resize_to_1024px(image_path: str) -> Optional[bytes]:
    """
    将图片调整到1024px（用于4XX错误处理）

    专门用于处理4XX HTTP错误时的图片尺寸调整，
    将图片调整到1024px以确保在VLM API的最佳处理范围内。

    Args:
        image_path: 图片文件路径

    Returns:
        Optional[bytes]: 调整后的图片二进制数据，失败时返回None
    """
    try:
        with Image.open(image_path) as img:
            # 验证图片有效性
            try:
                img.verify()
                img = Image.open(image_path)  # 重新打开进行操作
            except Exception:
                return None

            width, height = img.size
            target_size = 1024

            print(f"{Fore.CYAN}4XX错误处理：将图片从 ({width}x{height}) 调整到 1024px{Style.RESET_ALL}")

            # 计算新尺寸，保持宽高比
            if width > height:
                new_width = target_size
                new_height = int(target_size * height / width)
            else:
                new_height = target_size
                new_width = int(target_size * width / height)

            # 使用高质量LANCZOS重采样
            resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # 保存到内存
            byte_arr = io.BytesIO()
            img_format = img.format if img.format in ['JPEG', 'PNG', 'WEBP'] else 'JPEG'
            resized_img.save(byte_arr, format=img_format)

            return byte_arr.getvalue()

    except Exception as e:
        print(f"{Fore.RED}1024px调整失败: {e}{Style.RESET_ALL}")
        return None

def convert_score_to_range(score: float) -> int:
    """
    将0-10分数转换为1-9整数范围

    用于将JSON文件中的score字段转换为适合标签的整数格式

    Args:
        score: 原始分数 (0.0-10.0)

    Returns:
        int: 转换后的分数 (1-9)
    """
    try:
        # 确保输入在合理范围内
        score = max(0.0, min(10.0, float(score)))

        # 转换公式：将0-10映射到1-9
        # 使用线性映射：(score / 10) * 8 + 1
        # 这样0->1, 10->9, 5->5
        if score == 0:
            return 1
        elif score == 10:
            return 9
        else:
            # 线性插值映射
            converted = round((score / 10.0) * 8 + 1)
            return max(1, min(9, converted))

    except (ValueError, TypeError):
        # 如果转换失败，返回默认值5
        return 5

def extract_interior_design_result(text: str) -> Dict:
    """
    从模型输出中提取室内设计分析结果

    提取<tags>和<detail>XML元素，用于室内设计图像分析

    Args:
        text: 模型的原始输出文本

    Returns:
        Dict: 包含'tags'和'detail'字段的字典，或包含'error'字段的错误信息
    """
    try:
        # 提取<tags>标签内容
        tags_pattern = r'<tags[^>]*>(.*?)</tags>'
        tags_match = re.search(tags_pattern, text, re.DOTALL | re.IGNORECASE)

        # 提取<detail>标签内容
        detail_pattern = r'<detail[^>]*>(.*?)</detail>'
        detail_match = re.search(detail_pattern, text, re.DOTALL | re.IGNORECASE)

        result = {}

        # 处理tags内容
        if tags_match:
            tags_content = tags_match.group(1).strip()
            # 清理可能的markdown标记和多余空白
            tags_content = re.sub(r'```[a-zA-Z]*\s*', '', tags_content)
            tags_content = re.sub(r'\s*```', '', tags_content)
            tags_content = re.sub(r'\s+', ' ', tags_content)
            result['tags'] = tags_content
        else:
            result['tags'] = ''

        # 处理detail内容
        if detail_match:
            detail_content = detail_match.group(1).strip()
            # 清理可能的markdown标记
            detail_content = re.sub(r'```[a-zA-Z]*\s*', '', detail_content)
            detail_content = re.sub(r'\s*```', '', detail_content)
            # 保持段落结构，但清理多余空白
            detail_content = re.sub(r'\n\s*\n', '\n', detail_content)
            detail_content = re.sub(r'[ \t]+', ' ', detail_content)
            result['detail'] = detail_content
        else:
            result['detail'] = ''

        # 如果两个字段都为空，返回错误
        if not result['tags'] and not result['detail']:
            return {
                "error": "XML_TAGS_NOT_FOUND",
                "message": "未找到<tags>或<detail>标签",
                "raw_output": text[:500] + "..." if len(text) > 500 else text
            }

        return result

    except Exception as e:
        return {
            "error": "XML_PARSING_ERROR",
            "message": f"XML解析失败: {str(e)}",
            "raw_output": text[:500] + "..." if len(text) > 500 else text,
            "traceback": traceback.format_exc()
        }

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

        report = "\nCost Analysis Report:\n"
        report += "-" * 40 + "\n"

        # Token使用统计
        report += "Token Usage:\n"
        report += f"  Input tokens: {cost_data['input_tokens']:,}\n"
        report += f"  Output tokens: {cost_data['output_tokens']:,}\n"
        if cost_data['reasoning_tokens'] > 0:
            report += f"  Reasoning tokens: {cost_data['reasoning_tokens']:,}\n"
        report += f"  Total output tokens: {cost_data['total_output_tokens']:,}\n"

        # 费用计算
        report += "\nCost Breakdown:\n"
        report += f"  Input cost: ¥{cost_data['input_cost']:.4f}\n"
        report += f"  Output cost: ¥{cost_data['output_cost']:.4f}\n"
        report += f"  Total cost: ¥{cost_data['total_cost']:.4f}\n"

        # 平均成本
        if image_count > 0:
            avg_cost = cost_data['total_cost'] / image_count
            report += f"  Cost per image: ¥{avg_cost:.4f}\n"

        # 请求统计
        report += "\nRequest Statistics:\n"
        report += f"  Successful requests: {cost_data['successful_requests']}\n"
        report += f"  Total requests: {cost_data['total_requests']}\n"

        # 效率统计
        if processing_time > 0:
            cost_per_second = cost_data['total_cost'] / processing_time
            report += f"  Cost per second: ¥{cost_per_second:.6f}\n"

        report += "-" * 40 + "\n"

        return report, cost_data


