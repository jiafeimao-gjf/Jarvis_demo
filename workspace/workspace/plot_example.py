#!/usr/bin/env python3
"""
Python 画图脚本示例
使用 matplotlib 绘制多种图表
"""

import matplotlib.pyplot as plt
import numpy as np

# 设置中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 创建数据
x = np.linspace(0, 10, 100)
y1 = np.sin(x)
y2 = np.cos(x)

# 创建第一个图表 - 折线图
plt.figure(figsize=(12, 8))

# 绘制折线图
plt.plot(x, y1, label='sin(x)', color='blue', linewidth=2, marker='o')
plt.plot(x, y2, label='cos(x)', color='red', linewidth=2, marker='s')

# 添加填充区域
plt.fill_between(x, y1, alpha=0.3)
plt.fill_between(x, y2, alpha=0.3)

# 添加标题和标签
plt.title('正弦和余弦函数图', fontsize=16)
plt.xlabel('X 轴', fontsize=12)
plt.ylabel('Y 轴', fontsize=12)

# 添加网格
plt.grid(True, alpha=0.3)

# 添加图例
plt.legend()

# 设置 X 轴刻度
plt.xticks(np.arange(0, 11, 2))

# 显示图片
plt.tight_layout()
plt.savefig('./sine_cosine_plot.png', dpi=150)
plt.show()

print("折线图已绘制并保存为：sine_cosine_plot.png")
