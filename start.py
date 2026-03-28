"""
📈 서버 시작 스크립트 (Windows / Mac / Linux 모두 지원)

사용법:
  python start.py
"""

import os
import sys
from pathlib import Path


def load_env():
    """프로젝트 루트의 .env 파일에서 환경변수를 읽어옵니다."""
    env_file = Path(__file__).parent / ".env"

    if not env_file.exists():
        print("=" * 55)
        print("  ⚠️  .env 파일이 없습니다!")
        print("=" * 55)
        print()
        print("  아래 순서대로 설정해주세요:")
        print()
        print("  1. .env.example 파일을 복사해서 .env로 이름 변경")
        print("     Windows CMD:  copy .env.example .env")
        print("     Mac/Linux:    cp .env.example .env")
        print()
        print("  2. .env 파일을 메모장으로 열어서 API 키 입력")
        print("     Windows CMD:  notepad .env")
        print()
        print("  3. 다시 실행:  python start.py")
        print()
        print("=" * 55)
        sys.exit(1)

    loaded = 0
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if value and value not in ("your-app-key-here", "your-app-secret-here",
                                           "sk-ant-your-key-here", "your-naver-client-id",
                                           "your-naver-client-secret", "00000000-01"):
                    os.environ[key] = value
                    loaded += 1

    return loaded


def check_keys():
    """필수 API 키가 설정되었는지 확인합니다."""
    print()
    print("=" * 55)
    print("  📈 나만의 주식 매매 추천 AI API v3")
    print("=" * 55)
    print()

    checks = [
        ("ANTHROPIC_API_KEY", "Claude AI (분석용)", True),
        ("KIS_APP_KEY", "한투 API (시세용)", True),
        ("KIS_APP_SECRET", "한투 API (시크릿)", True),
        ("KIS_ACCOUNT_NO", "한투 계좌번호", False),
        ("NAVER_CLIENT_ID", "네이버 뉴스 API", False),
        ("NAVER_CLIENT_SECRET", "네이버 뉴스 시크릿", False),
    ]

    all_ok = True
    for key, name, required in checks:
        value = os.getenv(key, "")
        if value:
            masked = value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
            print(f"  ✅ {name}: {masked}")
        elif required:
            print(f"  ❌ {name}: 미설정 (필수!)")
            all_ok = False
        else:
            print(f"  ⬜ {name}: 미설정 (선택사항)")

    print()

    if not all_ok:
        print("  ❌ 필수 API 키가 설정되지 않았습니다.")
        print("  .env 파일을 열어서 키를 입력해주세요.")
        print("  (데모 모드로 일부 기능은 작동합니다)")
        print()

    return all_ok


def main():
    # 1. .env 파일 로드
    loaded = load_env()
    print(f"  .env에서 {loaded}개 환경변수 로드")

    # 2. 키 확인
    check_keys()

    # 3. 서버 실행
    print("  🚀 서버 시작 중...")
    print("  📖 API 문서: http://localhost:8000/docs")
    print("  🎯 매매 추천: POST http://localhost:8000/recommend")
    print()
    print("  종료하려면 Ctrl+C")
    print("=" * 55)
    print()

    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
