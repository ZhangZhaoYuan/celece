# 企业微信桥接脚本配置指南

## 配置步骤

### 1. 在企业微信管理后台创建应用

1. 登录企业微信管理后台: https://work.weixin.qq.com/wework_admin/frame
2. 进入「应用管理」→「自建」→「创建应用」
3. 设置应用名称（如：小赛助手）
4. 上传应用图标
5. 记录以下信息:
   - **CorpID**: 我的企业 → 企业信息 → 企业ID
   - **AgentId**: 应用详情页的 AgentId
   - **Secret**: 应用详情页的 Secret

### 2. 配置回调URL

1. 在「应用详情」→「接收消息」→「设置API接收」
2. 填写回调URL: `http://你的公网IP:9000/callback`
3. 设置 Token 和 EncodingAESKey（可选）

### 3. 修改配置文件

编辑 `wecom_bridge.py` 文件，修改以下配置:

```python
WECOM_CORP_ID = "ww1234567890abcdef"  # 替换为你的 CorpID
WECOM_AGENT_ID = "1000001"             # 替换为你的 AgentId
WECOM_SECRET = "abcdefghijklmnop=="   # 替换为你的 Secret
WECOM_TOKEN = ""                       # 留空则不需要验证
WECOM_ENCODING_AES_KEY = ""            # 留空则不需要加密
```

### 4. 启动服务

```bash
cd D:\小赛助手
python wecom_bridge.py
```

### 5. 内网穿透（如果需要）

如果企业微信需要从公网访问，使用 ngrok 或其他内网穿透工具:

```bash
# 使用 ngrok
ngrok http 9000

# 将生成的公网URL配置到企业微信后台
# 例如: https://xxxx.ngrok.io/callback
```

## 工作流程

```
企业微信用户发消息
    ↓
企业微信服务器
    ↓
回调到 wecom_bridge.py (端口9000)
    ↓
提取用户ID和消息内容
    ↓
调用小赛助手API创建/查找客户
    ↓
写入消息到数据库
    ↓
生成话术并回复（后续扩展）
```

## 注意事项

1. 小赛助手需要在端口 8800 运行
2. 企业微信回调URL必须是公网可访问的地址
3. 如果使用内网穿透，确保穿透服务稳定运行
4. 日志文件保存在 `wecom_bridge.log`
