"""
📊 신호 통합 엔진
- 뉴스 감성 점수 + 기술적 지표를 합산하여 종합 매매 점수를 산출합니다.
- 점수 범위: -100 (강력 매도) ~ +100 (강력 매수)
- 가중치는 사용자가 조절할 수 있습니다.
"""

from typing import Optional


# ============================================================
# 🎯 기본 가중치 설정 (본인 스타일에 맞게 조절!)
# ============================================================
DEFAULT_WEIGHTS = {
    "news": 0.40,       # 뉴스 감성 비중 40%
    "technical": 0.60,  # 기술적 분석 비중 60%
}


def _load_optimized_weights() -> dict:
    """저장된 최적화 가중치가 있으면 로드"""
    import json, os
    weights_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "optimized_weights.json")
    try:
        if os.path.exists(weights_file):
            with open(weights_file, "r", encoding="utf-8") as f:
                w = json.load(f)
            if "news" in w and "technical" in w:
                return {"news": w["news"], "technical": w["technical"]}
    except Exception:
        pass
    return DEFAULT_WEIGHTS

# 기술적 지표별 점수 규칙
TECHNICAL_RULES = {
    # RSI 기반
    "rsi_oversold":       {"condition": "RSI_14 <= 30", "score": +15, "label": "RSI 과매도 (매수 기회)"},
    "rsi_overbought":     {"condition": "RSI_14 >= 70", "score": -15, "label": "RSI 과매수 (매도 주의)"},
    "rsi_neutral_bullish": {"condition": "40 <= RSI_14 <= 60", "score": +3, "label": "RSI 중립 (안정적)"},

    # 이동평균 배열
    "ma_golden_cross":    {"condition": "골든크로스 발생", "score": +20, "label": "골든크로스 (강한 매수)"},
    "ma_dead_cross":      {"condition": "데드크로스 발생", "score": -20, "label": "데드크로스 (강한 매도)"},
    "ma_bullish":         {"condition": "정배열", "score": +10, "label": "이평선 정배열 (상승 추세)"},
    "ma_bearish":         {"condition": "역배열", "score": -10, "label": "이평선 역배열 (하락 추세)"},

    # MACD
    "macd_positive":      {"condition": "MACD > 0", "score": +8, "label": "MACD 양수 (상승 모멘텀)"},
    "macd_negative":      {"condition": "MACD < 0", "score": -8, "label": "MACD 음수 (하락 모멘텀)"},

    # 볼린저 밴드
    "bb_oversold":        {"condition": "하단 밴드 근접", "score": +10, "label": "볼린저 하단 (반등 가능)"},
    "bb_overbought":      {"condition": "상단 밴드 근접", "score": -10, "label": "볼린저 상단 (조정 가능)"},

    # 거래량
    "volume_surge_bull":  {"condition": "거래량 급증 + 양봉", "score": +12, "label": "거래량 동반 상승 (신뢰도 높음)"},
    "volume_surge_bear":  {"condition": "거래량 급증 + 음봉", "score": -12, "label": "거래량 동반 하락 (투매 가능)"},
    "volume_low":         {"condition": "거래량 극감", "score": -5, "label": "거래량 감소 (관심 하락)"},

    # 캔들 패턴
    "candle_bullish":     {"condition": "장대양봉/망치형", "score": +8, "label": "강세 캔들 패턴"},
    "candle_bearish":     {"condition": "장대음봉", "score": -8, "label": "약세 캔들 패턴"},

    # 추세
    "trend_up":           {"condition": "5일 상승 추세", "score": +5, "label": "단기 상승 추세"},
    "trend_down":         {"condition": "5일 하락 추세", "score": -5, "label": "단기 하락 추세"},
}

# 종합 점수 → 추천 매핑
SCORE_THRESHOLDS = [
    (70,  "강력 매수", "기술적 지표와 뉴스 모두 매우 긍정적입니다."),
    (30,  "매수 고려", "긍정 신호가 우세하나 리스크 요인도 확인하세요."),
    (-30, "관망",      "뚜렷한 방향성이 없습니다. 추가 신호를 기다리세요."),
    (-70, "매도 고려", "부정 신호가 우세합니다. 보유 중이면 비중 축소를 검토하세요."),
]
SCORE_DEFAULT = ("강력 매도", "기술적 지표와 뉴스 모두 매우 부정적입니다.")


class SignalEngine:
    """뉴스 + 기술적 분석을 통합하여 매매 신호를 생성합니다."""

    def __init__(self, weights: Optional[dict] = None):
        self.weights = weights or _load_optimized_weights()

    # ----------------------------------------------------------
    # 메인: 종합 신호 생성
    # ----------------------------------------------------------
    def generate_signal(
        self,
        news_sentiment: dict,
        technical_indicators: dict,
        price_data: dict,
    ) -> dict:
        """
        뉴스 감성과 기술적 지표를 합산하여 종합 매매 신호를 생성합니다.

        Returns:
            {
                "total_score": 58,
                "recommendation": "매수 고려",
                "confidence": "보통",
                "news_score": 28.0,
                "technical_score": 30.0,
                "signals_positive": [...],
                "signals_negative": [...],
                "risk_factors": [...],
                "detail": {...}
            }
        """
        # 1) 뉴스 감성 → 점수 (-100 ~ +100 스케일)
        news_raw = news_sentiment.get("overall_score", 0)  # -1.0 ~ +1.0
        news_score = news_raw * 100  # -100 ~ +100

        # 최신 가중치 로드 (자동최적화 반영)
        self.weights = _load_optimized_weights()

        # 2) 기술적 지표 → 점수 (-100 ~ +100 스케일)
        tech_result = self._evaluate_technical(technical_indicators, price_data)
        tech_raw = tech_result["raw_score"]
        # 새 FeatureBuilder는 이미 -100~+100 스케일
        if "기술_종합점수" in technical_indicators:
            tech_score = max(-100, min(100, tech_raw))
        else:
            # 구버전: 정규화 필요
            max_possible = sum(abs(r["score"]) for r in TECHNICAL_RULES.values()) / 2
            tech_score = (tech_raw / max_possible * 100) if max_possible > 0 else 0
            tech_score = max(-100, min(100, tech_score))

        # 3) 가중치 합산
        w_news = self.weights.get("news", 0.4)
        w_tech = self.weights.get("technical", 0.6)

        weighted_news = news_score * w_news
        weighted_tech = tech_score * w_tech
        total_score = round(weighted_news + weighted_tech, 1)

        # 4) 추천 결정
        recommendation, explanation = self._score_to_recommendation(total_score)

        # 5) 신뢰도 판단
        confidence = self._calculate_confidence(
            news_sentiment, tech_result, news_score, tech_score
        )

        # 6) 수수료/세금 반영 참고 정보
        current_price = price_data.get("현재가", 0)
        fee_info = self._calculate_fees(current_price)

        return {
            "total_score": round(total_score, 1),
            "recommendation": recommendation,
            "explanation": explanation,
            "confidence": confidence,
            "news_score": round(weighted_news, 1),
            "news_raw": round(news_raw, 2),
            "technical_score": round(weighted_tech, 1),
            "technical_raw": round(tech_raw, 1),
            "signals_positive": tech_result["positive"],
            "signals_negative": tech_result["negative"],
            "news_positive": news_sentiment.get("key_positive", []),
            "news_negative": news_sentiment.get("key_negative", []),
            "risk_factors": news_sentiment.get("risk_factors", []),
            "weights": {"news": f"{w_news*100:.0f}%", "technical": f"{w_tech*100:.0f}%"},
            "fee_info": fee_info,
            # PPT 설계 추가 정보
            "regime": technical_indicators.get("시장_Regime", ""),
            "regime_전략": technical_indicators.get("Regime_전략", ""),
            "변동성_regime": technical_indicators.get("변동성_Regime", ""),
            "신호_강도": technical_indicators.get("신호_강도", ""),
        }

    # ----------------------------------------------------------
    # 기술적 지표 평가
    # ----------------------------------------------------------
    def _evaluate_technical(self, indicators: dict, price_data: dict) -> dict:
        """기술적 지표를 평가합니다. (PPT 설계 기반 고급 피처 활용)"""
        # 새 FeatureBuilder가 이미 종합점수와 신호를 계산함
        if "기술_종합점수" in indicators:
            return {
                "raw_score": indicators["기술_종합점수"],
                "positive": indicators.get("긍정_신호", []),
                "negative": indicators.get("부정_신호", []),
            }

        # 구버전 호환 (기존 지표만 있을 때)
        score = 0
        positive = []
        negative = []

        rsi = indicators.get("RSI_14")
        if rsi is not None:
            if rsi <= 30:
                score += 15; positive.append(f"RSI {rsi} (과매도)")
            elif rsi >= 70:
                score -= 15; negative.append(f"RSI {rsi} (과매수)")

        ma_state = indicators.get("이평선_상태", "")
        if "정배열" in ma_state:
            score += 10; positive.append("이평선 정배열")
        elif "역배열" in ma_state:
            score -= 10; negative.append("이평선 역배열")

        cross = indicators.get("크로스_신호", "")
        if "골든크로스" in cross:
            score += 20; positive.append("골든크로스")
        elif "데드크로스" in cross:
            score -= 20; negative.append("데드크로스")

        macd = indicators.get("MACD")
        if macd is not None:
            if macd > 0: score += 8; positive.append("MACD 양수")
            else: score -= 8; negative.append("MACD 음수")

        return {"raw_score": score, "positive": positive, "negative": negative}

    # ----------------------------------------------------------
    # 추천 결정
    # ----------------------------------------------------------
    @staticmethod
    def _score_to_recommendation(score: float) -> tuple[str, str]:
        for threshold, label, explanation in SCORE_THRESHOLDS:
            if score >= threshold:
                return label, explanation
        return SCORE_DEFAULT

    # ----------------------------------------------------------
    # 신뢰도 계산
    # ----------------------------------------------------------
    @staticmethod
    def _calculate_confidence(
        news_sentiment: dict,
        tech_result: dict,
        news_score: float,
        tech_score: float,
    ) -> str:
        """
        뉴스와 기술적 분석이 같은 방향을 가리키면 신뢰도 높음,
        반대면 낮음.
        """
        # 뉴스와 기술 분석의 방향이 일치하는가?
        news_dir = 1 if news_score > 10 else (-1 if news_score < -10 else 0)
        tech_dir = 1 if tech_score > 10 else (-1 if tech_score < -10 else 0)

        # 분석된 기사 수
        article_count = news_sentiment.get("analyzed_count", 0)

        # 기술적 신호 수
        signal_count = len(tech_result.get("positive", [])) + len(tech_result.get("negative", []))

        if news_dir == tech_dir and news_dir != 0:
            if article_count >= 10 and signal_count >= 4:
                return "높음"
            return "보통"
        elif news_dir != 0 and tech_dir != 0 and news_dir != tech_dir:
            return "낮음 (뉴스와 기술 분석이 상반됨)"
        else:
            return "보통"

    # ----------------------------------------------------------
    # 수수료/세금 계산 (실전 투자용)
    # ----------------------------------------------------------
    @staticmethod
    def _calculate_fees(price: int, quantity: int = 1) -> dict:
        """
        실전 거래 시 수수료와 세금을 계산합니다.
        한국투자증권 온라인 기준:
        - 매수 수수료: 약 0.015%
        - 매도 수수료: 약 0.015%
        - 증권거래세: 0.18% (코스피), 0.18% (코스닥) - 2025년 기준
        """
        if not price:
            return {}

        trade_amount = price * quantity
        buy_fee = round(trade_amount * 0.00015)         # 매수 수수료
        sell_fee = round(trade_amount * 0.00015)         # 매도 수수료
        tax = round(trade_amount * 0.0018)               # 거래세
        total_cost = buy_fee + sell_fee + tax
        cost_pct = total_cost / trade_amount * 100 if trade_amount > 0 else 0

        # 손익분기 가격 (이 가격 이상 올라야 본전)
        breakeven_price = round(price * (1 + cost_pct / 100))

        return {
            "매수_수수료": f"{buy_fee:,}원",
            "매도_수수료": f"{sell_fee:,}원",
            "거래세": f"{tax:,}원",
            "왕복_총비용": f"{total_cost:,}원 ({cost_pct:.2f}%)",
            "손익분기_가격": f"{breakeven_price:,}원",
            "참고": "수수료율은 증권사/이벤트에 따라 다를 수 있음",
        }
