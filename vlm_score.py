import os
import glob
import json
import re
import argparse
import base64
import asyncio
import aiohttp
import aiofiles
from tqdm.asyncio import tqdm
import xmltodict
import traceback
from dotenv import load_dotenv
import filetype
from colorama import init, Fore, Style
import time

# 初始化colorama用于彩色输出
init(autoreset=True)

# 加载环境变量
load_dotenv()

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

# 验证配置
validate_config()

# 用户定义的提示词模板（增强XML输出格式）
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

class ImageQualityAnalyzer:
    def __init__(self, model_name=None, concurrent_limit=None):
        """初始化异步API客户端，使用环境变量配置"""
        self.api_endpoint = os.getenv('VLM_API_ENDPOINT')
        self.api_token = os.getenv('VLM_API_TOKEN')
        self.model_name = model_name or os.getenv('VLM_MODEL_NAME')
        self.max_tokens = int(os.getenv('VLM_MAX_TOKENS', '16384'))
        self.temperature = float(os.getenv('VLM_TEMPERATURE', '0.3'))
        self.timeout = int(os.getenv('VLM_TIMEOUT', '180'))
        self.concurrent_limit = concurrent_limit or int(os.getenv('CONCURRENT_LIMIT', '3'))
        
        # 创建信号量控制并发
        self.semaphore = asyncio.Semaphore(self.concurrent_limit)
        
        # 构建请求头，包含认证信息
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}"
        }
    
    async def _image_to_base64(self, image_path):
        """异步将图片转换为Base64编码"""
        async with aiofiles.open(image_path, "rb") as img_file:
            content = await img_file.read()
            return base64.b64encode(content).decode('utf-8')
    
    def _build_payload(self, base64_image, img_type):
        """构建API请求负载，适配Volces API格式"""
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": USER_PROMPT
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{img_type};base64,{base64_image}",
                                "detail": "low"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }

    def _extract_xml(self, text):
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

    async def analyze_image(self, session, image_path):
        """通过VLM API异步分析单张图片"""
        async with self.semaphore:  # 控制并发数量
            try:
                # 异步读取和编码图片
                base64_image = await self._image_to_base64(image_path)
                
                # 检测图片类型
                img_type = 'jpeg'  # 默认
                try:
                    kind = filetype.guess(image_path)
                    if kind and kind.mime.startswith('image/'):
                        img_type = kind.extension
                        if img_type == 'jpg':
                            img_type = 'jpeg'
                except Exception:
                    pass
                
                # 构建请求负载
                payload = self._build_payload(base64_image, img_type)
                
                # 发送异步请求
                async with session.post(
                    self.api_endpoint,
                    headers=self.headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        error_msg = f"API错误 ({response.status})"
                        
                        try:
                            error_data = await response.json()
                            error_msg += f": {error_data.get('message', '未知错误')}"
                        except:
                            error_msg += f": {error_text[:200]}"
                        
                        return {
                            "error": "API_ERROR",
                            "message": error_msg,
                            "status_code": response.status
                        }
                    
                    # 解析响应
                    response_data = await response.json()
                    
                    # Ensure usage data is robust before it's used or saved
                    usage_data = response_data.get("usage", {})
                    usage_data.setdefault('prompt_tokens', 0)
                    usage_data.setdefault('completion_tokens', 0)
                    usage_data.setdefault('total_tokens', usage_data.get('prompt_tokens', 0) + usage_data.get('completion_tokens', 0))
                    response_data['usage'] = usage_data

                    if "choices" not in response_data or len(response_data["choices"]) == 0:
                        return {
                            "error": "NO_RESPONSE",
                            "message": "API返回了空响应"
                        }
                    
                    content = response_data["choices"][0]["message"]["content"]
                    
                    # 提取XML结果
                    result = self._extract_xml(content)
                    
                    # 添加元数据
                    if isinstance(result, dict) and "error" not in result:
                        result["api_usage"] = response_data.get("usage", {})
                        result["api_provider"] = "volces"
                    
                    return result
                    
            except asyncio.TimeoutError:
                return {
                    "error": "TIMEOUT_ERROR",
                    "message": f"请求超时 (超过 {self.timeout} 秒)"
                }
            except aiohttp.ClientError as e:
                return {
                    "error": "CONNECTION_ERROR",
                    "message": f"网络连接失败: {str(e)}"
                }
            except Exception as e:
                return {
                    "error": "EXCEPTION",
                    "message": str(e),
                    "traceback": traceback.format_exc()
                }

def find_images(root_dir, extensions=('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
    """递归查找所有图片文件"""
    all_images = []
    for ext in extensions:
        all_images.extend(glob.glob(os.path.join(root_dir, '**', f'*{ext}'), recursive=True))
        all_images.extend(glob.glob(os.path.join(root_dir, '**', f'*{ext.upper()}'), recursive=True))
    return sorted(list(set(all_images)))  # 去重并排序

async def process_single_image(analyzer, session, img_path, force_rerun, debug_mode, cost_calculator):
    """处理单个图片的异步函数（增加成本统计）"""
    json_path = os.path.splitext(img_path)[0] + '.json'
    
    # 检查是否需要重新处理
    if os.path.exists(json_path) and not force_rerun:
        return {"status": "skipped", "path": img_path}
    
    # 分析图片
    result = await analyzer.analyze_image(session, img_path)
    
    if result and "error" not in result:
        try:
            # 统计API使用成本
            if "api_usage" in result:
                cost_calculator.add_usage(result["api_usage"])
            
            # 异步保存结果
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            async with aiofiles.open(json_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(result, ensure_ascii=False, indent=2))
            return {"status": "success", "path": img_path, "result": result}
        except Exception as e:
            return {
                "status": "save_error", 
                "path": img_path, 
                "error": str(e),
                "result": result
            }
    else:
        # 即使失败也要统计请求数
        cost_calculator.total_requests += 1
        return {
            "status": "analysis_error", 
            "path": img_path, 
            "error": result
        }

async def main():
    parser = argparse.ArgumentParser(description='异步批量分析图片质量')
    parser.add_argument('root_dir', type=str, help='包含图片的根目录')
    args = parser.parse_args()

    try:
        start_time = time.time()
        
        # 初始化分析器和成本计算器
        analyzer = ImageQualityAnalyzer()
        cost_calculator = CostCalculator()
        
        # 查找所有图片
        all_images = find_images(args.root_dir)
        
        # 从环境变量读取配置
        force_rerun = os.getenv('FORCE_RERUN', 'false').lower() == 'true'
        log_file = os.getenv('LOG_FILE', 'processing_errors.jsonl')
        debug_mode = os.getenv('DEBUG_MODE', 'false').lower() == 'true'

        # 过滤需要处理的任务
        tasks_to_process = []
        skipped_count = 0
        
        for img_path in all_images:
            json_path = os.path.splitext(img_path)[0] + '.json'
            if not os.path.exists(json_path) or force_rerun:
                tasks_to_process.append(img_path)
            else:
                skipped_count += 1

        # 美化的统计信息输出
        print(f"\n{Fore.CYAN}📊 图片处理统计:{Style.RESET_ALL}")
        print(f"  📁 扫描目录: {Fore.YELLOW}{args.root_dir}{Style.RESET_ALL}")
        print(f"  🖼️  发现图片: {Fore.GREEN}{len(all_images)}{Style.RESET_ALL} 张")
        print(f"  ⏭️  已处理: {Fore.BLUE}{skipped_count}{Style.RESET_ALL} 张 (跳过)")
        print(f"  🔄 待处理: {Fore.MAGENTA}{len(tasks_to_process)}{Style.RESET_ALL} 张")
        
        if len(tasks_to_process) == 0:
            print(f"\n{Fore.GREEN}✅ 所有图片都已处理完成！{Style.RESET_ALL}")
            return 0
        
        print(f"\n{Fore.YELLOW}🚀 开始异步处理...{Style.RESET_ALL}")
        
        # 创建异步HTTP会话
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=300)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 创建所有处理任务
            processing_tasks = [
                process_single_image(analyzer, session, img_path, force_rerun, debug_mode, cost_calculator)
                for img_path in tasks_to_process
            ]
            
            # 异步执行所有任务，带进度条
            results = []
            
            # 使用tqdm的异步进度条包装asyncio.as_completed
            with tqdm(total=len(processing_tasks), desc=f"{Fore.GREEN}处理进度{Style.RESET_ALL}") as pbar:
                for coro in asyncio.as_completed(processing_tasks):
                    result = await coro
                    results.append(result)
                    pbar.update(1)
                    
                    # 实时显示处理状态
                    if result["status"] == "success":
                        pbar.set_postfix_str(f"{Fore.GREEN}✓{Style.RESET_ALL} {os.path.basename(result['path'])}")
                    elif result["status"] == "analysis_error":
                        pbar.set_postfix_str(f"{Fore.RED}✗{Style.RESET_ALL} {os.path.basename(result['path'])}")
        
        # 统计结果
        success_count = sum(1 for r in results if r["status"] == "success")
        skipped_count_new = sum(1 for r in results if r["status"] == "skipped")
        error_count = len(results) - success_count - skipped_count_new
        
        # 处理错误日志
        error_log = []
        for result in results:
            if result["status"] in ["analysis_error", "save_error"]:
                img_path = result["path"]
                if result["status"] == "analysis_error":
                    error_info = result["error"]
                    error_entry = {
                        "file": img_path,
                        "error_type": error_info.get("error", "UNKNOWN_ERROR"),
                        "message": error_info.get("message", "未知错误"),
                        "raw_output": error_info.get("raw_output", ""),
                        "traceback": error_info.get("traceback", ""),
                        "status_code": error_info.get("status_code", "")
                    }
                else:  # save_error
                    error_entry = {
                        "file": img_path,
                        "error_type": "SAVE_ERROR",
                        "message": result["error"],
                        "analysis_result": result.get("result", {})
                    }
                
                error_log.append(error_entry)
                
                # 实时显示错误信息
                print(f"\n{Fore.RED}❌ 处理失败{Style.RESET_ALL} {os.path.basename(img_path)}:")
                print(f"   {Fore.YELLOW}错误类型:{Style.RESET_ALL} {error_entry.get('error_type', 'UNKNOWN')}")
                print(f"   {Fore.YELLOW}错误信息:{Style.RESET_ALL} {error_entry.get('message', '未知错误')}")
                
                if debug_mode and error_entry.get('raw_output'):
                    print(f"   {Fore.CYAN}原始输出:{Style.RESET_ALL} {error_entry['raw_output'][:100]}...")
        
        # 计算处理时间
        end_time = time.time()
        processing_time = end_time - start_time
        
        # 最终统计输出
        print(f"\n{Fore.GREEN}🎉 处理完成！{Style.RESET_ALL}")
        print(f"  ✅ 成功: {Fore.GREEN}{success_count}{Style.RESET_ALL}/{len(tasks_to_process)}")
        print(f"  ❌ 失败: {Fore.RED}{error_count}{Style.RESET_ALL}")
        print(f"  ⏱️  耗时: {Fore.BLUE}{processing_time:.1f}{Style.RESET_ALL} 秒")
        print(f"  🚀 平均速度: {Fore.MAGENTA}{len(tasks_to_process)/processing_time:.1f}{Style.RESET_ALL} 张/秒")
        
        # 显示成本报告
        cost_report, cost_data = cost_calculator.format_cost_report(processing_time, success_count)
        print(cost_report)
        
        # 保存错误日志
        if error_log:
            async with aiofiles.open(log_file, 'w', encoding='utf-8') as f:
                for entry in error_log:
                    await f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            print(f"  📝 错误日志: {Fore.YELLOW}{log_file}{Style.RESET_ALL}")
        
        # 可选：保存成本报告到文件
        cost_report_file = os.getenv('COST_REPORT_FILE', 'cost_report.json')
        if os.getenv('SAVE_COST_REPORT', 'false').lower() == 'true':
            async with aiofiles.open(cost_report_file, 'w', encoding='utf-8') as f:
                cost_data['processing_time'] = processing_time
                cost_data['processed_images'] = success_count
                cost_data['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
                await f.write(json.dumps(cost_data, ensure_ascii=False, indent=2))
            print(f"  💰 成本报告: {Fore.YELLOW}{cost_report_file}{Style.RESET_ALL}")
                    
    except ValueError as e:
        print(f"{Fore.RED}❌ 配置错误:{Style.RESET_ALL} {e}")
        print("请确保 .env 文件存在并包含所有必需的配置项。")
        return 1
    except Exception as e:
        print(f"{Fore.RED}❌ 程序执行失败:{Style.RESET_ALL} {e}")
        if os.getenv('DEBUG_MODE', 'false').lower() == 'true':
            print(traceback.format_exc())
        return 1
        
    return 0

if __name__ == "__main__":
    exit(asyncio.run(main()))