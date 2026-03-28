"""
⏰ 매일 자동 스캔 스크립트
윈도우 작업 스케줄러로 매일 장 마감 후 실행하면
관심 종목 중 기회를 찾아서 텔레그램으로 알려줍니다.

사용법:
  python daily_scan.py

윈도우 작업 스케줄러 등록:
  1. 작업 스케줄러 열기 (시작 → "작업 스케줄러" 검색)
  2. "기본 작업 만들기" 클릭
  3. 이름: "주식AI 자동 스캔"
  4. 트리거: 매일, 오후 3:40 (장 마감 직후)
  5. 동작: 프로그램 시작
     프로그램: python
     인수: daily_scan.py
     시작 위치: C:\\Users\\user\\Desktop\\ai트레이닝\\stock-ai-api-v3\\stock-ai-api
  6. 완료!
"""

import asyncio
import httpx

API_URL = "http://localhost:8000"


async def daily_scan():
    print("=" * 50)
    print("  🔍 일일 자동 스캔 시작")
    print("=" * 50)

    async with httpx.AsyncClient(timeout=300) as client:

        # 1. 서버 상태 확인
        try:
            resp = await client.get(f"{API_URL}/")
            print(f"\n  ✅ 서버 연결 OK")
        except Exception:
            print(f"\n  ❌ 서버가 꺼져있습니다!")
            print(f"  주식AI.bat을 먼저 실행하세요.")
            return

        # 2. 빠른 스캔 (무료)
        print(f"\n  ⚡ 빠른 스캔 중 (기술적 분석만, 크레딧 무료)...")
        try:
            resp = await client.post(
                f"{API_URL}/scan/quick",
                json={"stock_codes": []},
                timeout=120,
            )
            data = resp.json().get("data", {})
            total = data.get("total_scanned", 0)
            buys = data.get("buy_signals", [])
            sells = data.get("sell_signals", [])

            print(f"  → {total}개 종목 스캔 완료")
            print(f"  → 매수 신호: {len(buys)}개, 매도 신호: {len(sells)}개")

            if buys:
                print(f"\n  🟢 매수 신호:")
                for b in buys[:5]:
                    print(f"     {b['stock_name']} ({b['현재가']:,}원) 점수: {b['tech_score']}")

            if sells:
                print(f"\n  🔴 매도 신호:")
                for s in sells[:5]:
                    print(f"     {s['stock_name']} ({s['현재가']:,}원) 점수: {s['tech_score']}")

        except Exception as e:
            print(f"  ❌ 빠른 스캔 실패: {e}")
            return

        # 3. 강한 신호가 있으면 풀 스캔 (크레딧 사용)
        if buys or sells:
            print(f"\n  🔍 풀 스캔 중 (뉴스 분석 + 텔레그램 알림)...")
            try:
                resp = await client.post(
                    f"{API_URL}/scan/full",
                    json={"stock_codes": []},
                    timeout=300,
                )
                full = resp.json().get("data", {})
                strong_buy = full.get("strong_buy", [])
                strong_sell = full.get("strong_sell", [])
                print(f"  → 후보 {full.get('candidates_analyzed', 0)}개 심층 분석")
                print(f"  → 강력 매수: {len(strong_buy)}개, 강력 매도: {len(strong_sell)}개")
                print(f"  → 텔레그램 알림 전송 완료!")
            except Exception as e:
                print(f"  ❌ 풀 스캔 실패: {e}")
        else:
            print(f"\n  📊 뚜렷한 신호 없음 — 풀 스캔 건너뜀 (크레딧 절약)")

        # 4. 성과 업데이트
        print(f"\n  📈 성과 업데이트 중...")
        try:
            resp = await client.post(f"{API_URL}/performance/update")
            perf = resp.json().get("data", {})
            print(f"  → {perf.get('updated', 0)}건 업데이트")
        except Exception as e:
            print(f"  → 건너뜀: {e}")

    print("\n" + "=" * 50)
    print("  ✅ 일일 스캔 완료!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(daily_scan())
