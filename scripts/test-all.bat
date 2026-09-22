@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
rem ===========================================================================
rem  RIC Console full check: backend pytest, then tsc, then vite build.
rem  Saved as GBK so the Chinese output renders on a Chinese Windows console.
rem  Stops on the first failure and returns a non-zero exit code.
rem  Nothing is hidden and nothing is installed by this script.
rem ===========================================================================

cd /d "%~dp0.."
set "ROOT=%CD%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "VENV_PY=%BACKEND%\.venv\Scripts\python.exe"

echo ================================
echo  RIC Console 全项目检查
echo  项目目录：%CD%
echo ================================
echo.

if exist "%VENV_PY%" goto :run_pytest
echo [错误] 未找到后端虚拟环境：%VENV_PY%
echo        请先运行 scripts\dev.bat install 安装依赖后重试
goto :fail

:run_pytest
echo [1/3] 后端测试（pytest）
pushd "%BACKEND%"
"%VENV_PY%" -m pytest
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" goto :fail_pytest
echo [OK] 后端测试通过
echo.

if exist "%FRONTEND%\node_modules\" goto :run_tsc
echo [错误] 未找到前端依赖：%FRONTEND%\node_modules
echo        请先运行 scripts\dev.bat install 安装依赖后重试
goto :fail

:run_tsc
echo [2/3] 前端类型检查（tsc -b）
pushd "%FRONTEND%"
call npx tsc -b
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" goto :fail_tsc
echo [OK] 前端类型检查通过
echo.

echo [3/3] 前端构建（vite build）
pushd "%FRONTEND%"
call npx vite build
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" goto :fail_build
echo [OK] 前端构建通过
echo.

echo ================================
echo  RIC Console 全部检查通过
echo  Backend tests: PASS
echo  TypeScript: PASS
echo  Vite build: PASS
echo ================================
endlocal
exit /b 0

:fail_pytest
echo [错误] 后端测试未通过（上面是 pytest 的完整输出），已停止。
goto :fail

:fail_tsc
echo [错误] 前端类型检查未通过（上面是 tsc 的完整输出），已停止。
goto :fail

:fail_build
echo [错误] 前端构建失败（上面是 vite build 的完整输出），已停止。
goto :fail

:fail
echo.
echo ================================
echo  RIC Console 检查未通过
echo ================================
endlocal
exit /b 1
