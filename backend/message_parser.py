# -*- coding: utf-8 -*-
"""
微信聊天记录解析模块
将微信导出的完整聊天记录拆分成独立的消息，并识别发送者角色
"""

import re
from datetime import datetime
from typing import List, Dict, Optional


def parse_wechat_messages(content: str) -> List[Dict]:
    """
    解析微信导出的聊天记录，按发送者标记拆分
    
    支持的发送者格式：
    - 张兆渊(赛乐赛客服)
    - 张兆渊(🔥赛乐赛瘦身客服🔥未成年勿➕)
    - 26810陈莉莉158.49.100@微信
    - 26810陈莉莉158.49.100@微信联系人
    - A一26518陈伟文175.180.31@微信
    - A二26224黄信茹165.130.44@微信
    
    返回: list of {role, sender, clean_sender, text, timestamp, customer_name}
    """
    if not content:
        return []
    
    # 发送者识别正则
    # 匹配：张兆渊+括号内容，或 数字ID+姓名+@微信/微信联系人
    sender_pattern = r'(张兆渊\([^)]+\)|\d{5,}[^\s@]+@\w+(?:联系人)?)'
    
    # 时间戳正则（用于提取timestamp）
    timestamp_pattern = r'(\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}:\d{2})'
    
    # 按发送者标记拆分
    parts = re.split(f'({sender_pattern})', content)
    
    messages = []
    current_sender = None
    current_text_parts = []
    
    for i, part in enumerate(parts):
        if not part.strip():
            continue
        
        # 检查是否是发送者标记
        sender_match = re.match(f'^{sender_pattern}$', part.strip())
        if sender_match:
            # 保存之前的消息
            if current_sender and current_text_parts:
                text = '\n'.join(current_text_parts).strip()
                if text:
                    messages.append({
                        'role': 'assistant' if '张兆渊' in current_sender else 'customer',
                        'sender': current_sender,
                        'clean_sender': _clean_sender(current_sender),
                        'text': text,
                        'timestamp': _extract_timestamp(text, current_text_parts),
                        'customer_name': _extract_customer_name(current_sender)
                    })
            
            # 开始新的消息
            current_sender = part.strip()
            current_text_parts = []
        else:
            # 这是消息内容
            current_text_parts.append(part)
    
    # 处理最后一条消息
    if current_sender and current_text_parts:
        text = '\n'.join(current_text_parts).strip()
        if text:
            messages.append({
                'role': 'assistant' if '张兆渊' in current_sender else 'customer',
                'sender': current_sender,
                'clean_sender': _clean_sender(current_sender),
                'text': text,
                'timestamp': _extract_timestamp(text, current_text_parts),
                'customer_name': _extract_customer_name(current_sender)
            })
    
    return messages


def _clean_sender(sender: str) -> str:
    """清理发送者名称，提取关键信息"""
    # 张兆渊的情况
    if '张兆渊' in sender:
        return '张兆渊'
    
    # 客户ID的情况：提取姓名
    # 格式：A一26518陈伟文175.180.31@微信
    match = re.match(r'[A-Za-z]+\D*(\d{5,})([^\d@]+?)(?:\d+\.?\d*\.?\d*\.?\d*@)?', sender)
    if match:
        return match.group(2).strip()
    
    # 其他情况：尝试提取中文名称
    match = re.search(r'([一-鿿]{2,4})', sender)
    if match:
        return match.group(1)
    
    return sender[:20]  # 截断过长的名称


def _extract_timestamp(text: str, text_parts: List[str]) -> str:
    """从消息中提取时间戳"""
    full_text = text if text else '\n'.join(text_parts)
    
    # 尝试匹配常见的时间格式
    patterns = [
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',  # 2026-08-14 10:30:00
        r'(\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}:\d{2})',   # 7/14 10:30:00
        r'(\d{4}年\d{1,2}月\d{1,2}日)',                 # 2026年7月14日
        r'(\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})',        # 7月14日 10:30
    ]
    
    for pattern in patterns:
        match = re.search(pattern, full_text)
        if match:
            return match.group(1)
    
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _extract_customer_name(sender: str) -> str:
    """从发送者名称中提取客户名"""
    if '张兆渊' in sender:
        return '张兆渊'
    
    # 提取数字ID后的中文名称
    match = re.search(r'\d{5,}([^\d@]+?)(?:@\w+)?', sender)
    if match:
        return match.group(1).strip()
    
    # 提取中文名称
    match = re.search(r'([一-鿿]{2,4})', sender)
    if match:
        return match.group(1)
    
    return sender[:20]


def parse_and_split_messages(messages: List[Dict]) -> List[Dict]:
    """
    完整流程：解析并分组消息
    按customer_name分组合并间隔<5分钟的连续消息
    
    参数:
        messages: 数据库中的原始消息列表
    返回:
        拆分后的消息列表
    """
    result = []
    
    for msg in messages:
        content = msg.get('content', '')
        customer_id = msg.get('customer_id', 0)
        
        # 解析微信聊天记录
        parsed_msgs = parse_wechat_messages(content)
        
        if not parsed_msgs:
            # 如果没有匹配到发送者标记，保留原消息
            result.append({
                'id': msg['id'],
                'customer_id': customer_id,
                'role': msg.get('role', 'unknown'),
                'content': content,
                'timestamp': msg.get('timestamp', ''),
                'session_id': msg.get('session_id', '')
            })
        else:
            # 添加解析后的消息
            for pmsg in parsed_msgs:
                result.append({
                    'id': msg['id'],
                    'customer_id': customer_id,
                    'role': pmsg['role'],
                    'sender': pmsg['sender'],
                    'clean_sender': pmsg['clean_sender'],
                    'content': pmsg['text'],
                    'timestamp': pmsg['timestamp'],
                    'session_id': msg.get('session_id', '')
                })
    
    return result


def group_consecutive_messages(messages: List[Dict], max_gap_minutes: int = 5) -> List[Dict]:
    """
    将连续的消息按客户分组合并（间隔小于max_gap_minutes的消息合并）
    
    参数:
        messages: 已解析的消息列表
        max_gap_minutes: 最大时间间隔（分钟）
    返回:
        分组后的消息列表
    """
    if not messages:
        return []
    
    # 按时间排序
    sorted_msgs = sorted(messages, key=lambda x: x.get('timestamp', ''))
    
    groups = []
    current_group = [sorted_msgs[0]]
    current_customer = sorted_msgs[0].get('customer_name') or sorted_msgs[0].get('clean_sender')
    
    for msg in sorted_msgs[1:]:
        msg_customer = msg.get('customer_name') or msg.get('clean_sender')
        msg_time = msg.get('timestamp', '')
        
        # 检查是否属于同一客户且时间间隔小于阈值
        if msg_customer == current_customer and current_group:
            # 计算时间间隔
            last_time = current_group[-1].get('timestamp', '')
            if last_time and msg_time:
                try:
                    t1 = datetime.strptime(last_time, '%Y-%m-%d %H:%M:%S')
                    t2 = datetime.strptime(msg_time, '%Y-%m-%d %H:%M:%S')
                    gap = (t2 - t1).total_seconds() / 60
                    
                    if gap <= max_gap_minutes:
                        current_group.append(msg)
                        continue
                except:
                    pass
        
        # 开启新组
        groups.append(current_group)
        current_group = [msg]
        current_customer = msg_customer
    
    # 添加最后一组
    if current_group:
        groups.append(current_group)
    
    # 合并每组消息
    result = []
    for group in groups:
        if len(group) == 1:
            result.append(group[0])
        else:
            # 合并多条消息
            first = group[0]
            combined = {
                **first,
                'content': '\n\n'.join(m['content'] for m in group),
                'timestamp': group[-1].get('timestamp', first.get('timestamp', ''))
            }
            result.append(combined)
    
    return result


if __name__ == '__main__':
    # 测试示例
    test_content = """张兆渊(🔥赛乐赛瘦身客服🔥未成年勿➕) 7/1 11:39:14
今天午饭就这一块肉吗[破涕为笑]

张兆渊(🔥赛乐赛瘦身客服🔥未成年勿➕) 7/1 11:39:38
碳水占了2/3，姐[破涕为笑]

A二26224黄信茹165.130.44@微信@微信联系人 7/1 11:45:21
没喜欢吃的

A二26224黄信茹165.130.44@微信@微信联系人 7/1 11:45:34
只能吃饼了"""
    
    print("=" * 70)
    print("📊 测试消息解析")
    print("=" * 70)
    
    messages = parse_wechat_messages(test_content)
    print(f"\n✅ 成功解析 {len(messages)} 条消息:")
    
    for i, msg in enumerate(messages, 1):
        print(f"\n--- 消息 {i} ---")
        print(f"  角色: {msg['role']}")
        print(f"  发送者: {msg['sender']}")
        print(f"  清理后: {msg['clean_sender']}")
        print(f"  时间: {msg['timestamp']}")
        print(f"  内容: {msg['text'][:50]}...")
    
    print("\n" + "=" * 70)
