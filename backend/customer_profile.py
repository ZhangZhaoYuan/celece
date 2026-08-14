# -*- coding: utf-8 -*-
"""
客户画像分析模块
分析客户情绪、流失风险、生命周期、RFM分层、价值分
"""
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from database import get_db, get_messages, get_purchase_stats, PRODUCTS

# 关键词映射
EMOTION_POSITIVE = ['好的', '谢谢', '开心', '高兴', '满意', '不错', '有效', '轻了', '瘦了', '棒', '赞', '感谢']
EMOTION_NEGATIVE = ['不', '别', '不用', '不要', '不需要', '算了', '太贵', '没钱', '失望', '生气', '烦', '难过']
CHURN_SIGNALS = ['不做了', '不喝了', '停了', '不买了', '没效果', '放弃了', '退款', '退钱']
ENGAGEMENT_HIGH = ['今天', '早上', '晚上', '反馈', '数据', '照片', '图']
ENGAGEMENT_LOW = ['嗯', '哦', '好', '知道了', '行', 'ok']


def analyze_emotion(messages: List[dict]) -> Dict[str, Any]:
    """分析客户情绪状态"""
    if not messages:
        return {"score": 0, "label": "中性", "reason": "无消息"}
    
    # 获取最近10条客户消息
    user_msgs = [m for m in messages if m.get('role') == 'user'][-10:]
    if not user_msgs:
        return {"score": 0, "label": "中性", "reason": "无客户消息"}
    
    combined_text = " ".join([m.get('content', '') for m in user_msgs])
    score = 0
    positive_count = 0
    negative_count = 0
    
    for word in EMOTION_POSITIVE:
        if word in combined_text:
            positive_count += 1
            score += 10
    
    for word in EMOTION_NEGATIVE:
        if word in combined_text:
            negative_count += 1
            score -= 10
    
    # 计算消息长度和积极性
    avg_length = sum(len(m.get('content', '')) for m in user_msgs) / len(user_msgs)
    if avg_length > 30:
        score += 5  # 愿意多说通常是积极信号
    
    # 限制范围
    score = max(-100, min(100, score))
    
    if score >= 30:
        label = "积极"
    elif score <= -30:
        label = "消极"
    else:
        label = "中性"
    
    return {
        "score": score,
        "label": label,
        "positive_words": positive_count,
        "negative_words": negative_count,
        "reason": f"积极词{positive_count}个，消极词{negative_count}个"
    }


def analyze_engagement(messages: List[dict]) -> Dict[str, Any]:
    """分析客户配合度"""
    if not messages:
        return {"level": "unknown", "detail": "无消息"}
    
    user_msgs = [m for m in messages if m.get('role') == 'user'][-10:]
    if not user_msgs:
        return {"level": "unknown", "detail": "无客户消息"}
    
    high_signals = 0
    low_signals = 0
    total_chars = 0
    
    for msg in user_msgs:
        content = msg.get('content', '')
        total_chars += len(content)
        
        for word in ENGAGEMENT_HIGH:
            if word in content:
                high_signals += 1
        for word in ENGAGEMENT_LOW:
            if word in content:
                low_signals += 1
    
    # 判断配合度
    if high_signals >= 3 or total_chars > 100:
        level = "high"
    elif low_signals >= 2 and total_chars < 30:
        level = "low"
    else:
        level = "medium"
    
    return {
        "level": level,
        "high_signals": high_signals,
        "low_signals": low_signals,
        "total_chars": total_chars
    }


def analyze_churn_risk(customer: Dict, messages: List[dict], purchase_stats: Optional[Dict]) -> Dict[str, Any]:
    """分析流失风险"""
    risk_score = 0
    reasons = []
    
    # 1. 沉默天数
    if messages:
        last_msg = max(messages, key=lambda m: m.get('timestamp', ''))
        last_time = last_msg.get('timestamp', '')
        if last_time:
            try:
                last_dt = datetime.strptime(last_time, "%Y-%m-%d %H:%M:%S")
                days_silent = (datetime.now() - last_dt).days
                if days_silent > 14:
                    risk_score += 40
                    reasons.append(f"沉默{days_silent}天")
                elif days_silent > 7:
                    risk_score += 20
                    reasons.append(f"沉默{days_silent}天")
            except:
                pass
    
    # 2. 购买历史
    if purchase_stats:
        latest = purchase_stats.get('latest', {})
        if latest:
            latest_date = latest.get('date', '')
            if latest_date:
                try:
                    latest_dt = datetime.strptime(latest_date[:10], "%Y-%m-%d")
                    days_since_purchase = (datetime.now() - latest_dt).days
                    if days_since_purchase > 60:
                        risk_score += 30
                        reasons.append(f"距上次购买{days_since_purchase}天")
                except:
                    pass
        
        # 购买次数少
        if purchase_stats.get('total_purchases', 0) == 1:
            risk_score += 10
            reasons.append("首次购买")
    
    # 3. 聊天记录中的流失信号
    if messages:
        user_msgs = [m for m in messages if m.get('role') == 'user']
        combined = " ".join([m.get('content', '') for m in user_msgs[-10:]])
        for signal in CHURN_SIGNALS:
            if signal in combined:
                risk_score += 30
                reasons.append(f"发现流失信号: {signal}")
    
    # 4. 配合度低
    engagement = analyze_engagement(messages)
    if engagement.get('level') == 'low':
        risk_score += 20
        reasons.append("配合度低")
    
    # 确定风险等级
    risk_score = min(100, max(0, risk_score))
    if risk_score >= 60:
        risk_level = "high"
    elif risk_score >= 30:
        risk_level = "medium"
    else:
        risk_level = "low"
    
    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "reasons": reasons
    }


def analyze_lifecycle(customer: Dict, purchase_stats: Optional[Dict], messages: List[dict]) -> Dict[str, Any]:
    """分析客户生命周期阶段"""
    if not customer:
        return {"stage": "unknown", "days": 0}
    
    # 计算客户天数
    created_at = customer.get('created_at', '')
    days_active = 0
    if created_at:
        try:
            created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            days_active = (datetime.now() - created_dt).days
        except:
            pass
    
    # 根据购买历史和消息判断阶段
    total_purchases = purchase_stats.get('total_purchases', 0) if purchase_stats else 0
    total_amount = purchase_stats.get('total_amount', 0) if purchase_stats else 0
    engagement = analyze_engagement(messages)
    
    if total_purchases >= 3 and total_amount >= 2000:
        stage = "vip"
    elif total_purchases >= 2:
        stage = "active"
    elif total_purchases == 1:
        if days_active < 7:
            stage = "new"
        else:
            stage = "training"
    else:
        if days_active < 3:
            stage = "new"
        else:
            stage = "training"
    
    # 检查是否流失
    if messages:
        last_msg = max(messages, key=lambda m: m.get('timestamp', ''))
        last_time = last_msg.get('timestamp', '')
        if last_time:
            try:
                last_dt = datetime.strptime(last_time, "%Y-%m-%d %H:%M:%S")
                days_silent = (datetime.now() - last_dt).days
                if days_silent > 30 and total_purchases > 0:
                    stage = "churned"
            except:
                pass
    
    return {
        "stage": stage,
        "days": days_active,
        "stage_label": {
            "new": "新客户",
            "training": "训练期",
            "active": "活跃客户",
            "vip": "VIP客户",
            "churned": "流失客户"
        }.get(stage, stage)
    }


def calculate_rfm(customer: Dict, purchase_stats: Optional[Dict]) -> Dict[str, Any]:
    """计算RFM指标"""
    if not purchase_stats or not customer:
        return {
            "r_days": None,
            "f_count": 0,
            "m_amount": 0,
            "tier": "E"
        }
    
    # R: 最近购买距离天数
    r_days = None
    latest = purchase_stats.get('latest', {})
    if latest and latest.get('date'):
        try:
            latest_dt = datetime.strptime(latest['date'][:10], "%Y-%m-%d")
            r_days = (datetime.now() - latest_dt).days
        except:
            pass
    
    # F: 购买次数
    f_count = purchase_stats.get('total_purchases', 0)
    
    # M: 累计消费金额
    m_amount = purchase_stats.get('total_amount', 0)
    
    # 计算RFM评分（1-5分）
    def r_score(days):
        if days is None:
            return 1
        if days <= 7:
            return 5
        elif days <= 14:
            return 4
        elif days <= 30:
            return 3
        elif days <= 60:
            return 2
        else:
            return 1
    
    def f_score(count):
        if count >= 5:
            return 5
        elif count >= 3:
            return 4
        elif count >= 2:
            return 3
        elif count >= 1:
            return 2
        else:
            return 1
    
    def m_score(amount):
        if amount >= 5000:
            return 5
        elif amount >= 3000:
            return 4
        elif amount >= 1500:
            return 3
        elif amount >= 500:
            return 2
        else:
            return 1
    
    r = r_score(r_days)
    f = f_score(f_count)
    m = m_score(m_amount)
    
    # RFM综合分层
    rfm_total = r + f + m
    if rfm_total >= 13:
        tier = "A"
    elif rfm_total >= 10:
        tier = "B"
    elif rfm_total >= 7:
        tier = "C"
    elif rfm_total >= 4:
        tier = "D"
    else:
        tier = "E"
    
    return {
        "r_days": r_days,
        "r_score": r,
        "f_count": f_count,
        "f_score": f,
        "m_amount": m_amount,
        "m_score": m,
        "rfm_total": rfm_total,
        "tier": tier
    }


def calculate_value_score(
    emotion: Dict,
    churn_risk: Dict,
    lifecycle: Dict,
    rfm: Dict,
    engagement: Dict
) -> int:
    """计算综合价值分（0-100）"""
    score = 50  # 基础分
    
    # 情绪加成（-20到+20）
    emotion_score = emotion.get('score', 0)
    score += emotion_score * 0.2
    
    # 流失风险减分（高风险-30，中风险-15）
    risk_level = churn_risk.get('risk_level', 'low')
    if risk_level == 'high':
        score -= 30
    elif risk_level == 'medium':
        score -= 15
    
    # 生命周期加成
    stage = lifecycle.get('stage', 'new')
    stage_scores = {
        'vip': 25,
        'active': 15,
        'training': 5,
        'new': 0,
        'churned': -20
    }
    score += stage_scores.get(stage, 0)
    
    # RFM分层加成
    tier = rfm.get('tier', 'E')
    tier_scores = {'A': 20, 'B': 15, 'C': 10, 'D': 5, 'E': 0}
    score += tier_scores.get(tier, 0)
    
    # 配合度加成
    eng_level = engagement.get('level', 'medium')
    if eng_level == 'high':
        score += 10
    elif eng_level == 'low':
        score -= 10
    
    # 限制范围
    return max(0, min(100, int(score)))


def analyze_customer_profile(customer_id: int) -> Dict[str, Any]:
    """分析客户完整画像"""
    from database import get_customer
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取客户信息
    customer = get_customer(customer_id)
    if not customer:
        return None
    
    # 获取消息历史
    messages = get_messages(customer_id)
    
    # 获取购买统计
    purchase_history = customer.get('purchase_history', '[]')
    purchase_stats = get_purchase_stats(purchase_history)
    
    # 执行各项分析
    emotion = analyze_emotion(messages)
    engagement = analyze_engagement(messages)
    churn_risk = analyze_churn_risk(customer, messages, purchase_stats)
    lifecycle = analyze_lifecycle(customer, purchase_stats, messages)
    rfm = calculate_rfm(customer, purchase_stats)
    value_score = calculate_value_score(emotion, churn_risk, lifecycle, rfm, engagement)
    
    # 准备更新数据
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    update_data = {
        'emotion_score': emotion['score'],
        'churn_risk': churn_risk['risk_level'],
        'lifecycle_stage': lifecycle['stage'],
        'rfm_tier': rfm['tier'],
        'value_score': value_score,
        'rfm_r_days': rfm.get('r_days'),
        'rfm_f_count': rfm.get('f_count', 0),
        'rfm_m_amount': rfm.get('m_amount', 0),
        'ai_analysis_at': now,
        'ai_version': 'v1',
        'updated_at': now
    }
    
    # 更新数据库
    cursor.execute("""
        UPDATE customers SET 
            emotion_score=?, churn_risk=?, lifecycle_stage=?, rfm_tier=?, value_score=?,
            rfm_r_days=?, rfm_f_count=?, rfm_m_amount=?, ai_analysis_at=?, ai_version=?, updated_at=?
        WHERE id=?
    """, (
        update_data['emotion_score'],
        update_data['churn_risk'],
        update_data['lifecycle_stage'],
        update_data['rfm_tier'],
        update_data['value_score'],
        update_data['rfm_r_days'],
        update_data['rfm_f_count'],
        update_data['rfm_m_amount'],
        update_data['ai_analysis_at'],
        update_data['ai_version'],
        update_data['updated_at'],
        customer_id
    ))
    conn.commit()
    
    conn.close()
    
    # 生成跟进建议
    recommendations = generate_recommendations(emotion, churn_risk, lifecycle, rfm, engagement)
    
    return {
        "customer_id": customer_id,
        "name": customer.get('name', ''),
        "emotion": emotion,
        "engagement": engagement,
        "churn_risk": churn_risk,
        "lifecycle": lifecycle,
        "rfm": rfm,
        "value_score": value_score,
        "recommendations": recommendations,
        "analyzed_at": now
    }


def generate_recommendations(emotion, churn_risk, lifecycle, rfm, engagement):
    """生成AI跟进建议"""
    recs = []
    
    # 基于情绪的建议
    if emotion['label'] == '消极':
        recs.append("客户情绪低落，先用关心语气问候，不要急于推销")
    elif emotion['label'] == '积极':
        recs.append("客户情绪积极，可以趁热打铁推进复购")
    
    # 基于流失风险的建议
    if churn_risk['risk_level'] == 'high':
        recs.append(f"⚠️ 高风险流失客户！原因: {', '.join(churn_risk['reasons'][:2])}")
        recs.append("优先挽回，了解具体原因，提供针对性解决方案")
    elif churn_risk['risk_level'] == 'medium':
        recs.append("客户有流失迹象，加强互动，关注需求变化")
    
    # 基于生命周期的建议
    stage = lifecycle.get('stage')
    if stage == 'new':
        recs.append("新客户，重点介绍产品原理和使用方法，建立信任")
    elif stage == 'training':
        recs.append("训练中客户，关注数据反馈，及时调整方案")
    elif stage == 'vip':
        recs.append("VIP客户，提供专属优惠，维护好关系促进转介绍")
    elif stage == 'churned':
        recs.append("已流失客户，尝试召回，了解流失原因")
    
    # 基于配合度的建议
    if engagement['level'] == 'low':
        recs.append("客户配合度低，简化话术，一次只问一个问题")
    
    # 基于RFM的建议
    if rfm['tier'] in ['A', 'B']:
        recs.append(f"高价值客户(RFM:{rfm['tier']})，重点关注，及时响应")
    
    return recs[:5]  # 最多返回5条建议


def batch_analyze_customers(limit: int = 50) -> Dict[str, Any]:
    """批量分析客户画像"""
    from database import list_customers
    
    customers = list_customers()[:limit]
    results = {
        "total": len(customers),
        "analyzed": 0,
        "failed": 0,
        "details": []
    }
    
    for customer in customers:
        try:
            profile = analyze_customer_profile(customer['id'])
            if profile:
                results["analyzed"] += 1
                results["details"].append({
                    "customer_id": customer['id'],
                    "name": customer['name'],
                    "value_score": profile['value_score'],
                    "lifecycle": profile['lifecycle']['stage'],
                    "churn_risk": profile['churn_risk']['risk_level']
                })
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "customer_id": customer['id'],
                "name": customer['name'],
                "error": str(e)
            })
    
    return results
