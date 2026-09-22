@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
rem ===========================================================================
rem  RIC Console environment checker (read-only).
rem  Saved as GBK so the Chinese output renders on a Chinese Windows console.
rem  Comments stay ASCII on purpose: cmd mis-parses non-ASCII in some paths.
rem  Usage: scripts\check-env.bat      exit 0 = pass, 1 = something is missing
rem  This script never installs anything and never edits PATH.
rem ===========================================================================

cd /d "%~dp0.."

set "FAIL=0"

echo ================================
echo  RIC Console 环境检查
echo  项目目录：%CD%
echo ================================
echo.
echo [工具检查]

call :check_tool git    "Git"
call :check_tool python "Python"
call :check_tool node   "Node.js"
call :check_tool npm    "npm"

echo.
echo [目录检查]
call :check_dir backend  "后端 FastAPI 源码"
call :check_dir frontend "前端 React + Vite 源码"
call :check_dir scripts  "脚本目录"
call :check_dir data     "SQLite 数据目录"
call :check_file frontend\package.json        "前端依赖清单"
call :check_file frontend\package-lock.json   "前端锁定文件（保证装出同样的版本）"
call :check_file backend\requirements.txt     "后端依赖清单"
call :check_file backend\requirements-dev.txt "测试依赖清单"
call :check_file backend\config\parser.yaml   "DHJ-9 字段映射配置"

echo.
echo [版本要求]
echo   Python   需要 3.10 及以上（fastapi / uvicorn / starlette 的要求）
echo            本项目实际验证版本：3.11.15
echo   Node.js  需要 20.19 及以上，或 22.12 及以上（Vite 8 的要求）
echo            本项目实际验证版本：22.23.2
echo   npm      随 Node.js 一起安装即可（本项目验证 12.0.2）
echo   Git      较新版本均可（本项目验证 2.54.0）
echo   操作系统  Windows 11 64 位为主，Windows 10 64 位同样可用

echo.
echo [提示]
echo   DHJ-9 真机还需要 Silicon Labs CP210x VCP 驱动。驱动是否就绪不在本脚本
echo   检查范围内，请按 docs\WINDOWS_SETUP_AND_DHJ9_TEST.md 第 4 节在设备
echo   管理器中确认。本脚本不会修改 PATH，也不会下载安装任何软件。

echo.
if not "%FAIL%"=="0" goto :report_fail

echo ================================
echo  环境检查通过
echo ================================
endlocal
exit /b 0

:report_fail
echo ================================
echo  环境检查失败：请处理上面标记为 [ERROR] 的项后重新运行
echo ================================
endlocal
exit /b 1

rem ---------------------------------------------------------------------------
rem  :check_tool <command> <display name>
:check_tool
where %~1 >nul 2>nul
if not errorlevel 1 goto :tool_present
echo [ERROR] 未找到 %~2，请先安装后重新运行
set "FAIL=1"
exit /b 0

:tool_present
set "VER="
for /f "delims=" %%v in ('%~1 --version 2^>^&1') do if not defined VER set "VER=%%v"
if not defined VER set "VER=已安装（未输出版本号）"
echo [OK] %~2: !VER!
exit /b 0

rem  :check_dir <relative path> <description>
:check_dir
if exist "%~1\" goto :dir_present
echo [ERROR] 缺少目录：%~1  （%~2）
set "FAIL=1"
exit /b 0

:dir_present
echo [OK] 目录存在：%~1  （%~2）
exit /b 0

rem  :check_file <relative path> <description>
:check_file
if exist "%~1" goto :file_present
echo [ERROR] 缺少文件：%~1  （%~2）
set "FAIL=1"
exit /b 0

:file_present
echo [OK] 文件存在：%~1  （%~2）
exit /b 0
