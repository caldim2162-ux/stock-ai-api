@echo off
cd /d "%~dp0"

REM 환경변수는 .env 파일에서 자동으로 로드됩니다.
REM 키 설정 방법: .env.example 파일을 .env로 복사한 후 실제 값을 입력하세요.

if not exist .env (
    echo [오류] .env 파일이 없습니다.
    echo .env.example 파일을 .env로 복사한 후 API 키를 입력하세요.
    echo 예: copy .env.example .env
    pause
    exit /b 1
)

uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
