@echo off
chcp 936 >nul
setlocal enabledelayedexpansion

rem ===========================================================================
rem  RIC Console (轨道检测车综合检测中控平台) — Windows dev launcher
rem
rem    scripts\dev.bat            start backend + frontend, installing on demand
rem    scripts\dev.bat install    (re)install dependencies, do not start servers
rem    scripts\dev.bat backend    backend only
rem    scripts\dev.bat frontend   frontend only
rem
rem  Ports: override with RIC_DEV_PORT_API / RIC_DEV_PORT_WEB before launching.
rem ===========================================================================

cd /d "%~dp0.."
set "ROOT=%CD%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "VENV=%BACKEND%\.venv"
set "PY=%VENV%\Scripts\python.exe"

set "API_PORT=%RIC_DEV_PORT_API%"
if "%API_PORT%"=="" set "API_PORT=8000"
set "WEB_PORT=%RIC_DEV_PORT_WEB%"
if "%WEB_PORT%"=="" set "WEB_PORT=5173"

if /I "%~1"=="install"  goto :install
if /I "%~1"=="backend"  goto :run_backend
if /I "%~1"=="frontend" goto :run_frontend

call :ensure_backend || goto :fail
call :ensure_frontend || goto :fail
goto :start_both

rem ---------------------------------------------------------------------------
:start_both
echo.
echo  [run] backend  http://127.0.0.1:%API_PORT%   (OpenAPI: /docs)
start "RIC Backend" cmd /k "cd /d "%BACKEND%" && "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT% --reload"

echo  [run] frontend http://localhost:%WEB_PORT%
start "RIC Frontend" cmd /k "cd /d "%FRONTEND%" && set "VITE_API_PROXY_TARGET=http://127.0.0.1:%API_PORT%" && call npm run dev -- --port %WEB_PORT%"

echo.
echo  Two console windows were opened; close them to stop.
echo  The frontend stays on mock data unless frontend\.env sets VITE_USE_MOCK=false
exit /b 0

:run_backend
call :ensure_backend || goto :fail
echo  [run] backend only — http://127.0.0.1:%API_PORT%
cd /d "%BACKEND%"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT% --reload
exit /b 0

:run_frontend
call :ensure_frontend || goto :fail
echo  [run] frontend only — http://localhost:%WEB_PORT%
cd /d "%FRONTEND%"
set "VITE_API_PROXY_TARGET=http://127.0.0.1:%API_PORT%"
call npm run dev -- --port %WEB_PORT%
exit /b 0

:install
call :ensure_backend || goto :fail
call :pip_install || goto :fail
call :ensure_frontend || goto :fail
call :npm_install || goto :fail
echo  [ok] dependencies installed
exit /b 0

rem ---------------------------------------------------------------------------
:ensure_backend
if not exist "%PY%" (
  echo  [setup] 正在创建后端虚拟环境：%VENV%
  where python >nul 2>nul || (echo  [错误] 未找到 python 命令，请先安装 Python 3.10+ 并运行 scripts\check-env.bat 检查 & exit /b 1)
  python -m venv "%VENV%" || exit /b 1
  call :pip_install || exit /b 1
)
exit /b 0

:pip_install
echo  [setup] pip install -r backend\requirements.txt
"%PY%" -m pip install --disable-pip-version-check -q -r "%BACKEND%\requirements.txt" || exit /b 1
exit /b 0

:ensure_frontend
call :ensure_web_env || exit /b 1
if not exist "%FRONTEND%\node_modules\" call :npm_install || exit /b 1
exit /b 0

rem First run on a new machine: give the frontend its own .env to edit.
rem An existing .env is never touched, so local overrides survive.
:ensure_web_env
if exist "%FRONTEND%\.env" exit /b 0
if not exist "%FRONTEND%\.env.example" (
  echo  [错误] 缺少 frontend\.env.example，无法生成配置文件
  exit /b 1
)
copy /y "%FRONTEND%\.env.example" "%FRONTEND%\.env" >nul || exit /b 1
echo  [setup] 已从 .env.example 创建 frontend\.env（默认 VITE_USE_MOCK=true 演示模式）
echo         真机测试前请把 VITE_USE_MOCK 改为 false；本脚本不会覆盖你改过的 .env
exit /b 0

:npm_install
echo  [setup] npm install in frontend
pushd "%FRONTEND%"
call npm install --no-audit --no-fund || (popd & exit /b 1)
popd
exit /b 0

rem ---------------------------------------------------------------------------
:fail
echo.
echo  [error] dev launcher stopped. See the messages above.
exit /b 1
