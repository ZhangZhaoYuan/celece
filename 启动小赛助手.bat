@echo off
chcp 65001 >nul
echo ===== 小赛助手启动器（正式版）=====
echo.

:: 关闭所有已启动的小赛助手服务
echo 正在关闭旧服务...
for /l %%p in (8800,1,8900) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p "') do (
    taskkill /f /pid %%a 2>nul
  )
)
timeout /t 1 /nobreak >nul

echo 正在启动小赛助手...
echo 访问地址: http://localhost:8800
echo.

:: 启动服务
start /B C:\Users\M\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe "D:\小赛助手\launcher.py"

:: 等待服务启动
timeout /t 3 /nobreak >nul

start http://localhost:8800

echo 小赛助手已启动！
echo.
pause >nul
exit