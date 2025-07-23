#!/usr/bin/env python3
"""
InteriorDesignAnalyzer - 室内设计图像分析器
基于BatchImageQualityAnalyzer，增强4XX错误处理和自动图片调整功能
"""

import os
import asyncio
import aiohttp
import traceback
import base64
import io
from typing import Dict, Any, Optional

# 导入共享工具模块
from vlm_common import (
    image_to_base64, get_image_type, extract_interior_design_result, 
    INTERIOR_DESIGN_PROMPT, Fore, Style, resize_to_1024px, quick_validate_image
)


class InteriorDesignAnalyzer:
    """
    室内设计图像分析器
    
    特性:
    - 使用室内设计专用提示词
    - 增强的4XX错误处理（400-499状态码）
    - 自动图片尺寸检测和调整（500px-2000px范围）
    - 支持1024px目标尺寸调整
    - 提取<tags>和<detail>XML内容
    """
    
    def __init__(self, model_name=None, concurrent_limit=50000):
        """
        初始化室内设计分析器
        
        Args:
            model_name: 模型名称，默认从环境变量获取
            concurrent_limit: 并发限制（仅用于兼容性）
        """
        self.api_endpoint = os.getenv('VLM_BATCH_API_ENDPOINT')
        self.api_token = os.getenv('VLM_API_TOKEN')
        self.model_name = model_name or os.getenv('VLM_BATCH_MODEL_NAME')
        self.max_tokens = int(os.getenv('VLM_MAX_TOKENS', '16384'))
        self.temperature = float(os.getenv('VLM_TEMPERATURE', '0.3'))
        
        # 使用室内设计专用提示词
        self.prompt = INTERIOR_DESIGN_PROMPT
        
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
        
        # 4XX错误重试配置
        self.max_4xx_retries = 2
        self.size_check_range = (500, 2000)  # 尺寸检查范围
        
    def _build_payload(self, base64_image: str, img_type: str) -> Dict[str, Any]:
        """
        构建API请求负载
        
        Args:
            base64_image: Base64编码的图片数据
            img_type: 图片类型
            
        Returns:
            Dict: API请求负载
        """
        return {
            "model": self.model_name,
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": self.prompt
                }, {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{img_type};base64,{base64_image}",
                        "detail": "low"
                    }
                }]
            }],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }
    
    async def _send_request(self, session: aiohttp.ClientSession, payload: Dict[str, Any]) -> aiohttp.ClientResponse:
        """
        发送API请求
        
        Args:
            session: aiohttp会话对象
            payload: 请求负载
            
        Returns:
            aiohttp.ClientResponse: 响应对象
        """
        return await session.post(
            self.api_endpoint,
            json=payload,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
    
    async def _handle_4xx_error(self, image_path: str, status_code: int, retry_count: int = 0) -> Optional[bytes]:
        """
        处理4XX HTTP错误，检查图片尺寸并进行调整
        
        Args:
            image_path: 图片文件路径
            status_code: HTTP状态码
            retry_count: 当前重试次数
            
        Returns:
            Optional[bytes]: 调整后的图片数据，如果不需要调整则返回None
        """
        if not (400 <= status_code < 500) or retry_count >= self.max_4xx_retries:
            return None
            
        print(f"{Fore.YELLOW}🔧 处理4XX错误 (状态码: {status_code})，检查图片尺寸...{Style.RESET_ALL}")
        
        # 快速检查图片尺寸
        validation = quick_validate_image(image_path, max_size=self.size_check_range[1], min_size=self.size_check_range[0])
        
        if not validation["valid"]:
            print(f"{Fore.RED}❌ 图片无效，跳过调整{Style.RESET_ALL}")
            return None
            
        width, height = validation["width"], validation["height"]
        
        # 检查是否需要调整尺寸
        needs_resize = (
            width < self.size_check_range[0] or 
            height < self.size_check_range[0] or 
            width > self.size_check_range[1] or 
            height > self.size_check_range[1]
        )
        
        if needs_resize:
            print(f"{Fore.CYAN}📏 图片尺寸 ({width}x{height}) 超出范围 ({self.size_check_range[0]}-{self.size_check_range[1]}px)，调整到1024px{Style.RESET_ALL}")
            return resize_to_1024px(image_path)
        else:
            print(f"{Fore.GREEN}✅ 图片尺寸 ({width}x{height}) 在合理范围内{Style.RESET_ALL}")
            return None
    
    async def analyze_image(self, session: aiohttp.ClientSession, image_path: str) -> Dict[str, Any]:
        """
        分析室内设计图像
        
        Args:
            session: aiohttp会话对象
            image_path: 图片文件路径
            
        Returns:
            Dict: 分析结果，包含tags和detail字段
        """
        try:
            # 读取和编码图片
            base64_image = await image_to_base64(image_path)
            img_type = get_image_type(image_path)
            payload = self._build_payload(base64_image, img_type)
            
            # 发送初始请求
            response = await self._send_request(session, payload)
            retry_count = 0
            
            # 处理4XX错误的重试逻辑
            while 400 <= response.status < 500 and retry_count < self.max_4xx_retries:
                print(f"{Fore.YELLOW}⚠️ 收到4XX错误 (状态码: {response.status})，尝试图片调整...{Style.RESET_ALL}")
                
                # 尝试调整图片尺寸
                resized_data = await self._handle_4xx_error(image_path, response.status, retry_count)
                
                if resized_data:
                    # 使用调整后的图片重试
                    base64_image = base64.b64encode(resized_data).decode('utf-8')
                    img_type = 'jpeg'  # 调整后统一使用JPEG格式
                    payload = self._build_payload(base64_image, img_type)
                    
                    print(f"{Fore.CYAN}🔄 使用调整后的图片重试请求...{Style.RESET_ALL}")
                    response = await self._send_request(session, payload)
                    retry_count += 1
                else:
                    # 无法调整或不需要调整，退出重试循环
                    break
            
            # 处理最终响应
            if response.status == 200:
                response_data = await response.json()
                content = response_data["choices"][0]["message"]["content"]
                
                # 提取室内设计分析结果
                result = extract_interior_design_result(content)
                
                # 添加API使用信息
                if "usage" in response_data:
                    result["api_usage"] = response_data["usage"]
                
                # 添加API提供商信息
                result["api_provider"] = "batch_interior_design"
                
                return result
                
            else:
                # 处理非200状态码
                error_text = await response.text()
                return {
                    "error": f"HTTP_{response.status}",
                    "message": f"API请求失败: {response.status}",
                    "details": error_text[:500] if error_text else "无详细信息",
                    "retry_count": retry_count
                }
                
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
