# 客户信息字段设计模式

> 小赛助手客户数据建模最佳实践
> 创建日期：2026-08-03

---

## 核心原则

### 1. 派生数据不存储
**规则**：能从一个字段实时计算出来的数据，不要单独存储。

| 字段 | 是否存储 | 原因 |
|------|----------|------|
| `total_spent`（累计消费） | ❌ 不存 | 从 `purchase_history` 计算，避免不一致 |
| `total_count`（购买次数） | ❌ 不存 | `len(purchase_history)` 即可 |
| `silent_days`（沉默天数） | ❌ 不存 | `today - last_msg_time` 即可 |
| `bmi`（BMI指数） | ❌ 不存 | `weight / (height/100)²` 即可 |
| `health_level`（健康等级） | ❌ 不存 | 基于 BMI 判断，无需存储 |

### 2. 高频查询字段必须存储
**规则**：被频繁查询、用于筛选排序的字段，存储并加索引。

| 字段 | 是否存储 | 原因 |
|------|----------|------|
| `last_msg_time` | ✅ 必须 | 跟进提醒核心依据，高频查询 |
| `communication_count` | ✅ 存储 | 活跃客户筛选，触发器自动维护 |
| `purchase_history` | ✅ 必须 | 核心业务数据，JSON数组存储 |

### 3. 自动计算 vs 手动维护的平衡
- **自动计算**：派生字段（BMI、沉默天数）
- **手动填写**：基础信息（姓名、年龄）
- **触发器维护**：高频统计（沟通次数）

---

## 购买记录设计

### 数据结构

```sql
-- 客户表
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT,           -- 称呼（张姐/李总）
    age INTEGER,
    height INTEGER,       -- 身高(cm)
    weight INTEGER,       -- 体重(斤)
    target_weight INTEGER, -- 目标体重
    purchase_history TEXT DEFAULT '[]',  -- 购买历史(JSON)
    last_msg_time TEXT,   -- 最后沟通时间
    communication_count INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    remark TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

### purchase_history 格式

```json
[
  {
    "date": "2024-06-01",
    "cycles": 4,
    "pills": 120,
    "amount": 2970
  },
  {
    "date": "2024-08-01",
    "cycles": 6,
    "pills": 180,
    "amount": 3960
  }
]
```

### 自动计算逻辑

```python
from datetime import datetime, timedelta
import json

# 产品周期配置（赛乐赛固定规格：120mg/粒）
PRODUCT_CYCLES = {
    4: {"days": 14, "pills_per_day": 3, "name": "4疗程"},
    6: {"days": 21, "pills_per_day": 3, "name": "6疗程"},
    8: {"days": 28, "pills_per_day": 3, "name": "8疗程"},
    10: {"days": 35, "pills_per_day": 3, "name": "10疗程"},
}

def calc_purchase_stats(purchase_history_json):
    """计算购买统计信息"""
    history = json.loads(purchase_history_json or '[]')
    
    if not history:
        return {
            'total_count': 0,
            'total_amount': 0,
            'last_purchase_date': None,
            'next_rebuy_date': None,
            'days_remaining': None
        }
    
    # 累计统计
    total_count = len(history)
    total_amount = sum(r['amount'] for r in history)
    last_purchase = max(r['date'] for r in history)
    
    # 下次复购计算（基于最近一次购买）
    last_record = next(r for r in history if r['date'] == last_purchase)
    cycle_days = PRODUCT_CYCLES.get(last_record['cycles'], PRODUCT_CYCLES[4])
    next_rebuy = datetime.strptime(last_purchase, '%Y-%m-%d') + timedelta(days=cycle_days-3)
    days_remaining = (next_rebuy - datetime.now()).days
    
    return {
        'total_count': total_count,
        'total_amount': total_amount,
        'last_purchase_date': last_purchase,
        'next_rebuy_date': next_rebuy.strftime('%Y-%m-%d'),
        'days_remaining': days_remaining
    }
```

---

## 跟进提醒设计

### 触发规则

| 时间 | 触发条件 | 话术建议 |
|------|----------|----------|
| +3天 | 购买后第3天 | "张姐，用药3天了，排油怎么样？" |
| +7天 | 购买后第7天 | "一周了，体重有变化吗？" |
| +14天 | 购买后第14天 | "半疗程了，现在续费有优惠哦" |
| +28天 | 购买后第28天 | "一个疗程快完了，准备续上吗？" |
| -3天 | 下次复购前3天 | "张姐，您的药快吃完了，现在续费有优惠" |

### 跟进状态

```python
FOLLOW_UP_STATUSES = {
    'pending': '待跟进',
    'completed': '已完成',
    'snoozed': '已延期'
}
```

---

## 前端展示优化

### 客户卡片显示

```html
<div class="sidebar-item">
  <div class="top-row">
    <span class="name">张三</span>
    <span class="rebuy-badge upcoming">3天后复购</span>
  </div>
  <div class="preview">
    6个疗程 · 剩余12粒 · 购买于2024-08-01
  </div>
</div>
```

### 购买历史展示

```html
<div class="purchase-history">
  <div class="purchase-item">
    <span class="date">2024-08-01</span>
    <span class="cycles">6疗程</span>
    <span class="pills">180粒</span>
    <span class="amount">3960元</span>
  </div>
  <div class="purchase-item">
    <span class="date">2024-06-01</span>
    <span class="cycles">4疗程</span>
    <span class="pills">120粒</span>
    <span class="amount">2970元</span>
  </div>
</div>
```

---

## 数据迁移

### 新增字段（兼容现有数据）

```sql
-- 新增购买相关字段
ALTER TABLE customers ADD COLUMN purchase_history TEXT DEFAULT '[]';
ALTER TABLE customers ADD COLUMN last_msg_time TEXT DEFAULT NULL;
ALTER TABLE customers ADD COLUMN communication_count INTEGER DEFAULT 0;

-- 新增触发器（自动累加沟通次数）
CREATE TRIGGER increment_msg_count
AFTER INSERT ON messages
FOR EACH ROW
BEGIN
    UPDATE customers 
    SET communication_count = communication_count + 1,
        last_msg_time = NEW.timestamp
    WHERE id = NEW.customer_id;
END;
```

---

## 注意事项

1. **不要新增单独的购买记录表** - 用 JSON 数组足够，避免多表关联复杂度
2. **不要存储派生字段** - 累计消费、购买次数等实时计算即可
3. **购买金额固定** - 4疗程2970、6疗程3960、8疗程4950、10疗程5940，前端下拉选择疗程数即可
4. **每日用量固定3粒** - 赛乐赛标准用法，无需客户填写
5. **复购缓冲期3天** - 提前3天提醒复购，给用户预留时间
