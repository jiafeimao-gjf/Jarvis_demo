def quick_sort(arr):
    """
    快速排序算法实现
    时间复杂度：平均 O(n log n)，最坏 O(n²)
    空间复杂度：O(log n)
    """
    if len(arr) <= 1:
        return arr
    
    pivot = arr[len(arr) // 2]  # 选择中间元素作为基准
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    
    return quick_sort(left) + middle + quick_sort(right)


# 测试示例
if __name__ == "__main__":
    arr = [3, 6, 8, 10, 1, 2, 1]
    print(f"原始数组: {arr}")
    sorted_arr = quick_sort(arr)
    print(f"排序后数组: {sorted_arr}")