# 네이버 사이트 자동 신고 프로그램

카드깡 / 신용카드현금화 관련 사이트를 네이버 고객센터에 신고할 때, GPT로 신고 문구를 리라이트하고 Selenium으로 폼을 자동 입력합니다.

> 순위체크 프로그램(`naver-rank-checker`)과 **별도 폴더**로 분리되어 있습니다.

## 요구 사항

- Python 3.10+
- Google Chrome (Selenium용)

## 설치

```powershell
cd C:\Users\thdco\naver-report-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 실행

```powershell
python run.py
```

또는 `start.bat` / `release\NaverReport\NaverReport.exe` (빌드 후)

## 설정 파일

| 파일 | 설명 |
|------|------|
| `settings.json` | OpenAI API Key, GPT 모델 |
| `accounts.json` | 네이버 로그인 계정 목록 |
| `tasks.json` | 신고 대상 사이트·유형·원본 문구 |
| `results.json` | 리라이트 결과 저장 (자동 생성) |
| `data/templates.json` | 신고 원본 템플릿 |

처음 설정 시 `*.example` 파일을 참고하여 `settings.json`, `accounts.json`을 만드세요.

## EXE 빌드

```bat
build.bat
```

결과: `release\NaverReport\` 폴더 전체를 배포 (exe만 따로 복사하지 마세요).

## GitHub 배포 (자동 업데이트)

```bat
deploy.bat
```

또는 `.\scripts\publish.ps1 -Notes "변경 내용"`

## 주요 기능

- **Home**: 신고 항목 등록/삭제, 사이트별 신고 집계
- **리라이트 결과**: GPT 변형 결과 조회·수정·삭제
- **Settings**: API Key, 네이버 계정 관리 (대량 등록)
- **실행 로그**: 자동 신고 진행 상황, Hagrid(헤드리스) 모드
- **신고 원본**: `templates.json` 기반 원본 문구 관리

## 구조

- `app.py` — CustomTkinter GUI
- `naver_reporter.py` — Selenium 로그인·폼 작성·CAPTCHA(GPT Vision)
- `run.py` — 실행 진입점
- `updater.py` / `update_ui.py` — GitHub 자동 업데이트
