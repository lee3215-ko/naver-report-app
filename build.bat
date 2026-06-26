@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q pyinstaller pillow

python make_icon.py
pyinstaller --noconfirm --clean build.spec
if errorlevel 1 exit /b 1

set "RELEASE=release\NaverReport"
if exist "release" rmdir /s /q "release"
mkdir "%RELEASE%"
xcopy /E /I /Y "dist\NaverReport\*" "%RELEASE%\" >nul

if not exist "%RELEASE%\data" mkdir "%RELEASE%\data"
if exist "data\templates.json" copy /Y "data\templates.json" "%RELEASE%\data\templates.json" >nul

> "%RELEASE%\실행.bat" echo @echo off
>> "%RELEASE%\실행.bat" echo cd /d "%%~dp0"
>> "%RELEASE%\실행.bat" echo start "" "NaverReport.exe"

endlocal
