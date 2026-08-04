"""
历史消息筛选：遍历所有消息，找出有效话术
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "backend"))

from database import get_db, get_messages_db
from effective_scripts import add_effective_script

def scan_all():
    conn = get_db()
    customers = {r["id"]: r for r in conn.execute("SELECT id, name, customer_type FROM customers").fetchall()}
    msg_conn = get_messages_db()
    
    saved = 0
    
    for cid, c in customers.items():
        ctype = c["customer_type"] if c["customer_type"] else ""
        ctype_label = {"package": "套餐客户", "treatment": "疗程客户", "cid": "CID客户"}.get(ctype, "CID客户")
        
        msgs = msg_conn.execute(
            "SELECT * FROM messages WHERE customer_id=? ORDER BY id ASC",
            (cid,)
        ).fetchall()
        
        if len(msgs) < 2:
            continue
        
        for i in range(len(msgs) - 1):
            if msgs[i]["role"] == "assistant":
                content = msgs[i]["content"]
                next_msg = msgs[i + 1]
                
                if len(content) < 10:
                    continue
                    
                user_reply = next_msg["content"]
                positive = True
                for w in ["不", "别", "不用", "不要", "不需要", "算了", "再考虑", "太贵", "没钱"]:
                    if w in user_reply:
                        positive = False
                        break
                
                if positive:
                    scenario = "效果确认"
                    if "排油" in content or "排便" in content: scenario = "排油跟进"
                    elif "买" in content or "续费" in content or "优惠" in content: scenario = "复购推荐"
                    elif "瘦" in content or "体重" in content: scenario = "效果确认"
                    elif "贵" in content or "价格" in content: scenario = "价格异议"
                    elif "付款" in content or "下单" in content: scenario = "逼单成交"
                    
                    result = add_effective_script(content[:500], scenario, ctype_label, 1)
                    saved += 1
                    action = "🔄 更新" if result.get("updated") else "✅ 新增"
                    print(f"  {action} [{scenario}] {ctype_label}: {content[:40]}...")
    
    msg_conn.close()
    conn.close()
    print(f"\n✅ 完成：已保存 {saved} 条有效话术")

if __name__ == "__main__":
    scan_all()