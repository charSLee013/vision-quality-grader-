# Result Analyzer 使用说明

## 功能概述

`result_analyzer.py` 是一个专门用于分析 `vlm_score.py` 生成的JSON结果文件的辅助工具。它提供以下核心功能：

1. **JSON格式验证** - 检查结果文件是否符合预期的数据结构
2. **成本统计分析** - 汇总API调用成本和token使用情况
3. **质量分析报告** - 生成详细的图像质量评估统计
4. **多格式输出** - 支持控制台、CSV、HTML等多种报告格式

## 安装依赖

```bash
pip install pandas colorama
```

## 基本用法

### 1. 基本分析（控制台输出）
```bash
python result_analyzer.py /path/to/results
```

### 2. 详细模式
```bash
python result_analyzer.py /path/to/results --verbose
```

### 3. 导出CSV报告
```bash
python result_analyzer.py /path/to/results --export-csv analysis.csv
```

### 4. 导出HTML报告
```bash
python result_analyzer.py /path/to/results --export-html report.html
```

### 5. 生成所有格式报告
```bash
python result_analyzer.py /path/to/results --output-format all --export-path ./reports/
```

## 命令行参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `results_directory` | 位置参数 | 包含JSON结果文件的目录路径 |
| `--output-format` | 选择 | 输出格式：console/csv/html/all (默认: console) |
| `--export-path` | 路径 | 导出文件的基础路径 |
| `--verbose, -v` | 标志 | 详细模式，显示每个文件的验证结果 |
| `--export-csv` | 路径 | 指定CSV文件的输出路径 |
| `--export-html` | 路径 | 指定HTML报告的输出路径 |
| `--filter-valid` | 标志 | 只分析有效的JSON文件 |

## 验证规则

### 必需字段
- `is_ai_generated` (布尔值) - AI生成检测结果
- `watermark_present` (布尔值) - 水印检测结果
- `watermark_location` (字符串) - 水印位置描述
- `score` (0.0-10.0浮点数) - 质量评分
- `feedback` (字符串) - 评分反馈
- `api_usage` (字典) - API使用统计
- `api_provider` (字符串) - API提供商

### api_usage 子字段
- `prompt_tokens` (整数) - 输入token数量
- `completion_tokens` (整数) - 输出token数量
- `total_tokens` (整数) - 总token数量

### 数值范围验证
- `score`: 必须在 0.0-10.0 之间
- 所有token数量: 必须为非负整数

## 输出报告内容

### 控制台报告
- 📋 文件验证统计（总数、有效、无效、成功率）
- 💰 成本分析统计（图片数量、token使用、总成本、平均成本）
- 📈 详细统计分析（成本分布、质量分布、AI检测、水印统计）
- 🔍 详细错误信息（在verbose模式下）

### CSV报告
包含每个文件的详细分析数据：
- file_path, prompt_tokens, completion_tokens, reasoning_tokens
- total_tokens, input_cost, output_cost, total_cost
- score, is_ai_generated, watermark_present

### HTML报告
美观的网页格式报告，包含：
- 可视化统计卡片
- 响应式布局
- 时间戳信息

## 错误处理

工具会自动处理以下错误情况：
- 📁 目录不存在或无法访问
- 📄 JSON文件格式错误
- 📝 字段缺失或类型错误
- 📊 数值范围超出限制
- 💾 文件读写权限问题

## 使用场景示例

### 1. 快速检查结果质量
```bash
# 快速查看整体统计
python result_analyzer.py ./images_results
```

### 2. 深度问题诊断
```bash
# 详细查看所有错误
python result_analyzer.py ./images_results --verbose
```

### 3. 生成项目报告
```bash
# 生成完整的分析报告
python result_analyzer.py ./images_results \
  --output-format all \
  --export-path ./project_reports/$(date +%Y%m%d)
```

### 4. 成本预算管理
```bash
# 专注于成本分析
python result_analyzer.py ./images_results \
  --filter-valid \
  --export-csv cost_analysis.csv
```

## 常见问题

**Q: 为什么有些文件验证失败？**
A: 可能原因包括JSON格式错误、字段缺失、数据类型不匹配等。使用 `--verbose` 参数查看详细错误信息。

**Q: 成本计算是否准确？**
A: 成本计算使用与 `vlm_score.py` 相同的定价模型（输入0.15元/百万token，输出1.50元/百万token）。

**Q: 如何只分析特定类型的文件？**
A: 使用 `--filter-valid` 参数只分析格式正确的文件，或者手动整理目录结构。

**Q: 报告文件保存在哪里？**
A: 默认保存在当前工作目录，可通过 `--export-path` 指定输出目录。 