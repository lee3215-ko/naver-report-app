# 네이버 사이트 자동 신고 프로그램

카드깡 / 신용카드현금화 관련 사이트를 네이버 고객센터에 신고할 때, GPT로 신고 문구를 리라이트하고 Selenium으로 폼을 자동 입력합니다.

## 요구 사항

- Python 3.10+
- Google Chrome (Selenium용)

## 설치

```powershell
cd naver-report-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 실행

```powershell
python run.py
```

## 설정 파일

| 파일 | 설명 |
|------|------|
| `settings.json` | OpenAI API Key, GPT 모델 |
| `accounts.json` | 네이버 로그인 계정 목록 |
| `tasks.json` | 신고 대상 사이트·유형·원본 문구 |
| `results.json` | 리라이트 결과 저장 (자동 생성) |

처음 설정 시 `*.example` 파일을 참고하여 `settings.json`, `accounts.json`을 만드세요.

## 주요 기능

- **Home**: 고정 신고 원본 편집, 신고 항목 등록/삭제
- **리라이트 결과**: GPT 변형 결과 조회·수정·삭제
- **Settings**: API Key, 네이버 계정 관리
- **실행 로그**: 자동 신고 진행 상황

## 구조

- `app.py` — Tkinter/CustomTkinter GUI
- `naver_reporter.py` — Selenium 로그인·폼 작성·CAPTCHA(GPT Vision)
- `run.py` — 실행 진입점 (작업 디렉터리 자동 설정)
