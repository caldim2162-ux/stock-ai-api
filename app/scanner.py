"""
🔍 자동 종목 스캐너
- 관심 종목 + 인기 종목을 자동 스캔합니다.
- 매수/매도 신호가 강한 종목만 필터링합니다.
- 텔레그램으로 결과를 알려줍니다.
- 매일 자동 실행하면 기회를 놓치지 않습니다.
"""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.kis_client import KISClient
from app.news_collector import NewsCollector
from app.news_sentiment import NewsSentimentAnalyzer
from app.auto_learner import AutoLearner
from app.signal_engine import SignalEngine
from app.knowledge_manager import KnowledgeManager
from app.telegram_bot import TelegramBot

WATCHLIST_FILE = Path(__file__).parent.parent / "data" / "watchlist.json"
SCAN_HISTORY_FILE = Path(__file__).parent.parent / "data" / "scan_history.json"

# ============================================================
# 🎯 기본 인기 종목 (코스피 대형주)
# ============================================================
DEFAULT_POPULAR = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
    {"code": "035420", "name": "NAVER"},
    {"code": "035720", "name": "카카오"},
    {"code": "005380", "name": "현대차"},
    {"code": "006400", "name": "삼성SDI"},
    {"code": "051910", "name": "LG화학"},
    {"code": "068270", "name": "셀트리온"},
    {"code": "373220", "name": "LG에너지솔루션"},
    {"code": "207940", "name": "삼성바이오로직스"},
    {"code": "005490", "name": "POSCO홀딩스"},
    {"code": "055550", "name": "신한지주"},
    {"code": "105560", "name": "KB금융"},
    {"code": "003670", "name": "포스코퓨처엠"},
    {"code": "247540", "name": "에코프로비엠"},
    {"code": "006800", "name": "미래에셋증권"},
    {"code": "003490", "name": "대한항공"},
    {"code": "028260", "name": "삼성물산"},
    {"code": "012330", "name": "현대모비스"},
    {"code": "066570", "name": "LG전자"},
]


class StockScanner:
    """관심 종목을 자동 스캔하여 기회를 찾습니다."""

    def __init__(
        self,
        kis: KISClient,
        knowledge: KnowledgeManager,
        learner: AutoLearner,
        telegram: TelegramBot,
    ):
        self.kis = kis
        self.knowledge = knowledge
        self.learner = learner
        self.telegram = telegram
        self.news = NewsCollector()
        self.sentiment = NewsSentimentAnalyzer()
        self.signal = SignalEngine()

    # ----------------------------------------------------------
    # 1) 관심 종목 관리
    # ----------------------------------------------------------
    def get_watchlist(self) -> list[dict]:
        """관심 종목 목록을 조회합니다."""
        try:
            if WATCHLIST_FILE.exists():
                with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def add_to_watchlist(self, stock_code: str, stock_name: str) -> list[dict]:
        """관심 종목을 추가합니다."""
        watchlist = self.get_watchlist()
        # 중복 체크
        if any(w["code"] == stock_code for w in watchlist):
            return watchlist
        watchlist.append({"code": stock_code, "name": stock_name})
        self._save_watchlist(watchlist)
        return watchlist

    def remove_from_watchlist(self, stock_code: str) -> list[dict]:
        """관심 종목을 제거합니다."""
        watchlist = self.get_watchlist()
        watchlist = [w for w in watchlist if w["code"] != stock_code]
        self._save_watchlist(watchlist)
        return watchlist

    def _save_watchlist(self, watchlist: list[dict]):
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(watchlist, f, ensure_ascii=False, indent=2)

    # ----------------------------------------------------------
    # 2) 빠른 스캔 (뉴스 감성만, 크레딧 절약)
    # ----------------------------------------------------------
    async def quick_scan(self, stocks: Optional[list[dict]] = None) -> dict:
        """
        빠른 스캔: 현재가 + 기술적 지표만 확인 (크레딧 안 듦)
        뉴스 감성 분석은 건너뛰고, 기술적 신호만으로 필터링합니다.
        """
        if stocks is None:
            stocks = self.get_watchlist() or DEFAULT_POPULAR

        results = []
        for stock in stocks:
            try:
                # 현재가 조회
                price = await self.kis.get_current_price(stock["code"])

                # 일봉 + 기술적 지표
                daily = await self.kis.get_daily_prices(stock["code"])
                indicators = self.learner._calculate_indicators(daily)

                # 기술적 신호만으로 점수 계산
                tech_result = self.signal._evaluate_technical(indicators, price)

                results.append({
                    "stock_code": stock["code"],
                    "stock_name": stock.get("name", price.get("종목명", stock["code"])),
                    "현재가": price.get("현재가", 0),
                    "등락률": price.get("등락률", ""),
                    "tech_score": tech_result["raw_score"],
                    "signals_positive": tech_result["positive"],
                    "signals_negative": tech_result["negative"],
                    "signal_count": len(tech_result["positive"]) + len(tech_result["negative"]),
                })
            except Exception as e:
                results.append({
                    "stock_code": stock["code"],
                    "stock_name": stock.get("name", ""),
                    "error": str(e),
                })

            # API 호출 제한 방지
            await asyncio.sleep(0.3)

        # 점수순 정렬
        valid = [r for r in results if "error" not in r]
        valid.sort(key=lambda r: r["tech_score"], reverse=True)

        # 강한 신호만 필터
        buy_signals = [r for r in valid if r["tech_score"] >= 15]
        sell_signals = [r for r in valid if r["tech_score"] <= -15]

        return {
            "scan_time": datetime.now().isoformat(),
            "total_scanned": len(stocks),
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "all_results": valid,
            "errors": [r for r in results if "error" in r],
            "mode": "quick (기술적 분석만, 크레딧 무료)",
        }

    # ----------------------------------------------------------
    # 3) 풀 스캔 (뉴스 + 기술 + AI, 크레딧 사용)
    # ----------------------------------------------------------
    async def full_scan(
        self,
        stocks: Optional[list[dict]] = None,
        score_threshold: int = 40,
    ) -> dict:
        """
        풀 스캔: 빠른 스캔으로 후보를 걸러낸 뒤,
        강한 신호가 있는 종목만 뉴스 분석 + AI 추천 (크레딧 절약)
        """
        # 1단계: 빠른 스캔으로 후보 필터
        quick = await self.quick_scan(stocks)
        candidates = [
            r for r in quick["all_results"]
            if abs(r["tech_score"]) >= 10 or r["signal_count"] >= 2
        ]

        if not candidates:
            # 신호가 약해도 상위 5개는 분석
            candidates = quick["all_results"][:5]

        # 2단계: 후보만 뉴스 감성 분석 (크레딧 사용)
        full_results = []
        for stock in candidates:
            try:
                code = stock["stock_code"]
                name = stock["stock_name"]

                # 뉴스 수집 + 감성 분석
                articles = await self.news.collect(code, name, max_articles=10)
                sentiment = await self.sentiment.analyze(articles, name, code)

                # 종합 점수 계산
                signal = self.signal.generate_signal(
                    news_sentiment=sentiment,
                    technical_indicators={"RSI_14": None},  # 이미 계산된 걸 활용
                    price_data={"현재가": stock["현재가"]},
                )

                # 기술 점수는 빠른 스캔 결과 사용
                total = round(
                    sentiment.get("overall_score", 0) * 100 * 0.4
                    + stock["tech_score"] * 0.6,
                    1
                )

                full_results.append({
                    "stock_code": code,
                    "stock_name": name,
                    "현재가": stock["현재가"],
                    "등락률": stock["등락률"],
                    "total_score": total,
                    "news_score": round(sentiment.get("overall_score", 0) * 100 * 0.4, 1),
                    "tech_score": round(stock["tech_score"] * 0.6, 1),
                    "news_sentiment": sentiment.get("overall_label", ""),
                    "recommendation": self._score_to_rec(total),
                    "key_positive": sentiment.get("key_positive", [])[:2],
                    "key_negative": sentiment.get("key_negative", [])[:2],
                    "tech_signals": stock["signals_positive"][:2] + stock["signals_negative"][:2],
                })
            except Exception as e:
                full_results.append({
                    "stock_code": stock["stock_code"],
                    "stock_name": stock["stock_name"],
                    "error": str(e),
                })

            await asyncio.sleep(0.5)

        # 점수순 정렬
        valid = [r for r in full_results if "error" not in r]
        valid.sort(key=lambda r: r["total_score"], reverse=True)

        # 강한 신호 필터
        strong_buy = [r for r in valid if r["total_score"] >= score_threshold]
        strong_sell = [r for r in valid if r["total_score"] <= -score_threshold]

        result = {
            "scan_time": datetime.now().isoformat(),
            "total_scanned": len(stocks or self.get_watchlist() or DEFAULT_POPULAR),
            "candidates_analyzed": len(candidates),
            "strong_buy": strong_buy,
            "strong_sell": strong_sell,
            "all_results": valid,
            "mode": f"full (뉴스+기술, 후보 {len(candidates)}개만 AI 분석)",
        }

        # 텔레그램 알림
        if self.telegram.is_configured and (strong_buy or strong_sell):
            await self._send_scan_telegram(result)

        # 스캔 이력 저장
        self._save_scan_history(result)

        return result

    # ----------------------------------------------------------
    # 텔레그램 알림
    # ----------------------------------------------------------
    async def _send_scan_telegram(self, result: dict):
        msg = f"🔍 <b>자동 스캔 완료</b> ({result['scan_time'][:16]})\n"
        msg += f"총 {result['total_scanned']}개 → 후보 {result['candidates_analyzed']}개 분석\n\n"

        if result["strong_buy"]:
            msg += "🟢 <b>매수 기회</b>\n"
            for r in result["strong_buy"][:5]:
                msg += f"  • {r['stock_name']} {r['현재가']:,}원 (점수 {r['total_score']})\n"
                if r.get("key_positive"):
                    msg += f"    ✅ {', '.join(r['key_positive'][:2])}\n"

        if result["strong_sell"]:
            msg += "\n🔴 <b>매도 주의</b>\n"
            for r in result["strong_sell"][:5]:
                msg += f"  • {r['stock_name']} {r['현재가']:,}원 (점수 {r['total_score']})\n"

        if not result["strong_buy"] and not result["strong_sell"]:
            msg += "📊 뚜렷한 매매 신호 없음 (관망)\n"

        msg += "\n자세한 분석은 대시보드에서 확인하세요."
        await self.telegram.send(msg)

    # ----------------------------------------------------------
    # 유틸
    # ----------------------------------------------------------
    @staticmethod
    def _score_to_rec(score: float) -> str:
        if score >= 70:
            return "강력 매수"
        elif score >= 30:
            return "매수 고려"
        elif score > -30:
            return "관망"
        elif score > -70:
            return "매도 고려"
        return "강력 매도"

    def _save_scan_history(self, result: dict):
        try:
            SCAN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            history = []
            if SCAN_HISTORY_FILE.exists():
                with open(SCAN_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            history.append({
                "time": result["scan_time"],
                "scanned": result["total_scanned"],
                "buy_count": len(result["strong_buy"]),
                "sell_count": len(result["strong_sell"]),
                "top_buy": result["strong_buy"][0]["stock_name"] if result["strong_buy"] else None,
                "top_sell": result["strong_sell"][0]["stock_name"] if result["strong_sell"] else None,
            })
            history = history[-100:]
            with open(SCAN_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def get_default_stocks() -> list[dict]:
        return DEFAULT_POPULAR
