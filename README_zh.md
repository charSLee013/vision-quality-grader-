[English](README.md)

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
vision-quality-grader/
├── vlm_common.py                    # 共享工具模块
├── vlm_score_online.py              # 在线推理脚本 (3并发)
├── vlm_score_batch.py               # 批量推理脚本 (50,000并发)
├── batch_task_pool.py               # 高性能任务池管理器
├── batch_image_quality_analyzer.py  # 批量推理分析器
├── batch_processing.py              # 批量处理逻辑
├── test_vlm_common.py               # 公共模块测试
├── README.md                        # 项目说明文档
└── requirements.txt                 # 依赖包列表
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
基于`.env.example`创建`.env`文件:

```bash
# 共享配置
VLM_API_TOKEN=your_api_token_here

# 在线推理配置
VLM_ONLINE_API_ENDPOINT=https://ark.cn-beijing.volces.com/api/v3/chat/completions
VLM_ONLINE_MODEL_NAME=your_online_model_name_here

# 批量推理配置
VLM_BATCH_API_ENDPOINT=https://ark.cn-beijing.volces.com/api/v3/batch/chat/completions
VLM_BATCH_MODEL_NAME=your_batch_model_name_here

# 请求参数
VLM_MAX_TOKENS=16384
VLM_TEMPERATURE=0.3
VLM_TIMEOUT=3600

# 批量推理并发配置
VLM_BATCH_CONCURRENT_LIMIT=10000
```

### 4. 验证安装
```bash
python vlm_score_online.py --help
```

## 🎯 使用指南

### 在线推理模式

适用于实时处理，支持中等并发（最多3个并发请求）。

```bash
# 基本用法
python vlm_score_online.py --root-dir ./images

# 指定并发数
python vlm_score_online.py --root-dir ./images --max-concurrent 3

# 强制重新处理已有结果
python vlm_score_online.py --root-dir ./images --force-rerun

# 查看帮助
python vlm_score_online.py --help
```

### 批量推理模式

专为大规模处理设计，支持超高并发（最多50,000个并发请求）。

```bash
# 基本用法
python vlm_score_batch.py ./images

# 指定自定义并发限制
python vlm_score_batch.py ./images --concurrent-limit 25000

# 强制重新处理已有结果
python vlm_score_batch.py ./images --force-rerun

# 启用调试模式
python vlm_score_batch.py ./images --debug

# 查看帮助
python vlm_score_batch.py --help
```

### 性能对比

| 模式 | 并发数 | 超时时间 | 适用场景 |
|------|--------|----------|----------|
| 在线推理 | 3个请求 | 3分钟 | 实时处理、小批量 |
| 批量推理 | 50,000个请求 | 72小时 | 大规模处理、海量数据集 |

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

## 📊 结果分析

分析和验证VLM评分工具生成的JSON结果，提供全面的成本统计分析。

### 主要功能
- **JSON格式验证**: 检查结果文件结构和数据完整性
- **成本分析**: 计算API调用总成本和token使用统计
- **质量洞察**: 生成评分和检测结果的分布分析
- **多格式报告**: 支持控制台、CSV、HTML等多种报告格式

### 安装依赖
```bash
pip install pandas colorama
```

### 基本用法
```bash
# 基本分析（控制台输出）
python result_analyzer.py /path/to/results

# 导出详细CSV报告
python result_analyzer.py /path/to/results --export-csv analysis.csv

# 生成所有格式报告
python result_analyzer.py /path/to/results --output-format all --export-path ./reports/
```

### 报告内容
- 📋 文件验证统计（成功率、错误类型）
- 💰 成本分析（总成本、平均每张成本、token使用量）
- 📈 质量分布（评分范围、AI检测、水印统计）

## 🔬 结果筛选

在分析完结果后，您可以使用 `image_filter_tool.py` 脚本，根据特定标准筛选图片及其对应的 `.json` 文件，并将它们复制到一个新目录中。

### 基本用法
```bash
python image_filter_tool.py --source <源目录> --dest <目标目录> [筛选条件]
```

### 使用示例

**1. 筛选高质量、非AI、无水印的图片:**
此命令将复制分数大于等于8.0、非AI生成且无水印的图片。

```bash
python image_filter_tool.py --source ./images --dest ./high_quality_images --score '>=:8.0' --is-ai false --has-watermark false
```

**2. 筛选低质量图片 或 AI生成的图片:**
此命令使用 `OR` 逻辑来查找分数低于5分或被识别为AI生成的图片。

```bash
python image_filter_tool.py --source ./images --dest ./review_needed --score '<:5' --is-ai true --logic OR
```

**3. 使用模拟运行模式预览结果:**
`--dry-run` 标志可以让你在不实际复制任何文件的情况下预览操作结果。

```bash
python image_filter_tool.py --source ./images --dest ./filtered --score '>:9.0' --dry-run
```

**4. 平铺输出目录并用哈希值重命名文件：**
此命令筛选高质量图片，并将它们复制到一个平铺的目录中，同时将每个文件重命名为其SHA256哈希值，以防止文件名冲突。

```bash
python image_filter_tool.py --source ./images --dest ./high_quality_flat --score '>=:8.0' --flat-output
```

### 全部参数说明
- `--source`: (必需) 包含源图片和JSON文件的目录。
- `--dest`: (必需) 用于存放筛选后文件的目标目录。
- `--score`: 按分数筛选。格式: `'操作符:值'` (例如, `'>:8.5'`) 或 `'between:最小值:最大值'`。
- `--is-ai`: 按AI生成状态筛选 (`true` 或 `false`)。
- `--has-watermark`: 按水印状态筛选 (`true` 或 `false`)。
- `--logic`: 多个筛选条件间的逻辑关系，`AND` (默认) 或 `OR`。
- `--workers`: 使用的并行工作线程数。
- `--dry-run`: 模拟运行，不实际复制文件。
- `--flat-output`: 将所有文件复制到单个平铺目录中，并使用其SHA256哈希值重命名以避免文件名冲突。
- `--log-file`: 指定日志文件的路径。

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