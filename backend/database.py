"""
数据库操作模块 - 小赛助手
使用 SQLite 存储客户数据、消息记录和知识库内容
"""
import sqlite3
import os
import json
import re
import time
from datetime import datetime
from pathlib import Path
import sys
from typing import Optional, List

# 数据库路径
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# 主数据库：客户、配置、话术模板
DB_PATH = DATA_DIR / "customers.db"
# 消息数据库（单独文件，减少主库体积）
DB_MESSAGES_PATH = DATA_DIR / "messages.db"
# 向量数据库（知识库向量，大文件独立）
DB_VECTORS_PATH = DATA_DIR / "vectors.db"
# 图片向量数据库
DB_IMAGE_VEC_PATH = DATA_DIR / "image_vectors.db"

# 启动标记：检查是否需要迁移
_DB_MIGRATED = False


def ensure_data_dir():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    """获取主数据库连接（客户/配置/话术模板）"""
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_messages_db():
    """获取消息数据库连接（单独文件）"""
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_MESSAGES_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # 初始化消息表（如果尚未创建）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            session_id TEXT DEFAULT '',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    # 索引
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_customer_id ON messages(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_customer_ts ON messages(customer_id, timestamp)")
    except:
        pass
    conn.commit()
    return conn


def get_vectors_db():
    """获取知识库向量数据库连接（单独文件）"""
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_VECTORS_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # 初始化向量表
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_vectors USING vec0(
                id TEXT PRIMARY KEY,
                vector FLOAT[1536]
            )
        """)
    except Exception:
        pass
    return conn


def get_image_vec_db():
    """获取图片向量数据库连接（单独文件）"""
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_IMAGE_VEC_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # 初始化图片向量表
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS image_vectors USING vec0(
                image_id INTEGER PRIMARY KEY,
                vector FLOAT[1536]
            )
        """)
    except Exception:
        pass
    return conn


def ensure_data_dir():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def init_db():
    """初始化数据库表"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 客户表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    title TEXT,
    age TEXT,
    height TEXT,
    weight TEXT,
    target_weight TEXT,
    purchase TEXT,
    purchase_history TEXT DEFAULT '[]',
    customer_type TEXT,
    remark TEXT,
    created_at TEXT,
    updated_at TEXT
        )
    """)
    
    # 知识库 chunks 表（主库中保留文本数据）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    filename TEXT,
    title TEXT,
    created_at TEXT
        )
    """)
    
    # 初始化消息库（独立文件）
    try:
        mconn = get_messages_db()
        mconn.close()
    except Exception:
        pass
    
    # 初始化向量库（独立文件）
    try:
        vconn = get_vectors_db()
        vconn.close()
    except Exception:
        pass
    
    # 初始化图片向量库（独立文件）
    try:
        ivconn = get_image_vec_db()
        ivconn.close()
    except Exception:
        pass

    # 图片索引表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS image_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    file_hash TEXT,
    category TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    applicable_customers TEXT DEFAULT '',
    case_group_id TEXT DEFAULT '',
    img_order INTEGER DEFAULT 0,
    error_msg TEXT DEFAULT '',
    file_size INTEGER DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    
    # 兼容旧表：添加 purchase_history 字段（如果不存在）
    try:
        conn.execute("ALTER TABLE customers ADD COLUMN purchase_history TEXT DEFAULT '[]'")
    except:
        pass

    # 有效话术库表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS effective_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    scenario TEXT DEFAULT '',
    customer_type TEXT DEFAULT '',
    effective_count INTEGER DEFAULT 1,
    last_effective_at TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    vector_status TEXT DEFAULT 'pending'
        )
    """)

    # 兼容旧表：如果已有旧表，添加新字段
    try:
        conn.execute("ALTER TABLE effective_scripts ADD COLUMN vector_status TEXT DEFAULT 'pending'")
    except:
        pass

    # 兼容旧表：添加 score 字段
    try:
        conn.execute("ALTER TABLE effective_scripts ADD COLUMN score REAL DEFAULT 0")
    except:
        pass

    # 常见问题表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faq_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 兼容旧表：添加 FAQ 字段
    try:
        conn.execute("ALTER TABLE faq_entries ADD COLUMN category TEXT DEFAULT ''")
    except:
        pass

    # 兼容旧表：添加 applicable_customers 字段（如果不存在）
    try:
        conn.execute("ALTER TABLE image_index ADD COLUMN applicable_customers TEXT DEFAULT ''")
    except:
        pass

    # 图片多对多分类关联表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS image_categories (
            image_id INTEGER NOT NULL,
            category_name TEXT NOT NULL,
            PRIMARY KEY (image_id, category_name),
            FOREIGN KEY (image_id) REFERENCES image_index(id) ON DELETE CASCADE
        )
    """)

    # 子分类描述表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS category_profiles (
            name TEXT PRIMARY KEY,
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 分类描述向量表（语义搜索分类描述用）
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS category_profile_vectors USING vec0(
                category_name TEXT PRIMARY KEY,
                vector FLOAT[1536]
            )
        """)
    except Exception:
        # sqlite-vec 不可用时忽略
        pass

    # use_count 字段
    try:
        conn.execute("ALTER TABLE image_index ADD COLUMN use_count INTEGER DEFAULT 0")
    except:
        pass

    # 迁移现有数据：将 image_index.category 转入 image_categories（仅首次迁移）
    try:
        existing = conn.execute("SELECT COUNT(*) FROM image_categories").fetchone()[0]
        if existing == 0:
            rows = conn.execute("SELECT DISTINCT id, category FROM image_index WHERE category != '' AND category IS NOT NULL").fetchall()
            for row in rows:
                try:
                    conn.execute("INSERT OR IGNORE INTO image_categories (image_id, category_name) VALUES (?, ?)",
                                 (row["id"], row["category"]))
                except:
                    pass
    except:
        pass

    
    # ===== 性能优化：添加索引 =====
    # messages 表索引
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_customer_id ON messages(customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_customer_ts ON messages(customer_id, timestamp)")
    except:
        pass

    # knowledge_chunks 表索引
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_doc_id ON knowledge_chunks(doc_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_filename ON knowledge_chunks(filename)")
    except:
        pass

    # image_index 表索引
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_image_status ON image_index(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_image_category ON image_index(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_image_created ON image_index(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_image_use_count ON image_index(use_count)")
    except:
        pass

    # 定期 VACUUM（每100次启动执行一次）
    try:
        import random
        if random.randint(1, 100) == 1:
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
            conn.execute("PRAGMA incremental_vacuum(100)")
    except:
        pass

    
    # 话术模板表
    try:
        init_script_templates_table()
    except:
        pass
    conn.commit()
    conn.close()

def _pinyin_key(name):
    """姓名拼音排序键（支持中英文混排）"""
    try:
        from pypinyin import lazy_pinyin
        return ''.join(lazy_pinyin(name))
    except ImportError:
        # 降级：直接用原字符串
        return name


def list_customers(search=""):
    """列出所有客户，支持按姓名搜索，按姓名 A-Z 排序"""
    conn = get_db()
    if search:
        cursor = conn.execute(
            "SELECT * FROM customers WHERE name LIKE ? ORDER BY name COLLATE NOCASE, id DESC",
            (f"%{search}%",)
        )
    else:
        cursor = conn.execute("SELECT * FROM customers ORDER BY name COLLATE NOCASE, id DESC")
    customers = [dict(row) for row in cursor.fetchall()]
    conn.close()
    # 从消息库补充最后沟通时间
    try:
        mconn = get_messages_db()
        for c in customers:
            row = mconn.execute(
                "SELECT MAX(timestamp) as last_msg_time FROM messages WHERE customer_id=?",
                (c["id"],)
            ).fetchone()
            c["last_msg_time"] = row["last_msg_time"] if row and row["last_msg_time"] else None
        mconn.close()
    except Exception:
        pass
    # 按姓名 A-Z 排序，同名按 id 倒序
    customers.sort(key=lambda x: (x.get("name", "") or "").lower())
    return customers


def get_customer(customer_id):
    """获取单个客户"""
    conn = get_db()
    cursor = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,))
    customer = cursor.fetchone()
    conn.close()
    return dict(customer) if customer else None


def create_customer(name, title="", age="", height="", weight="", target_weight="", purchase="", customer_type="", remark="", purchase_history="[]"):
    """创建新客户"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO customers (name, title, age, height, weight, target_weight, purchase, purchase_history, customer_type, remark, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, title, age, height, weight, target_weight, purchase, purchase_history, customer_type, remark, now, now)
    )
    customer_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": customer_id, "name": name}


def update_customer(customer_id, name, title="", age="", height="", weight="", target_weight="", purchase="", customer_type="", remark="", purchase_history="[]"):
    """更新客户信息，返回更新后的客户"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    conn.execute(
        "UPDATE customers SET name=?, title=?, age=?, height=?, weight=?, target_weight=?, purchase=?, purchase_history=?, customer_type=?, remark=?, updated_at=? WHERE id=?",
        (name, title, age, height, weight, target_weight, purchase, purchase_history, customer_type, remark, now, customer_id)
    )
    conn.commit()
    # 返回更新后的客户
    cursor = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,))
    customer = cursor.fetchone()
    conn.close()
    return dict(customer) if customer else None


# 固定价格体系（按盒数）
PRODUCTS = {
    1: {"pills": 6, "amount": 198, "name": "1盒（6粒）"},
    2: {"pills": 12, "amount": 396, "name": "2盒（12粒）"},
    3: {"pills": 18, "amount": 594, "name": "3盒（18粒）"},
    4: {"pills": 24, "amount": 792, "name": "4盒（24粒）"},
    5: {"pills": 30, "amount": 990, "name": "5盒（30粒）"},
    6: {"pills": 36, "amount": 990, "name": "6盒（36粒）"},
    11: {"pills": 66, "amount": 1980, "name": "11盒（66粒）"},
    13: {"pills": 78, "amount": 1980, "name": "13盒（78粒）"},
    20: {"pills": 120, "amount": 2970, "name": "20盒（120粒）"},
    30: {"pills": 180, "amount": 3960, "name": "30盒（180粒）"},
    40: {"pills": 240, "amount": 4950, "name": "40盒（240粒）"},
    50: {"pills": 300, "amount": 5940, "name": "50盒（300粒）"},
}


def get_purchase_stats(purchase_history_json):
    """解析购买历史，返回最新购买信息和复购相关数据"""
    if not purchase_history_json:
        return None
    try:
        history = json.loads(purchase_history_json)
    except (json.JSONDecodeError, TypeError):
        return None
    
    if not history or len(history) == 0:
        return None
    
    # 按日期排序，取最新一条
    sorted_history = sorted(history, key=lambda x: x.get('date', ''), reverse=True)
    latest = sorted_history[0]
    
    # 计算累计信息
    total_purchases = len(history)
    total_amount = sum(r.get('amount', 0) for r in history)
    max_amount = max(r.get('amount', 0) for r in history)
    
    return {
        "latest": latest,
        "total_purchases": total_purchases,
        "total_amount": total_amount,
        "max_amount": max_amount,
        "history": sorted_history
    }


def delete_customer(customer_id):
    """删除客户及其所有消息"""
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    conn.commit()
    conn.close()
    # 同时删除消息库中的消息
    try:
        mconn = get_messages_db()
        mconn.execute("DELETE FROM messages WHERE customer_id=?", (customer_id,))
        mconn.commit()
        mconn.close()
    except Exception:
        pass


def get_messages(customer_id, session_id=None):
    """获取客户的所有消息"""
    conn = get_messages_db()
    if session_id:
        cursor = conn.execute(
            "SELECT * FROM messages WHERE customer_id=? AND session_id=? ORDER BY timestamp ASC",
            (customer_id, session_id)
        )
    else:
        cursor = conn.execute(
            "SELECT * FROM messages WHERE customer_id=? ORDER BY timestamp ASC",
            (customer_id,)
        )
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return messages


def add_message(customer_id, role, content, timestamp="", session_id=""):
    """添加消息"""
    if not session_id:
        session_id = f"c{customer_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    if not timestamp:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_messages_db()
    cursor = conn.execute(
        "INSERT INTO messages (customer_id, role, content, timestamp, session_id) VALUES (?, ?, ?, ?, ?)",
        (customer_id, role, content, timestamp, session_id)
    )
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": message_id, "customer_id": customer_id, "role": role, "content": content, "timestamp": timestamp, "session_id": session_id}


def delete_message(msg_id):
    """删除消息"""
    conn = get_messages_db()
    cursor = conn.execute("DELETE FROM messages WHERE id=?", (msg_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def export_all():
    """导出所有数据（用于迁移）"""
    conn = get_db()
    customers = conn.execute("SELECT * FROM customers").fetchall()
    chunks = conn.execute("SELECT * FROM knowledge_chunks").fetchall()
    conn.close()
    # 从消息库导出
    messages = []
    try:
        mconn = get_messages_db()
        messages = [dict(m) for m in mconn.execute("SELECT * FROM messages").fetchall()]
        mconn.close()
    except Exception:
        pass
    return {
        "customers": [dict(c) for c in customers],
        "messages": messages,
        "chunks": [dict(c) for c in chunks]
    }


def import_data(data):
    """导入数据（用于迁移）"""
    conn = get_db()
    for customer in data.get("customers", []):
        conn.execute(
            "INSERT OR REPLACE INTO customers (id, name, title, age, height, weight, target_weight, purchase, purchase_history, remark, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (customer["id"], customer["name"], customer.get("title", ""), customer.get("age", ""), customer.get("height", ""), customer.get("weight", ""), customer.get("target_weight", ""), customer.get("purchase", ""), customer.get("purchase_history", "[]"), customer.get("remark", ""), customer.get("created_at", ""), customer.get("updated_at", ""))
        )
    conn.commit()
    conn.close()
    # 消息导入到消息库
    try:
        mconn = get_messages_db()
        for msg in data.get("messages", []):
            mconn.execute(
                "INSERT OR REPLACE INTO messages (id, customer_id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (msg["id"], msg["customer_id"], msg.get("session_id", ""), msg["role"], msg["content"], msg.get("timestamp", ""))
            )
        mconn.commit()
        mconn.close()
    except Exception:
        pass
    for chunk in data.get("chunks", []):
        conn.execute(
            "INSERT OR REPLACE INTO knowledge_chunks (id, doc_id, chunk_index, content, filename, title, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chunk["id"], chunk["doc_id"], chunk["chunk_index"], chunk["content"], chunk.get("filename", ""), chunk.get("title", ""), chunk.get("created_at", ""))
        )
    conn.commit()
    conn.close()


def parse_customer_text(text: str) -> dict:
    """
    智能识别客户信息
    规则:
      汉字前面的数字全部忽略
      汉字就是客户的名称（2~4个字）
      汉字后面的数字：
        - 用 . 分隔 → 身高.体重.年龄[.减重需求]
        - 用 / 分隔 → 年龄/身高/体重[/减重需求]
      减重需求如果没填默认0，目标体重始终留空

    示例:
      2674测试177.160.33       → 测试(177cm/160斤/33岁)
      2674测试177.160.33.10    → 测试(177cm/160斤/33岁/减10斤)
      26.6.7宋玉玲46/163/128   → 宋玉玲(46岁/163cm/128斤)
      26.6.7宋玉玲46/163/128/10 → 宋玉玲(46岁/163cm/128斤/减10斤)
    """
    import re
    result = {}
    text = text.strip()

    # 姓名可以是1个或多个汉字+英文字母
    # 找到姓名：从后往前找汉字，优先找数字前面的那组汉字（避免匹配前缀如"A二"）
    # 策略：找所有汉字组，选最后一个（最靠近数字数据的那个）
    all_names = re.findall(r"[\u4e00-\u9fa5a-zA-Z]+", text)
    if not all_names:
        return result
    
    name = all_names[-1]  # 取最后一组汉字作为姓名（最靠近数字数据）
    result["name"] = name
    # 找到姓名在原文中的位置
    name_end = text.rfind(name) + len(name)
    after_name = text[name_end:].strip()
    numbers = re.findall(r"\d+", after_name)
    if not numbers:
        return result

    sep_dot = after_name.find(".")
    sep_slash = after_name.find("/")

    if sep_slash >= 0 and (sep_dot < 0 or sep_slash < sep_dot):
        # / 分隔 → 年龄/身高/体重[/减重需求]
        if len(numbers) >= 1: result["age"] = numbers[0]
        if len(numbers) >= 2: result["height"] = numbers[1]
        if len(numbers) >= 3: result["weight"] = numbers[2]
        if len(numbers) >= 4: result["weight_loss_demand"] = numbers[3]
    else:
        # . 分隔或无分隔符 → 身高.体重.年龄[.减重需求]
        if len(numbers) >= 1: result["height"] = numbers[0]
        if len(numbers) >= 2: result["weight"] = numbers[1]
        if len(numbers) >= 3: result["age"] = numbers[2]
        if len(numbers) >= 4: result["weight_loss_demand"] = numbers[3]

    return result

    return result


def extract_customer_messages(text: str) -> str:
    """从粘贴的聊天记录中提取客户的消息内容"""
    import re
    if not text.strip():
        return text
    blocks = text.strip().split("\n\n")
    msgs = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        header = lines[0] if lines else ""
        content = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        is_customer = False
        if "@微信联系人" in header or "@微信" in header:
            is_customer = True
        if content and ("吗" in content or "呢" in content or content.endswith("？") or content.endswith("?")):
            is_customer = True
        if is_customer and content:
            msgs.append(content)
    return "\n".join(msgs) if msgs else text


def dedup_recent_messages(recent_messages: str, chat_history: str) -> str:
    """聊天记录去重：提取客户消息，与历史对比，去掉已存在的"""
    import re
    if not recent_messages or not chat_history:
        return recent_messages
    customer_msgs = extract_customer_messages(recent_messages)
    if not customer_msgs:
        return recent_messages
    history_contents = set()
    for line in chat_history.split("\n"):
        line = line.strip()
        if not line:
            continue
        content = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} 客户: ", "", line)
        if content:
            history_contents.add(content)
    new_msgs = []
    for msg in customer_msgs.split("\n"):
        msg = msg.strip()
        if not msg:
            continue
        if msg in history_contents:
            continue
        is_dup = False
        for hc in history_contents:
            if msg[:20] in hc or hc[:20] in msg:
                is_dup = True
                break
        if not is_dup:
            new_msgs.append(msg)
    if new_msgs:
        return "\n".join(new_msgs)
    # 全部去重了，说明没有新消息，返回空
    return ""


def classify_customer(customer):
    """根据purchase_history值自动分类客户（优先使用手动设置的customer_type）"""
    manual = customer.get('customer_type', '') or ''
    if manual and manual.strip() and manual in ('cid', 'treatment', 'package'):
        return manual
    # 根据购买历史判断
    ph = customer.get('purchase_history', '') or '[]'
    try:
        history = json.loads(ph)
    except (json.JSONDecodeError, TypeError):
        history = []
    if not history:
        return 'cid'
    max_amount = max(r.get('amount', 0) for r in history)
    if max_amount >= 2970:
        return 'package'
    else:
        return 'treatment'


def group_customers():
    """获取所有客户并按分类分组（组内按拼音排序）"""
    import sqlite3
    conn = get_db()
    cursor = conn.execute('SELECT * FROM customers')
    all_customers = [dict(row) for row in cursor.fetchall()]
    conn.close()

    groups = {
        'cid': {'id': 'cid', 'label': 'CID客户', 'count': 0, 'customers': []},
        'treatment': {'id': 'treatment', 'label': '疗程客户', 'count': 0, 'customers': []},
        'package': {'id': 'package', 'label': '套餐客户', 'count': 0, 'customers': []}
    }
    for c in all_customers:
        cat = classify_customer(c)
        groups[cat]['customers'].append(c)
        groups[cat]['count'] += 1
    # 组内按拼音排序
    for cat in groups:
        groups[cat]['customers'].sort(key=lambda x: _pinyin_key(x.get('name', '')))
    return [groups['cid'], groups['treatment'], groups['package']]


# ===== 图片索引功能 =====
import hashlib
from pathlib import Path
import sys

def _compute_file_hash(file_path):
    try:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""

def scan_folder_for_index(base_path):
    base = Path(base_path)
    results = []
    if not base.exists():
        return results
    for entry in sorted(base.iterdir()):
        if entry.is_dir():
            # 子文件夹：以文件夹名作为分类
            category = entry.name
            for f in sorted(entry.iterdir()):
                if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'):
                    file_hash = _compute_file_hash(str(f))
                    file_size = f.stat().st_size
                    results.append({
                        'file_path': str(f),
                        'file_hash': file_hash,
                        'category': category,
                        'file_size': file_size
                    })
        elif entry.is_file() and entry.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'):
            # 根目录直接有图片：以父文件夹名作为分类
            file_hash = _compute_file_hash(str(entry))
            file_size = entry.stat().st_size
            results.append({
                'file_path': str(entry),
                'file_hash': file_hash,
                'category': base.name,
                'file_size': file_size
            })
    return results

def image_index_sync(scan_results):
    conn = get_db()
    # 安全保护：空扫描结果不执行任何删除操作
    if not scan_results:
        conn.close()
        return {'new': [], 'reindex': [], 'deleted': [], 'total': 0, 'existing': 0}
    cursor = conn.execute("SELECT id, file_path, file_hash FROM image_index")
    db_map = {row['file_path']: {'id': row['id'], 'file_hash': row['file_hash']} for row in cursor.fetchall()}
    scan_map = {r['file_path']: r for r in scan_results}
    deleted = []
    for fp, info in db_map.items():
        if fp not in scan_map:
            conn.execute("UPDATE image_index SET status='deleted', updated_at=datetime('now','localtime') WHERE id=?", (info['id'],))
            deleted.append(fp)
    new_items, reindex_items = [], []
    for r in scan_results:
        fp = r['file_path']
        category_name = r.get('category', '未分类')
        if fp in db_map:
            if db_map[fp]['file_hash'] and db_map[fp]['file_hash'] != r['file_hash']:
                conn.execute("UPDATE image_index SET file_hash=?, status='pending', description='', tags='[]', case_group_id='', img_order=0, error_msg='', updated_at=datetime('now','localtime') WHERE id=?", (r['file_hash'], db_map[fp]['id']))
                reindex_items.append(fp)
            # 确保 image_categories 关联存在
            img_id = db_map[fp]['id']
            existing_cat = conn.execute(
                "SELECT id FROM image_categories WHERE image_id=? AND category_name=?",
                (img_id, category_name)
            ).fetchone()
            if not existing_cat:
                conn.execute(
                    "INSERT OR IGNORE INTO image_categories (image_id, category_name) VALUES (?, ?)",
                    (img_id, category_name)
                )
        else:
                    from pathlib import Path
                    BASE_DIR = Path(__file__).resolve().parent.parent
                    rel_fp = str(Path(fp).relative_to(BASE_DIR)) if os.path.isabs(fp) else fp
                    conn.execute("INSERT INTO image_index (file_path, file_hash, category, status, description, tags, file_size, created_at, updated_at) VALUES (?, ?, ?, 'pending', '', '[]', ?, datetime('now','localtime'), datetime('now','localtime'))", (rel_fp, r['file_hash'], category_name, r['file_size']))
                    new_items.append(fp)
    # 为新插入的图片建立 image_categories 关联
    if new_items:
        cursor2 = conn.execute(
            "SELECT id, file_path FROM image_index WHERE file_path IN ({})".format(
                ','.join('?' for _ in new_items)
            ), new_items
        )
        for row2 in cursor2.fetchall():
            img_id = row2['id']
            fp2 = row2['file_path']
            cat = scan_map.get(fp2, {}).get('category', '未分类')
            conn.execute(
                "INSERT OR IGNORE INTO image_categories (image_id, category_name) VALUES (?, ?)",
                (img_id, cat)
            )
            # 确保 category_profiles 存在
            existing_cp = conn.execute("SELECT name FROM category_profiles WHERE name=?", (cat,)).fetchone()
            if not existing_cp:
                conn.execute("INSERT INTO category_profiles (name, description) VALUES (?, '')", (cat,))
    conn.commit()
    conn.close()
    return {'new': new_items, 'reindex': reindex_items, 'deleted': deleted, 'total': len(scan_results), 'existing': len(scan_results) - len(new_items) - len(reindex_items)}

def image_index_scan_incremental(category_name, scan_results):
    """
    增量扫描：只新增数据库中没有的图片，不删除任何已有图片。
    如果 category_name 不存在于 category_profiles，自动创建。
    返回：{new_ids: [...], new_count: N, skipped: N}
    """
    conn = get_db()
    # 1. 确保 category_profiles 存在
    existing_cp = conn.execute("SELECT name FROM category_profiles WHERE name=?", (category_name,)).fetchone()
    if not existing_cp:
        conn.execute("INSERT INTO category_profiles (name, description) VALUES (?, '')", (category_name,))
    # 2. 查出数据库中已有file_path
    existing_paths = set(
        row['file_path'] for row in conn.execute(
            "SELECT file_path FROM image_index WHERE status != 'deleted'"
        ).fetchall()
    )
    new_ids = []
    skipped = 0
    for r in scan_results:
        fp = r['file_path']
        if fp in existing_paths:
            skipped += 1
            continue
        # 插入新图片
        conn.execute(
            "INSERT INTO image_index (file_path, file_hash, category, status, description, tags, file_size, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', '', '[]', ?, datetime('now','localtime'), datetime('now','localtime'))",
            (fp, r['file_hash'], category_name, r['file_size'])
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        new_ids.append(new_id)
        # 建立 image_categories 关联
        conn.execute(
            "INSERT OR IGNORE INTO image_categories (image_id, category_name) VALUES (?, ?)",
            (new_id, category_name)
        )
    conn.commit()
    conn.close()
    return {'new_ids': new_ids, 'new_count': len(new_ids), 'skipped': skipped}

def get_image_index_status():
    conn = get_db()
    stats = {}
    stats['total'] = conn.execute("SELECT COUNT(*) FROM image_index WHERE status IN ('pending', 'done', 'failed')").fetchone()[0]
    stats['pending'] = conn.execute("SELECT COUNT(*) FROM image_index WHERE status='pending'").fetchone()[0]
    stats['done'] = conn.execute("SELECT COUNT(*) FROM image_index WHERE status='done'").fetchone()[0]
    stats['failed'] = conn.execute("SELECT COUNT(*) FROM image_index WHERE status='failed'").fetchone()[0]
    stats['deleted'] = conn.execute("SELECT COUNT(*) FROM image_index WHERE status='deleted'").fetchone()[0]
    stats['categories'] = [{'category': r['category'], 'count': r['cnt']} for r in conn.execute("SELECT category, COUNT(*) as cnt FROM image_index WHERE status='done' GROUP BY category ORDER BY category")]
    stats['case_groups'] = conn.execute("SELECT COUNT(DISTINCT case_group_id) FROM image_index WHERE status='done' AND case_group_id != ''").fetchone()[0]
    conn.close()
    return stats

def get_pending_images(limit=50):
    conn = get_db()
    cursor = conn.execute("SELECT id, file_path, category, file_size FROM image_index WHERE status='pending' ORDER BY id LIMIT ?", (limit,))
    images = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return images

def update_image_result(image_id, description, tags, case_group_id=None, img_order=None, error_msg=None, applicable_customers=""):
    conn = get_db()
    if error_msg:
        conn.execute("UPDATE image_index SET status='failed', error_msg=?, description=?, updated_at=datetime('now','localtime') WHERE id=?", (error_msg, description or '', image_id))
    else:
        sql = "UPDATE image_index SET status='done', description=?, tags=?, applicable_customers=?, updated_at=datetime('now','localtime')"
        params = [description, json.dumps(tags, ensure_ascii=False), applicable_customers]
        if case_group_id is not None:
            sql += ", case_group_id=? "
            params.append(case_group_id)
        if img_order is not None:
            sql += ", img_order=? "
            params.append(img_order)
        sql += " WHERE id=?"
        params.append(image_id)
        conn.execute(sql, params)
    conn.commit()
    conn.close()


def delete_image_category(category_name):
    """删除指定分类的所有图片记录"""
    conn = get_db()
    deleted = conn.execute("DELETE FROM image_index WHERE category=?", (category_name,)).rowcount
    conn.commit()
    conn.close()
    return deleted


def search_images(query="", category="", case_group_id="", limit=20):
    conn = get_db()
    conditions = ["ii.status='done'"]
    params = []
    need_join = False
    if query:
        conditions.append("(ii.description LIKE ? OR ii.tags LIKE ? OR ii.applicable_customers LIKE ? OR cp.description LIKE ?)")
        params.extend([f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'])
        need_join = True
    if category:
        # 支持通过 image_categories 关联表筛选
        conditions.append("ic.category_name=?")
        params.append(category)
        need_join = True
    if case_group_id:
        conditions.append("ii.case_group_id=?")
        params.append(case_group_id)

    if need_join:
        sql = f"SELECT DISTINCT ii.* FROM image_index ii LEFT JOIN image_categories ic ON ii.id = ic.image_id LEFT JOIN category_profiles cp ON ic.category_name = cp.name WHERE {' AND '.join(conditions)} ORDER BY ii.img_order, ii.id LIMIT ?"
    else:
        # 无查询条件时，不需要 JOIN（避免 DISTINCT 开销）
        conditions = [c.replace("ii.", "") for c in conditions]
        sql = f"SELECT * FROM image_index WHERE {' AND '.join(conditions)} ORDER BY img_order, id LIMIT ?"
    params.append(limit)
    cursor = conn.execute(sql, params)
    images = []
    for row in cursor.fetchall():
        img = dict(row)
        try:
            img['tags'] = json.loads(img['tags']) if img['tags'] else []
        except (json.JSONDecodeError, TypeError):
            img['tags'] = [t.strip() for t in img['tags'].split(',') if t.strip()] if img['tags'] else []
        images.append(img)
    conn.close()
    return images


def get_category_images(category_name, limit=500, offset=0, q="", sort="created_at", order="desc"):
    """获取指定分类的所有图片（含描述、标签、适用客户）- 支持分页/搜索/排序"""
    conn = get_db()
    where = "ic.category_name=? AND ii.status!='deleted'"
    params = [category_name]
    if q:
        where += " AND (ii.description LIKE ? OR ii.tags LIKE ? OR ii.applicable_customers LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])
    valid_sorts = {"created_at": "ii.created_at", "updated_at": "ii.updated_at",
                   "id": "ii.id", "use_count": "ii.use_count",
                   "id_asc": "ii.id", "id_desc": "ii.id"}
    if sort == "id_asc":
        sort_col = "ii.id"
        order_sql = "ASC"
    elif sort == "id_desc":
        sort_col = "ii.id"
        order_sql = "DESC"
    else:
        sort_col = valid_sorts.get(sort, "ii.created_at")
        order_sql = "DESC" if order == "desc" else "ASC"
    cursor = conn.execute(
        f"SELECT ii.* FROM image_index ii "
        f"JOIN image_categories ic ON ii.id = ic.image_id "
        f"WHERE {where} "
        f"ORDER BY {sort_col} {order_sql} "
        f"LIMIT ? OFFSET ?",
        params + [limit, offset]
    )
    images = []
    for row in cursor.fetchall():
        img = dict(row)
        try:
            try:
                img['tags'] = json.loads(img['tags']) if img['tags'] else []
            except (json.JSONDecodeError, TypeError):
                img['tags'] = [t.strip() for t in img['tags'].split(',') if t.strip()] if img['tags'] else []
        except:
            img['tags'] = []
        images.append(img)
    conn.close()
    return images

def image_index_clear():
    conn = get_db()
    conn.execute("DELETE FROM image_index")
    conn.commit()
    conn.close()
    return True

def get_image_detail(image_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM image_index WHERE id=?", (image_id,)).fetchone()
    conn.close()
    if not row:
        return None
    img = dict(row)
    try:
        img['tags'] = json.loads(img['tags']) if img['tags'] else []
    except (json.JSONDecodeError, TypeError):
        img['tags'] = [t.strip() for t in img['tags'].split(',') if t.strip()] if img['tags'] else []
    return img

def get_case_group(case_group_id):
    conn = get_db()
    cursor = conn.execute("SELECT * FROM image_index WHERE case_group_id=? AND status='done' ORDER BY img_order", (case_group_id,))
    images = []
    for row in cursor.fetchall():
        img = dict(row)
        try:
            img['tags'] = json.loads(img['tags']) if img['tags'] else []
        except (json.JSONDecodeError, TypeError):
            img['tags'] = [t.strip() for t in img['tags'].split(',') if t.strip()] if img['tags'] else []
        images.append(img)
    conn.close()
    return images

def match_images_for_script(needs, top_k=5):
    results = []
    for need in needs:
        matched = search_images_hybrid(query=need, limit=top_k)
        if not matched:
            matched = search_images(category=need, limit=top_k)
        if matched:
            results.append({'need': need, 'matched': matched[:top_k], 'confidence': 'good'})
        else:
            results.append({'need': need, 'matched': [], 'confidence': 'none'})
    return results


def auto_group_cases():
    """自动归组：按mmexport时间戳连续<30秒归为一组，返回{group_id: [image_ids]}"""
    import re
    from datetime import datetime, timedelta

    conn = get_db()
    # 获取所有已识别的图片（status='done'），按file_path排序
    cursor = conn.execute("""
        SELECT id, file_path FROM image_index 
        WHERE status='done' AND (case_group_id='' OR case_group_id IS NULL)
        ORDER BY file_path
    """)
    images = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # 提取时间戳
    def extract_ts(filepath):
        m = re.search(r'mmexport(\d{4,14})', filepath)
        if not m:
            return None
        ts_str = m.group(1)
        try:
            # 支持12位(秒)和14位(毫秒)时间戳
            if len(ts_str) == 14:
                ts_str = ts_str[:12]
            ts = datetime.fromtimestamp(int(ts_str))
            return ts
        except (ValueError, OSError, OverflowError):
            return None

    grouped = {}
    for img in images:
        ts = extract_ts(img['file_path'])
        if not ts:
            continue
        # 找最近的组
        found = False
        for gid, members in grouped.items():
            last_ts = members[-1].get('_ts')
            if last_ts and (ts - last_ts).total_seconds() < 30:
                members.append({'id': img['id'], '_ts': ts})
                found = True
                break
        if not found:
            gid = f"auto_{len(grouped)+1:03d}"
            grouped[gid] = [{'id': img['id'], '_ts': ts}]

    # 清理临时_ts字段
    for gid in grouped:
        for m in grouped[gid]:
            m.pop('_ts', None)

    return grouped


def assign_case_group(group_id, image_ids):
    """将一组图片分配case_group_id和img_order"""
    conn = get_db()
    for i, img_id in enumerate(image_ids, 1):
        conn.execute(
            "UPDATE image_index SET case_group_id=?, img_order=? WHERE id=?",
            (group_id, i, img_id)
        )
    conn.commit()
    conn.close()


def get_ungrouped_images(limit=50):
    """获取未归组的已识别图片"""
    conn = get_db()
    cursor = conn.execute("""
        SELECT id, file_path, category, description, tags, file_size
        FROM image_index 
        WHERE status='done' AND (case_group_id='' OR case_group_id IS NULL)
        ORDER BY id
        LIMIT ?
    """, (limit,))
    images = []
    for row in cursor.fetchall():
        img = dict(row)
        try:
            img['tags'] = json.loads(img['tags']) if img.get('tags') else []
        except (json.JSONDecodeError, TypeError):
            img['tags'] = [t.strip() for t in img['tags'].split(',') if t.strip()] if img.get('tags') else []
        images.append(img)
    conn.close()
    return images


# 从配置读取embedding参数
def _get_image_embedding_config():
    from config_manager import get_embedding_config
    return get_embedding_config()

_IMAGE_EMBEDDING_DIM = None  # 动态获取
_IMAGE_EMBEDDING_AVAILABLE = True  # 仅控制 sqlite-vec 扩展是否可用


def _get_image_embedding_dim():
    from config_manager import get_embedding_config
    ec = get_embedding_config()
    return ec.get("dim", 1024)


def _get_image_vec_conn() -> sqlite3.Connection:
    """获取启用了 sqlite-vec 的图片向量库连接（独立文件）"""
    global _IMAGE_EMBEDDING_AVAILABLE
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_IMAGE_VEC_PATH))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    try:
        import sqlite_vec
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        try:
            # 尝试找 vec0.dll
            path = _find_image_vec_dll()
            if path and os.path.exists(path):
                conn.load_extension(path)
                conn.enable_load_extension(False)
            else:
                _IMAGE_EMBEDDING_AVAILABLE = False
        except Exception:
            _IMAGE_EMBEDDING_AVAILABLE = False
    return conn


def _find_image_vec_dll() -> str:
    """寻找 vec0.dll"""
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(sys._MEIPASS, 'sqlite_vec', 'vec0.dll'))
        candidates.append(os.path.join(os.path.dirname(sys.executable), '_internal', 'sqlite_vec', 'vec0.dll'))
    try:
        import sqlite_vec
        candidates.append(os.path.join(os.path.dirname(sqlite_vec.__file__), 'vec0.dll'))
    except Exception:
        pass
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""


def _get_image_embedding(text: str) -> tuple:
    """调用 embedding API 获取向量，返回 (vector, None) 或 (None, error_msg)"""
    try:
        import urllib.request
        import urllib.error
        from config_manager import load_config
        config = load_config()
        api_key = config.get("embedding_api_key", "")
        if not api_key:
            api_key = config.get("llm", {}).get("api_key", "")
        if not api_key:
            return None, "未配置 API Key"

        text = text.strip()[:2000]
        if not text:
            return None, "描述为空"

        # 从配置读取 embedding 模型和 URL
        embedding_config = _get_image_embedding_config()
        model_name = embedding_config.get("model", "text-embedding-v3")
        api_url = embedding_config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings")
        api_mode = embedding_config.get("api_mode", "openai")
        dim = embedding_config.get("dim", 1024)

        # OpenAI 模式自动补 /embeddings
        if api_mode == "openai" and not api_url.rstrip("/").endswith("/embeddings"):
            api_url = api_url.rstrip("/") + "/embeddings"

        # 根据 api_mode 选择请求格式
        if api_mode == "dashscope_multimodal":
            data = json.dumps({
                "model": model_name,
                "input": {"contents": [{"text": text}]},
                "parameters": {"dimension": dim}
            }).encode("utf-8")
        elif api_mode == "dashscope_text":
            data = json.dumps({
                "model": model_name,
                "input": {"texts": [text]}
            }).encode("utf-8")
        else:  # openai (默认)
            data = json.dumps({"input": text, "model": model_name}).encode("utf-8")

        req = urllib.request.Request(
            api_url, data=data,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode("utf-8"))

        # 根据 api_mode 从响应中提取向量
        if api_mode in ("dashscope_multimodal", "dashscope_text"):
            vector = result["output"]["embeddings"][0]["embedding"]
        else:  # openai
            vector = result["data"][0]["embedding"]

        # L2 归一化
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector, None
    except Exception as e:
            err = str(e)[:100]
            import traceback
            print(f"[embedding] ERROR: {e}", file=__import__('sys').stderr)
            traceback.print_exc()
            return None, err


def _vec_to_str(vec: List[float]) -> str:
    """向量转字符串格式"""
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def ensure_image_vectors_table():
    """创建图片向量索引表（自动适配当前向量维度）"""
    if not _IMAGE_EMBEDDING_AVAILABLE:
        return False
    dim = _get_image_embedding_dim()
    try:
        conn = _get_image_vec_conn()
        # 检查旧表维度，如果不匹配则重建
        cursor = conn.execute("SELECT sql FROM sqlite_master WHERE name='image_vectors'")
        info = cursor.fetchone()
        if info:
            old_dim_match = __import__("re").search(r"FLOAT\[(\d+)\]", info[0])
            if old_dim_match and int(old_dim_match.group(1)) != dim:
                conn.execute("DROP TABLE IF EXISTS image_vectors")
                conn.commit()
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS image_vectors USING vec0(
                image_id INTEGER PRIMARY KEY,
                vector FLOAT[{dim}]
            )
        """)
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# 向量重建进度回调（由 main.py 设置）
_image_reindex_progress_callback = None


def rebuild_image_vectors(batch_size=20, force=False):
    """批量重建图片向量索引"""
    if not ensure_image_vectors_table():
        return {"status": "error", "message": "向量扩展不可用"}

    if force:
        # 清空现有向量，全量重建
        vconn = _get_image_vec_conn()
        vconn.execute("DELETE FROM image_vectors")
        vconn.commit()
        vconn.close()

    conn = get_db()
    cursor = conn.execute(
        "SELECT id, description FROM image_index WHERE status='done' AND description != '' ORDER BY id"
    )
    images = cursor.fetchall()
    conn.close()
    total = len(images)
    if total == 0:
        return {"status": "ok", "total": 0, "message": "无待处理图片"}

    success = 0
    failed = 0
    processed = 0
    failed_errors = {}  # {image_id: error_msg}
    # 复用 vec 连接，避免每次新建加载扩展失败
    vconn_main = _get_image_vec_conn()
    for i in range(0, total, batch_size):
        batch = images[i:i + batch_size]
        for row in batch:
            img_id = row["id"]
            desc = (row["description"] or "").strip()
            if not desc:
                processed += 1
                continue
            vec, err = _get_image_embedding(desc)
            if vec is None:
                failed += 1
                failed_errors[str(img_id)] = err or "未知错误"
                processed += 1
                continue
            try:
                vconn_main.execute("DELETE FROM image_vectors WHERE image_id=?", (img_id,))
                vconn_main.execute(
                    "INSERT INTO image_vectors (image_id, vector) VALUES (?, ?)",
                    (img_id, _vec_to_str(vec))
                )
                vconn_main.commit()
                success += 1
            except Exception as e:
                failed += 1
            processed += 1
            # 每处理一张更新进度回调
            if _image_reindex_progress_callback:
                _image_reindex_progress_callback(processed, total, success, failed, dict(failed_errors))
        # 每批结束后暂停一下避免 API 限流
        if i + batch_size < total:
            time.sleep(0.5)
    vconn_main.close()

    return {"status": "ok", "total": total, "success": success, "failed": failed, "failed_errors": failed_errors}


def rebuild_category_profile_vectors(batch_size=5):
    """批量重建分类描述向量索引，使分类描述也能被语义搜索命中"""
    if not _IMAGE_EMBEDDING_AVAILABLE:
        return {"status": "error", "message": "向量扩展不可用"}

    try:
            vconn = _get_image_vec_conn()
            dim = _get_image_embedding_dim()
            vconn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS category_profile_vectors USING vec0(category_name TEXT PRIMARY KEY, vector FLOAT[{dim}])")
            vconn.execute("DELETE FROM category_profile_vectors")
            vconn.commit()
    except Exception:
        pass

    conn = get_db()
    rows = conn.execute(
        "SELECT name, description FROM category_profiles WHERE description != '' ORDER BY name"
    ).fetchall()
    conn.close()

    total = len(rows)
    if total == 0:
        return {"status": "ok", "total": 0, "message": "无待处理分类描述"}

    success = 0
    failed = 0
    for row in rows:
        name = row["name"]
        desc = (row["description"] or "").strip()
        if not desc:
            failed += 1
            continue
        vec = _get_image_embedding(desc)
        if vec is None:
            failed += 1
            continue
        try:
            vconn = _get_image_vec_conn()
            vconn.execute(
                "INSERT OR REPLACE INTO category_profile_vectors (category_name, vector) VALUES (?, ?)",
                (name, _vec_to_str(vec))
            )
            vconn.commit()
            success += 1
        except Exception:
            failed += 1
        time.sleep(0.3)  # 避免API限流

    return {"status": "ok", "total": total, "success": success, "failed": failed, "failed_errors": failed_errors}


def _split_keywords(text: str) -> list:
    """将文本拆分成关键词：按标点和常见分隔符拆分，提取2字以上的词"""
    # 移除常见分隔符和标点（中英文）
    raw = re.sub(r'[→▶➡\-–—,，、：:()（）【】\[\]{}。！？；;!?\s%…""''《》<>]', ' ', text)
    # 按空格拆分，过滤过短的词
    words = [w.strip() for w in raw.split() if len(w.strip()) >= 2]
    # 如果拆分后没有词或全是长词（>4字），用2-4字滑动窗口提取
    if (not words or all(len(w) > 4 for w in words)) and len(text) >= 2:
        cleaned = re.sub(r'[→▶➡\-–—,，、：:()（）【】\[\]{}。！？；;!?\s%…""''《》<>]', '', text)
        for win_size in [4, 3, 2]:
            for i in range(len(cleaned) - win_size + 1):
                words.append(cleaned[i:i+win_size])
        words = list(dict.fromkeys(words))[:20]
    # 去重保留顺序，限制20个关键词
    seen = set()
    result = []
    for w in words[:20]:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result


def search_images_hybrid(query="", category="", limit=12):
    """混合搜索：以分类匹配为主，个体图片搜索为辅"""
    conn = get_db()

    # 0. 如果指定了分类，直接返回该分类的图片
    if category:
        results = search_images(query="", category=category, limit=limit)
        for r in results:
            r['_kw_score'] = 1.0
            r['_source'] = 'category'
        conn.close()
        return results

    # 1. 拆关键词
    keywords = _split_keywords(query) if query else []
    query_vec = None
    if _IMAGE_EMBEDDING_AVAILABLE and query:
        query_vec, _ = _get_image_embedding(query)

    # 2. 匹配分类（语义 + 关键词 双路）
    cat_scores = {}  # category_name → score
    try:
        # 2a. 语义匹配分类描述
        if query_vec:
            vconn = _get_image_vec_conn()
            vec_str = _vec_to_str(query_vec)
            cat_rows = vconn.execute(
                "SELECT cpv.category_name, cpv.distance FROM category_profile_vectors cpv WHERE cpv.vector MATCH ? AND k=? ORDER BY cpv.distance",
                (vec_str, limit * 2)
            ).fetchall()
            for r in cat_rows:
                cat_scores[r["category_name"]] = max(0, 1.0 - r["distance"] / 2.0)
            vconn.close()

        # 2b. 关键词匹配分类名
        all_cats = [r[0] for r in conn.execute(
            "SELECT DISTINCT ic.category_name FROM image_categories ic ORDER BY ic.category_name"
        ).fetchall()]
        for kw in keywords:
            if len(kw) < 2: continue
            kw_clean = kw.replace('的','').replace('个','').replace('了','').replace('是','').replace('在','')
            for cat in all_cats:
                cat_clean = cat.replace('的','').replace('个','').replace('了','').replace('是','').replace('在','')
                match_len = 0
                if kw in cat or cat in kw:
                    match_len = len(kw)
                elif kw_clean in cat_clean or cat_clean in kw_clean:
                    match_len = min(len(kw_clean), len(cat_clean))
                elif len(kw_clean) >= 3 and len(cat_clean) >= 3 and kw_clean[:3] == cat_clean[:3]:
                    match_len = 2
                if match_len > 0:
                    precision = min(len(kw_clean), len(cat_clean)) / max(len(kw_clean), len(cat_clean), 1)
                    kw_score = 1.0 + match_len * 0.3 * precision
                    cat_scores[cat] = max(cat_scores.get(cat, 0), kw_score)

        # 2c. 语义匹配分类描述 + 关键词也匹配同一分类 → 加权
        if query_vec:
            vconn = _get_image_vec_conn()
            cat_rows = vconn.execute(
                "SELECT cpv.category_name, cpv.distance FROM category_profile_vectors cpv WHERE cpv.vector MATCH ? AND k=? ORDER BY cpv.distance",
                (vec_str, limit * 2)
            ).fetchall()
            for r in cat_rows:
                sem_score = max(0, 1.0 - r["distance"] / 2.0)
                if r["category_name"] in cat_scores:
                    # 语义+关键词都命中 → 加权
                    cat_scores[r["category_name"]] += sem_score * 0.5
                else:
                    cat_scores[r["category_name"]] = sem_score * 0.6
            vconn.close()

    except Exception:
        pass

    # 3. 从匹配的分类中取图片
    seen_ids = set()
    merged = []

    # 按分数从高到低遍历分类
    for cat_name, _ in sorted(cat_scores.items(), key=lambda x: -x[1]):
        imgs = conn.execute(
            "SELECT ii.* FROM image_index ii JOIN image_categories ic ON ii.id = ic.image_id WHERE ic.category_name=? AND ii.status='done' ORDER BY ii.img_order, ii.id LIMIT ?",
            (cat_name, limit)
        ).fetchall()
        for img in imgs:
            if len(merged) >= limit:
                break
            if img["id"] not in seen_ids:
                seen_ids.add(img["id"])
                img = dict(img)
                try:
                    img['tags'] = json.loads(img['tags']) if img.get('tags') else []
                except (json.JSONDecodeError, TypeError):
                    img['tags'] = [t.strip() for t in img['tags'].split(',') if t.strip()] if img.get('tags') else []
                img['_kw_score'] = cat_scores[cat_name]
                img['_source'] = 'category_match'
                img['_matched_category'] = cat_name
                merged.append(img)
        if len(merged) >= limit:
            break

    # 4. 如果分类匹配不够，用个体图片搜索兜底
    if len(merged) < limit:
        keyword_results = search_images(query=query, limit=limit)
        if not keyword_results and keywords:
            kw_seen = set()
            for kw in keywords[:5]:
                kws = search_images(query=kw, limit=limit)
                for img in kws:
                    if img["id"] not in kw_seen and img["id"] not in seen_ids:
                        kw_seen.add(img["id"])
                        seen_ids.add(img["id"])
                        img['_kw_score'] = 0.8
                        img['_source'] = 'keyword_fallback'
                        merged.append(img)
                        if len(merged) >= limit:
                            break
        else:
            for img in keyword_results:
                if len(merged) >= limit:
                    break
                if img["id"] not in seen_ids:
                    seen_ids.add(img["id"])
                    img['_kw_score'] = 1.0
                    img['_source'] = 'keyword_fallback'
                    merged.append(img)

    conn.close()
    return merged[:limit]


# ===== v2 图片索引新功能 =====

def create_subcategory(name: str, description: str = ""):
    """创建子分类（如不存在）"""
    conn = get_db()
    existing = conn.execute("SELECT name FROM category_profiles WHERE name=?", (name,)).fetchone()
    if not existing:
        conn.execute("INSERT INTO category_profiles (name, description) VALUES (?, ?)", (name, description))
        conn.commit()
    conn.close()

def get_all_subcategories():
    """获取所有子分类（含图片数+描述）"""
    conn = get_db()
    rows = conn.execute("""
        SELECT ic.category_name as name, 
               COUNT(ic.image_id) as count,
               cp.description,
               cp.created_at
        FROM image_categories ic
        LEFT JOIN category_profiles cp ON ic.category_name = cp.name
        LEFT JOIN image_index ii ON ic.image_id = ii.id
        WHERE ii.status != 'deleted'
        GROUP BY ic.category_name
        ORDER BY ic.category_name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_subcategory_profile(name: str, description: str = ""):
    """更新子分类描述"""
    conn = get_db()
    existing = conn.execute("SELECT name FROM category_profiles WHERE name=?", (name,)).fetchone()
    if existing:
        conn.execute("UPDATE category_profiles SET description=?, updated_at=datetime('now','localtime') WHERE name=?", (description, name))
    else:
        conn.execute("INSERT INTO category_profiles (name, description) VALUES (?, ?)", (name, description))
    conn.commit()
    conn.close()


def delete_subcategory(name: str):
    """删除子分类+解除所有图片关联"""
    conn = get_db()
    conn.execute("DELETE FROM image_categories WHERE category_name=?", (name,))
    conn.execute("DELETE FROM category_profiles WHERE name=?", (name,))
    conn.commit()
    conn.close()


def get_subcategory_images(name: str, q: str = "", sort: str = "created_at", order: str = "desc", offset: int = 0, limit: int = 50):
    """获取子分类内的图片（支持搜索/排序/分页）"""
    conn = get_db()
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    valid_sorts = {"created_at", "updated_at", "use_count", "id"}
    if sort not in valid_sorts:
        sort = "created_at"

    where = "WHERE ic.category_name=? AND ii.status != 'deleted'"
    params = [name]

    if q:
        where += " AND (ii.description LIKE ? OR ii.tags LIKE ? OR ii.applicable_customers LIKE ?)"
        like_q = f"%{q}%"
        params.extend([like_q, like_q, like_q])

    # Count total
    total = conn.execute(
        f"SELECT COUNT(*) FROM image_categories ic JOIN image_index ii ON ic.image_id=ii.id {where}",
        params
    ).fetchone()[0]

    # Get data
    rows = conn.execute(
        f"SELECT ii.* FROM image_categories ic JOIN image_index ii ON ic.image_id=ii.id {where} ORDER BY ii.{sort} {order_dir} LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()

    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        d['tags'] = json.loads(d.get('tags', '[]')) if d.get('tags') else []
        results.append(d)

    return {"images": results, "total": total}


def update_image_fields(image_id: int, data: dict):
    """更新图片字段（只更新提供的字段）"""
    allowed = {"description", "tags", "applicable_customers", "case_group_id", "img_order", "remark"}
    fields = []
    params = []
    for k, v in data.items():
        if k in allowed:
            if k == "tags" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            fields.append(f"{k}=?")
            params.append(v)
    if not fields:
        return False
    fields.append("updated_at=datetime('now','localtime')")
    params.append(image_id)

    conn = get_db()
    conn.execute(f"UPDATE image_index SET {', '.join(fields)} WHERE id=?", params)
    conn.commit()
    conn.close()
    return True


def soft_delete_image(image_id: int):
    """软删除单张图片"""
    conn = get_db()
    conn.execute("UPDATE image_index SET status='deleted', updated_at=datetime('now','localtime') WHERE id=?", (image_id,))
    conn.execute("DELETE FROM image_categories WHERE image_id=?", (image_id,))
    conn.commit()
    conn.close()


def batch_delete_images(image_ids: list):
    """批量软删除图片"""
    if not image_ids:
        return 0
    conn = get_db()
    placeholders = ",".join("?" * len(image_ids))
    conn.execute(f"UPDATE image_index SET status='deleted', updated_at=datetime('now','localtime') WHERE id IN ({placeholders})", image_ids)
    conn.execute(f"DELETE FROM image_categories WHERE image_id IN ({placeholders})", image_ids)
    conn.commit()
    conn.close()
    return len(image_ids)


def batch_tag_images(image_ids: list, tags: list):
    """批量设置标签"""
    if not image_ids:
        return 0
    tag_str = json.dumps(tags, ensure_ascii=False)
    conn = get_db()
    placeholders = ",".join("?" * len(image_ids))
    conn.execute(f"UPDATE image_index SET tags=?, updated_at=datetime('now','localtime') WHERE id IN ({placeholders})", [tag_str] + image_ids)
    conn.commit()
    conn.close()
    return len(image_ids)


def add_image_record(file_path: str, category_names: list = None, status: str = "pending"):
    """添加新图片记录到索引"""
    import hashlib
    from pathlib import Path
    # 自动转为相对路径（相对于项目根目录）
    BASE_DIR = Path(__file__).resolve().parent.parent
    if os.path.isabs(file_path):
        try:
            file_path = str(Path(file_path).relative_to(BASE_DIR))
        except ValueError:
            pass  # 不在项目目录内，保留原路径
    conn = get_db()

    # Compute hash
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
    except:
        file_hash = ""

    # Check if already exists
    existing = conn.execute("SELECT id FROM image_index WHERE file_path=?", (file_path,)).fetchone()
    if existing:
        img_id = existing["id"]
        conn.execute("UPDATE image_index SET status=?, updated_at=datetime('now','localtime') WHERE id=?", (status, img_id))
    else:
        cur = conn.execute(
            "INSERT INTO image_index (file_path, file_hash, status) VALUES (?, ?, ?)",
            (file_path, file_hash, status)
        )
        img_id = cur.lastrowid

    # Add categories
    if category_names:
        conn.execute("DELETE FROM image_categories WHERE image_id=?", (img_id,))
        for cat in category_names:
            conn.execute("INSERT OR IGNORE INTO image_categories (image_id, category_name) VALUES (?, ?)", (img_id, cat))

    conn.commit()
    conn.close()
    return img_id


def copy_image_to_category(image_id: int, category_name: str):
    """将图片复制到另一个分类"""
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO image_categories (image_id, category_name) VALUES (?, ?)", (image_id, category_name))
    conn.commit()
    conn.close()


def increment_image_use_count(image_id: int):
    """增加图片使用次数"""
    conn = get_db()
    conn.execute("UPDATE image_index SET use_count=COALESCE(use_count,0)+1, updated_at=datetime('now','localtime') WHERE id=?", (image_id,))
    conn.commit()
    conn.close()

# ===== 话术模板库 =====

def init_script_templates_table():
    """初始化话术模板表"""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS script_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            category TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()

def list_script_templates(search="", category=""):
    """列出话术模板"""
    conn = get_db()
    query = "SELECT * FROM script_templates WHERE 1=1"
    params = []
    if search:
        query += " AND (title LIKE ? OR content LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if category:
        query += " AND category=?"
        params.append(category)
    query += " ORDER BY updated_at DESC"
    cursor = conn.execute(query, params)
    results = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return results

def add_script_template(title, content, tags=None, category=""):
    """添加话术模板"""
    conn = get_db()
    import json
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    cursor = conn.execute(
        "INSERT INTO script_templates (title, content, tags, category) VALUES (?, ?, ?, ?)",
        (title, content, tags_json, category)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def update_script_template(template_id, title=None, content=None, tags=None, category=None):
    """更新话术模板"""
    conn = get_db()
    updates = []
    params = []
    if title is not None:
        updates.append("title=?")
        params.append(title)
    if content is not None:
        updates.append("content=?")
        params.append(content)
    if tags is not None:
        import json
        updates.append("tags=?")
        params.append(json.dumps(tags, ensure_ascii=False))
    if category is not None:
        updates.append("category=?")
        params.append(category)
    if not updates:
        conn.close()
        return
    updates.append("updated_at=datetime('now','localtime')")
    params.append(template_id)
    conn.execute(f"UPDATE script_templates SET {', '.join(updates)} WHERE id=?", params)
    conn.commit()
    conn.close()

def delete_script_template(template_id):
    """删除话术模板"""
    conn = get_db()
    conn.execute("DELETE FROM script_templates WHERE id=?", (template_id,))
    conn.commit()
    conn.close()

def get_script_template(template_id):
    """获取单个话术模板"""
    conn = get_db()
    cursor = conn.execute("SELECT * FROM script_templates WHERE id=?", (template_id,))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

