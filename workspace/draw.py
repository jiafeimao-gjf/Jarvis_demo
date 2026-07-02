import matplotlib.pyplot as plt
import numpy as np

# 设置中文支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 创建画布
fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 5))

# 图1：折线图
x = np.linspace(0, 10, 100)
y = np.sin(x)
ax1.plot(x, y, 'r-', linewidth=2, label='sin(x)')
ax1.set_title('正弦波')
ax1.grid(True, alpha=0.3)
ax1.set_xlabel('x')
ax1.set_ylabel('y')

# 图2：柱状图
categories = ['A', 'B', 'C', 'D', 'E']
values = [10, 15, 7, 12, 20]
ax2.bar(categories, values, color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd'])
ax2.set_title('柱状图')
ax2.grid(True, alpha=0.3, axis='y')
ax2.set_ylabel('数值')

# 图3：散点图
ax3.scatter(x, np.cos(x), color='g', marker='o', alpha=0.6)
ax3.plot(x, np.cos(x), 'b--', linewidth=1, alpha=0.5)
ax3.set_title('散点图+曲线')
ax3.grid(True, alpha=0.3)
ax3.set_xlabel('x')
ax3.set_ylabel('cos(x)')
ax3.legend()

plt.tight_layout()
plt.savefig('chart.png', dpi=150, bbox_inches='tight')
plt.close()

print("图表已保存为 chart.png")