"""
清空旧数据，按新规则重新扫描所有客户消息
新规则：
1. 按发送者分割消息块（不是按空行）
2. 三级评分：即时反应+话术质量
3. 评分≥2才存
"""
import sys
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "backend"))

from database import get_db, get_messages_db
from effective_scripts import add_effective_script


def extract_content_from_block(block):
    """从消息块中提取纯文本内容（去掉头部发送者信息）"""
    lines = block.split("\n")
    if len(lines) > 1:
        return "\n".join(lines[1:]).strip()
    return block.strip()


def score_script(B_content, C_content):
    """三级评分"""
    score = 0
    response_type = "中性"
    scenario = "效果确认"
    
    # 第一层：即时反应
    buy_words = ["买", "付款", "多少钱", "下单", "转账", "支付", "收款码", "怎么付"]
    positive_words = ["好的", "瘦", "效果", "谢谢", "继续", "行", "可以", "不错", "有效", "轻了"]
    reject_words = ["不", "别", "不用", "不要", "不需要", "算了", "再考虑", "太贵", "没钱", "自己来"]
    
    for w in buy_words:
        if w in C_content:
            score += 3
            response_type = "成交"
            scenario = "复购推荐"
            break
    
    if response_type == "中性":
        for w in positive_words:
            if w in C_content:
                score += 2
                response_type = "积极"
                break
    
    if response_type == "中性":
        for w in reject_words:
            if w in C_content:
                score -= 1
                response_type = "消极"
                break
    
    if response_type == "中性" and len(C_content) > 0:
        score += 1
    
    # 第二层：话术质量
    if 30 <= len(B_content) <= 600:
        score += 1
    if "?" in B_content or "？" in B_content or "对不对" in B_content or "是吧" in B_content:
        score += 1
    if any(c.isdigit() for c in B_content):
        score += 1
    if "开心" in B_content or "高兴" in B_content or "放心" in B_content or "心疼" in B_content or "感动" in B_content:
        score += 1
    
    # 判断场景
    if "排油" in B_content or "排便" in B_content or "油脂" in B_content:
        scenario = "排油跟进"
    elif "瘦" in B_content or "体重" in B_content or "斤" in B_content:
        scenario = "效果确认"
    elif "买" in B_content or "续费" in B_content or "优惠" in B_content or "活动" in B_content:
        scenario = "复购推荐"
    elif "贵" in B_content or "价格" in B_content or "钱" in B_content:
        scenario = "异议处理"
    elif "阶段" in B_content or "周期" in B_content or "过程" in B_content:
        scenario = "科普教育"
    
    return score, response_type, scenario


def main():
    # 1. 清空旧数据
    conn = get_db()
    old_count = conn.execute("SELECT COUNT(*) FROM effective_scripts").fetchone()[0]
    conn.execute("DELETE FROM effective_scripts")
    conn.commit()
    conn.close()
    print(f"✅ 已清空 {old_count} 条旧数据")
    
    # 2. 获取所有客户
    conn = get_db()
    customers = conn.execute("SELECT id, name, customer_type FROM customers").fetchall()
    conn.close()
    print(f"📋 共 {len(customers)} 个客户")
    
    # 3. 获取所有消息
    msg_conn = get_messages_db()
    
    saved = 0
    skipped = 0
    
    for c in customers:
        cid = c["id"]
        cname = c["name"]
        ctype = c["customer_type"] if c["customer_type"] else ""
        ctype_label = {"package": "套餐客户", "treatment": "疗程客户", "cid": "CID客户"}.get(ctype, "CID客户")
        
        # 获取该客户所有消息，按时间排序
        msgs = msg_conn.execute(
            "SELECT * FROM messages WHERE customer_id=? ORDER BY id ASC",
            (cid,)
        ).fetchall()
        
        if len(msgs) < 2:
            continue
        
        # 遍历消息，找配对：张兆渊发的消息(B) → 客户回复(C)
        for i in range(len(msgs) - 1):
            msg = msgs[i]
            next_msg = msgs[i + 1]
            
            # B：张兆渊发的消息（role=user，内容含"张兆渊"）
            is_B_yours = "张兆渊" in (msg["content"] or "")
            # C：客户发的消息（role=user，内容不含"张兆渊"）
            is_C_customer = "张兆渊" not in (next_msg["content"] or "")
            
            if not is_B_yours or not is_C_customer:
                continue
            
            # 提取纯内容
            B_content = extract_content_from_block(msg["content"])
            C_content = extract_content_from_block(next_msg["content"])
            
            if len(B_content) < 10:
                continue
            
            # 评分
            score, response_type, scenario = score_script(B_content, C_content)
            
            if score >= 2:
                add_effective_script(B_content[:500], scenario, ctype_label, 1, score)
                saved += 1
                print(f"  ✅ [{scenario}] ⭐{score} ({response_type}) {cname}: {B_content[:40]}...")
            else:
                skipped += 1
    
    msg_conn.close()
    print(f"\n📊 结果：")
    print(f"   新增有效话术: {saved} 条")
    print(f"   评分不足跳过: {skipped} 条")
    
    # 4. 重新向量化
    print("\n🔄 开始向量化...")
    conn = get_db()
    scripts = conn.execute("SELECT id, content FROM effective_scripts WHERE vector_status='pending'").fetchall()
    conn.close()
    
    if scripts:
        from knowledge import get_embedding
        vec_ok = 0
        vec_fail = 0
        for s in scripts:
            try:
                vec = get_embedding(s["content"])
                if vec:
                    conn = get_db()
                    conn.execute("UPDATE effective_scripts SET vector_status='done' WHERE id=?", (s["id"],))
                    conn.commit()
                    conn.close()
                    vec_ok += 1
                else:
                    conn = get_db()
                    conn.execute("UPDATE effective_scripts SET vector_status='failed' WHERE id=?", (s["id"],))
                    conn.commit()
                    conn.close()
                    vec_fail += 1
            except:
                vec_fail += 1
        print(f"   向量化成功: {vec_ok}，失败: {vec_fail}")
    else:
        print("   无待向量化数据")


if __name__ == "__main__":
    main()