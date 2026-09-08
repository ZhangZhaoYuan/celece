# RAG 优化（2026-08-30）

小赛助手知识库搜索的四大优化，显著提升检索精准度。

## 优化概览

| 优化项 | 做法 | 预期提升 |
|--------|------|----------|
| Query改写 | 关键词扩展（同义词映射） | +15%命中率 |
| 知识切片 | 自动分类+类型标签 | +10%召回率 |
| Metadata过滤 | 类型权重调节 | +5%精准度 |
| Reranker | 百度千帆 bce-reranker-base | +20%精准度 |

## 1. Query改写（knowledge.py `rewrite_query`）

**原理**: 用户输入时自动扩展同义词，提高命中概率。

**实现**:
```python
_SYNONYMS = {
    "减肥": ["瘦身", "减脂", "掉秤", "降体重"],
    "价格": ["多少钱", "费用", "价位", "收费", "定价"],
    "套餐": ["组合", "疗程", "方案", "套装"],
}

def rewrite_query(original_query: str) -> list:
    queries = [original_query]
    keywords = re.findall(r'[\u4e00-\u9fa5]{2,6}', original_query)
    for kw in keywords:
        if kw in _SYNONYMS:
            queries.extend(_SYNONYMS[kw])
    return list(dict.fromkeys(queries))[:5]
```

**效果**: "减肥产品多少钱" → 同时搜索多个相关查询

## 2. 知识切片增强（knowledge.py `_chunk_text_improved`）

**改进点**: 每个 chunk 包含 `type` 字段，自动分类为:
- `price` - 价格/套餐相关
- `faq` - 问答相关
- `case` - 案例相关
- `instruction` - 用法相关
- `warning` - 禁忌相关
- `intro` - 产品介绍相关
- `general` - 其他

**chunk_size**: 从500改为300，更细粒度切分

## 3. Metadata过滤（knowledge.py `search_knowledge`）

**权重配置**:
```python
type_weights = {
    "price": 1.2,   # 价格信息最重要
    "case": 1.1,    # 案例次之
    "faq": 1.0,     # FAQ标准
    "general": 0.9  # 其他略降
}
```

**应用位置**: RRF融合后、Reranker前

## 4. Reranker集成（knowledge.py `rerank_documents`）

**服务商**: 百度千帆
**模型**: `bce-reranker-base`
**API端点**: `https://qianfan.baidubce.com/v2/rerank`

**启用方式** (config.json):
```json
{
  "embedding": {
    "api_key": "bce-v3/...",
    "reranker": {
      "enabled": true,
      "model": "bce-reranker-base"
    }
  }
}
```

**流程**: sqlite-vec检索 top-50 → RRF融合 → Metadata加权 → Reranker精排 top-10→top-5

## API响应字段

`/api/generate` 返回新增字段:
- `knowledge_mode`: "hybrid_rerank" 或 "hybrid"
- `reranker_available`: true/false
- `rewritten_queries`: ["原文", "同义词1", ...]
- `knowledge_results_sample`: 前3条知识结果（含type和rerank_score）

## 注意事项

1. Reranker配置必须加 `enabled: true`
2. `bge-reranker-v2-m3` 返回404，使用 `bce-reranker-base`
3. 类型推断基于关键词匹配，不是LLM分类