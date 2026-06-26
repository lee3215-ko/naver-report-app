@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Naver Report - EXE 빌드
echo ============================================

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] 가상환경 생성...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [2/4] 패키지 설치...
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q pyinstaller pillow

echo [3/4] 아이콘 생성 및 PyInstaller 빌드...
python make_icon.py
pyinstaller --noconfirm --clean build.spec
if errorlevel 1 (
    echo 빌드 실패
    exit /b 1
)

echo [4/4] 배포 폴더 준비...
set "RELEASE=release\NaverReport"
if exist "release" rmdir /s /q "release"
mkdir "%RELEASE%"
xcopy /E /I /Y "dist\NaverReport\*" "%RELEASE%\"

if not exist "%RELEASE%\data" mkdir "%RELEASE%\data"
if exist "data\templates.json" copy /Y "data\templates.json" "%RELEASE%\data\templates.json"

> "%RELEASE%\실행.bat" echo @echo off
>> "%RELEASE%\실행.bat" echo cd /d "%%~dp0"
>> "%RELEASE%\실행.bat" echo start "" "NaverReport.exe"

echo.
echo ============================================
echo  빌드 완료
echo  배포: release\NaverReport 폴더 전체를 복사
echo    - NaverReport.exe 실행
echo    - _internal 폴더는 반드시 exe와 함께 유지
echo    - data\ 폴더에 설정/계정 저장
echo  대상 PC에 Google Chrome 설치 필요
echo ============================================
pause
