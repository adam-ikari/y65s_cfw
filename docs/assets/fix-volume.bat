@echo off
chcp 65001 >nul
title YD-Y65S 一键修复音量条
cd /d "%~dp0"
echo.
echo   正在修复屏幕上的音量条，请不要拔掉键盘的 USB 线。
echo   过程：读出固件 -^> 备份 -^> 打补丁 -^> 写入 -^> 读回校验
echo.
y65s.exe fix-volume
echo.
pause
