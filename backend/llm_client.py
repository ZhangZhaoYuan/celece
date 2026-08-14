"""
LLM API 调用客户端 - 兼容 OpenAI 格式的 API
支持商汤/智谱/OpenRouter 等所有 OpenAI 兼容接口
"""

import sys
from pathlib import Path

import json
import httpx
from typing import Optional

# 确保能导入同级模块
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config_manager


# 系统提示词 - 从文件加载（可前端编辑）
_SYSTEM_PROMPT_CACHE = None

def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is not None:
        return _SYSTEM_PROMPT_CACHE
    # 通过 config_manager 读取（自动处理 data/ → backend/ → _internal/backend/ 回退链）
    _SYSTEM_PROMPT_CACHE = config_manager.get_system_prompt().strip()
    if _SYSTEM_PROMPT_CACHE:
        return _SYSTEM_PROMPT_CACHE
    # 如果没有文件，使用默认提示词
    _SYSTEM_PROMPT_CACHE = fallback_prompt()
    return _SYSTEM_PROMPT_CACHE


def reload_system_prompt():
    """重新加载提示词（前端修改后调用）"""
    global _SYSTEM_PROMPT_CACHE
    _SYSTEM_PROMPT_CACHE = None
    return _load_system_prompt()


def fallback_prompt() -> str:
    return """你是一名赛乐赛金牌瘦身顾问，负责指导客户减脂瘦身全流程。

## 你的工作目标
让客户从60mg体验装（CID客户）复购120mg疗程套餐，成交后持续指导，促进再次复购。

## 核心要求
- 开口必带称呼
- 口语化语气词，短句为主
- 每段话术用"---"分隔
- 禁止出现违禁词
- 直接输出话术，不要解释
- 参考历史中的【未使用话术】标记，避免重复"""


def get_llm_client():
    """获取LLM配置"""
    config = config_manager.get_llm_config()
    return config


async def generate_script_stream(customer_info: dict,
                                  recent_messages: str,
                                  chat_history: str,
                                  knowledge_results: list,
                                  settings: dict,
                                  current_time: str = "",
                                  image_results: list = None,
                                  local_image_matches: list = None,
                                  effective_refs: list = None,
                                  feedback_analysis: str = ""):
    """
    流式生成销售话术 — 逐段 yield，遇到 [生成图片: xxx] 时 yield image_pending
    yield 事件格式:
      {"type": "text", "content": "段落文字"}
      {"type": "image_pending", "description": "图片描述"}
      {"type": "error", "content": "错误信息"}
      {"type": "done", "local_matches": [...], "pending_image_matches": {...}}
    """
    import re as _re
    config = get_llm_client()
    api_key = config["api_key"]
    base_url = config["base_url"]
    model = config["model"]

    # 知识库结果
    if knowledge_results:
        knowledge_text = "\n\n".join([
            f"[{r.get('filename', '未知')}] {r.get('content', '')}"
            for r in knowledge_results
        ])
    else:
        knowledge_text = "（暂无相关知识库内容）"

    chat_history_text = chat_history if chat_history else "（暂无历史沟通记录）"
    customer_title = customer_info.get("title", customer_info.get("name", ""))
    customer_remark = customer_info.get("remark", "")

    # 处理有效话术参考
    effective_refs_text = ""
    if effective_refs:
        effective_refs_text = "\n【有效话术参考】\n" + "\n".join(effective_refs)

    # 处理话术效果分析
    feedback_text = ""
    if feedback_analysis:
        feedback_text = f"\n{feedback_analysis}\n"

    if not current_time:
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 图片匹配结果
    image_text = ""
    if image_results:
        image_items = []
        for img in image_results[:5]:
            desc = img.get("description", "")
            if desc:
                image_items.append(f"- 图片({img.get('filename','')}): {desc}")
        if image_items:
            image_text = "【相关客户图片】\n" + "\n".join(image_items) + "\n"

    # 本地图片库匹配
    local_image_text = ""
    if local_image_matches:
        local_items = []
        for match in local_image_matches:
            for img in match.get("matched", [])[:3]:
                desc = img.get("description", "")
                path = img.get("file_path", "")
                if desc and path:
                    local_items.append(f"- {desc}")
        if local_items:
            local_image_text = """【优先使用本地图片库（重要！）】
以下图片库有真实可用的图片。请优先从中选择适合当前话术的图片，用 `[生成图片: 精确描述]` 引用，描述文字必须与下方完全一致。只有本地图库没有合适图片时，才自行构思生成新图片。
""" + "\n".join(local_items) + "\n"

    # 检查是否需要跳过问候（30分钟内客户回复了你的提问）
    skip_greeting = False
    if recent_messages:
        import re
        ts_pattern = r'(\d{1,2}/\d{1,2} \d{1,2}:\d{2})'
        all_ts = re.findall(ts_pattern, recent_messages)
        sender_pattern = r'(?:^|\n)([^\n]+?)(?: \d{1,2}/\d{1,2})'
        senders = re.findall(sender_pattern, recent_messages)
        if len(all_ts) >= 2 and len(senders) >= 2:
            last_sender = senders[-1]
            prev_sender = senders[-2]
            if "张兆渊" in prev_sender and "张兆渊" not in last_sender:
                try:
                    from datetime import datetime
                    now = datetime.now()
                    prev_dt = datetime.strptime(f"{now.year}/{all_ts[-2]}", "%Y/%m/%d %H:%M")
                    last_dt = datetime.strptime(f"{now.year}/{all_ts[-1]}", "%Y/%m/%d %H:%M")
                    if last_dt < prev_dt:
                        prev_dt = prev_dt.replace(year=now.year-1)
                    diff_min = (last_dt - prev_dt).total_seconds() / 60
                    if 0 < diff_min <= 30:
                        skip_greeting = True
                except:
                    pass

    skip_greeting_text = "⚠️ 注意：客户在30分钟内回复了你的提问，直接回复客户，不要问候、不要道歉、不要说'我看到你的消息了'，继续正常对话。\n" if skip_greeting else ""

    user_message = f"""【当前时间】
{current_time}
{skip_greeting_text}【知识库参考内容】
{knowledge_text}

【客户信息】
- 称呼：{customer_title}
- 姓名：{customer_info.get('name', '')}
- 年龄：{customer_info.get('age', '')}岁
- 身高：{customer_info.get('height', '')}cm
- 体重：{customer_info.get('weight', '')}斤
- 目标体重：{customer_info.get('target_weight', '')}斤
- 购买记录：{customer_info.get('purchase', '')}

【客户备注/特点】
{customer_remark if customer_remark else "（无）"}

【客户最新描述/问题】
{recent_messages}

【历史沟通记录（含每条消息的时间）】
{chat_history_text}

{image_text}
{local_image_text}
{effective_refs_text}
{feedback_text}
【聊天风格要求】
（已包含在系统提示词中）

【语言习惯】
（已包含在系统提示词中）

【话术风格】
（已包含在系统提示词中）

【违禁词（绝对禁止出现）】
{settings.get('banned_words', '')}

请根据以上信息生成话术，每段用 --- 分隔。"""

    # 违禁词
    banned_words_list = [w.strip() for w in settings.get('banned_words', '').split('\n') if w.strip()]
    banned_replacements = {
        '黑色': '油花', '黑油': '油花', '黄油': '油脂', '黄色': '淡黄色',
        '棕色': '深色', '褐色': '深色', '墨汁': '深色', '墨水': '深色',
        '粘稠': '油状', '脂肪层': '多余油分', '表层': '表面', '中层': '中间',
        '黑内脂': '多余油分', '内脂': '多余油分', '脂肪组织': '多余油分',
        '顽固脂肪': '难减的部分', '深层脂肪': '堆积的油分', '内脏脂肪': '内部的油分',
        '筋膜脂肪': '堆积的油分', '分解': '帮助消耗', '瓦解': '帮助消耗',
        '软化': '逐步改善', '凝固': '积聚', '打破': '突破', '激活': '提升',
        '排黑': '排出', '绝对': '基本', '百分百': '很有把握', '一次性': '集中',
        '最后一次': '这次', '结案套餐': '方案', '保障': '服务', '保证': '承诺',
        '易瘦体质': '好的代谢', '改善体质': '调整身体状态', '亚健康': '身体状态',
        '提高代谢': '帮助代谢', '双配方': '科学配方', '缩短': '加快',
        '越深': '越明显', '更深': '更明显', '彻底': '逐步',
        '体验装': '体验组合', '正装': '标准装', '黑乎乎': '颜色深',
        '湿气': '体内水分', '毒素': '多余废物',
    }

    def _apply_banned(text: str) -> str:
        if not banned_words_list:
            return text
        result = text
        for bw in banned_words_list:
            bw = bw.strip()
            if bw:
                replacement = banned_replacements.get(bw, '**')
                result = _re.sub(_re.escape(bw), replacement, result, flags=_re.IGNORECASE)
        return result

    messages = [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": user_message}
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True
    }

    api_url = f"{base_url.rstrip('/')}/chat/completions"

    buffer = ""
    pending_images = []
    all_local_matches = local_image_matches or []
    all_pending_matches = {}

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", api_url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    error_text = ""
                    try:
                        error_text = (await response.aread()).decode('utf-8')[:200]
                    except:
                        pass
                    yield {"type": "error", "content": f"API调用失败 (HTTP {response.status_code}): {error_text}"}
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if not content:
                        continue

                    buffer += content

                    # 检查 buffer 中的 [生成图片: xxx] 和 --- 分隔符
                    while True:
                        img_match = _re.search(r'\[生成图片:\s*(.*?)\]', buffer)
                        if img_match:
                            before_img = buffer[:img_match.start()]
                            if before_img.strip():
                                yield {"type": "text", "content": _apply_banned(before_img.strip())}
                            desc = img_match.group(1).strip()
                            if desc:
                                pending_images.append(desc)
                                yield {"type": "image_pending", "description": desc}
                            buffer = buffer[img_match.end():]
                            continue

                        sep_idx = buffer.find('---')
                        if sep_idx >= 0:
                            segment = buffer[:sep_idx].strip()
                            if segment:
                                yield {"type": "text", "content": _apply_banned(segment)}
                            buffer = buffer[sep_idx + 3:]
                            continue

                        break

    except httpx.TimeoutException:
        yield {"type": "error", "content": "API请求超时，请稍后重试"}
        return
    except Exception as e:
        import traceback; traceback.print_exc(); yield {"type": "error", "content": f"请求异常: {str(e)[:200]}"}
        return

    # 输出剩余 buffer 内容
    remaining = buffer.strip()
    if remaining:
        yield {"type": "text", "content": _apply_banned(remaining)}

    # 查找本地图片匹配
    for desc in pending_images:
        if desc:
            try:
                from database import search_images_hybrid, increment_image_use_count
                sim_matches = search_images_hybrid(query=desc, limit=5)
                if sim_matches:
                    all_pending_matches[desc] = sim_matches
                    for img in sim_matches:
                        if img.get('id'):
                            try: increment_image_use_count(img['id'])
                            except: pass
            except:
                pass

    if all_local_matches:
        try:
            from database import increment_image_use_count
            for match in all_local_matches:
                for img in match.get("matched", []):
                    if img.get('id'):
                        try: increment_image_use_count(img['id'])
                        except: pass
        except:
            pass

    yield {"type": "done", "local_matches": all_local_matches, "pending_image_matches": all_pending_matches}



async def generate_script(customer_info: dict,
                          recent_messages: str,
                          chat_history: str,
                          knowledge_results: list,
                          settings: dict,
                          current_time: str = "",
                          image_results: list = None,
                          local_image_matches: list = None,
                          effective_refs: list = None,
                          feedback_analysis: str = "") -> str:
    """
    生成销售话术
    """
    config = get_llm_client()
    api_key = config["api_key"]
    base_url = config["base_url"]
    model = config["model"]

    # 处理知识库结果
    if knowledge_results:
        knowledge_text = "\n\n".join([
            f"[{r.get('filename', '未知')}] {r.get('content', '')}"
            for r in knowledge_results
        ])
    else:
        knowledge_text = "（暂无相关知识库内容）"

    # 处理聊天历史
    chat_history_text = chat_history if chat_history else "（暂无历史沟通记录）"

    # 处理客户信息
    customer_title = customer_info.get("title", customer_info.get("name", ""))
    customer_remark = customer_info.get("remark", "")

    # 获取当前时间
    if not current_time:
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 处理图片匹配结果（客户发送的图片）
    image_text = ""
    if image_results:
        image_items = []
        for img in image_results[:5]:
            desc = img.get("description", "")
            if desc:
                image_items.append(f"- 图片({img.get('filename','')}): {desc}")
        if image_items:
            image_text = "【相关客户图片】\n" + "\n".join(image_items) + "\n"

    # 处理本地图片库匹配结果（话术可参考使用的图片）
    local_image_text = ""
    if local_image_matches:
        local_items = []
        for match in local_image_matches:
            for img in match.get("matched", [])[:3]:
                desc = img.get("description", "")
                path = img.get("file_path", "")
                if desc and path:
                    local_items.append(f"- {desc}")
        if local_items:
            local_image_text = """【优先使用本地图片库（重要！）】
以下图片库有真实可用的图片。请优先从中选择适合当前话术的图片，用 `[生成图片: 精确描述]` 引用，描述文字必须与下方完全一致。只有本地图库没有合适图片时，才自行构思生成新图片。
""" + "\n".join(local_items) + "\n"

    # 检查是否需要跳过问候（30分钟内客户回复了你的提问）
    skip_greeting = False
    if recent_messages:
        import re
        # 提取最后两条消息的时间戳
        ts_pattern = r'(\d{1,2}/\d{1,2} \d{1,2}:\d{2})'
        all_ts = re.findall(ts_pattern, recent_messages)
        # 提取最后两条消息的发送者
        sender_pattern = r'(?:^|\n)([^\n]+?)(?: \d{1,2}/\d{1,2})'
        senders = re.findall(sender_pattern, recent_messages)
        if len(all_ts) >= 2 and len(senders) >= 2:
            last_sender = senders[-1]
            prev_sender = senders[-2]
            # 上一条是张兆渊（提问），最后一条是客户（回复）
            if "张兆渊" in prev_sender and "张兆渊" not in last_sender:
                try:
                    from datetime import datetime
                    now = datetime.now()
                    prev_dt = datetime.strptime(f"{now.year}/{all_ts[-2]}", "%Y/%m/%d %H:%M")
                    last_dt = datetime.strptime(f"{now.year}/{all_ts[-1]}", "%Y/%m/%d %H:%M")
                    # 跨年处理
                    if last_dt < prev_dt:
                        prev_dt = prev_dt.replace(year=now.year-1)
                    diff_min = (last_dt - prev_dt).total_seconds() / 60
                    if 0 < diff_min <= 30:
                        skip_greeting = True
                except:
                    pass

    skip_greeting_text = "⚠️ 注意：客户在30分钟内回复了你的提问，直接回复客户，不要问候、不要道歉、不要说'我看到你的消息了'，继续正常对话。\n" if skip_greeting else ""

    # 有效话术参考 + 话术效果分析
    script_ref_text = ""
    if effective_refs:
        script_ref_text = "【有效话术参考（过往被客户认可的话术，可参考其表达方式）】\n" + "\n".join(effective_refs) + "\n"
    feedback_text = feedback_analysis if feedback_analysis else ""

    # 构建用户消息
    user_message = f"""【当前时间】
    {current_time}
    {skip_greeting_text}【知识库参考内容】
{knowledge_text}

【客户信息】
- 称呼：{customer_title}
- 姓名：{customer_info.get('name', '')}
- 年龄：{customer_info.get('age', '')}岁
- 身高：{customer_info.get('height', '')}cm
- 体重：{customer_info.get('weight', '')}斤
- 目标体重：{customer_info.get('target_weight', '')}斤
- 购买记录：{customer_info.get('purchase', '')}

【客户备注/特点】
{customer_remark if customer_remark else "（无）"}

【客户最新描述/问题】
{recent_messages}

【历史沟通记录（含每条消息的时间）】
{chat_history_text}

{script_ref_text}
{feedback_text}

{image_text}
{local_image_text}
【聊天风格要求】
（已包含在系统提示词中）

【语言习惯】
（已包含在系统提示词中）

【话术风格】
（已包含在系统提示词中）

【违禁词（绝对禁止出现）】
{settings.get('banned_words', '')}

请根据以上信息生成话术，每段用 --- 分隔。"""

    # 收集违禁词做后处理
    banned_words_list = [w.strip() for w in settings.get('banned_words', '').split('\n') if w.strip()]

    # 构建 API 请求
    messages = [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": user_message}
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096
    }

    api_url = f"{base_url.rstrip('/')}/chat/completions"

    # 重试逻辑：遇到429限流自动等待重试（最多3次）
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(api_url, json=payload, headers=headers)

            if response.status_code == 429:
                wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(wait)
                    continue
                return f"【限流】API请求过于频繁，请稍后再试 (已重试{max_retries}次)"

            if response.status_code != 200:
                error_detail = ""
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text[:200]
                return f"【API调用失败】HTTP {response.status_code}: {error_detail}"

            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                raw = data["choices"][0]["message"]["content"].strip()
                # 违禁词后处理：替换为合规说法（不再用 **）
                if banned_words_list:
                    import re
                    # 违禁词 → 合规替换词映射
                    banned_replacements = {
                        '黑色': '油花',
                        '黑油': '油花',
                        '黄油': '油脂',
                        '黄色': '淡黄色',
                        '棕色': '深色',
                        '褐色': '深色',
                        '墨汁': '深色',
                        '墨水': '深色',
                        '粘稠': '油状',
                        '脂肪层': '多余油分',
                        '表层': '表面',
                        '中层': '中间',
                        '黑内脂': '多余油分',
                        '内脂': '多余油分',
                        '脂肪组织': '多余油分',
                        '顽固脂肪': '难减的部分',
                        '深层脂肪': '堆积的油分',
                        '内脏脂肪': '内部的油分',
                        '筋膜脂肪': '堆积的油分',
                        '分解': '帮助消耗',
                        '瓦解': '帮助消耗',
                        '软化': '逐步改善',
                        '凝固': '积聚',
                        '打破': '突破',
                        '激活': '提升',
                        '排黑': '排出',
                        '绝对': '基本',
                        '百分百': '很有把握',
                        '一次性': '集中',
                        '最后一次': '这次',
                        '结案套餐': '方案',
                        '保障': '服务',
                        '保证': '承诺',
                        '易瘦体质': '好的代谢',
                        '改善体质': '调整身体状态',
                        '亚健康': '身体状态',
                        '提高代谢': '帮助代谢',
                        '双配方': '科学配方',
                        '缩短': '加快',
                        '越深': '越明显',
                        '更深': '更明显',
                        '彻底': '逐步',
                        '体验装': '体验组合',
                        '正装': '标准装',
                        '黑乎乎': '颜色深',
                        '湿气': '体内水分',
                        '毒素': '多余废物',
                    }
                    for bw in banned_words_list:
                        bw = bw.strip()
                        if bw:
                            replacement = banned_replacements.get(bw, '**')
                            raw = re.sub(re.escape(bw), replacement, raw, flags=re.IGNORECASE)
                return raw
            else:
                return f"【API返回异常】未找到生成结果: {json.dumps(data, ensure_ascii=False)[:200]}"

        except httpx.TimeoutException:
            if attempt < max_retries - 1:
                import asyncio
                await asyncio.sleep(5 * (2 ** attempt))
                continue
            return "【超时】API请求超时，请稍后重试"
        except Exception as e:
            return f"【请求异常】{str(e)[:200]}"


async def chat_completion(messages: list, model: str = None,
                          temperature: float = 0.7) -> str:
    """
    通用聊天补全调用
    """
    config = get_llm_client()
    api_key = config["api_key"]
    base_url = config["base_url"]
    model = model or config["model"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096
    }

    api_url = f"{base_url.rstrip('/')}/chat/completions"

    # 重试逻辑：遇到429限流自动等待重试（最多3次）
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(api_url, json=payload, headers=headers)

            if response.status_code == 429:
                wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(wait)
                    continue
                error_detail = ""
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text[:200]
                return f"【限流】API请求过于频繁，请稍后再试 (已重试{max_retries}次)"

            if response.status_code != 200:
                return f"【API错误】{response.status_code}: {response.text[:200]}"

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"【错误】{str(e)[:200]}"


async def _analyze_image(file_path: str, category: str = "") -> tuple:
    """分析图片，返回 (description, tags, applicable_customers)（自动选择模型）"""
    # 获取所有vision模型，逐一尝试
    models = config_manager.get_vision_model_list()
    if not models:
        models = [config_manager.get_vision_model_config()]
    last_error = None
    for m in models:
        try:
            return await _analyze_image_with_model(file_path, category, m)
        except Exception as e:
            last_error = e
            continue
    raise Exception(f"视觉模型调用失败，所有模型均不可用: {last_error}")


async def _analyze_image_with_model(file_path: str, category: str, model_cfg: dict) -> tuple:
    """使用指定模型分析图片，返回 (description, tags, applicable_customers)"""
    import base64
    import httpx
    from pathlib import Path

    with open(file_path, 'rb') as f:
        img_data = base64.b64encode(f.read()).decode('utf-8')

    ext = Path(file_path).suffix.lower()
    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'}
    mime_type = mime_map.get(ext, 'image/jpeg')

    from prompts import get_prompt
    prompt_text = get_prompt(category)

    key = model_cfg.get("api_key", "")
    base = model_cfg.get("base_url", "").rstrip("/")
    model = model_cfg.get("model", "")
    model_id = model_cfg.get("_id", model)

    if not key or not base:
        raise Exception(f"[{model_id}] 配置不完整")

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_data}"}}
            ]
        }],
        "max_tokens": 800
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{base}/chat/completions", json=payload, headers=headers)

    if resp.status_code != 200:
        raise Exception(f"[{model_id}] HTTP {resp.status_code}: {resp.text[:100]}")

    data = resp.json()
    msg = data.get("choices", [{}])[0].get("message", {})
    content = msg.get("content", "")
    # 商汤日日新模型把结果放在 reasoning 字段
    if not content and msg.get("reasoning"):
        content = msg["reasoning"]
    if not content:
        raise Exception(f"[{model_id}] 返回内容为空")

    desc, tags, customers = _parse_analysis(content, category)
    return desc, tags, customers


def _parse_analysis(content: str, category: str = "") -> tuple:
    """解析AI返回的结构化内容，返回 (description, tags_list, applicable_customers_str)"""
    desc = ""
    tags = []
    customers = ""
    
    # 提取描述
    if '【详细描述】' in content:
        start = content.find('【详细描述】') + len('【详细描述】')
        end = content.find('【关键标签】')
        if end > start:
            desc = content[start:end].strip()
        else:
            desc = content[start:].strip()
    
    # 提取标签
    if '【关键标签】' in content:
        start = content.find('【关键标签】') + len('【关键标签】')
        end = content.find('【适用客户】')
        if end > start:
            tag_str = content[start:end].strip()
        else:
            tag_str = content[start:].strip()
        tag_str = tag_str.replace('\n', ',').replace('，', ',')
        tags = [t.strip().strip('"').strip("'") for t in tag_str.split(',') if t.strip() and not t.strip().startswith('-')]
    
    # 提取适用客户
    if '【适用客户】' in content:
        start = content.find('【适用客户】') + len('【适用客户】')
        raw = content[start:].strip()
        # 只取有实际内容的
        if len(raw) > 10:
            customers = raw
    
    # 如果适用客户为空，从分类配置取默认值
    if not customers and category:
        try:
            from prompts import get_default_scenarios, get_category_config
            cfg = get_category_config(category)
            scenarios = cfg.get("default_scenarios", [])
            if scenarios:
                parts = []
                for priority, target, reason in scenarios:
                    parts.append(f"- {priority}：{target} — {reason}")
                customers = '\n'.join(parts)
        except Exception:
            pass
    
    # 如果描述为空，取全文的前200字
    if not desc:
        desc = content[:200]
    
    return desc, tags, customers


async def _confirm_case_group(group_images: list, group_id: str) -> dict:
    """
    LLM确认归组：判断一组图片是否属于同一个客户案例。
    group_images: [{"id": int, "file_path": str, "description": str, "category": str}]
    返回: {"confirmed": True/False, "reason": str, "sub_groups": [...]}
    """
    if len(group_images) < 2:
        return {"confirmed": True, "reason": "只有1张图片，自动确认", "sub_groups": []}

    # 构建图片列表
    image_list = ""
    for i, img in enumerate(group_images, 1):
        desc = img.get("description", "未识别")[:80]
        image_list += f"图片{i}: {desc}\n"

    messages = [
        {"role": "system", "content": "你是一名瘦身顾问的图片整理助手。用户发给你一组微信聊天记录中的截图，你需要判断这些图片是否属于同一个客户案例（同一个时间段的对话）。"},
        {"role": "user", "content": f"以下是{len(group_images)}张图片的描述：\n\n{image_list}\n\n请问这些图片是否属于同一个客户案例？请回答：\n1. 是否确认归组（是/否）\n2. 简要原因\n3. 如果否，请给出正确的分组建议（每组的图片编号）"}
    ]

    config = get_llm_client()
    api_key = config["api_key"]
    base_url = config["base_url"]
    model = config["model"]

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 500},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
        if response.status_code == 200:
            content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            # 简单解析：是否包含"否"
            if "否" in content or "不是" in content:
                return {"confirmed": False, "reason": content[:200], "sub_groups": []}
            else:
                return {"confirmed": True, "reason": content[:200], "sub_groups": []}
        return {"confirmed": False, "reason": f"API错误: {response.status_code}", "sub_groups": []}
    except Exception as e:
        return {"confirmed": False, "reason": f"调用失败: {str(e)[:100]}", "sub_groups": []}

