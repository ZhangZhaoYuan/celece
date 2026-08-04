@echo off
chcp 65001 >nul
echo ===== Xiao Sai Helper =====
echo.

echo Killing old services...
for /l %%p in (8800,1,8900) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p "') do (
    taskkill /f /pid %%a >nul 2>nul
  )
)
timeout /t 1 /nobreak >nul

echo Starting Xiao Sai Helper...
echo.
echo Visit: http://localhost:8800
echo.

start "" /B "C:\Users\M\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" "D:\小赛助手\launcher.py"

timeout /t 3 /nobreak >nul

start "" "http://localhost:8800"

echo Done! Browser should open automatically.
echo.
echo Press any key to close this window...
pause >nul
exit