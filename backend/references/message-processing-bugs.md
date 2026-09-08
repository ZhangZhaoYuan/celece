# 消息处理 Bug 与修复记录

## 2026-08-31: 删除消息后 user 消息丢失问题

### 问题现象
用户删除 assistant 消息后刷新页面，发现最后一条 user 消息也消失了，且之前消息的时间戳被覆盖为最后一条 user 消息的时间。

### 根本原因
前端 `mergeConsecutiveMessages()` 函数会合并所有连续的同角色消息：
```javascript
// 修复前：合并所有同角色消息
if (msg.role === current.role) {
```
导致：
- 陈伟文的 5 条 user 消息被合并成 1 条
- 时间戳被覆盖为最后一条消息的时间
- 删除 assistant 消息后重新加载，触发了合并逻辑

### 修复方案
**文件**: `frontend/index.html:1358`

```javascript
// 修复后：只合并 assistant 消息，user 消息保持独立
if (msg.role === current.role && msg.role === 'assistant') {
```

### 删除逻辑修复
**文件**: `frontend/index.html:1615`

```javascript
async function deleteMessage(msgId, idx) {
  const ok = await showConfirm('确定删除此消息？', '删除消息');
  if (!ok) return;
  try {
    const resp = await api('DELETE', `/api/messages/${msgId}`);
    if (resp.status === 'ok') {
      // 删除成功后重新加载消息列表，确保状态一致
      await loadMessages(selectedCustomerId);
    } else {
      // 用 msgId 找当前索引，避免 idx 过期
      const realIdx = messages.findIndex(m => m.id === msgId);
      if (realIdx !== -1) {
        messages.splice(realIdx, 1);
        renderMessages();
      }
    }
  } catch(e) { showToast('删除失败: '+e.message); }
}
```

### 验证结果
- 陈伟文(52): 5 条 user 消息正常显示
- 魏女士(55): 8 条 user 消息正常显示
- 删除 assistant 消息后，user 消息不受影响

### 历史数据损失
- assistant 消息从未保存到 messages.db（保存功能是新添加的）
- 历史 assistant 消息无法恢复
- 以后生成的新话术会正常保存

## 数据库 ID 断点分析

检查 messages.db 发现 22 个 ID 断点，表明大量历史消息曾存在后被删除。这是正常业务行为，不是 bug。

| ID 范围 | 缺失数量 |
|---------|----------|
| 1395-1484 | 89 |
| 其他分散断点 | 若干 |

### 建议
定期备份 messages.db，防止误删恢复困难。

## 消息保存流程

```
用户发送消息
  ↓
前端 POST /api/customers/{id}/messages (role=user)
  ↓
后端保存到 messages.db
  ↓
生成话术
  ↓
前端 POST /api/customers/{id}/messages (role=assistant)
  ↓
后端保存到 messages.db
```

### 注意事项
1. assistant 消息保存失败时，前端会显示 toast 错误提示
2. 删除消息后必须重新加载，否则前端状态与数据库不同步
3. user 消息不合并，保持独立显示
4. 连续 assistant 消息可合并显示（多段话术）

## 排查方法

### 检查数据库消息完整性
```bash
python -c "
import sqlite3
from pathlib import Path

msg_db = Path('data/messages.db')
conn = sqlite3.connect(msg_db)
cur = conn.cursor()

# 检查特定客户的消息
print('=== 陈伟文(52) 消息列表 ===')
cur.execute('SELECT id, role, timestamp FROM messages WHERE customer_id=52 ORDER BY timestamp')
for row in cur.fetchall():
    print(f'  id={row[0]}, role={row[1]}, time={row[2]}')

# 检查 ID 断点
print('\\n=== ID 断点分析 ===')
cur.execute('SELECT id FROM messages ORDER BY id')
all_ids = [r[0] for r in cur.fetchall()]
gaps = []
for i in range(1, len(all_ids)):
    if all_ids[i] - all_ids[i-1] > 1:
        gaps.append((all_ids[i-1], all_ids[i], all_ids[i] - all_ids[i-1] - 1))
print(f'发现 {len(gaps)} 个断点')
for start, end, count in gaps[:5]:
    print(f'  {start}-{end}: 缺失 {count} 条')
"
```

### 检查前端合并逻辑
```bash
grep -n "mergeConsecutiveMessages" frontend/index.html
```

确认当前实现：
```javascript
// 正确的实现：只合并 assistant 消息
if (msg.role === current.role && msg.role === 'assistant') {
```
