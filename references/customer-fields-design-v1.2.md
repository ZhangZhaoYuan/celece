# 客户信息字段设计方案

> **版本**：V1.2  
> **日期**：2026年8月4日  
> **状态**：待实施

---

## 一、字段设计原则

### 核心原则

1. **只存事实，不存计算结果** - 原始数据存库，派生数据实时计算
2. **避免数据不一致** - 不在多处存储同一信息的不同形式
3. **最小化字段** - 只存必要字段，非必要的实时计算

---

## 二、最终字段设计

### 客户表（customers）

| 字段 | 类型 | 必填 | 来源 | 说明 |
|------|------|------|------|------|
| id | INTEGER | ✅ | 自动生成 | 主键 |
| name | TEXT | ✅ | 手动填写 | 客户姓名 |
| title | TEXT | ❌ | 手动填写 | 称呼（张姐/李总） |
| age | TEXT | ❌ | 手动填写 | 年龄 |
| height | INTEGER | ❌ | 手动填写 | 身高(cm) |
| weight | INTEGER | ❌ | 手动填写 | 当前体重(斤) |
| target_weight | INTEGER | ❌ | 手动填写 | 目标体重(斤) |
| **purchase_history** | TEXT | ❌ | 手动添加 | JSON数组，存储所有购买记录 |
| customer_type | TEXT | ❌ | 自动/手动 | cid/treatment/package |
| remark | TEXT | ❌ | 手动填写 | 备注 |
| created_at | TEXT | ✅ | 自动生成 | 创建时间 |
| updated_at | TEXT | ✅ | 自动生成 | 更新时间 |

---

### purchase_history 字段结构

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

---

## 三、固定价格体系

| 疗程数 | 粒数 | 价格 | 产品名称 |
|--------|------|------|----------|
| 4疗程 | 120粒 | 2970元 | 标准疗程 |
| 6疗程 | 180粒 | 3960元 | 完整疗程 |
| 8疗程 | 240粒 | 4950元 | 加强疗程 |
| 10疗程 | 300粒 | 5940元 | 超级疗程 |

**规格**：120mg/粒，每小盒6粒，每疗程5小盒

---

## 四、自动计算逻辑

### 1. 最新一次购买信息

```javascript
function getLatestPurchase(history) {
  if (!history || history.length === 0) return null;
  const sorted = history.slice().sort((a, b) => 
    new Date(b.date) - new Date(a.date)
  );
  return sorted[0];
}
```

### 2. 累计购买次数

```javascript
function getTotalPurchases(history) {
  if (!history || history.length === 0) return 0;
  return history.length;
}
```

### 3. 累计消费金额

```javascript
function getTotalSpent(history) {
  if (!history || history.length === 0) return 0;
  return history.reduce((sum, r) => sum + r.amount, 0);
}
```

### 4. 下次复购日期

```javascript
const PRODUCT_CYCLES = {
  4: { days: 14, name: '4疗程（120粒）' },
  6: { days: 21, name: '6疗程（180粒）' },
  8: { days: 30, name: '8疗程（240粒）' },
  10: { days: 45, name: '10疗程（300粒）' },
};

function getNextRebuyDate(history) {
  if (!history || history.length === 0) return null;
  const latest = getLatestPurchase(history);
  const cycle = PRODUCT_CYCLES[latest.cycles] || PRODUCT_CYCLES[4];
  const purchaseDate = new Date(latest.date);
  const rebuyDate = new Date(purchaseDate);
  rebuyDate.setDate(rebuyDate.getDate() + cycle.days - 3); // 提前3天提醒
  return rebuyDate.toISOString().slice(0, 10);
}
```

---

## 五、前端交互设计

### 1. 侧边栏显示

```javascript
function renderCustomerItem(c) {
  const history = JSON.parse(c.purchase_history || '[]');
  const latest = getLatestPurchase(history);
  
  return `<div class="sidebar-item">
    <div class="top-row">
      <span class="name">${c.name}${c.title ? ' ('+c.title+')' : ''}</span>
    </div>
    <div class="preview">
      ${latest ? `${latest.cycles}疗程 · ${latest.amount}元` : '暂无购买记录'}
      ${c.remark ? ' · ' + c.remark.slice(0,20) : ''}
    </div>
  </div>`;
}
```

### 2. 购买历史下拉展示

```
┌─────────────────────────────────────────┐
│ 📅 2024-08-01  6疗程  180粒  3960元  ▼ │  ← 点击展开
└─────────────────────────────────────────┘
    ┌─────────────────────────────────┐
    │ 📅 2024-08-01  6疗程  180粒  3960元 │
    │ 📅 2024-06-01  4疗程  120粒  2970元 │
    │ 📅 2024-03-15  4疗程  120粒  2970元 │
    ├─────────────────────────────────┤
    │ ➕ 新增购买记录                 │
    └─────────────────────────────────┘
```

### 3. 新增购买表单

```html
<div class="add-purchase-form">
  <div class="form-row">
    <div class="form-group">
      <label>购买日期</label>
      <input type="date" id="newPurchaseDate" value="2024-08-01">
    </div>
    <div class="form-group">
      <label>购买疗程数</label>
      <select id="newPurchaseCycles">
        <option value="4">4疗程（120粒）- 2970元</option>
        <option value="6">6疗程（180粒）- 3960元</option>
        <option value="8">8疗程（240粒）- 4950元</option>
        <option value="10">10疗程（300粒）- 5940元</option>
      </select>
    </div>
  </div>
  <div class="form-row">
    <button onclick="addPurchaseRecord()">✅ 保存</button>
    <button onclick="cancelAddPurchase()">取消</button>
  </div>
</div>
```

---

## 六、数据库迁移

### SQL 迁移脚本

```sql
-- 新增 purchase_history 字段
ALTER TABLE customers ADD COLUMN purchase_history TEXT DEFAULT '[]';

-- 可选：移除旧的 purchase 字段（如果确定不再使用）
-- ALTER TABLE customers DROP COLUMN purchase;
```

### 现有数据补录

对于已有客户的购买历史，需要通过以下流程补录：

1. 打开客户编辑弹窗
2. 在"购买历史"区域点击"➕ 新增购买"
3. 填写购买日期和疗程数
4. 系统自动计算粒数和金额
5. 保存后更新显示

---

## 七、后端 API 修改

### 1. 创建/更新客户

```python
def create_customer(
    name: str,
    title: str = "",
    age: str = "",
    height: str = "",
    weight: str = "",
    target_weight: str = "",
    purchase_history: str = "[]",
    customer_type: str = "",
    remark: str = ""
):
    """创建新客户"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO customers 
           (name, title, age, height, weight, target_weight, 
            purchase_history, customer_type, remark, created_at, updated_at) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, title, age, height, weight, target_weight, 
         purchase_history, customer_type, remark, now, now)
    )
    customer_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": customer_id, "name": name}
```

### 2. 返回客户数据时附带计算字段

```python
def list_customers(search: str = "") -> List[dict]:
    """获取客户列表"""
    conn = get_db()
    if search:
        cursor = conn.execute(
            """SELECT * FROM customers 
               WHERE name LIKE ? OR remark LIKE ?
               ORDER BY created_at DESC""",
            (f"%{search}%", f"%{search}%")
        )
    else:
        cursor = conn.execute("SELECT * FROM customers ORDER BY created_at DESC")
    
    customers = []
    for row in cursor.fetchall():
        c = dict(row)
        # 实时计算展示字段
        history = json.loads(c.get('purchase_history') or '[]')
        if history:
            c['latest_purchase'] = history[-1]  # 最后一条是最新的
            c['total_purchases'] = len(history)
            c['next_rebuy_date'] = calc_next_rebuy_date(history)
        customers.append(c)
    
    conn.close()
    return customers
```

---

## 八、实施计划

### Phase 1：数据库 + 后端（0.5天）
- [ ] 新增 `purchase_history` 字段
- [ ] 修改 `create_customer` / `update_customer` 函数
- [ ] 修改 `list_customers` 返回计算字段

### Phase 2：前端表单（0.5天）
- [ ] 修改客户编辑弹窗，新增购买历史组件
- [ ] 实现下拉展示、新增、删除功能
- [ ] 实现自动计算逻辑

### Phase 3：侧边栏展示（0.5天）
- [ ] 修改客户列表渲染逻辑
- [ ] 显示最新购买信息

### Phase 4：数据补录（按需）
- [ ] 为已有客户补录购买历史
- [ ] 验证计算结果正确性

---

## 九、注意事项

1. **向后兼容** - 新字段有默认值 `[]`，不影响现有客户
2. **数据迁移** - 迁移后需重启服务
3. **备份策略** - 修改前备份数据库到 `D:\备份\小赛助手\`
4. **测试验证** - 新功能上线前验证购买历史计算逻辑

---

**文档完成日期**：2026年8月4日  
**下一步**：确认设计，开始实施
