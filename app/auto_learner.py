"""
🧠 자동 학습기 (Auto Learner)
- 한투 API에서 데이터를 가져와 기술적 지표를 계산하고
- 지식 베이스에 자동 등록합니다.
- PPT 설계 기반 고급 Feature Engineering 적용
"""

from datetime import datetime
from typing import Optional

from app.kis_client import KISClient
from app.knowledge_manager import KnowledgeManager
from app.feature_builder import FeatureBuilder


class AutoLearner:

    def __init__(self, kis: KISClient, knowledge: KnowledgeManager):
        self.kis = kis
        self.knowledge = knowledge
        self.fb = FeatureBuilder()

    # ----------------------------------------------------------
    # 1) 종목 스냅샷 학습
    # ----------------------------------------------------------
    async def learn_stock_snapshot(self, stock_code: str) -> dict:
        price = await self.kis.get_current_price(stock_code)
        daily = await self.kis.get_daily_prices(stock_code)
        indicators = self._calculate_indicators(daily)

        stock_name = price.get("종목명", stock_code)
        content = self._build_snapshot_content(price, indicators)

        entry = self.knowledge.add({
            "category": "indicator",
            "title": f"[{stock_name}] 시장 데이터 스냅샷 ({datetime.now().strftime('%Y-%m-%d')})",
            "content": content,
            "tags": [stock_name, stock_code, "현재가", "기술적분석", "자동학습"],
        })

        return {
            "status": "learned",
            "stock": stock_name,
            "price": price,
            "indicators": indicators,
            "knowledge_id": entry["id"],
        }

    # ----------------------------------------------------------
    # 2) 거래량/투자자 동향 학습
    # ----------------------------------------------------------
    async def learn_investor_trend(self, stock_code: str) -> dict:
        price = await self.kis.get_current_price(stock_code)
        stock_name = price.get("종목명", stock_code)
        daily = await self.kis.get_daily_prices(stock_code)
        vol_analysis = self._analyze_volume(daily)

        content = (
            f"종목: {stock_name} ({stock_code})\n"
            f"현재가: {price['현재가']:,}원 ({price['등락률']})\n\n"
            f"[거래량 분석]\n{vol_analysis}\n\n"
            f"분석 시점: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

        entry = self.knowledge.add({
            "category": "pattern",
            "title": f"[{stock_name}] 거래량 동향 ({datetime.now().strftime('%Y-%m-%d')})",
            "content": content,
            "tags": [stock_name, stock_code, "거래량", "자동학습"],
        })

        return {"status": "learned", "stock": stock_name, "knowledge_id": entry["id"]}

    # ----------------------------------------------------------
    # 3) 포트폴리오 학습
    # ----------------------------------------------------------
    async def learn_portfolio(self) -> dict:
        balance = await self.kis.get_balance()
        if not balance["보유종목"]:
            return {"status": "empty", "message": "보유 종목이 없습니다."}

        lines = [
            "[내 포트폴리오 현황]",
            f"총 평가금액: {balance['총평가금액']:,}원",
            f"총 평가손익: {balance['총평가손익']:,}원",
            "",
        ]
        for h in balance["보유종목"]:
            lines.append(
                f"- {h['종목명']}({h['종목코드']}): "
                f"{h['보유수량']}주, 평균 {h['매입평균가']:,}원 → "
                f"현재 {h['현재가']:,}원 ({h['수익률']})"
            )

        tags = ["포트폴리오", "잔고", "자동학습"]
        tags.extend([h["종목명"] for h in balance["보유종목"]])

        entry = self.knowledge.add({
            "category": "strategy",
            "title": f"내 포트폴리오 ({datetime.now().strftime('%Y-%m-%d')})",
            "content": "\n".join(lines),
            "tags": tags,
        })

        return {"status": "learned", "holdings_count": len(balance["보유종목"]), "knowledge_id": entry["id"]}

    # ----------------------------------------------------------
    # 4) 다종목 일괄 학습
    # ----------------------------------------------------------
    async def learn_watchlist(self, stock_codes: list[str]) -> list[dict]:
        results = []
        for code in stock_codes:
            try:
                results.append(await self.learn_stock_snapshot(code))
            except Exception as e:
                results.append({"status": "error", "stock_code": code, "error": str(e)})
        return results

    # ----------------------------------------------------------
    # 기술적 지표 계산
    # ----------------------------------------------------------
    def _calculate_indicators(self, daily: list[dict]) -> dict:
        """PPT 설계 기반 고급 피처 계산 (80+ 지표)"""
        return self.fb.build(daily)

    def _build_snapshot_content(self, price: dict, indicators: dict) -> str:
        lines = [
            f"종목: {price.get('종목명', '')} ({price.get('종목코드', '')})",
            f"현재가: {price.get('현재가', 0):,}원 ({price.get('등락률', '')})",
            f"시가총액: {price.get('시가총액_억', '')}억원",
            f"PER: {price.get('PER', 0)} / PBR: {price.get('PBR', 0)}",
            f"52주 범위: {price.get('52주최저', 0):,} ~ {price.get('52주최고', 0):,}원",
            "",
            "[기술적 지표 (자동 계산)]",
        ]
        for k, v in indicators.items():
            if k != "error":
                lines.append(f"- {k}: {v}")
        lines.append(f"\n수집 시점: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        return "\n".join(lines)

    @staticmethod
    def _calc_ema(data: list, period: int) -> float:
        """지수이동평균(EMA)을 계산합니다."""
        if len(data) < period:
            return sum(data) / len(data)
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for val in data[period:]:
            ema = (val - ema) * multiplier + ema
        return ema

    def _analyze_volume(self, daily: list[dict]) -> str:
        if not daily or len(daily) < 5:
            return "데이터 부족"
        volumes = [d["거래량"] for d in daily]
        avg_5 = sum(volumes[-5:]) / 5
        if len(volumes) >= 20:
            avg_20 = sum(volumes[-20:]) / 20
            ratio = avg_5 / avg_20 if avg_20 > 0 else 0
            if ratio > 2:
                trend = "거래량 급증 (강한 관심)"
            elif ratio > 1.3:
                trend = "거래량 증가 추세"
            elif ratio < 0.7:
                trend = "거래량 감소 (관심 하락)"
            else:
                trend = "보통 수준"
            return f"- 5일 평균: {avg_5:,.0f}\n- 20일 평균: {avg_20:,.0f}\n- 비율: {ratio:.1f}배\n- 판단: {trend}"
        return f"- 5일 평균 거래량: {avg_5:,.0f}"
