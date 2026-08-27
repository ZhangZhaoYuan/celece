"""
配置管理器 - 管理LLM供应商、API密钥等配置
配置文件存放在 data/config.json
"""

import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "llm": {
        "provider": "sensenova",
        "api_key": "",
        "model": "deepseek-v4-flash",
        "base_url": "https://token.sensenova.cn/v1"
    },
    "embedding_api_key": "",
    "models": {
        "default_id": "",
        "list": {}
    },
    "image_generation": {
        "enabled": True,
        "provider": "agnes",
        "api_key": "",
        "model": "agnes-image-2.1-flash",
        "fallback_model": "agnes-image-2.0-flash",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "size": "1024x1024"
    },
    "vision": {
        "primary": {
            "model": "agnes-2.0-flash",
            "base_url": "https://apihub.agnes-ai.com/v1"
        },
        "fallback": {
            "model": "sensenova-6.7-flash-lite",
            "base_url": "https://token.sensenova.cn/v1"
        }
    },
    "embedding": {
        "model": "text-embedding-v2",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
        "dim": 1536
    },
    "app": {
        "port": 8800,
        "theme": "auto"
    },
    "settings": {},
    "prompts": {
        "image_generation": "一张简洁的减肥瘦身科普知识图，白色背景为主，用中文清晰大字展示以下内容：{description}。风格扁平化、卡通、配色清新。",
        "image_recognition_chat": "请分析这张客户反馈图片：\n1. 如果是排油排便图 → 输出6个指标：油脂量/油脂状态/油脂颜色/大便量/大便状态/大便颜色\n2. 如果是饮食图 → 简单描述食物内容\n3. 如果是体重照 → 提取体重数字（如有）\n4. 如果是体型照 → 简单描述可见变化\n每项一句话，不要多余内容。",
        "image_recognition_index": "请详细描述这张图片的全部内容：\n1. 图片主体、场景、颜色构成\n2. 如果是客户反馈图 → 详细描述排油量、油脂状态、排便情况\n3. 如果是饮食图 → 食物种类、分量、烹饪方式、容器\n4. 如果是体型照 → 拍摄角度、身体部位、可见变化\n5. 提取3-5个中文关键词标签\n6. 判断适合什么类型的客户参考\n尽可能详细完整。"
    }
}


def get_system_prompt() -> str:
    """获取系统提示词"""
    # 优先从 data 目录读取（UI修改后存这里，始终可写）
    prompt_file = DATA_DIR / "SYSTEM_PROMPT.txt"
    if prompt_file.exists():
        try:
            return prompt_file.read_text(encoding="utf-8")
        except Exception:
            pass
    # 回退：dev 模式 backend/SYSTEM_PROMPT.txt
    dev_file = BASE_DIR / "backend" / "SYSTEM_PROMPT.txt"
    if dev_file.exists():
        try:
            return dev_file.read_text(encoding="utf-8")
        except Exception:
            pass
    # 回退：exe 内置 _internal/backend/SYSTEM_PROMPT.txt
    exe_file = BASE_DIR / "_internal" / "backend" / "SYSTEM_PROMPT.txt"
    if exe_file.exists():
        try:
            return exe_file.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


def save_system_prompt(prompt: str):
    """保存系统提示词（写到 data/ 目录，持久化）"""
    ensure_data_dir()
    (DATA_DIR / "SYSTEM_PROMPT.txt").write_text(prompt, encoding="utf-8")


def ensure_data_dir():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "knowledge").mkdir(parents=True, exist_ok=True)


def _generate_model_id(provider: str, model: str) -> str:
    """生成唯一模型ID"""
    raw = f"{provider}_{model}"
    # 只保留字母数字下划线
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', raw)
    return safe.strip('_')


def load_config():
    """加载配置，不存在则创建默认配置"""
    ensure_data_dir()
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        # 合并默认值
        merged = dict(DEFAULT_CONFIG)
        for key in merged:
            if key in config:
                if isinstance(merged[key], dict):
                    merged[key].update(config[key])
                else:
                    merged[key] = config[key]
        # 保留 config 中 DEFAULT_CONFIG 没有的自定义键（如 tags）
        for key in config:
            if key not in merged:
                merged[key] = config[key]
        # 迁移旧配置：如果 llm 有 api_key 但 models 为空，自动迁移
        llm = merged.get("llm", {})
        models = merged.get("models", {"default_id": "", "list": {}})
        if llm.get("api_key") and not models.get("list"):
            mid = _generate_model_id(llm.get("provider", ""), llm.get("model", ""))
            models["list"][mid] = {
                "provider": llm["provider"],
                "api_key": llm["api_key"],
                "model": llm["model"],
                "base_url": llm["base_url"]
    }
            models["default_id"] = mid
            merged["models"] = models
            save_config(merged)
        return merged
    except (json.JSONDecodeError, IOError):
        return dict(DEFAULT_CONFIG)


def get_image_gen_config():
    """获取图片生成配置 - 返回 provider 列表（按优先级排列，已过滤过期）"""
    from datetime import datetime
    config = load_config()
    ig = config.get("image_generation", {})
    if not ig.get("enabled", True):
        return None

    def _is_expired(expires_at):
        if not expires_at:
            return False
        try:
            expire = datetime.fromisoformat(expires_at)
            return datetime.now() >= expire
        except Exception:
            return False

    providers = []

    # 1. 主模型：从 models.list[image_gen_default_id] 读取
    main_model_cfg = get_image_gen_model_config()
    gen_expires = ig.get("expires_at", "")
    if main_model_cfg and not _is_expired(gen_expires):
        providers.append({
            "model": main_model_cfg["model"],
            "api_key": main_model_cfg["api_key"],
            "base_url": main_model_cfg["base_url"],
            "size": ig.get("size", "1024x1024")
        })

    # 2. fallback (agnes-2.1-flash 如果没有过期且不是主模型)
    fb_model = ig.get("fallback_model", "agnes-image-2.1-flash")
    fb_expires = ig.get("fallback_expires", "")
    if fb_model and fb_model != main_model and not _is_expired(fb_expires):
        fb_key = ig.get("fallback_api_key", main_key)
        fb_base = ig.get("fallback_base_url", "https://apihub.agnes-ai.com/v1")
        providers.append({
            "model": fb_model,
            "api_key": fb_key,
            "base_url": fb_base,
            "size": ig.get("size", "1024x1024")
        })

    # 3. second_fallback (agnes-2.0-flash)
    sfb_model = ig.get("second_fallback", "")
    if sfb_model and sfb_model != main_model and sfb_model != fb_model:
        sfb_key = ig.get("second_fallback_api_key", "")
        sfb_base = ig.get("second_fallback_base_url", "https://apihub.agnes-ai.com/v1")
        if not sfb_key:
            sfb_key = main_key  # 复用同一个key
        if sfb_key:
            providers.append({
                "model": sfb_model,
                "api_key": sfb_key,
                "base_url": sfb_base,
                "size": "2048x2048"  # sensenova-u1-fast 需要大尺寸
    })

    # 4. third_fallback (sensenova-u1-fast)
    tfb_model = ig.get("third_fallback", "")
    if tfb_model and tfb_model != main_model and tfb_model != fb_model:
        tfb_key = ig.get("third_fallback_api_key", "")
        tfb_base = ig.get("third_fallback_base_url", "https://token.sensenova.cn/v1")
        if not tfb_key:
            # 从LLM配置读取
            llm = config.get("llm", {})
            tfb_key = llm.get("api_key", "")
        if tfb_key:
            providers.append({
                "model": tfb_model,
                "api_key": tfb_key,
                "base_url": tfb_base,
                "size": "2048x2048"  # sensenova-u1-fast 需要大尺寸
    })

    return providers if providers else None


    def get_vision_config():
        """获取视觉识别模型配置（主模型+备用）"""
        config = load_config()
        vision = config.get("vision", DEFAULT_CONFIG.get("vision", {}))
        ig = config.get("image_generation", {})
        # 主模型API key复用图片生成的agnes key
        primary_key = ig.get("api_key", "")
        # 备用模型API key复用LLM的key
        fallback_key = config.get("llm", {}).get("api_key", "")
        return {
            "primary": {
                "model": vision.get("primary", {}).get("model", "agnes-2.0-flash"),
                "base_url": vision.get("primary", {}).get("base_url", "https://apihub.agnes-ai.com/v1"),
                "api_key": primary_key
    },
            "fallback": {
                "model": vision.get("fallback", {}).get("model", "sensenova-6.7-flash-lite"),
                "base_url": vision.get("fallback", {}).get("base_url", "https://token.sensenova.cn/v1"),
                "api_key": fallback_key
    }
        }


def get_embedding_config():
    """获取Embedding模型配置（优先从 models.list 读取）"""
    config = load_config()
    models = config.get("models", {})
    model_list = models.get("list", {})
    
    # 先查找embedding类型的模型
    emb_model = None
    for model_id, model_config in model_list.items():
        if "embedding" in model_config.get("categories", []):
            emb_model = model_config
            break
    
    if emb_model:
        base_url = emb_model.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings")
        api_mode = emb_model.get("api_mode", "openai")
        # OpenAI 模式自动补 /embeddings
        if api_mode == "openai" and not base_url.rstrip("/").endswith("/embeddings"):
            base_url = base_url.rstrip("/") + "/embeddings"
        return {
            "model": emb_model.get("model", "text-embedding-v2"),
            "base_url": base_url,
            "dim": emb_model.get("dim") or config.get("embedding", {}).get("dim", 1536),
            "api_key": emb_model.get("api_key", ""),
            "api_mode": api_mode,
            "dimension": emb_model.get("dimension", emb_model.get("dim", 1024))
        }
    
    # Fallback to old embedding section
    emb = config.get("embedding", DEFAULT_CONFIG.get("embedding", {}))
    # 优先使用embedding部分的api_key，其次使用embedding_api_key，最后使用llm的api_key
    api_key = emb.get("api_key", "") or config.get("embedding_api_key", "") or config.get("llm", {}).get("api_key", "")
    return {
        "model": emb.get("model", "text-embedding-v2"),
        "base_url": emb.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"),
        "dim": emb.get("dim", emb.get("dimension", 1024)),
        "api_key": api_key,
        "api_mode": emb.get("api_mode", "openai"),
        "dimension": emb.get("dimension", emb.get("dim", 1024))
    }


    def save_config(config):
        """保存配置"""
    ensure_data_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)



def get_prompts() -> dict:
    """获取所有可编辑提示词"""
    config = load_config()
    default_prompts = dict(DEFAULT_CONFIG.get("prompts", {}))
    saved = config.get("prompts", {})
    default_prompts.update(saved)
    return default_prompts


def save_prompt(name: str, content: str):
    """保存单个提示词"""
    config = load_config()
    if "prompts" not in config:
        config["prompts"] = {}
    config["prompts"][name] = content
    save_config(config)


def get_llm_config():
    """获取当前默认LLM配置"""
    config = load_config()
    models = config.get("models", {})
    default_id = models.get("default_id", "")
    model_list = models.get("list", {})
    
    if default_id and default_id in model_list:
        return dict(model_list[default_id])
    
    # Fallback to old llm section
    return dict(config.get("llm", DEFAULT_CONFIG["llm"]))


def save_config(config):
    """保存配置到文件"""
    ensure_data_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_vision_model_config():
    """获取图片识别模型配置"""
    config = load_config()
    models = config.get("models", {})
    vision_id = models.get("vision_default_id", "")
    model_list = models.get("list", {})

    if vision_id and vision_id in model_list:
        return dict(model_list[vision_id])

    # Fallback to main llm config
    return get_llm_config()


def get_vision_model_list():
    """获取所有支持 vision 的模型列表（按优先级排序）"""
    config = load_config()
    models = config.get("models", {}).get("list", {})
    # 按模型ID（非模型名）指定顺序
    id_order = ["qwen3.5_omni_plus",
                "qwen3.5_omni_plus_2026_03_15",
                "qwen3.5_omni_flash",
                "Agnes_agnes_2_0_flash"]
    result = []
    for mid in id_order:
        m = models.get(mid)
        if m and "vision" in m.get("categories", []):
            entry = dict(m)
            entry["_id"] = mid  # 保留原始ID用于日志
            result.append(entry)
    return result


def get_image_gen_model_config():
    """获取图片生成主模型配置"""
    config = load_config()
    models = config.get("models", {})
    gen_id = models.get("image_gen_default_id", "")
    model_list = models.get("list", {})
    
    if gen_id and gen_id in model_list:
        return dict(model_list[gen_id])
    
    return None


def update_llm_config(provider, api_key, model, base_url):
    """更新LLM配置并设为默认"""
    config = load_config()
    
    # 更新旧版 llm 字段（向后兼容）
    config["llm"] = {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url.rstrip("/")
    }
    
    # 更新 models 列表
    mid = _generate_model_id(provider, model)
    models = config.get("models", {"default_id": "", "list": {}})
    models["list"][mid] = {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url.rstrip("/")
    }
    models["default_id"] = mid
    config["models"] = models
    
    save_config(config)
    return config["llm"]


# ===== 多模型管理 =====

def list_models():
    """获取所有已配置模型"""
    config = load_config()
    models = config.get("models", {})
    default_id = models.get("default_id", "")
    vision_id = models.get("vision_default_id", "")
    gen_id = models.get("image_gen_default_id", "")
    emb_id = models.get("embedding_default_id", "")
    model_list = models.get("list", {})
    
    result = []
    for mid, m in model_list.items():
        key = m.get("api_key", "")
        masked_key = (key[:8] + "****" + key[-4:]) if len(key) > 8 else "****"
        result.append({
                    "id": mid,
                    "provider": m.get("provider", ""),
                    "model": m.get("model", ""),
                    "base_url": m.get("base_url", ""),
                    "api_key_masked": masked_key,
                    "categories": m.get("categories", []),
                    "is_default": (mid == default_id),
                    "is_vision_default": (mid == vision_id),
                    "is_image_gen_default": (mid == gen_id),
                    "is_embedding_default": (mid == emb_id)
        })
    return {
        "models": result,
        "default_ids": {
            "chat": default_id,
            "vision": vision_id,
            "imagegen": gen_id,
            "embedding": emb_id
        }
    }


def add_model(provider: str, api_key: str, model: str, base_url: str, categories: list = None, api_mode: str = "openai") -> dict:
    """添加一个新模型配置"""
    config = load_config()
    base_url = base_url.rstrip("/")
    mid = _generate_model_id(provider, model)

    models = config.get("models", {"default_id": "", "list": {}})
    models.setdefault("list", {})[mid] = {
                "provider": provider,
                "api_key": api_key,
                "model": model,
                "base_url": base_url,
                "categories": categories or [],
                "api_mode": api_mode
    }
    
    # 如果是第一个模型，自动设为默认
    if not models["default_id"]:
        models["default_id"] = mid
        # 同步更新 llm 字段
        config["llm"] = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "base_url": base_url
        }
    
    config["models"] = models
    save_config(config)
    
    return {"id": mid, "provider": provider, "model": model, "base_url": base_url, "is_default": (mid == models["default_id"])}


def set_default_model(model_id: str) -> dict:
    """设置默认模型（话术）"""
    config = load_config()
    models = config.get("models", {"default_id": "", "list": {}})
    
    if model_id not in models.get("list", {}):
        raise ValueError(f"模型 {model_id} 不存在")
    
    models["default_id"] = model_id
    m = models["list"][model_id]
    
    # 同步到旧的 llm 字段
    config["llm"] = {
        "provider": m["provider"],
        "api_key": m["api_key"],
        "model": m["model"],
        "base_url": m["base_url"]
    }
    
    config["models"] = models
    save_config(config)
    return {"id": model_id, "type": "chat", "provider": m["provider"], "model": m["model"]}


def set_vision_default_model(model_id: str) -> dict:
    """设置图片识别默认模型"""
    config = load_config()
    models = config.get("models", {"vision_default_id": "", "list": {}})
    
    if model_id not in models.get("list", {}):
        raise ValueError(f"模型 {model_id} 不存在")
    
    models["vision_default_id"] = model_id
    m = models["list"][model_id]
    config["models"] = models
    save_config(config)
    return {"id": model_id, "type": "vision", "provider": m["provider"], "model": m["model"]}


def set_image_gen_default_model(model_id: str) -> dict:
    """设置图片生成默认模型"""
    config = load_config()
    models = config.get("models", {"image_gen_default_id": "", "list": {}})
    
    if model_id not in models.get("list", {}):
        raise ValueError(f"模型 {model_id} 不存在")
    
    models["image_gen_default_id"] = model_id
    m = models["list"][model_id]
    config["models"] = models
    save_config(config)
    return {"id": model_id, "type": "imagegen", "provider": m["provider"], "model": m["model"]}


def set_embedding_default_model(model_id: str) -> dict:
    """设置Embedding默认模型"""
    config = load_config()
    models = config.get("models", {"embedding_default_id": "", "list": {}})
    
    if model_id not in models.get("list", {}):
        raise ValueError(f"模型 {model_id} 不存在")
    
    models["embedding_default_id"] = model_id
    m = models["list"][model_id]
    config["models"] = models
    
    # 同步到旧的 embedding 字段
    config["embedding"] = {
            "model": m["model"],
            "base_url": m["base_url"],
            "dim": config.get("embedding", {}).get("dim", 1536),
            "api_mode": m.get("api_mode", "openai")
        }
    config["embedding_api_key"] = m["api_key"]
    
    save_config(config)
    return {"id": model_id, "type": "embedding", "provider": m["provider"], "model": m["model"]}


def remove_model(model_id: str):
    """删除一个模型配置"""
    config = load_config()
    models = config.get("models", {"default_id": "", "vision_default_id": "", "image_gen_default_id": "", "list": {}})
    
    if model_id not in models.get("list", {}):
        raise ValueError(f"模型 {model_id} 不存在")
    
    del models["list"][model_id]
    
    # 如果删除的是任一默认模型，重置对应字段
    if models.get("default_id") == model_id:
        remaining = list(models["list"].keys())
        if remaining:
            models["default_id"] = remaining[0]
            m = models["list"][remaining[0]]
            config["llm"] = {
                "provider": m["provider"],
                "api_key": m["api_key"],
                "model": m["model"],
                "base_url": m["base_url"]
    }
        else:
            models["default_id"] = ""
            config["llm"] = dict(DEFAULT_CONFIG["llm"])
    
    if models.get("vision_default_id") == model_id:
        remaining = list(models["list"].keys())
        models["vision_default_id"] = remaining[0] if remaining else ""
    
    if models.get("image_gen_default_id") == model_id:
        remaining = list(models["list"].keys())
        models["image_gen_default_id"] = remaining[0] if remaining else ""
    
    config["models"] = models
    save_config(config)
