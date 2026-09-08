"""
企业微信桥接脚本
将企业微信消息同步到 Hermes 小赛助手

配置方法:
1. 在企业微信管理后台创建应用
2. 获取 CorpID, AgentId, Secret
3. 修改下面的配置
4. 运行: python wecom_bridge.py
"""

import os
import sys
import json
import hashlib
import hmac
import base64
import time
import logging
from datetime import datetime
from pathlib import Path

# 配置
CORS_URLS = ["http://localhost:8800", "http://127.0.0.1:8800"]
API_BASE_URL = "http://127.0.0.1:8800"

# 企业微信凭证 - 请修改这些值
WECOM_CORP_ID = "YOUR_CORP_ID"
WECOM_AGENT_ID = "YOUR_AGENT_ID"
WECOM_SECRET = "YOUR_SECRET"
WECOM_TOKEN = ""  # 回调验证Token，留空则不需要验证
WECOM_ENCODING_AES_KEY = ""  # 消息加密Key，留空则不需要加密

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("wecom_bridge.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 内存存储消息队列
message_queue = []
user_cache = {}  # userid -> customer_id 映射


def get_wecom_token():
    """获取企业微信 access_token"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_SECRET}"
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "access_token" in data:
                logger.info(f"获取 access_token 成功")
                return data["access_token"]
            else:
                logger.error(f"获取 token 失败: {data}")
                return None
    except Exception as e:
        logger.error(f"获取 token 异常: {e}")
        return None


def get_user_info(access_token, userid):
    """获取用户信息"""
    url = f"https://qyapi.weixin.qq.com/cgi-bin/user/get?access_token={access_token}&userid={userid}"
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"获取用户信息失败: {e}")
        return None


def sync_to_xiaosai(userid, content, username=None):
    """同步消息到小赛助手"""
    import urllib.request
    
    # 先查找或创建客户
    try:
        # 获取客户列表
        req = urllib.request.Request(f"{API_BASE_URL}/api/customers")
        with urllib.request.urlopen(req, timeout=10) as resp:
            customers_data = json.loads(resp.read().decode("utf-8"))
            customers = customers_data.get("customers", [])
        
        # 查找匹配的客户
        customer = None
        for c in customers:
            if c.get("weixin_id") == userid or c.get("phone") == userid:
                customer = c
                break
        
        # 如果没找到，创建新客户
        if not customer:
            customer_data = {
                "name": username or userid,
                "weixin_id": userid
            }
            req = urllib.request.Request(
                f"{API_BASE_URL}/api/customers",
                data=json.dumps(customer_data).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                customer = json.loads(resp.read().decode("utf-8")).get("customer")
            
            logger.info(f"创建新客户: {customer.get('name')} (ID: {customer.get('id')})")
        
        # 写入消息
        msg_data = {
            "role": "user",
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        req = urllib.request.Request(
            f"{API_BASE_URL}/api/customers/{customer['id']}/messages",
            data=json.dumps(msg_data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        
        logger.info(f"消息已同步到客户 {customer['name']} (ID: {customer['id']})")
        return customer["id"]
        
    except Exception as e:
        logger.error(f"同步消息失败: {e}")
        return None


def handle_message(userid, content):
    """处理收到的消息"""
    logger.info(f"收到消息: userid={userid}, content={content[:50]}...")
    
    # 同步到小赛助手
    customer_id = sync_to_xiaosai(userid, content)
    
    if customer_id:
        # 这里可以调用 Hermes 生成话术并回复
        # 简单实现：直接返回确认消息
        return f"消息已收到，正在为您生成回复..."
    else:
        return "处理消息时出错"


def verify_signature(timestamp, nonce, signature):
    """验证企业微信签名"""
    if not WECOM_TOKEN:
        return True
    sorted_params = sorted([WECOM_TOKEN, timestamp, nonce])
    string = "".join(sorted_params)
    sha1 = hashlib.sha1(string.encode("utf-8")).hexdigest()
    return sha1 == signature


def create_webhook_server():
    """创建 Webhook 服务器接收企业微信回调"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse
    
    class WeComHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            """处理验证请求"""
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                params = urllib.parse.parse_qs(parsed.query)
                signature = params.get("signature", [""])[0]
                timestamp = params.get("timestamp", [""])[0]
                nonce = params.get("nonce", [""])[0]
                echostr = params.get("echostr", [""])[0]
                
                if verify_signature(timestamp, nonce, signature):
                    self.send_response(200)
                    self.send_header("Content-type", "text/plain")
                    self.end_headers()
                    self.wfile.write(echostr.encode("utf-8"))
                    logger.info("回调验证成功")
                else:
                    self.send_response(403)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
        
        def do_POST(self):
            """处理消息回调"""
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                
                # 解析 XML 消息
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(body)
                    userid = root.findtext(".//ToUserName")
                    content = root.findtext(".//Content")
                    msg_type = root.findtext(".//MsgType")
                    
                    if msg_type == "text" and content:
                        logger.info(f"收到文本消息: {userid} - {content}")
                        handle_message(userid, content)
                    
                    self.send_response(200)
                    self.send_header("Content-type", "text/xml")
                    self.end_headers()
                    resp_xml = "<xml><ToUserName><![CDATA[]]></ToUserName><FromUserName><![CDATA[]]></FromUserName><CreateTim>0</CreateTim><MsgType><![CDATA[text]]></MsgType><Content><![CDATA[消息已接收]]></Content></xml>"
                    self.wfile.write(resp_xml.encode("utf-8"))
                except Exception as e:
                    logger.error(f"解析消息失败: {e}")
                    self.send_response(500)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            logger.debug(f"{self.address_string()} - {format % args}")
    
    return WeComHandler


def main():
    """主函数"""
    logger.info("="*50)
    logger.info("企业微信桥接脚本启动")
    logger.info(f"CorpID: {WECOM_CORP_ID[:8]}...")
    logger.info(f"AgentId: {WECOM_AGENT_ID}")
    logger.info(f"回调地址: 请在企业微信后台配置")
    logger.info("="*50)
    
    # 验证配置
    if WECOM_CORP_ID == "YOUR_CORP_ID":
        logger.error("请先配置 CorpID!")
        return
    
    if WECOM_AGENT_ID == "YOUR_AGENT_ID":
        logger.error("请先配置 AgentId!")
        return
    
    if WECOM_SECRET == "YOUR_SECRET":
        logger.error("请先配置 Secret!")
        return
    
    # 测试获取 token
    token = get_wecom_token()
    if not token:
        logger.error("无法获取 access_token，请检查凭证是否正确")
        return
    
    # 创建服务器
    handler = create_webhook_server()
    server = HTTPServer(("0.0.0.0", 9000), handler)
    
    logger.info("Webhook 服务器启动在端口 9000")
    logger.info("请在企业微信后台配置回调 URL: http://你的公网IP:9000/callback")
    logger.info("按 Ctrl+C 停止服务")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
