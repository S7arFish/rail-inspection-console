@echo off
setlocal enabledelayedexpansion
rem ===========================================================================
rem  Build the React SPA and stage it for Raspberry Pi production hosting.
rem  Saved as GBK for Chinese Windows consoles; comments stay ASCII.
rem
rem  Run on the Windows dev machine:  scripts\package-pi-web.bat
rem  Output: deploy\pi\web\  (committed to git; the Pi serves it via FastAPI)
rem  Nothing on the Pi needs Node or npm.
rem ===========================================================================

cd /d "%~dp0.."
set "ROOT=%CD%"
set "FRONTEND=%ROOT%\frontend"
set "DIST=%FRONTEND%\dist"
set "WEB=%ROOT%\deploy\pi\web"

echo ================================
echo  RIC Console Pi web 打包
echo ================================
echo.

if not exist "%FRONTEND%\package.json" (
  echo [错误] 找不到 frontend\package.json，请在项目根目录运行本脚本
  goto :fail
)

pushd "%FRONTEND%"

rem --- 1. dependencies ---------------------------------------------------------
if exist "node_modules\" (
  echo [1/5] 前端依赖已存在，跳过安装
) else if exist "package-lock.json" (
  echo [1/5] npm ci（按 package-lock.json 精确还原）
  call npm ci --no-audit --no-fund
  if errorlevel 1 (popd & echo [错误] npm ci 失败 & goto :fail)
) else (
  echo [1/5] npm install（无锁文件，使用 npm install）
  call npm install --no-audit --no-fund
  if errorlevel 1 (popd & echo [错误] npm install 失败 & goto :fail)
)

rem --- 2. production env guard -------------------------------------------------
findstr /C:"VITE_USE_MOCK=false" ".env.production" >nul 2>nul
if errorlevel 1 (
  popd
  echo [错误] frontend\.env.production 缺少 VITE_USE_MOCK=false，生产包不允许演示数据
  goto :fail
)
echo [2/5] 已确认 .env.production 中 VITE_USE_MOCK=false

rem --- 3. build -----------------------------------------------------------------
echo [3/5] npm run build（tsc -b + vite build）
call npm run build
if errorlevel 1 (popd & echo [错误] 前端构建失败 & goto :fail)
popd

if not exist "%DIST%\index.html" (
  echo [错误] 构建产物缺少 dist\index.html
  goto :fail
)

rem --- 4. stage into deploy/pi/web ---------------------------------------------
echo [4/5] 复制 dist 到 deploy\pi\web
if exist "%WEB%" rmdir /s /q "%WEB%"
if not exist "%WEB%" mkdir "%WEB%"
xcopy "%DIST%\*" "%WEB%\" /E /I /Y /Q >nul
if errorlevel 1 (
  echo [错误] 复制构建产物失败
  goto :fail
)

rem --- 5. verify ----------------------------------------------------------------
if not exist "%WEB%\index.html" (
  echo [错误] deploy\pi\web\index.html 不存在，打包未完成
  goto :fail
)
echo [5/5] 校验通过

echo.
echo ================================
echo  Pi web 打包完成
echo  产物目录：deploy\pi\web
echo  入口文件：deploy\pi\web\index.html
echo ================================
echo.
echo  下一步（Windows）：
echo    git add deploy/pi/web frontend/.env.production
echo    git commit -m "build: update pi web bundle"
echo    git push
echo.
echo  下一步（Raspberry Pi）：
echo    cd ~/rail-inspection-console ^&^& git pull --ff-only
echo    sudo bash ./scripts/pi-install.sh
echo.
echo  提示：deploy\pi\web 是构建产物，请只通过本脚本更新，不要手工编辑。
endlocal
exit /b 0

:fail
echo.
echo [失败] RIC Console Pi web 打包未完成，请查看上面的错误信息。
endlocal
exit /b 1
