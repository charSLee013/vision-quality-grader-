[简体中文](README_zh.md)

# Vision Quality Grader

An intelligent image quality assessment tool based on the Volcano Engine Vision Large Model (VLM), providing professional analysis and evaluation services for image quality.

## ✨ Key Features

- **Intelligent Scoring**: Provides a professional 10-point scoring system based on advanced VLM.
- **Multi-dimensional Analysis**: Covers technical quality, composition aesthetics, and content quality.
- **AI & Watermark Detection**: Automatically identifies AI-generated content and watermarks.
- **Batch Processing**: Supports recursive directory scanning for automated processing of large image sets.
- **High-Efficiency Async**: Utilizes asynchronous concurrent processing to significantly boost performance.
- **Result Persistence**: Automatically generates detailed analysis reports in JSON format.
- **Cost Tracking**: Monitors API call costs and token usage in real-time.
- **Fault Tolerance**: Implements intelligent retries and error handling for stable processing.
- **Graceful Shutdown**: Supports `Ctrl+C` for elegant interruption, saving progress.

## 📦 Project Structure

```
vision-quality-grader/
├── vlm_common.py           # Shared utility module
├── vlm_score_online.py     # Online inference script
├── test_vlm_common.py      # Test script for common module
├── README.md              # Project documentation
└── requirements.txt       # Dependency list
```

## 🛠 Installation & Configuration

### 1. Prerequisites
- Python 3.7+
- Supported OS: Windows, macOS, Linux

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file or set system environment variables:

```bash
# Required
export VLM_API_BASE="https://ark.cn-beijing.volces.com"
export VLM_API_KEY="your_api_key_here"
export VLM_MODEL_NAME="doubao-vision-pro-32k"

# Optional
export VLM_MAX_CONCURRENT="5"  # Max concurrent requests, default is 5
```

### 4. Verify Installation
```bash
python vlm_score_online.py --help
```

## 🎯 Usage Guide

### Online Inference Mode

Ideal for real-time processing of images with high-concurrency support.

```bash
# Basic usage
python vlm_score_online.py --root-dir ./images

# Specify concurrency limit
python vlm_score_online.py --root-dir ./images --max-concurrent 10

# Show help
python vlm_score_online.py --help
```

**Output**: A corresponding `.json` file is generated in the same directory as each image.

## 📊 Output Format

### Single Image Result Example
```json
{
    "image_path": "/path/to/image.jpg",
    "timestamp": "2024-12-03T10:30:45",
    "analysis_result": {
        "is_ai_generated": "false",
        "watermark_present": "false", 
        "watermark_location": "none",
        "score": "8.5",
        "feedback": "The image has good clarity, natural colors, and a reasonable composition. Rich in detail and of excellent overall quality."
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

## 🔧 API Reference

### `vlm_common` Module

#### Configuration Validation
```python
from vlm_common import validate_config
config = validate_config()
```

#### Image Processing
```python
from vlm_common import find_images, image_to_base64
images = find_images("/path/to/images")
base64_data = await image_to_base64("/path/to/image.jpg")
```

#### XML Result Parsing
```python
from vlm_common import extract_xml_result
result = extract_xml_result(api_response_text)
```

#### Cost Calculation
```python
from vlm_common import CostCalculator
calculator = CostCalculator()
cost_info = calculator.calculate_cost(prompt_tokens=1000, completion_tokens=200)
```

## 🧪 Testing

### Running Tests
```bash
# Test the common module
python test_vlm_common.py

# Or use unittest discovery
python -m unittest discover -s . -p "test_*.py" -v
```

### Test Coverage
- ✅ Configuration Validation
- ✅ Image File Discovery
- ✅ Base64 Conversion
- ✅ XML Parsing
- ✅ Cost Calculation

## 📊 Result Analysis

Analyze and validate the JSON results generated by the VLM scoring tool with comprehensive cost statistics.

### Features
- **JSON Format Validation**: Verify result file structure and data integrity
- **Cost Analysis**: Calculate total API costs and token usage statistics  
- **Quality Insights**: Generate distribution analysis for scores and detection results
- **Multi-format Reports**: Export results as console, CSV, or HTML reports

### Installation
```bash
pip install pandas colorama
```

### Basic Usage
```bash
# Basic analysis with console output
python result_analyzer.py /path/to/results

# Export detailed CSV report
python result_analyzer.py /path/to/results --export-csv analysis.csv

# Generate all report formats
python result_analyzer.py /path/to/results --output-format all --export-path ./reports/
```

### Report Contents
- 📋 File validation statistics (success rate, error types)
- 💰 Cost analysis (total cost, average per image, token usage)
- 📈 Quality distribution (score ranges, AI detection, watermark statistics)

## 🔬 Result Filtering

After analyzing the results, you can use the `image_filter_tool.py` script to filter and copy images and their corresponding `.json` files to a new directory based on specific criteria.

### Basic Usage
```bash
python image_filter_tool.py --source <source_directory> --dest <destination_directory> [FILTERS]
```

### Examples

**1. Filter for high-quality, non-AI, watermark-free images:**
This command copies images with a score of 8.0 or higher, which are not AI-generated and have no watermarks.

```bash
python image_filter_tool.py --source ./images --dest ./high_quality_images --score '>=:8.0' --is-ai false --has-watermark false
```

**2. Filter for low-quality images OR AI-generated images:**
This uses `OR` logic to find images that have a score below 5 or are identified as AI-generated.

```bash
python image_filter_tool.py --source ./images --dest ./review_needed --score '<:5' --is-ai true --logic OR
```

**3. Perform a dry run to see what will be copied:**
The `--dry-run` flag lets you preview the results without copying any files.

```bash
python image_filter_tool.py --source ./images --dest ./filtered --score '>:9.0' --dry-run
```

**4. Flatten output directory and rename files with hash:**
This command filters for high-quality images and copies them to a single flat directory, renaming each file to its SHA256 hash to prevent name collisions.

```bash
python image_filter_tool.py --source ./images --dest ./high_quality_flat --score '>=:8.0' --flat-output
```

### All Arguments
- `--source`: (Required) The directory containing the source images and JSON files.
- `--dest`: (Required) The destination directory for the filtered files.
- `--score`: Filter by score. Format: `'OP:VALUE'` (e.g., `'>:8.5'`) or `'between:MIN:MAX'`.
- `--is-ai`: Filter by AI-generated status (`true` or `false`).
- `--has-watermark`: Filter by watermark presence (`true` or `false`).
- `--logic`: The logic between filters, `AND` (default) or `OR`.
- `--workers`: Number of parallel threads to use.
- `--dry-run`: Simulate the process without copying files.
- `--flat-output`: Copy all files into a single flat directory, renaming them with their SHA256 hash to avoid name conflicts.
- `--log-file`: Specify a path for the log file.

## 📝 Scoring Criteria

The system evaluates image quality based on the following professional dimensions:

### Scoring Dimensions
1.  **Technical Quality** (40%)
    -   Clarity and sharpness
    -   Exposure and contrast
    -   Color accuracy
    -   Noise and distortion control

2.  **Compositional Aesthetics** (30%)
    -   Balance and proportion
    -   Visual focus and guidance
    -   Creativity and uniqueness

3.  **Content Quality** (20%)
    -   Subject clarity
    -   Content richness
    -   Expressive effectiveness

4.  **AI Generation Detection** (10%)
    -   AI artifact identification
    -   Authenticity assessment

### Scoring Tiers
- **9-10**: Professional-grade quality, excellent in both technique and aesthetics.
- **7-8**: High quality, suitable for commercial use.
- **5-6**: Medium quality, generally usable.
- **3-4**: Lower quality, with noticeable flaws.
- **1-2**: Low quality, not recommended for use.

## ⚠️ Important Notes

### Data Security
- Images are used only for quality assessment and are not stored or used for other purposes.
- It is recommended to periodically clean up the generated result files.
- Use caution with sensitive images.

### Performance Optimization
- Set a reasonable concurrency limit to avoid API rate limiting.
- It is advisable to process large numbers of images in batches.

### Error Handling
- Network exceptions will trigger automatic retries.
- All errors are logged in detail.

## 🤝 Troubleshooting

### Common Issues

**Q: "Invalid API Key" error**
A: Check if the `VLM_API_KEY` environment variable is set correctly and ensure the key is valid.

**Q: Some images fail to process**
A: Verify that the image format is supported (jpg/jpeg/png/gif/bmp) and that the file is not corrupted.

### Debug Mode
Enable detailed logging by setting an environment variable:
```bash
export VLM_DEBUG=1
python vlm_score_online.py --root-dir ./images
```

## 📄 License

This project is licensed under the MIT License. See the LICENSE file for details.

## 🆘 Support

If you encounter issues, please provide the following information:
1.  Python version and operating system
2.  Error message and stack trace
3.  Sample input data
4.  Expected output

