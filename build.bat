@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "KEEP_SCREENSHOT_COUNT=3"

set "CON_CP="
for /f "tokens=2 delims=:" %%a in ('chcp') do set "CON_CP=%%a"
set "CON_CP=!CON_CP: =!"

set "USE_CN=0"
set "SYS_LANG="
for /f "tokens=3" %%a in ('reg query "HKCU\Control Panel\International" /v LocaleName 2^>nul ^| findstr /i "LocaleName"') do set "SYS_LANG=%%a"
if not defined SYS_LANG (
    for /f "tokens=3" %%a in ('reg query "HKCU\Control Panel\International" /v Locale 2^>nul ^| findstr /i "Locale"') do (
        if /i "%%a"=="0x804" set "SYS_LANG=zh-CN"
    )
)
if /i "!SYS_LANG:~0,2!"=="zh" set "USE_CN=1"
if "!CON_CP!"=="936" set "USE_CN=1"

if "!USE_CN!"=="1" chcp 936 >nul
if "!USE_CN!"=="1" (
    set "M_STEP_SYNC=正在同步依赖（uv sync --group dev）..."
    set "M_STEP_BUILD=正在使用 PyInstaller 构建，配置文件："
    set "M_STEP_PACK=构建后打包处理..."
    set "M_REMOVE_BUILD=正在删除 build 文件夹..."
    set "M_REMOVE_RELEASE=正在删除旧 release 文件夹..."
    set "M_RENAME=正在将 dist 改名为 release..."
    set "M_COPY=正在复制附加文件到"
    set "M_ERR_COPY=错误：复制 README.assets 失败。"
    set "M_DONE=构建完成。"
    set "M_OUT=输出文件夹："
    set "M_ERR_SPEC=错误：未找到 EFMI_Mod_Manager_v*.spec 构建配置文件，搜索目录："
    set "M_ERR_SYNC=错误：uv sync 失败。"
    set "M_ERR_BUILD=错误：PyInstaller 构建失败。"
    set "M_ERR_RM=错误：删除文件夹失败："
    set "M_ERR_REN=错误：无法将 dist 改名为 release。"
    set "M_ERR_APPDIR=错误：未找到 release\EFMI_Mod_Manager_v* 应用目录。"
    set "M_ZIP=正在压缩 ZIP 压缩包：
    set "M_ERR_ZIP=错误：ZIP 压缩失败。
) else (
    set "M_STEP_SYNC=Syncing dependencies with uv (uv sync --group dev)..."
    set "M_STEP_BUILD=Building with PyInstaller, spec file:"
    set "M_STEP_PACK=Post-build packaging..."
    set "M_REMOVE_BUILD=Removing build folder..."
    set "M_REMOVE_RELEASE=Removing old release folder..."
    set "M_RENAME=Renaming dist to release..."
    set "M_COPY=Copying assets to"
    set "M_ERR_COPY=ERROR: Failed to copy README.assets."
    set "M_DONE=Build completed successfully."
    set "M_OUT=Output folder:"
    set "M_ERR_SPEC=ERROR: Could not find EFMI_Mod_Manager_v*.spec, searched in:"
    set "M_ERR_SYNC=ERROR: uv sync failed."
    set "M_ERR_BUILD=ERROR: PyInstaller build failed."
    set "M_ERR_RM=ERROR: Failed to remove folder:"
    set "M_ERR_REN=ERROR: Failed to rename dist to release."
    set "M_ERR_APPDIR=ERROR: Could not find release\EFMI_Mod_Manager_v* app folder."
    set "M_ZIP=Creating ZIP archive:
    set "M_ERR_ZIP=ERROR: ZIP creation failed.
)

set "SPEC_FILE="
for %%f in (EFMI_Mod_Manager_v*.spec) do (
    if not defined SPEC_FILE set "SPEC_FILE=%%f"
)
if not defined SPEC_FILE (
    echo [ERROR] !M_ERR_SPEC! %~dp0
    exit /b 1
)

echo [1/4] !M_STEP_SYNC!
uv sync --group dev
if errorlevel 1 (
    echo [ERROR] !M_ERR_SYNC!
    exit /b 1
)

echo [2/4] !M_STEP_BUILD! !SPEC_FILE!
uv run pyinstaller "!SPEC_FILE!"
if errorlevel 1 (
    echo [ERROR] !M_ERR_BUILD!
    exit /b 1
)

echo [3/4] !M_STEP_PACK!
if exist "build" (
    echo !M_REMOVE_BUILD!
    rmdir /s /q "build"
    if errorlevel 1 (
        echo [ERROR] !M_ERR_RM! build
        exit /b 1
    )
)
if exist "release" (
    echo !M_REMOVE_RELEASE!
    rmdir /s /q "release"
    if errorlevel 1 (
        echo [ERROR] !M_ERR_RM! release
        exit /b 1
    )
)
echo !M_RENAME!
ren "dist" "release"
if errorlevel 1 (
    echo [ERROR] !M_ERR_REN!
    exit /b 1
)

set "APP_DIR="
set "APP_NAME="
for /d %%d in (release\EFMI_Mod_Manager_v*) do (
    if not defined APP_DIR (
        set "APP_DIR=%%d"
        set "APP_NAME=%%~nxd"
    )
)
if not defined APP_DIR (
    echo [ERROR] !M_ERR_APPDIR!
    exit /b 1
)

echo !M_COPY! !APP_DIR!
copy /y "app.ico" "!APP_DIR!\" >nul
copy /y "LICENSE" "!APP_DIR!\" >nul
copy /y "README.md" "!APP_DIR!\" >nul
copy /y "README_EN.md" "!APP_DIR!\" >nul
copy /y "THIRD_PARTY_NOTICES.txt" "!APP_DIR!\" >nul
if exist "licenses" (
    xcopy /e /i /y /q "licenses" "!APP_DIR!\licenses" >nul
)
if exist "locales" (
    xcopy /e /i /y /q "locales" "!APP_DIR!\locales" >nul
)
if exist "README.assets" (
    robocopy "README.assets" "!APP_DIR!\README.assets" /E ^
        /XF screenshot-*.png ^
        /NFL /NDL /NJH /NJS /NP
    if errorlevel 8 (
        echo [ERROR] !M_ERR_COPY!
        exit /b 1
    )
    for /l %%n in (1,1,!KEEP_SCREENSHOT_COUNT!) do (
        if exist "README.assets\screenshot-%%n.png" copy /y "README.assets\screenshot-%%n.png" "!APP_DIR!\README.assets\" >nul
    )
)

echo [4/4] !M_ZIP! !APP_NAME!
tar -a -c -f "!APP_DIR!.zip" -C "release" "!APP_NAME!"
if errorlevel 1 (
    echo [ERROR] !M_ERR_ZIP!
    exit /b 1
)

echo.
echo !M_DONE!
echo !M_OUT! %~dp0release
endlocal
