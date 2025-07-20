#!/usr/bin/env python3
"""
BatchImageQualityAnalyzer - 批量推理图片质量分析器
基于vlm_score_online.py的ImageQualityAnalyzer，移除semaphore限制，支持72小时超时
"""

import os
import asyncio
import aiohttp
import traceback
import base64
import io

# 导入共享工具模块
from vlm_common import (
    image_to_base64, get_image_type, extract_xml_result, 
    USER_PROMPT, Fore, Style, resize_image_if_needed
)


class BatchImageQualityAnalyzer:
    """
    批量推理图片质量分析器
    
    特性:
    - 移除semaphore并发限制，由任务池管理
    - 72小时超长请求超时
    - 保持与在线推理相同的结果格式
    - 支持图片压缩重试机制
    """
    
    def __init__(self, model_name=None, concurrent_limit=50000):
        """
        初始化批量推理API客户端
        
        Args:
            model_name: 模型名称，默认从环境变量获取
            concurrent_limit: 并发限制（仅用于兼容性，实际不使用）
        """
        self.api_endpoint = os.getenv('VLM_BATCH_API_ENDPOINT')
        self.api_token = os.getenv('VLM_API_TOKEN')
        self.model_name = model_name or os.getenv('VLM_BATCH_MODEL_NAME')
        self.max_tokens = int(os.getenv('VLM_MAX_TOKENS', '16384'))
        self.temperature = float(os.getenv('VLM_TEMPERATURE', '0.3'))
        
        # 批量推理使用72小时超时
        self.timeout = 72 * 3600  # 72小时
        
        # 移除semaphore限制，改用任务池管理
        self.semaphore = None
        self.concurrent_limit = concurrent_limit  # 仅用于记录
        
        # 构建请求头，包含认证信息
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}"
        }
    
    def _build_payload(self, base64_image, img_type):
        """
        构建API请求负载，适配Volces API格式
        
        Args:
            base64_image: Base64编码的图片数据
            img_type: 图片类型
            
        Returns:
            Dict: API请求负载
        """
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
    
    async def _send_request(self, session, payload):
        """
        发送API请求并返回响应
        
        Args:
            session: aiohttp会话对象
            payload: 请求负载
            
        Returns:
            aiohttp.ClientResponse: HTTP响应对象
        """
        return await session.post(
            self.api_endpoint,
            headers=self.headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
    
    async def analyze_image(self, session, image_path):
        """
        通过VLM API异步分析单张图片
        移除semaphore控制，直接执行分析
        
        Args:
            session: aiohttp会话对象
            image_path: 图片文件路径
            
        Returns:
            Dict: 分析结果，格式与在线推理保持一致
        """
        # 移除 async with self.semaphore 包装，直接执行
        try:
            # 异步读取和编码图片
            base64_image = await image_to_base64(image_path)
            img_type = get_image_type(image_path)
            payload = self._build_payload(base64_image, img_type)
            
            # 首次发送异步请求
            response = await self._send_request(session, payload)
            
            # 如果遇到400错误，尝试压缩图片后重试
            if response.status == 400:
                compressed_data = resize_image_if_needed(image_path)
                if compressed_data:
                    base64_image = base64.b64encode(compressed_data).decode('utf-8')
                    # 图片类型可能因压缩而改变，这里简单处理
                    img_type = get_image_type(io.BytesIO(compressed_data))
                    payload = self._build_payload(base64_image, img_type)
                    
                    print(f"{Fore.CYAN}正在使用压缩后的图片重试...{Style.RESET_ALL}")
                    response = await self._send_request(session, payload)  # 重试
            
            # 处理非200响应
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
            
            # 添加元数据，保持与在线推理格式一致
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
    
    def get_config_info(self):
        """
        获取配置信息
        
        Returns:
            Dict: 配置信息字典
        """
        return {
            "api_endpoint": self.api_endpoint,
            "model_name": self.model_name,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "concurrent_limit": self.concurrent_limit,
            "semaphore_enabled": self.semaphore is not None
        }
