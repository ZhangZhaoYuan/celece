"""
后台向量重建脚本 - 分批执行避免超时
使用新的text-embedding-v4模型（1024维）
"""
import sys
import time
from pathlib import Path

# 添加backend目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

from database import rebuild_image_vectors

print("=" * 70)
print("🔄 开始后台向量重建（使用text-embedding-v4）")
print("=" * 70)

batch_size = 10
total_success = 0
total_failed = 0
total_processed = 0
batch_num = 0

while True:
    batch_num += 1
    print(f"\n[{batch_num}] 开始第 {batch_num} 批...")
    
    try:
        # force=True只在第一批执行
        result = rebuild_image_vectors(batch_size=batch_size, force=(batch_num == 1))
        
        processed = result.get('total', 0)
        success = result.get('success', 0)
        failed = result.get('failed', 0)
        
        total_success += success
        total_failed += failed
        total_processed += processed
        
        print(f"   ✅ 本批: 处理{processed}张, 成功{success}张, 失败{failed}张")
        
        # 如果没有处理任何图片，说明已完成
        if processed == 0:
            print("\n✅ 所有图片已处理完成！")
            break
            
    except Exception as e:
        print(f"   ❌ 本批失败: {e}")
        import traceback
        traceback.print_exc()
        break
    
    # 每批之间暂停，避免API限流
    time.sleep(1)

print("\n" + "=" * 70)
print("📊 重建结果:")
print(f"   总批次: {batch_num}")
print(f"   总处理: {total_processed} 张图片")
print(f"   成功: {total_success} 张")
print(f"   失败: {total_failed} 张")
print("=" * 70)
