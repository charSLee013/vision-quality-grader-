#!/usr/bin/env python3
"""
VLM图片质量评分 - 在线推理版本
使用异步并发处理进行实时图片质量分析
"""

import os
import json
import argparse
import asyncio
import aiohttp
import aiofiles
from tqdm.asyncio import tqdm
import traceback
import time

# 导入共享工具模块
from vlm_common import (
    validate_config, find_images, image_to_base64, get_image_type,
    extract_xml_result, CostCalculator, USER_PROMPT,
    Fore, Style
)

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

    async def analyze_image(self, session, image_path):
        """通过VLM API异步分析单张图片"""
        async with self.semaphore:  # 控制并发数量
            try:
                # 异步读取和编码图片
                base64_image = await image_to_base64(image_path)
                
                # 检测图片类型
                img_type = get_image_type(image_path)
                
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
                    
                    if "choices" not in response_data or len(response_data["choices"]) == 0:
                        return {
                            "error": "NO_RESPONSE",
                            "message": "API返回了空响应"
                        }
                    
                    content = response_data["choices"][0]["message"]["content"]
                    
                    # 提取XML结果
                    result = extract_xml_result(content)
                    
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

async def process_single_image(analyzer, session, img_path, force_rerun, debug_mode, cost_calculator):
    """处理单个图片的异步函数"""
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
    parser = argparse.ArgumentParser(description='异步批量分析图片质量 - 在线推理版本')
    parser.add_argument('root_dir', type=str, help='包含图片的根目录')
    parser.add_argument('--force-rerun', action='store_true', help='强制重新处理已存在的结果文件')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    parser.add_argument('--concurrent-limit', type=int, help='并发限制数量')
    args = parser.parse_args()

    try:
        start_time = time.time()
        
        # 验证配置
        validate_config()
        
        # 初始化分析器和成本计算器
        analyzer = ImageQualityAnalyzer(concurrent_limit=args.concurrent_limit)
        cost_calculator = CostCalculator()
        
        # 查找所有图片
        all_images = find_images(args.root_dir)
        
        # 过滤需要处理的任务
        tasks_to_process = []
        skipped_count = 0
        
        for img_path in all_images:
            json_path = os.path.splitext(img_path)[0] + '.json'
            if not os.path.exists(json_path) or args.force_rerun:
                tasks_to_process.append(img_path)
            else:
                skipped_count += 1

        # 美化的统计信息输出
        print(f"\n{Fore.CYAN}📊 在线推理处理统计:{Style.RESET_ALL}")
        print(f"  📁 扫描目录: {Fore.YELLOW}{args.root_dir}{Style.RESET_ALL}")
        print(f"  🖼️  发现图片: {Fore.GREEN}{len(all_images)}{Style.RESET_ALL} 张")
        print(f"  ⏭️  已处理: {Fore.BLUE}{skipped_count}{Style.RESET_ALL} 张 (跳过)")
        print(f"  🔄 待处理: {Fore.MAGENTA}{len(tasks_to_process)}{Style.RESET_ALL} 张")
        
        if len(tasks_to_process) == 0:
            print(f"\n{Fore.GREEN}✅ 所有图片都已处理完成！{Style.RESET_ALL}")
            return 0
        
        print(f"\n{Fore.YELLOW}🚀 开始在线推理处理...{Style.RESET_ALL}")
        
        # 创建异步HTTP会话
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=300)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 创建所有处理任务
            processing_tasks = [
                process_single_image(analyzer, session, img_path, args.force_rerun, args.debug, cost_calculator)
                for img_path in tasks_to_process
            ]
            
            # 异步执行所有任务，带进度条
            results = []
            
            # 使用tqdm的异步进度条
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
                
                if args.debug and error_entry.get('raw_output'):
                    print(f"   {Fore.CYAN}原始输出:{Style.RESET_ALL} {error_entry['raw_output'][:100]}...")
        
        # 计算处理时间
        end_time = time.time()
        processing_time = end_time - start_time
        
        # 最终统计输出
        print(f"\n{Fore.GREEN}🎉 在线推理处理完成！{Style.RESET_ALL}")
        print(f"  ✅ 成功: {Fore.GREEN}{success_count}{Style.RESET_ALL}/{len(tasks_to_process)}")
        print(f"  ❌ 失败: {Fore.RED}{error_count}{Style.RESET_ALL}")
        print(f"  ⏱️  耗时: {Fore.BLUE}{processing_time:.1f}{Style.RESET_ALL} 秒")
        print(f"  🚀 平均速度: {Fore.MAGENTA}{len(tasks_to_process)/processing_time:.1f}{Style.RESET_ALL} 张/秒")
        
        # 显示成本报告
        cost_report, cost_data = cost_calculator.format_cost_report(processing_time, success_count)
        print(cost_report)
        
        # 保存错误日志
        if error_log:
            log_file = 'processing_errors_online.jsonl'
            async with aiofiles.open(log_file, 'w', encoding='utf-8') as f:
                for entry in error_log:
                    await f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            print(f"  📝 错误日志: {Fore.YELLOW}{log_file}{Style.RESET_ALL}")
                    
    except ValueError as e:
        print(f"{Fore.RED}❌ 配置错误:{Style.RESET_ALL} {e}")
        print("请确保 .env 文件存在并包含所有必需的配置项。")
        return 1
    except Exception as e:
        print(f"{Fore.RED}❌ 程序执行失败:{Style.RESET_ALL} {e}")
        if args.debug:
            print(traceback.format_exc())
        return 1
        
    return 0

if __name__ == "__main__":
    exit(asyncio.run(main())) 