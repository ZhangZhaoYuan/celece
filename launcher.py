"""
小赛助手 - PyInstaller 启动入口
"""
import os
import sys
from pathlib import Path

# 设置控制台编码，防止 emoji 在 GBK 控制台下报错
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 确定基准目录（exe 所在位置）
if getattr(sys, 'frozen', False):
    # PyInstaller --onefile 模式下，数据解压在 sys._MEIPASS 指向的临时目录
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

# ===== 冻结模式 vs 开发模式的路径处理 =====
# --onefile 模式下，PyInstaller 把 datas 解压到临时目录根目录（_MEIxxxxx/）
# 不像 --onedir 有 _internal/ 子目录
if getattr(sys, 'frozen', False):
    DATA_ROOT = BASE_DIR / "data"
    FRONTEND_ROOT = BASE_DIR / "frontend"
    (DATA_ROOT / "knowledge").mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "chunks").mkdir(parents=True, exist_ok=True)
else:
    DATA_ROOT = BASE_DIR / "data"
    FRONTEND_ROOT = BASE_DIR / "frontend"
    (BASE_DIR / "data" / "knowledge").mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "data" / "chunks").mkdir(parents=True, exist_ok=True)

# 修复 frontend 路径
os.chdir(str(BASE_DIR))

# 添加 backend 目录到路径
# --onefile 模式：backend/ 在临时目录根目录
if getattr(sys, 'frozen', False):
    sys.path.insert(0, str(BASE_DIR / "backend"))
else:
    sys.path.insert(0, str(BASE_DIR / "backend"))

# ===== 关键修复：让所有用 __file__ 定位路径的模块找到正确位置 =====
# PyInstaller 打包后 __file__ 指向 _internal/，BASE_DIR 会错
# 这里直接修改各模块的 BASE_DIR 指向正确路径

import config_manager
config_manager.BASE_DIR = DATA_ROOT.parent
config_manager.DATA_DIR = DATA_ROOT
config_manager.CONFIG_FILE = DATA_ROOT / "config.json"

import database
database.BASE_DIR = DATA_ROOT.parent
database.DATA_DIR = DATA_ROOT
database.DB_PATH = DATA_ROOT / "customers.db"

import knowledge
knowledge.BASE_DIR = DATA_ROOT.parent
knowledge.DATA_DIR = DATA_ROOT
knowledge.KNOWLEDGE_DIR = DATA_ROOT / "knowledge"
knowledge.DB_PATH = DATA_ROOT / "customers.db"

import backend.main
backend.main.FRONTEND_DIR = FRONTEND_ROOT

# 启动服务
backend.main.start_server()