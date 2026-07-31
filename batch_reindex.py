"""
小赛助手 - 并行批量图片索引识别脚本 v2
使用多模型并行处理，每个模型每分钟1张
所有模型配置从 config.json 读取，不硬编码
"""

import sqlite3
import json
import base64
import time
import os
import sys
import threading
import requests
import re
from datetime import datetime
from pathlib import Path
from queue import Queue

# ===== 路径配置 =====
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "customers.db"
LOG_DIR = BASE_DIR / "data" / "logs"
PROGRESS_FILE = BASE_DIR / "data" / "batch_reindex_progress.json"

# 从 config.json 读取模型配置
def load_config():
    config_file = BASE_DIR / "data" / "config.json"
    if config_file.exists():
        return json.loads(config_file.read_text(encoding="utf-8"))
    return {}

# 获取可用的视觉模型列表（从 models.list 中筛选）
def get_vision_models():
    config = load_config()
    models = config.get("models", {}).get("list", {})
    vision_id = config.get("models", {}).get("vision_default_id", "")
    
    result = []
    # 先加默认视觉模型
    if vision_id and vision_id in models:
        m = models[vision_id]
        result.append({
            "id": vision_id,
            "model": m["model"],
            "api_key": m["api_key"],
            "base_url": m["base_url"].rstrip("/"),
            "is_default": True
        })
    
    # 再加其他可能是视觉模型的
    for mid, m in models.items():
        if mid == vision_id:
            continue
        mname = m.get("model", "").lower()
        # 视觉模型判断：包含 v-flash（智谱视觉）、或 step-xxx（阶跃多模态）
        is_vision = ("-4v-" in mname or "-1v-" in mname or "vision" in mname) or \
                    (mname.startswith("step-") and "flash" in mname)
        if is_vision:
            if not any(r["model"] == m["model"] for r in result):
                result.append({
                    "id": mid,
                    "model": m["model"],
                    "api_key": m["api_key"],
                    "base_url": m["base_url"].rstrip("/"),
                    "is_default": False
                })
    
    return result


sess = requests.Session()
sess.trust_env = False
sess.verify = False
sess_lock = threading.Lock()

# ===== 索引识别提示词（全局，供所有worker使用）=====
INDEX_PROMPT = """分析这张销售素材图，输出三段：

【是什么】一句话：图类型+金额/斤数+客户态度。
示例：「客户付了594元的付款截图，态度爽快」/「客户减了20斤的真实案例，反馈满意」

【标签】3个中文标签，英文逗号分隔。
格式：图类型_关键词,客户身份,场景
示例：付款_594,客户_女,场景_逼单
示例：案例_女案例,客户_女,场景_打消疑虑
示例：产品_1粒装,客户_女,场景_展示正规

【怎么用】3条使用场景，每条一句话。
格式：当[客户什么状态]时发给[谁]→[效果]
示例：当客户嫌594贵犹豫时发给想买但觉得贵的客户→减少犹豫
示例：当客户质疑效果慢时发给用了半个月没效果的客户→坚持就有结果

只输出这3段内容，不要多余文字。"""

# 进度锁
progress_lock = threading.Lock()
progress = {
    "phase": 1, "last_id": 0, "total_done": 0, "total_errors": 0,
    "phase1_total": 0, "phase2_total": 0
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "batch_reindex.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"phase": 1, "last_id": 0, "total_done": 0, "total_errors": 0}


def save_progress():
    with progress_lock:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def call_vision_api(file_path, model_name, api_key, base_url):
    """调用视觉模型分析图片，自动压缩大图"""
    from PIL import Image
    import io

    file_size = os.path.getsize(file_path)
    max_size = 4 * 1024 * 1024

    if file_size > max_size:
        log(f"  [!{model_name}] 图片过大 ({file_size/1024/1024:.1f}MB)，压缩")
        img = Image.open(file_path)
        max_dim = 1600
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
        buf = io.BytesIO()
        ext = Path(file_path).suffix.lower()
        if ext in ('.jpg', '.jpeg'):
            img.save(buf, format='JPEG', quality=85)
        else:
            img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
    else:
        try:
            with open(file_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception as e:
            return None, f"读取文件失败: {e}"

    ext = Path(file_path).suffix.lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

    payload = {
        "model": model_name,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": INDEX_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            ]
        }],
        "max_tokens": 800
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        with sess_lock:
            resp = sess.post(
                f"{base_url}/chat/completions",
                json=payload, headers=headers, timeout=120
            )
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            # 尝试 reasoning 字段（推理模型）
            content = data.get("choices", [{}])[0].get("message", {}).get("reasoning", "")
        if not content:
            return None, "返回内容为空"
        return content, None
    except requests.exceptions.Timeout:
        return None, "请求超时"
    except Exception as e:
        return None, str(e)


def parse_result(content):
    """解析AI返回的三段式内容（【是什么】【标签】【怎么用】）"""
    desc = ""
    tags = []
    customers = ""

    # 提取【是什么】作为description
    for marker in ["【是什么】", "### 是什么", "**是什么**"]:
        if marker in content:
            start = content.find(marker) + len(marker)
            if start < len(content) and content[start] in ("：", ":"):
                start += 1
            end = -1
            for nm in ["【标签】", "### 标签", "**标签**"]:
                pos = content.find(nm, start)
                if pos > start:
                    end = pos
                    break
            if end > start:
                desc = content[start:end].strip()
            else:
                desc = content[start:].strip()
            break

    # 提取【标签】
    tags_raw = ""
    for marker in ["【标签】", "### 标签", "**标签**"]:
        if marker in content:
            start = content.find(marker) + len(marker)
            if start < len(content) and content[start] in ("：", ":"):
                start += 1
            end = -1
            for nm in ["【怎么用】", "### 怎么用", "**怎么用**"]:
                pos = content.find(nm, start)
                if pos > start:
                    end = pos
                    break
            if end > start:
                tags_raw = content[start:end].strip()
            else:
                tags_raw = content[start:].strip()
            break

    if tags_raw:
        tag_items = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()]
        tags = [t.strip().strip('"') for t in tag_items if t.strip()]
        tags = tags[:5]

    # 提取【怎么用】作为适用客户
    for marker in ["【怎么用】", "### 怎么用", "**怎么用**"]:
        if marker in content:
            start = content.find(marker) + len(marker)
            if start < len(content) and content[start] in ("：", ":"):
                start += 1
            customers = content[start:].strip()
            break

    return desc.strip(), json.dumps(tags, ensure_ascii=False), customers.strip()


def worker_thread(model_cfg, image_queue, worker_id):
    """Worker线程：每个模型处理1张/分钟"""
    model_name = model_cfg["model"]
    api_key = model_cfg["api_key"]
    base_url = model_cfg["base_url"]
    model_label = model_cfg.get("id", model_name)

    log(f"  [线程{worker_id}] {model_name} 启动")

    while True:
        img = image_queue.get()
        if img is None:
            break

        img_id = img["id"]
        file_path = img["file_path"]
        category = img.get("category", "")
        file_name = Path(file_path).name

        # 检查文件是否存在
        if not os.path.exists(file_path):
            log(f"  [!{model_label}] #{img_id} 文件不存在: {file_path}")
            with progress_lock:
                progress["total_errors"] += 1
                progress["last_id"] = max(progress["last_id"], img_id)
            save_progress()
            image_queue.task_done()
            continue

        log(f"  [{model_label}] #{img_id} [{category}]: {file_name}")

        t0 = time.time()
        content, error = call_vision_api(file_path, model_name, api_key, base_url)
        elapsed = time.time() - t0

        if error:
            log(f"  [✗{model_label}] #{img_id} 失败 ({elapsed:.1f}s): {error}")
            with progress_lock:
                progress["total_errors"] += 1
                progress["last_id"] = max(progress["last_id"], img_id)
            try:
                conn = get_db()
                conn.execute("UPDATE image_index SET status='failed', error_msg=? WHERE id=?", (error[:200], img_id))
                conn.commit()
                conn.close()
            except Exception:
                pass
            save_progress()
            image_queue.task_done()
            continue

        desc, tags_json, customers = parse_result(content)
        log(f"  [✓{model_label}] #{img_id} 成功 ({elapsed:.1f}s) | 描述:{len(desc)}字")

        try:
            conn = get_db()
            conn.execute(
                """UPDATE image_index 
                   SET description=?, tags=?, applicable_customers=?, status='done',
                       error_msg='', updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (desc, tags_json, customers, img_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log(f"  [✗{model_label}] #{img_id} 数据库写入失败: {e}")

        with progress_lock:
            progress["total_done"] += 1
            progress["last_id"] = max(progress["last_id"], img_id)
        save_progress()

        image_queue.task_done()

        # 每个模型每张图片后等待60秒（限速）
        log(f"  [{model_label}] 等待60秒...")
        time.sleep(60)


def get_images_to_process(phase, last_id=0):
    """获取待处理的图片列表"""
    conn = get_db()
    if phase == 1:
        log(f"Phase 1: 处理描述为空的图片 (从 #{last_id} 开始)")
        rows = conn.execute(
            """SELECT id, file_path, category FROM image_index 
               WHERE (description IS NULL OR description = '' OR description = '[]')
               AND id > ?
               ORDER BY id""",
            (last_id,)
        ).fetchall()
    elif phase == 2:
        log(f"Phase 2: 重新识别已有描述的图片 (从 #{last_id} 开始)")
        rows = conn.execute(
            """SELECT id, file_path, category FROM image_index 
               WHERE description IS NOT NULL AND description != '' AND description != '[]'
               AND id > ?
               ORDER BY id""",
            (last_id,)
        ).fetchall()
    else:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def main():
    global progress

    log("=" * 60)
    log("并行批量图片索引识别 v2 启动")
    
    # 获取可用模型
    models = get_vision_models()
    log(f"可用视觉模型: {len(models)} 个")
    for m in models:
        tag = "【默认】" if m["is_default"] else ""
        log(f"  {tag} {m['model']} ({m['id']})")
    
    if not models:
        log("✗ 没有可用的视觉模型！")
        return
    
    log(f"限速: 每个模型60秒/张 → 总计 {len(models)} 张/分钟")
    log("=" * 60)
    
    # 加载进度
    saved = load_progress()
    progress.update(saved)
    log(f"恢复进度: Phase={progress['phase']}, 从ID #{progress['last_id']} 继续, 已完成{progress['total_done']}张")

    while progress["phase"] <= 2:
        images = get_images_to_process(progress["phase"], progress["last_id"])
        
        if not images:
            log(f"Phase {progress['phase']} 全部完成！")
            if progress["phase"] == 1:
                progress["phase"] = 2
                progress["last_id"] = 0
                save_progress()
                log("=" * 40)
                log("进入 Phase 2：重新识别已有描述的图片")
                log("=" * 40)
                continue
            else:
                break

        total = len(images)
        if progress["phase"] == 1:
            progress["phase1_total"] = total
        else:
            progress["phase2_total"] = total
        
        log(f"Phase {progress['phase']}: 待处理 {total} 张，使用 {len(models)} 个模型并行")

        # 创建队列并填充图片
        q = Queue()
        for img in images:
            q.put(img)

        # 启动worker线程
        threads = []
        for i, m in enumerate(models):
            t = threading.Thread(target=worker_thread, args=(m, q, i+1), daemon=True)
            t.start()
            threads.append(t)

        # 等待所有图片处理完成
        q.join()

        # 停止worker线程
        for _ in models:
            q.put(None)
        for t in threads:
            t.join(timeout=5)

        # 检查是否还有未处理的图片（可能因为线程退出而遗漏）
        if not q.empty():
            log(f"⚠ 队列中还有 {q.qsize()} 张未处理，继续下一轮")
            progress["last_id"] = 0  # 从头检查
        else:
            # 进入下一轮
            if progress["phase"] == 1:
                progress["phase"] = 2
                progress["last_id"] = 0
                save_progress()
                log("=" * 40)
                log("进入 Phase 2：重新识别已有描述的图片")
                log("=" * 40)
            else:
                break

    log("=" * 60)
    log(f"全部完成！")
    log(f"成功: {progress['total_done']} 张")
    log(f"失败: {progress['total_errors']} 张")
    log("=" * 60)


if __name__ == "__main__":
    main()