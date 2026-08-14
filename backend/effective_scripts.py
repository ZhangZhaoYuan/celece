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


def update_effective_script(script_id, content, scenario="", customer_type=""):
    """更新有效话术内容"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    conn.execute(
        "UPDATE effective_scripts SET content=?, scenario=?, customer_type=?, updated_at=? WHERE id=?",
        (content, scenario, customer_type, now, script_id)
    )
    conn.commit()
    conn.close()
    return True


def revectorize_script(script_id):
    """重新向量化单条话术"""
    conn = get_db()
    script = conn.execute("SELECT * FROM effective_scripts WHERE id=?", (script_id,)).fetchone()
    conn.close()
    if not script:
        return False
    try:
        from knowledge import _get_embedding as get_embedding
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
    """搜索相似场景的有效话术，支持向量语义搜索和关键词匹配"""
    conn = get_db()

    # 1. 尝试向量搜索
    vec_results = []
    try:
        from knowledge import _get_embedding as get_embedding, _embedding_available

        if _embedding_available and scenario:
            query_vec = get_embedding(scenario)
            if query_vec:
                from knowledge import _get_vec_conn, _vec_to_str
                vconn = _get_vec_conn()
                vcur = vconn.cursor()
                vec_str = _vec_to_str(query_vec)
                try:
                    # 先查effective_vectors表是否存在
                    vcur.execute("SELECT 1 FROM effective_vectors LIMIT 1")
                    rows = vcur.execute(
                        """
                        SELECT ev.id as vec_id, ev.distance
                        FROM effective_vectors ev
                        WHERE ev.vector MATCH ? AND k = ?
                        ORDER BY ev.distance
                        """,
                        (vec_str, top_k * 2)
                    ).fetchall()
                    for rank, row in enumerate(rows):
                        distance = row["distance"]
                        score = max(0, 1.0 - distance / 2.0)
                        vec_id = row["vec_id"]
                        if score > 0.3:  # 阈值过滤
                            # 通过映射表获取script_id
                            vcur.execute(
                                "SELECT script_id FROM effective_scripts_vector_map WHERE vec_id=?",
                                (vec_id,)
                            )
                            map_row = vcur.fetchone()
                            if map_row:
                                script = conn.execute(
                                    "SELECT * FROM effective_scripts WHERE id = ?",
                                    (map_row["script_id"],)
                                ).fetchone()
                                if script:
                                    vec_results.append({
                                        **dict(script),
                                        "_search_score": round(score, 4),
                                        "_search_method": "vector"
                                    })
                    vconn.close()
                except sqlite3.OperationalError:
                    # 表不存在，忽略向量搜索结果
                    pass
    except Exception as e:
        pass

    # 2. 关键词兜底搜索（当向量搜索结果为空或分数过低时）
    if not vec_results or len(vec_results) < top_k // 2:
        # 提取场景关键词
        keywords = []
        if scenario:
            # 常见场景关键词映射
            scenario_map = {
                "体重上涨": ["体重", "上涨", "增加", "涨秤"],
                "不回复": ["不回复", "没回复", "沉默", "不理"],
                "套餐推荐": ["套餐", "推荐", "买", "购买", "下单"],
                "减肥案例": ["案例", "成功", "效果", "反馈"],
                "排油跟进": ["排油", "排便", "油脂", "拉肚子"],
                "效果确认": ["瘦了", "体重", "斤", "数据", "效果"],
                "复购推荐": ["复购", "续费", "续单", "再买"],
                "异议处理": ["贵", "价格", "钱", "太贵", "划算"],
            }
            for kw, synonyms in scenario_map.items():
                if kw in scenario or any(s in scenario for s in synonyms):
                    keywords.extend(synonyms)
            if not keywords:
                keywords = [w for w in scenario.split() if len(w) > 1][:5]
        else:
            keywords = [w for w in scenario.split() if len(w) > 1][:5] if scenario else []

        # 关键词搜索
        conditions = ["vector_status='done'"]
        params = []
        if customer_type:
            conditions.append("(customer_type=? OR customer_type='')")
            params.append(customer_type)
        if keywords:
            kw_conditions = " OR ".join(["content LIKE ?" for _ in keywords])
            conditions.append(f"({kw_conditions})")
            params.extend([f"%{kw}%" for kw in keywords])

        where = " AND ".join(conditions)
        cursor = conn.execute(
            f"SELECT * FROM effective_scripts WHERE {where} ORDER BY score DESC, effective_count DESC LIMIT ?",
            params + [top_k]
        )
        kw_results = [dict(r) for r in cursor.fetchall()]
        for r in kw_results:
            r["_search_method"] = "keyword"
    else:
        kw_results = []

    conn.close()

    # 3. 合并结果（向量优先，去重）
    seen_ids = set()
    final_results = []
    for r in vec_results:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            final_results.append(r)
    for r in kw_results:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            final_results.append(r)

    return final_results[:top_k]


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