"""有效话术库管理"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from database import get_db


def add_effective_script(content, scenario="", customer_type="", effective_count=1, score=0):
    """添加有效话术，如果已存在相同内容则累加有效次数和评分"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    existing = conn.execute(
        "SELECT id, effective_count, score FROM effective_scripts WHERE content=?",
        (content,)
    ).fetchone()
    if existing:
        # 取最高评分，累加有效次数
        new_score = max(score, existing["score"])
        conn.execute(
            "UPDATE effective_scripts SET effective_count=effective_count+?, score=?, last_effective_at=?, vector_status='pending' WHERE id=?",
            (effective_count, new_score, now, existing["id"])
        )
        conn.commit()
        conn.close()
        return {"id": existing["id"], "updated": True, "effective_count": existing["effective_count"] + effective_count, "score": new_score}
    cursor = conn.execute(
        "INSERT INTO effective_scripts (content, scenario, customer_type, effective_count, score, last_effective_at) VALUES (?, ?, ?, ?, ?, ?)",
        (content, scenario, customer_type, effective_count, score, now)
    )
    script_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": script_id, "updated": False, "effective_count": effective_count, "score": score}


def list_effective_scripts(scenario="", customer_type="", sort_by="score", sort_order="desc", limit=100, offset=0):
    """列出有效话术，默认按评分排序"""
    conditions = []
    params = []
    if scenario:
        conditions.append("scenario=?")
        params.append(scenario)
    if customer_type:
        conditions.append("customer_type=?")
        params.append(customer_type)
    where = " AND ".join(conditions) if conditions else "1=1"
    allowed_sort = ("effective_count", "score", "last_effective_at", "created_at")
    order = f"{sort_by} {sort_order.upper()}" if sort_by in allowed_sort else "score DESC"
    conn = get_db()
    cursor = conn.execute(
        f"SELECT * FROM effective_scripts WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [limit, offset]
    )
    scripts = [dict(r) for r in cursor.fetchall()]
    total = conn.execute(f"SELECT COUNT(*) FROM effective_scripts WHERE {where}", params).fetchone()[0]
    conn.close()
    return {"total": total, "scripts": scripts, "limit": limit, "offset": offset}


def get_effective_script_stats():
    """获取有效话术统计"""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM effective_scripts").fetchone()[0]
    total_effective = conn.execute("SELECT SUM(effective_count) FROM effective_scripts").fetchone()[0] or 0
    by_scenario = [dict(r) for r in conn.execute(
        "SELECT scenario, COUNT(*) as count, SUM(effective_count) as total_effective FROM effective_scripts GROUP BY scenario ORDER BY total_effective DESC"
    ).fetchall()]
    by_customer_type = [dict(r) for r in conn.execute(
        "SELECT customer_type, COUNT(*) as count, SUM(effective_count) as total_effective FROM effective_scripts GROUP BY customer_type ORDER BY total_effective DESC"
    ).fetchall()]
    vector_failed = conn.execute("SELECT COUNT(*) FROM effective_scripts WHERE vector_status='failed'").fetchone()[0]
    conn.close()
    return {
        "total": total,
        "total_effective": total_effective,
        "by_scenario": by_scenario,
        "by_customer_type": by_customer_type,
        "vector_failed": vector_failed
    }


def delete_effective_script(script_id):
    """删除有效话术"""
    conn = get_db()
    conn.execute("DELETE FROM effective_scripts WHERE id=?", (script_id,))
    conn.commit()
    deleted = conn.total_changes > 0
    conn.close()
    return deleted


def update_script_vector_status(script_id, status):
    """更新向量化状态"""
    conn = get_db()
    conn.execute("UPDATE effective_scripts SET vector_status=? WHERE id=?", (status, script_id))
    conn.commit()
    conn.close()


def revectorize_script(script_id):
    """重新向量化单条话术"""
    conn = get_db()
    script = conn.execute("SELECT * FROM effective_scripts WHERE id=?", (script_id,)).fetchone()
    conn.close()
    if not script:
        return False
    try:
        from knowledge import get_embedding
        vec = get_embedding(script["content"])
        if vec:
            update_script_vector_status(script_id, "done")
            return True
        else:
            update_script_vector_status(script_id, "failed")
            return False
    except Exception:
        update_script_vector_status(script_id, "failed")
        return False


def search_effective_scripts_by_scenario(scenario, customer_type="", top_k=5):
    """搜索相似场景的有效话术，按评分排序"""
    conn = get_db()
    conditions = ["scenario=? OR ?=''"]
    params = [scenario, scenario]
    if customer_type:
        conditions.append("(customer_type=? OR customer_type='')")
        params.append(customer_type)
    where = " AND ".join(conditions)
    cursor = conn.execute(
        f"SELECT * FROM effective_scripts WHERE {where} AND vector_status='done' ORDER BY score DESC, effective_count DESC LIMIT ?",
        params + [top_k]
    )
    scripts = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return scripts


def dedup_effective_scripts():
    """去重合并：相似内容合并累加有效次数和评分"""
    conn = get_db()
    scripts = [dict(r) for r in conn.execute("SELECT * FROM effective_scripts ORDER BY score DESC, effective_count DESC").fetchall()]
    merged = 0
    deleted_ids = []
    for i in range(len(scripts)):
        if scripts[i]["id"] in deleted_ids:
            continue
        for j in range(i+1, len(scripts)):
            if scripts[j]["id"] in deleted_ids:
                continue
            a, b = scripts[i]["content"], scripts[j]["content"]
            if len(a) > 5 and len(b) > 5:
                if a in b or b in a:
                    new_score = max(scripts[i]["score"], scripts[j]["score"])
                    conn.execute(
                        "UPDATE effective_scripts SET effective_count=effective_count+?, score=? WHERE id=?",
                        (scripts[j]["effective_count"], new_score, scripts[i]["id"])
                    )
                    conn.execute("DELETE FROM effective_scripts WHERE id=?", (scripts[j]["id"],))
                    deleted_ids.append(scripts[j]["id"])
                    merged += 1
    conn.commit()
    conn.close()
    return {"merged": merged}