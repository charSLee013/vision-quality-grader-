# VLM图像质量评分工具

一个基于火山引擎视觉大模型(VLM)的智能图像质量评分工具，提供专业的图片质量分析和评估服务。

## ✨ 主要特性

- **智能评分**: 基于先进的视觉大模型，提供10分制专业评分
- **多维度分析**: 涵盖技术质量、构图美学、内容质量等多个维度
- **AI检测**: 自动识别AI生成图片和水印
- **批量处理**: 支持目录递归扫描，自动处理大量图片
- **异步高效**: 异步并发处理，大幅提升处理速度
- **结果保存**: 自动生成详细的JSON格式分析报告
- **成本追踪**: 实时监控API调用成本和token使用情况
- **容错机制**: 智能重试和错误处理，确保处理稳定性
- **优雅中断**: 支持`Ctrl+C`优雅停止，保存处理进度

## 📦 项目结构

```
vlm_score/
├── vlm_common.py           # 共享工具模块
├── vlm_score_online.py     # 在线推理脚本
├── test_vlm_common.py      # 公共模块测试
├── README.md              # 项目说明文档
└── requirements.txt       # 依赖包列表
```

## 🛠 安装配置

### 1. 环境要求
- Python 3.7+
- 支持的操作系统: Windows、macOS、Linux

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 环境变量配置
创建`.env`文件或设置系统环境变量:

```bash
# 必需配置
export VLM_API_BASE="https://ark.cn-beijing.volces.com"
export VLM_API_KEY="your_api_key_here"
export VLM_MODEL_NAME="doubao-vision-pro-32k"

# 可选配置
export VLM_MAX_CONCURRENT="5"  # 并发请求数，默认5
```

### 4. 验证安装
```bash
python vlm_score_online.py --help
```

## 🎯 使用指南

### 在线推理模式

适用于图片的实时处理，支持高并发异步处理。

```bash
# 基本用法
python vlm_score_online.py --root-dir ./images

# 指定并发数
python vlm_score_online.py --root-dir ./images --max-concurrent 10

# 查看帮助
python vlm_score_online.py --help
```

**输出**: 在每个图片同级目录生成对应的`.json`结果文件。

## 📊 输出格式

### 单张图片结果示例
```json
{
    "image_path": "/path/to/image.jpg",
    "timestamp": "2024-12-03T10:30:45",
    "analysis_result": {
        "is_ai_generated": "false",
        "watermark_present": "false", 
        "watermark_location": "none",
        "score": "8.5",
        "feedback": "图片清晰度较好，色彩自然，构图合理。细节丰富，整体质量优秀。"
    },
    "cost_info": {
        "prompt_tokens": 1024,
        "completion_tokens": 150,
        "total_tokens": 1174,
        "total_cost": 0.0024,
        "cost_cny": 0.0168
    }
}
```

## 🔧 API参考

### vlm_common模块

#### 配置验证
```python
from vlm_common import validate_config
config = validate_config()
```

#### 图片处理
```python
from vlm_common import find_images, image_to_base64
images = find_images("/path/to/images")
base64_data = await image_to_base64("/path/to/image.jpg")
```

#### XML结果解析
```python
from vlm_common import extract_xml_result
result = extract_xml_result(api_response_text)
```

#### 成本计算
```python
from vlm_common import CostCalculator
calculator = CostCalculator()
cost_info = calculator.calculate_cost(prompt_tokens=1000, completion_tokens=200)
```

## 🧪 测试

### 运行测试
```bash
# 测试公共模块
python test_vlm_common.py

# 或者使用unittest发现
python -m unittest discover -s . -p "test_*.py" -v
```

### 测试覆盖
- ✅ 配置验证测试
- ✅ 图片文件发现测试
- ✅ Base64转换测试
- ✅ XML解析测试
- ✅ 成本计算测试

## 📝 评分标准

系统基于以下维度对图像进行专业质量评估:

### 评分维度
1. **技术质量** (40%)
   - 清晰度和锐度
   - 曝光和对比度
   - 色彩还原准确性
   - 噪点和失真控制

2. **构图美学** (30%)
   - 构图平衡和比例
   - 视觉焦点和引导
   - 创意性和独特性

3. **内容质量** (20%)
   - 主题明确性
   - 内容丰富度
   - 表达效果

4. **AI生成检测** (10%)
   - AI痕迹识别
   - 真实性判断

### 评分等级
- **9-10分**: 专业级质量，技术和美学俱佳
- **7-8分**: 高质量，适合商业使用
- **5-6分**: 中等质量，基本可用
- **3-4分**: 较低质量，存在明显缺陷
- **1-2分**: 低质量，不建议使用

## ⚠️ 注意事项

### 数据安全
- 图片仅用于质量评估，不会存储或用于其他用途
- 建议定期清理生成的结果文件
- 敏感图片请谨慎使用

### 性能优化
- 合理设置并发数避免API限流
- 大量图片处理时建议分批进行

### 错误处理
- 网络异常会自动重试
- 所有错误信息会详细记录

## 🤝 故障排除

### 常见问题

**Q: 提示"API密钥无效"**
A: 检查环境变量`VLM_API_KEY`是否正确设置，确保API密钥有效。

**Q: 某些图片处理失败**
A: 检查图片格式是否支持(jpg/jpeg/png/gif/bmp)，以及文件是否损坏。

### 调试模式
设置环境变量启用详细日志:
```bash
export VLM_DEBUG=1
python vlm_score_online.py --root-dir ./images
```

## 📄 许可证

本项目采用MIT许可证。详情请参见LICENSE文件。

## 🆘 技术支持

如遇到问题，请提供以下信息：
1. Python版本和操作系统
2. 错误信息和堆栈跟踪
3. 输入数据示例
4. 期望的输出结果

---

**开发团队** | **更新时间**: 2024-12-03 | **版本**: v1.0.0 