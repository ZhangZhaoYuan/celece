"""常见问题管理"""
from datetime import datetime
from database import get_db


def list_faqs(category="", sort_by="sort_order", sort_order="asc"):
    """获取FAQ列表"""
    conn = get_db()
    if category:
        rows = conn.execute(
            f"SELECT * FROM faq_entries WHERE category=? ORDER BY {sort_by} {sort_order}",
            (category,)
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM faq_entries ORDER BY {sort_by} {sort_order}"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_faq(faq_id):
    """获取单个FAQ"""
    conn = get_db()
    faq = conn.execute("SELECT * FROM faq_entries WHERE id=?", (faq_id,)).fetchone()
    conn.close()
    return dict(faq) if faq else None


def add_faq(question, answer, category="", sort_order=0):
    """添加FAQ"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO faq_entries (question, answer, category, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (question, answer, category, sort_order, now, now)
    )
    faq_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _sync_faq_to_knowledge()
    return {"id": faq_id, "question": question}


def update_faq(faq_id, question, answer, category="", sort_order=0):
    """更新FAQ"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    conn.execute(
        "UPDATE faq_entries SET question=?, answer=?, category=?, sort_order=?, updated_at=? WHERE id=?",
        (question, answer, category, sort_order, now, faq_id)
    )
    conn.commit()
    conn.close()
    _sync_faq_to_knowledge()
    return True


def delete_faq(faq_id):
    """删除FAQ"""
    conn = get_db()
    conn.execute("DELETE FROM faq_entries WHERE id=?", (faq_id,))
    conn.commit()
    deleted = conn.total_changes > 0
    conn.close()
    _sync_faq_to_knowledge()
    return deleted


def _sync_faq_to_knowledge():
    """同步FAQ到知识库（自动向量化，供生成话术时搜索）"""
    import os
    from pathlib import Path
    from knowledge import KNOWLEDGE_DIR, add_document, reindex_document
    
    faqs = list_faqs()
    if not faqs:
        return
    
    # 生成FAQ文本
    lines = ["# 常见问题 - 赛乐赛瘦身顾问", "---"]
    for f in faqs:
        lines.append(f"问：{f['question']}")
        lines.append(f"答：{f['answer']}")
        lines.append("---")
    
    content = "\n\n".join(lines)
    
    # 写入知识库文件
    faq_file = KNOWLEDGE_DIR / "常见问题.txt"
    faq_file.write_text(content, encoding="utf-8")
    
    # 如果文档已存在，更新；否则新建
    try:
        reindex_document("常见问题.txt")
    except Exception:
        try:
            add_document("常见问题.txt", content)
        except Exception:
            pass