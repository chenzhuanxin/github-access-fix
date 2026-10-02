@echo off
chcp 65001 >nul
title GitHub 访问修复工具

:: ---------- 管理员检测 ----------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 请右键本文件, 选择"以管理员身份运行"。
    echo     (写 hosts 文件必须管理员权限)
    pause
    exit /b 1
)

:: ---------- 查找 Python ----------
set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE (
    echo [!] 本机未检测到 Python。
    echo.
    echo     方案一: 到 https://www.python.org/downloads/ 安装 Python 3,
    echo             安装时务必勾选 "Add python.exe to PATH", 然后重新运行本文件。
    echo.
    echo     方案二: 免装 Python —— 到本仓库 Releases 页下载 GitHubAccessFix.exe,
    echo             右键"以管理员身份运行"即可, 效果完全相同。
    echo.
    set /p go=按回车键退出...
    exit /b 1
)

echo 使用解释器: %PYEXE%
echo 运行修复脚本...
echo.
%PYEXE% "%~dp0GitHub访问修复.py" %*
echo.
set /p go=按回车键退出...
