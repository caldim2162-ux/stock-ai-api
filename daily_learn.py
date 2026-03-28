"""
⏰ 매일 자동 학습 스크립트
crontab이나 tmux로 매일 장 마감 후 실행하면
관심 종목 데이터가 자동으로 지식 베이스에 축적됩니다.

사용법:
  python daily_learn.py

crontab 예시 (매일 16:00에 실행):
  0 16 * * 1-5 cd /path/to/stock-ai-api && python daily_learn.py
"""

import asyncio
import httpx
import json

API_URL = "http://localhost:8000"

# ============================================================
# 🎯 여기에 관심 종목을 등록하세요!
# ============================================================
WATCHLIST = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "035420",  # NAVER
    "035720",  # 카카오
    "006400",  # 삼성SDI
    "051910",  # LG화학
    "005380",  # 현대차
    "068270",  # 셀트리온
    "003670",  # 포스코퓨처엠
    "247540",  # 에코프로비엠
]


async def daily_learn():
    print("=" * 50)
    print(f"📈 일일 자동 학습 시작")
    print("=" * 50)

    async with httpx.AsyncClient(timeout=120) as client:

        # 1. 관심 종목 일괄 학습
        print(f"\n🧠 관심 종목 {len(WATCHLIST)}개 학습 중...")
        resp = await client.post(
            f"{API_URL}/learn/watchlist",
            json={"stock_codes": WATCHLIST},
        )
        data = resp.json()
        print(f"   → {data.get('message', '완료')}")

        # 2. 포트폴리오 학습
        print("\n💼 포트폴리오 학습 중...")
        try:
            resp = await client.post(f"{API_URL}/learn/portfolio")
            data = resp.json()
            if data.get("data", {}).get("status") == "learned":
                print(f"   → {data['data']['holdings_count']}개 보유종목 학습 완료")
            else:
                print(f"   → {data.get('data', {}).get('message', '완료')}")
        except Exception as e:
            print(f"   → 포트폴리오 학습 건너뜀: {e}")

        # 3. 거래량 동향 학습 (관심 종목 상위 5개만)
        print("\n📊 거래량 동향 학습 중...")
        for code in WATCHLIST[:5]:
            try:
                resp = await client.post(
                    f"{API_URL}/learn/trend",
                    json={"stock_code": code},
                )
                data = resp.json()
                stock = data.get("data", {}).get("stock", code)
                print(f"   → {stock} 거래량 동향 학습 완료")
            except Exception as e:
                print(f"   → {code} 실패: {e}")

        # 4. 학습 결과 확인
        print("\n📚 현재 지식 베이스 현황:")
        resp = await client.get(f"{API_URL}/knowledge")
        data = resp.json()
        print(f"   총 지식 수: {data.get('total', 0)}개")
        cats = data.get("categories", {}).get("categories", {})
        for cat_key, cat_info in cats.items():
            print(f"   - {cat_info['name']}: {cat_info['count']}개")

    print("\n" + "=" * 50)
    print("✅ 일일 학습 완료!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(daily_learn())
