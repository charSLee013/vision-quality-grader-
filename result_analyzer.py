#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import glob
import json
import argparse
import traceback
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
from colorama import init, Fore, Style
import pandas as pd

# 初始化colorama用于彩色输出
init(autoreset=True)

class JsonValidator:
    """JSON结果文件验证器"""
    
    def __init__(self):
        """初始化验证器，定义预期的字段结构和验证规则"""
        # 必需字段定义
        self.required_fields = {
            'is_ai_generated': bool,
            'watermark_present': bool,
            'watermark_location': str,
            'score': (int, float),
            'feedback': str,
            'api_usage': dict,
            'api_provider': str
        }
        
        # API使用信息的必需子字段
        self.api_usage_fields = {
            'prompt_tokens': int,
            'completion_tokens': int,
            'total_tokens': int
        }
        
        # 数值范围约束
        self.value_constraints = {
            'score': (0.0, 10.0),
            'prompt_tokens': (0, float('inf')),
            'completion_tokens': (0, float('inf')),
            'total_tokens': (0, float('inf'))
        }
        
        # 统计计数器
        self.validation_stats = {
            'total_files': 0,
            'valid_files': 0,
            'invalid_files': 0,
            'parse_errors': 0,
            'field_errors': 0,
            'type_errors': 0,
            'range_errors': 0
        }
        
        # 详细错误记录
        self.detailed_errors = []
    
    def validate_single_file(self, file_path: str) -> Dict[str, Any]:
        """
        验证单个JSON文件
        
        Args:
            file_path: JSON文件路径
            
        Returns:
            包含验证结果的字典
        """
        self.validation_stats['total_files'] += 1
        
        validation_result = {
            'file_path': file_path,
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'data': None
        }
        
        try:
            # 尝试读取和解析JSON文件
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            validation_result['data'] = data
            
            # 执行各项验证
            field_errors = self._validate_required_fields(data)
            if field_errors:
                validation_result['errors'].extend(field_errors)
                validation_result['is_valid'] = False
                self.validation_stats['field_errors'] += 1
            
            type_errors = self._validate_field_types(data)
            if type_errors:
                validation_result['errors'].extend(type_errors)
                validation_result['is_valid'] = False
                self.validation_stats['type_errors'] += 1
            
            range_errors = self._validate_value_ranges(data)
            if range_errors:
                validation_result['errors'].extend(range_errors)
                validation_result['is_valid'] = False
                self.validation_stats['range_errors'] += 1
            
            # 生成警告信息
            warnings = self._generate_warnings(data)
            validation_result['warnings'].extend(warnings)
            
            if validation_result['is_valid']:
                self.validation_stats['valid_files'] += 1
            else:
                self.validation_stats['invalid_files'] += 1
                
        except json.JSONDecodeError as e:
            validation_result['is_valid'] = False
            validation_result['errors'].append(f"JSON解析错误: {str(e)}")
            self.validation_stats['parse_errors'] += 1
            self.validation_stats['invalid_files'] += 1
            
        except Exception as e:
            validation_result['is_valid'] = False
            validation_result['errors'].append(f"文件读取错误: {str(e)}")
            self.validation_stats['invalid_files'] += 1
        
        # 记录详细错误信息
        if not validation_result['is_valid']:
            self.detailed_errors.append(validation_result)
            
        return validation_result
    
    def _validate_required_fields(self, data: Dict) -> List[str]:
        """验证必需字段是否存在"""
        errors = []
        
        for field_name in self.required_fields.keys():
            if field_name not in data:
                errors.append(f"缺少必需字段: {field_name}")
        
        # 验证api_usage子字段
        if 'api_usage' in data and isinstance(data['api_usage'], dict):
            for sub_field in self.api_usage_fields.keys():
                if sub_field not in data['api_usage']:
                    errors.append(f"api_usage中缺少字段: {sub_field}")
        
        return errors
    
    def _validate_field_types(self, data: Dict) -> List[str]:
        """验证字段数据类型"""
        errors = []
        
        for field_name, expected_type in self.required_fields.items():
            if field_name in data:
                value = data[field_name]
                if not isinstance(value, expected_type):
                    errors.append(f"字段 {field_name} 类型错误: 期望 {expected_type.__name__}, 实际 {type(value).__name__}")
        
        # 验证api_usage子字段类型
        if 'api_usage' in data and isinstance(data['api_usage'], dict):
            for sub_field, expected_type in self.api_usage_fields.items():
                if sub_field in data['api_usage']:
                    value = data['api_usage'][sub_field]
                    if not isinstance(value, expected_type):
                        errors.append(f"api_usage.{sub_field} 类型错误: 期望 {expected_type.__name__}, 实际 {type(value).__name__}")
        
        return errors
    
    def _validate_value_ranges(self, data: Dict) -> List[str]:
        """验证数值范围"""
        errors = []
        
        # 验证score范围
        if 'score' in data:
            score = data['score']
            if isinstance(score, (int, float)):
                min_val, max_val = self.value_constraints['score']
                if not (min_val <= score <= max_val):
                    errors.append(f"score值超出范围: {score} (应在 {min_val}-{max_val} 之间)")
        
        # 验证token数量
        if 'api_usage' in data and isinstance(data['api_usage'], dict):
            for field in ['prompt_tokens', 'completion_tokens', 'total_tokens']:
                if field in data['api_usage']:
                    value = data['api_usage'][field]
                    if isinstance(value, int):
                        min_val, _ = self.value_constraints[field]
                        if value < min_val:
                            errors.append(f"api_usage.{field} 值无效: {value} (应 >= {min_val})")
        
        return errors
    
    def _generate_warnings(self, data: Dict) -> List[str]:
        """生成警告信息"""
        warnings = []
        
        # 检查feedback是否为空
        if 'feedback' in data and not data['feedback'].strip():
            warnings.append("feedback字段为空")
        
        # 检查score是否过低
        if 'score' in data and isinstance(data['score'], (int, float)):
            if data['score'] < 3.0:
                warnings.append(f"score值较低: {data['score']}")
        
        # 检查API提供商是否符合预期
        if 'api_provider' in data and data['api_provider'] != 'volces':
            warnings.append(f"意外的API提供商: {data['api_provider']}")
        
        return warnings

class CostAnalyzer:
    """成本分析器"""
    
    def __init__(self):
        """初始化成本分析器，使用与vlm_score.py相同的定价模型"""
        # 豆包模型定价（元/百万token）
        self.input_price = 0.15  # 输入token价格
        self.output_price = 1.50  # 输出token价格
        
        # 统计数据
        self.cost_stats = {
            'total_files_analyzed': 0,
            'successful_analyses': 0,
            'total_prompt_tokens': 0,
            'total_completion_tokens': 0,
            'total_reasoning_tokens': 0,
            'total_tokens': 0,
            'total_input_cost': 0.0,
            'total_output_cost': 0.0,
            'total_cost': 0.0,
            'average_cost_per_image': 0.0,
            'success_rate': 0.0
        }
        
        # 详细的per-file成本数据
        self.detailed_costs = []
    
    def analyze_costs(self, validation_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析所有验证结果中的成本信息
        
        Args:
            validation_results: JsonValidator生成的验证结果列表
            
        Returns:
            包含详细成本分析的字典
        """
        self.cost_stats['total_files_analyzed'] = len(validation_results)
        
        for result in validation_results:
            if result['is_valid'] and result['data']:
                data = result['data']
                file_cost = self._calculate_single_file_cost(data, result['file_path'])
                
                if file_cost:
                    self.detailed_costs.append(file_cost)
                    self.cost_stats['successful_analyses'] += 1
                    
                    # 累计统计
                    self.cost_stats['total_prompt_tokens'] += file_cost['prompt_tokens']
                    self.cost_stats['total_completion_tokens'] += file_cost['completion_tokens']
                    self.cost_stats['total_reasoning_tokens'] += file_cost['reasoning_tokens']
                    self.cost_stats['total_tokens'] += file_cost['total_tokens']
                    self.cost_stats['total_input_cost'] += file_cost['input_cost']
                    self.cost_stats['total_output_cost'] += file_cost['output_cost']
                    self.cost_stats['total_cost'] += file_cost['total_cost']
        
        # 计算平均值和效率指标
        self._calculate_efficiency_metrics()
        
        return self.cost_stats
    
    def _calculate_single_file_cost(self, data: Dict, file_path: str) -> Optional[Dict[str, Any]]:
        """计算单个文件的成本"""
        if 'api_usage' not in data or not isinstance(data['api_usage'], dict):
            return None
        
        api_usage = data['api_usage']
        
        # 提取token使用信息
        prompt_tokens = api_usage.get('prompt_tokens', 0)
        completion_tokens = api_usage.get('completion_tokens', 0)
        
        # reasoning_tokens可能在completion_tokens_details中
        reasoning_tokens = 0
        if 'completion_tokens_details' in api_usage:
            details = api_usage['completion_tokens_details']
            reasoning_tokens = details.get('reasoning_tokens', 0)
        
        total_tokens = prompt_tokens + completion_tokens + reasoning_tokens
        
        # 计算成本
        input_cost = (prompt_tokens / 1_000_000) * self.input_price
        output_cost = ((completion_tokens + reasoning_tokens) / 1_000_000) * self.output_price
        total_cost = input_cost + output_cost
        
        return {
            'file_path': file_path,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'reasoning_tokens': reasoning_tokens,
            'total_tokens': total_tokens,
            'input_cost': input_cost,
            'output_cost': output_cost,
            'total_cost': total_cost,
            'score': data.get('score', 0.0),
            'is_ai_generated': data.get('is_ai_generated', False),
            'watermark_present': data.get('watermark_present', False)
        }
    
    def _calculate_efficiency_metrics(self):
        """计算效率指标"""
        if self.cost_stats['total_files_analyzed'] > 0:
            self.cost_stats['success_rate'] = (
                self.cost_stats['successful_analyses'] / 
                self.cost_stats['total_files_analyzed'] * 100
            )
        
        if self.cost_stats['successful_analyses'] > 0:
            self.cost_stats['average_cost_per_image'] = (
                self.cost_stats['total_cost'] / 
                self.cost_stats['successful_analyses']
            )
    
    def get_cost_distribution_stats(self) -> Dict[str, Any]:
        """获取成本分布统计"""
        if not self.detailed_costs:
            return {}
        
        costs = [item['total_cost'] for item in self.detailed_costs]
        scores = [item['score'] for item in self.detailed_costs]
        
        return {
            'cost_stats': {
                'min_cost': min(costs),
                'max_cost': max(costs),
                'median_cost': sorted(costs)[len(costs)//2],
                'cost_std': self._calculate_std(costs)
            },
            'score_stats': {
                'min_score': min(scores),
                'max_score': max(scores),
                'average_score': sum(scores) / len(scores),
                'score_std': self._calculate_std(scores)
            },
            'ai_detection_stats': {
                'ai_generated_count': sum(1 for item in self.detailed_costs if item['is_ai_generated']),
                'ai_generated_ratio': sum(1 for item in self.detailed_costs if item['is_ai_generated']) / len(self.detailed_costs) * 100
            },
            'watermark_stats': {
                'watermark_count': sum(1 for item in self.detailed_costs if item['watermark_present']),
                'watermark_ratio': sum(1 for item in self.detailed_costs if item['watermark_present']) / len(self.detailed_costs) * 100
            }
        }
    
    def get_quality_distribution_data(self) -> List[Dict[str, Any]]:
        """
        计算详细的质量分布数据，用于生成表格
        
        Returns:
            一个字典列表，每个字典代表表格的一行
        """
        if not self.detailed_costs:
            return []

        df = pd.DataFrame(self.detailed_costs)
        total_images = len(df)

        # 定义分数区间和标签
        bins = [-0.1, 2.9, 4.9, 6.9, 8.9, 10.0]
        labels = ["[0.0-2.9] 低质", "[3.0-4.9] 需改进", "[5.0-6.9] 中等", "[7.0-8.9] 优质", "[9.0-10.0] 专业级"]
        
        df['quality_range'] = pd.cut(df['score'], bins=bins, labels=labels, right=True)

        # 按质量区间分组并聚合
        distribution = df.groupby('quality_range').agg(
            count=('score', 'count'),
            ai_count=('is_ai_generated', lambda x: x.sum()),
            watermark_count=('watermark_present', lambda x: x.sum())
        ).reset_index()

        # 计算衍生指标
        distribution['percentage'] = (distribution['count'] / total_images) * 100
        distribution['ai_rate'] = (distribution['ai_count'] / distribution['count']).fillna(0) * 100
        distribution['watermark_rate'] = (distribution['watermark_count'] / distribution['count']).fillna(0) * 100
        
        # 确保所有区间都存在，即使数量为0
        all_ranges = pd.DataFrame({'quality_range': labels})
        distribution = pd.merge(all_ranges, distribution, on='quality_range', how='left').fillna(0)

        # 转换数据类型为整数
        int_columns = ['count', 'ai_count', 'watermark_count']
        for col in int_columns:
            distribution[col] = distribution[col].astype(int)

        # 按照标签顺序排序
        distribution['quality_range'] = pd.Categorical(distribution['quality_range'], categories=labels, ordered=True)
        distribution = distribution.sort_values('quality_range')

        return distribution.to_dict('records')

    def _calculate_std(self, values: List[float]) -> float:
        """计算标准差"""
        if len(values) < 2:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5 

class ReportGenerator:
    """报告生成器"""
    
    def __init__(self, validator: JsonValidator, cost_analyzer: CostAnalyzer):
        """初始化报告生成器"""
        self.validator = validator
        self.cost_analyzer = cost_analyzer
    
    def print_console_report(self, verbose: bool = False):
        """生成并打印控制台报告"""
        print(f"\n{Fore.CYAN}📊 结果分析报告{Style.RESET_ALL}")
        print("=" * 60)
        
        # 验证统计报告
        self._print_validation_summary()
        
        # 成本分析报告
        self._print_cost_summary()
        
        # 详细统计
        self._print_detailed_stats()
        
        # 如果启用详细模式，显示错误详情
        if verbose and self.validator.detailed_errors:
            self._print_detailed_errors()
    
    def _print_validation_summary(self):
        """打印验证统计摘要"""
        stats = self.validator.validation_stats
        
        print(f"\n{Fore.YELLOW}📋 文件验证统计:{Style.RESET_ALL}")
        print(f"  📁 总文件数:     {Fore.GREEN}{stats['total_files']}{Style.RESET_ALL}")
        print(f"  ✅ 有效文件:     {Fore.GREEN}{stats['valid_files']}{Style.RESET_ALL}")
        print(f"  ❌ 无效文件:     {Fore.RED}{stats['invalid_files']}{Style.RESET_ALL}")
        
        if stats['total_files'] > 0:
            success_rate = (stats['valid_files'] / stats['total_files']) * 100
            print(f"  📈 成功率:       {Fore.CYAN}{success_rate:.1f}%{Style.RESET_ALL}")
        
        # 错误类型统计
        if stats['invalid_files'] > 0:
            print(f"\n{Fore.RED}🔍 错误类型分布:{Style.RESET_ALL}")
            print(f"  🚫 JSON解析错误: {Fore.RED}{stats['parse_errors']}{Style.RESET_ALL}")
            print(f"  📝 字段缺失错误: {Fore.YELLOW}{stats['field_errors']}{Style.RESET_ALL}")
            print(f"  🔄 类型错误:     {Fore.ORANGE}{stats['type_errors']}{Style.RESET_ALL}")
            print(f"  📊 范围错误:     {Fore.MAGENTA}{stats['range_errors']}{Style.RESET_ALL}")
    
    def _print_cost_summary(self):
        """打印成本统计摘要"""
        stats = self.cost_analyzer.cost_stats
        
        print(f"\n{Fore.YELLOW}💰 成本分析统计:{Style.RESET_ALL}")
        print(f"  🖼️  分析图片数:   {Fore.GREEN}{stats['successful_analyses']}{Style.RESET_ALL}")
        print(f"  🔤 总输入Token:  {Fore.BLUE}{stats['total_prompt_tokens']:,}{Style.RESET_ALL}")
        print(f"  📝 总输出Token:  {Fore.BLUE}{stats['total_completion_tokens']:,}{Style.RESET_ALL}")
        
        if stats['total_reasoning_tokens'] > 0:
            print(f"  �� 推理Token:    {Fore.MAGENTA}{stats['total_reasoning_tokens']:,}{Style.RESET_ALL}")
        
        print(f"  💵 总成本:       {Fore.RED}¥{stats['total_cost']:.4f}{Style.RESET_ALL}")
        
        if stats['successful_analyses'] > 0:
            print(f"  📷 平均单张成本: {Fore.CYAN}¥{stats['average_cost_per_image']:.4f}{Style.RESET_ALL}")
    
    def _print_detailed_stats(self):
        """打印详细统计信息"""
        distribution_stats = self.cost_analyzer.get_cost_distribution_stats()
        
        if not distribution_stats:
            return
        
        print(f"\n{Fore.YELLOW}📈 详细统计分析:{Style.RESET_ALL}")
        
        # 成本分布
        cost_stats = distribution_stats['cost_stats']
        print(f"  💸 成本分布:")
        print(f"    最低: {Fore.GREEN}¥{cost_stats['min_cost']:.4f}{Style.RESET_ALL}")
        print(f"    最高: {Fore.RED}¥{cost_stats['max_cost']:.4f}{Style.RESET_ALL}")
        print(f"    中位: {Fore.CYAN}¥{cost_stats['median_cost']:.4f}{Style.RESET_ALL}")
        
        # 打印新的质量分布详情表
        self._print_quality_distribution_table()
        
        # AI生成统计
        ai_stats = distribution_stats['ai_detection_stats']
        print(f"  🤖 AI生成检测 (全局):")
        print(f"    AI生成: {Fore.YELLOW}{ai_stats['ai_generated_count']}{Style.RESET_ALL} / {self.cost_analyzer.cost_stats['successful_analyses']} ({ai_stats['ai_generated_ratio']:.1f}%)")
        
        # 水印统计
        watermark_stats = distribution_stats['watermark_stats']
        print(f"  💧 水印检测 (全局):")
        print(f"    含水印: {Fore.BLUE}{watermark_stats['watermark_count']}{Style.RESET_ALL} / {self.cost_analyzer.cost_stats['successful_analyses']} ({watermark_stats['watermark_ratio']:.1f}%)")
    
    def _print_quality_distribution_table(self):
        """打印格式化的质量分布表格"""
        table_data = self.cost_analyzer.get_quality_distribution_data()
        
        if not table_data:
            return
            
        print(f"\n  ⭐ {Fore.CYAN}质量分布详情:{Style.RESET_ALL}")
        
        # 表头
        header = f"  {'分数区间':<18} | {'图片数量':>8} | {'占比':>7} | {'AI生成':>6} | {'区间AI率':>9} | {'含水印':>7} | {'区间水印率':>11} "
        print(f"  {Fore.WHITE}{Style.BRIGHT}{header}{Style.RESET_ALL}")
        print(f"  {'-'*len(header)}")

        # 表内容
        for row in table_data:
            line = (
                f"  {row['quality_range']:<18} | "
                f"{row['count']:>8,} | "
                f"{row['percentage']:>6.1f}% | "
                f"{row['ai_count']:>6,} | "
                f"{row['ai_rate']:>8.1f}% | "
                f"{row['watermark_count']:>7,} | "
                f"{row['watermark_rate']:>10.1f}% "
            )
            print(line)

    def _print_detailed_errors(self):
        """打印详细错误信息"""
        print(f"\n{Fore.RED}🔍 详细错误信息:{Style.RESET_ALL}")
        print("-" * 60)
        
        for error_info in self.validator.detailed_errors[:10]:  # 限制显示前10个错误
            file_name = os.path.basename(error_info['file_path'])
            print(f"\n{Fore.YELLOW}📄 {file_name}:{Style.RESET_ALL}")
            
            for error in error_info['errors']:
                print(f"  {Fore.RED}❌{Style.RESET_ALL} {error}")
            
            for warning in error_info['warnings']:
                print(f"  {Fore.ORANGE}⚠️{Style.RESET_ALL} {warning}")
        
        if len(self.validator.detailed_errors) > 10:
            remaining = len(self.validator.detailed_errors) - 10
            print(f"\n{Fore.YELLOW}... 还有 {remaining} 个错误未显示{Style.RESET_ALL}")
    
    def export_csv(self, output_path: str):
        """导出详细分析结果为CSV文件"""
        if not self.cost_analyzer.detailed_costs:
            print(f"{Fore.YELLOW}⚠️ 没有有效的成本数据可导出{Style.RESET_ALL}")
            return
        
        try:
            df = pd.DataFrame(self.cost_analyzer.detailed_costs)
            df.to_csv(output_path, index=False, encoding='utf-8')
            print(f"{Fore.GREEN}✅ CSV报告已导出到: {output_path}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}❌ CSV导出失败: {str(e)}{Style.RESET_ALL}")
    
    def generate_html_report(self, output_path: str):
        """生成HTML格式报告"""
        try:
            html_content = self._build_html_content()
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"{Fore.GREEN}✅ HTML报告已生成: {output_path}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}❌ HTML报告生成失败: {str(e)}{Style.RESET_ALL}")
    
    def _build_html_content(self) -> str:
        """构建HTML报告内容"""
        stats = self.validator.validation_stats
        cost_stats = self.cost_analyzer.cost_stats
        distribution_stats = self.cost_analyzer.get_cost_distribution_stats()
        
        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>图像质量分析报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ text-align: center; color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 20px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }}
        .stat-card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid #4CAF50; }}
        .stat-title {{ font-weight: bold; color: #333; margin-bottom: 10px; }}
        .stat-value {{ font-size: 1.2em; color: #2196F3; }}
        .error-section {{ background: #fff3cd; padding: 15px; border-radius: 8px; border-left: 4px solid #ffc107; margin: 20px 0; }}
        .cost-section {{ background: #d1ecf1; padding: 15px; border-radius: 8px; border-left: 4px solid #17a2b8; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🖼️ 图像质量分析报告</h1>
            <p>生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-title">📁 文件验证统计</div>
                <div class="stat-value">总文件: {stats['total_files']}</div>
                <div class="stat-value">有效文件: {stats['valid_files']}</div>
                <div class="stat-value">无效文件: {stats['invalid_files']}</div>
                <div class="stat-value">成功率: {(stats['valid_files']/stats['total_files']*100) if stats['total_files']>0 else 0:.1f}%</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-title">💰 成本统计</div>
                <div class="stat-value">分析图片: {cost_stats['successful_analyses']}</div>
                <div class="stat-value">总Token: {cost_stats['total_tokens']:,}</div>
                <div class="stat-value">总成本: ¥{cost_stats['total_cost']:.4f}</div>
                <div class="stat-value">平均成本: ¥{cost_stats['average_cost_per_image']:.4f}</div>
            </div>
        """
        
        if distribution_stats:
            score_stats = distribution_stats['score_stats']
            ai_stats = distribution_stats['ai_detection_stats']
            html += f"""
            <div class="stat-card">
                <div class="stat-title">⭐ 质量分析</div>
                <div class="stat-value">平均分: {score_stats['average_score']:.1f}</div>
                <div class="stat-value">最高分: {score_stats['max_score']:.1f}</div>
                <div class="stat-value">最低分: {score_stats['min_score']:.1f}</div>
                <div class="stat-value">AI生成: {ai_stats['ai_generated_ratio']:.1f}%</div>
            </div>
            """
        
        html += """
        </div>
    </div>
</body>
</html>
        """
        
        return html


def find_result_files(root_dir: str, extensions: Tuple[str, ...] = ('.json',)) -> List[str]:
    """
    递归查找结果JSON文件
    
    Args:
        root_dir: 搜索根目录
        extensions: 文件扩展名元组
        
    Returns:
        找到的JSON文件路径列表
    """
    all_files = []
    for ext in extensions:
        pattern = os.path.join(root_dir, '**', f'*{ext}')
        all_files.extend(glob.glob(pattern, recursive=True))
    
    return sorted(list(set(all_files)))  # 去重并排序 

def main():
    """主函数 - 命令行入口和主流程控制"""
    parser = argparse.ArgumentParser(
        description='分析vlm_score.py生成的JSON结果文件，验证格式并统计成本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python result_analyzer.py /path/to/results          # 基本分析
  python result_analyzer.py /path/to/results --verbose # 详细模式
  python result_analyzer.py /path/to/results --export-csv analysis.csv
  python result_analyzer.py /path/to/results --export-html report.html
  python result_analyzer.py /path/to/results --output-format all --export-path ./reports/
        """
    )
    
    # 位置参数
    parser.add_argument(
        'results_directory',
        help='包含JSON结果文件的目录路径'
    )
    
    # 可选参数
    parser.add_argument(
        '--output-format',
        choices=['console', 'csv', 'html', 'all'],
        default='console',
        help='输出格式 (默认: console)'
    )
    
    parser.add_argument(
        '--export-path',
        help='导出文件路径 (用于CSV/HTML输出)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细模式，显示每个文件的验证结果'
    )
    
    parser.add_argument(
        '--export-csv',
        help='导出CSV文件的路径'
    )
    
    parser.add_argument(
        '--export-html',
        help='导出HTML报告的路径'
    )
    
    parser.add_argument(
        '--filter-valid',
        action='store_true',
        help='只分析有效的JSON文件'
    )
    
    args = parser.parse_args()
    
    try:
        # 验证输入目录
        if not os.path.exists(args.results_directory):
            print(f"{Fore.RED}❌ 错误: 目录不存在: {args.results_directory}{Style.RESET_ALL}")
            return 1
        
        if not os.path.isdir(args.results_directory):
            print(f"{Fore.RED}❌ 错误: 指定路径不是目录: {args.results_directory}{Style.RESET_ALL}")
            return 1
        
        # 查找JSON文件
        print(f"{Fore.CYAN}🔍 正在扫描目录: {args.results_directory}{Style.RESET_ALL}")
        json_files = find_result_files(args.results_directory)
        
        if not json_files:
            print(f"{Fore.YELLOW}⚠️ 在指定目录中未找到JSON文件{Style.RESET_ALL}")
            return 0
        
        print(f"{Fore.GREEN}📁 找到 {len(json_files)} 个JSON文件{Style.RESET_ALL}")
        
        # 初始化分析器
        validator = JsonValidator()
        cost_analyzer = CostAnalyzer()
        report_generator = ReportGenerator(validator, cost_analyzer)
        
        # 验证所有文件
        print(f"{Fore.YELLOW}🔄 开始验证文件...{Style.RESET_ALL}")
        validation_results = []
        
        for json_file in json_files:
            if args.verbose:
                print(f"  验证: {os.path.basename(json_file)}", end=" ... ")
            
            result = validator.validate_single_file(json_file)
            validation_results.append(result)
            
            if args.verbose:
                status = f"{Fore.GREEN}✓{Style.RESET_ALL}" if result['is_valid'] else f"{Fore.RED}✗{Style.RESET_ALL}"
                print(status)
        
        # 过滤结果 (如果指定)
        if args.filter_valid:
            validation_results = [r for r in validation_results if r['is_valid']]
            print(f"{Fore.BLUE}📋 已过滤，仅分析 {len(validation_results)} 个有效文件{Style.RESET_ALL}")
        
        # 分析成本
        print(f"{Fore.YELLOW}💰 分析成本信息...{Style.RESET_ALL}")
        cost_analyzer.analyze_costs(validation_results)
        
        # 生成报告
        if args.output_format in ['console', 'all']:
            report_generator.print_console_report(verbose=args.verbose)
        
        # 导出CSV
        if args.export_csv or args.output_format in ['csv', 'all']:
            csv_path = args.export_csv
            if not csv_path:
                if args.export_path:
                    csv_path = os.path.join(args.export_path, 'analysis_results.csv')
                else:
                    csv_path = 'analysis_results.csv'
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(csv_path) if os.path.dirname(csv_path) else '.', exist_ok=True)
            report_generator.export_csv(csv_path)
        
        # 导出HTML
        if args.export_html or args.output_format in ['html', 'all']:
            html_path = args.export_html
            if not html_path:
                if args.export_path:
                    html_path = os.path.join(args.export_path, 'analysis_report.html')
                else:
                    html_path = 'analysis_report.html'
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(html_path) if os.path.dirname(html_path) else '.', exist_ok=True)
            report_generator.generate_html_report(html_path)
        
        # 最终提示
        print(f"\n{Fore.GREEN}✅ 分析完成！{Style.RESET_ALL}")
        
        # 如果有错误，建议用户查看详细信息
        if validator.validation_stats['invalid_files'] > 0:
            print(f"{Fore.YELLOW}💡 提示: 使用 --verbose 参数查看详细错误信息{Style.RESET_ALL}")
        
        return 0
        
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠️ 用户中断操作{Style.RESET_ALL}")
        return 130
    except Exception as e:
        print(f"{Fore.RED}❌ 程序执行失败: {str(e)}{Style.RESET_ALL}")
        if args.verbose:
            print(f"{Fore.RED}详细错误信息:{Style.RESET_ALL}")
            print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    """程序入口点"""
    try:
        exit_code = main()
        exit(exit_code)
    except Exception as e:
        print(f"{Fore.RED}❌ 致命错误: {str(e)}{Style.RESET_ALL}")
        print(traceback.format_exc())
        exit(1) 