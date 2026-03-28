"""
🎯 매매 추천 엔진
- 뉴스 수집 → 감성 분석 → 기술적 분석 → 신호 통합 → AI 최종 추천
- 모든 단계를 하나로 묶어서 실행합니다.
- 추천 이력을 저장하여 성과 추적이 가능합니다.
- 캐싱: 같은 종목을 1시간 이내에 다시 검색하면 이전 결과를 재사용합니다.
"""

import json
import os
import httpx
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from app.kis_client import KISClient
from app.news_collector import NewsCollector
from app.news_sentiment import NewsSentimentAnalyzer
from app.auto_learner import AutoLearner
from app.signal_engine import SignalEngine
from app.knowledge_manager import KnowledgeManager

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

# 추천 이력 저장 경로
HISTORY_FILE = Path(__file__).parent.parent / "data" / "recommendation_history.json"

# 캐시 유효 시간 (기본 1시간)
CACHE_TTL_MINUTES = 60


class RecommendationEngine:
    """
    전체 파이프라인을 실행하여 매매 추천을 생성합니다.

    흐름:
    1. 한투 API → 현재가 + 일봉 수집
    2. 자동 학습기 → 기술적 지표 계산
    3. 뉴스 수집기 → 관련 뉴스 수집
    4. 감성 분석기 → 뉴스 감성 점수
    5. 신호 엔진 → 종합 점수 산출
    6. Claude AI → 최종 추천 + 근거 + 목표가/손절가
    """

    def __init__(
        self,
        kis: KISClient,
        knowledge: KnowledgeManager,
        learner: AutoLearner,
    ):
        self.kis = kis
        self.knowledge = knowledge
        self.learner = learner
        self.news = NewsCollector()
        self.sentiment = NewsSentimentAnalyzer()
        self.signal = SignalEngine()
        self._cache = {}  # {stock_code: {"result": ..., "time": ...}}

    # ----------------------------------------------------------
    # 메인: 종목 매매 추천
    # ----------------------------------------------------------
    async def recommend(
        self,
        stock_code: str,
        stock_name: str = "",
        question: Optional[str] = None,
        force_refresh: bool = False,
    ) -> dict:
        """
        종목에 대한 매매 추천을 생성합니다.
        같은 종목을 1시간 이내에 다시 요청하면 캐시된 결과를 반환합니다.
        force_refresh=True면 캐시를 무시하고 새로 분석합니다.
        """
        # ---- 캐시 확인 ----
        if not force_refresh:
            cached = self._cache.get(stock_code)
            if cached:
                cache_age = datetime.now() - cached["time"]
                if cache_age < timedelta(minutes=CACHE_TTL_MINUTES):
                    result = cached["result"].copy()
                    mins = int(cache_age.total_seconds() / 60)
                    result["cached"] = True
                    result["cache_info"] = f"{mins}분 전 분석 결과 (캐시, 크레딧 미사용)"
                    result["cache_remaining"] = f"{CACHE_TTL_MINUTES - mins}분 후 갱신 가능"
                    return result

        steps = {}
        errors = []

        # ---- STEP 1: 주식 데이터 수집 + 기술적 지표 ----
        try:
            learn_result = await self.learner.learn_stock_snapshot(stock_code)
            price_data = learn_result["price"]
            indicators = learn_result["indicators"]
            stock_name = stock_name or price_data.get("종목명", stock_code)
            steps["price"] = "OK"
            steps["indicators"] = "OK"
        except Exception as e:
            errors.append(f"주식 데이터 수집 실패: {e}")
            price_data = {}
            indicators = {}
            steps["price"] = f"실패: {e}"

        # ---- STEP 2: 뉴스 수집 ----
        try:
            articles = await self.news.collect(
                stock_code=stock_code,
                stock_name=stock_name,
                max_articles=20,
            )
            steps["news"] = f"{len(articles)}건 수집"
        except Exception as e:
            errors.append(f"뉴스 수집 실패: {e}")
            articles = []
            steps["news"] = f"실패: {e}"

        # ---- STEP 3: 뉴스 감성 분석 ----
        try:
            sentiment_result = await self.sentiment.analyze(
                articles=articles,
                stock_name=stock_name,
                stock_code=stock_code,
            )
            steps["sentiment"] = f"점수: {sentiment_result.get('overall_score', 0)}"
        except Exception as e:
            errors.append(f"감성 분석 실패: {e}")
            sentiment_result = {"overall_score": 0, "overall_label": "분석 실패"}
            steps["sentiment"] = f"실패: {e}"

        # ---- STEP 4: 신호 통합 ----
        signal_result = self.signal.generate_signal(
            news_sentiment=sentiment_result,
            technical_indicators=indicators,
            price_data=price_data,
        )
        steps["signal"] = f"종합 {signal_result['total_score']}점"

        # ---- STEP 5: AI 최종 추천 ----
        try:
            ai_recommendation = await self._generate_ai_recommendation(
                stock_name=stock_name,
                stock_code=stock_code,
                price_data=price_data,
                indicators=indicators,
                sentiment=sentiment_result,
                signal=signal_result,
                news_text=self.news.format_for_analysis(articles, max_articles=10),
                question=question,
            )
            steps["ai"] = "OK"
        except Exception as e:
            errors.append(f"AI 추천 생성 실패: {e}")
            ai_recommendation = f"AI 추천 생성 실패: {e}"
            steps["ai"] = f"실패: {e}"

        # ---- 결과 조합 ----
        result = {
            "stock_name": stock_name,
            "stock_code": stock_code,
            "timestamp": datetime.now().isoformat(),
            "recommendation": signal_result["recommendation"],
            "total_score": signal_result["total_score"],
            "confidence": signal_result["confidence"],
            "ai_analysis": ai_recommendation,
            "signal_detail": {
                "news_score": signal_result["news_score"],
                "technical_score": signal_result["technical_score"],
                "weights": signal_result["weights"],
            },
            "news_summary": {
                "overall_sentiment": sentiment_result.get("overall_label", ""),
                "article_count": sentiment_result.get("article_count", 0),
                "key_positive": sentiment_result.get("key_positive", []),
                "key_negative": sentiment_result.get("key_negative", []),
            },
            "technical_signals": {
                "positive": signal_result["signals_positive"],
                "negative": signal_result["signals_negative"],
            },
            "price": {
                "current": price_data.get("현재가", 0),
                "change": price_data.get("등락률", ""),
            },
            "fee_info": signal_result.get("fee_info", {}),
            "risk_factors": signal_result.get("risk_factors", []),
            "pipeline_status": steps,
            "errors": errors if errors else None,
        }

        # ---- 추천 이력 저장 ----
        self._save_history(result)

        # ---- 캐시 저장 ----
        self._cache[stock_code] = {"result": result, "time": datetime.now()}
        result["cached"] = False
        result["cache_info"] = f"새로 분석 완료 (다음 {CACHE_TTL_MINUTES}분간 캐시됨)"

        return result

    # ----------------------------------------------------------
    # AI 최종 추천 생성
    # ----------------------------------------------------------
    async def _generate_ai_recommendation(
        self,
        stock_name: str,
        stock_code: str,
        price_data: dict,
        indicators: dict,
        sentiment: dict,
        signal: dict,
        news_text: str,
        question: Optional[str],
    ) -> str:
        """Claude AI로 최종 매매 추천을 생성합니다."""

        if not ANTHROPIC_API_KEY:
            return (
                f"[데모 모드] 종합점수 {signal['total_score']}점 → {signal['recommendation']}\n"
                f"실제 AI 분석을 위해 ANTHROPIC_API_KEY를 설정하세요."
            )

        # 지식 베이스에서 관련 지식 검색
        relevant_knowledge = self.knowledge.search(
            query=f"{stock_name} {stock_code}",
            top_k=5,
        )

        knowledge_text = ""
        if relevant_knowledge:
            knowledge_text = "\n\n[사용자 지식 베이스]\n"
            for i, k in enumerate(relevant_knowledge, 1):
                knowledge_text += f"지식 #{i}: {k['title']}\n{k['content']}\n\n"

        system_prompt = """너는 주식 매매 추천 AI 어드바이저다.
아래 데이터를 종합하여 최종 매매 추천을 생성한다.

출력 형식:
## 최종 판단
(매수/매도/관망 중 하나 + 한줄 이유)

## 핵심 근거
- 뉴스 측면: (뉴스 분석 결과 요약)
- 기술적 측면: (기술적 지표 분석 요약)
- 종합: (두 분석이 어떻게 맞물리는지)

## 매매 전략
- 목표가: (현재가 대비 상승 목표)
- 손절가: (최대 허용 손실 가격)
- 권장 비중: (포트폴리오의 몇 % 정도)
- 매매 타이밍: (지금 바로 / 분할 매수 / 대기 등)

## 리스크
- (구체적 리스크 요인 나열)

## 주의사항
이 분석은 참고용이며 투자 판단의 최종 책임은 투자자 본인에게 있습니다.

한국어로 답변한다. 구체적 수치를 반드시 포함한다."""

        user_message = f"""[분석 대상]
종목: {stock_name} ({stock_code})
현재가: {self._fmt(price_data.get('현재가', 'N/A'))}원 ({price_data.get('등락률', 'N/A')})
PER: {price_data.get('PER', 'N/A')} / PBR: {price_data.get('PBR', 'N/A')}
52주: {self._fmt(price_data.get('52주최저', 'N/A'))} ~ {self._fmt(price_data.get('52주최고', 'N/A'))}원

[신호 통합 결과]
종합점수: {signal['total_score']}점 / 100점 만점
기계적 추천: {signal['recommendation']}
신뢰도: {signal['confidence']}

뉴스 감성 점수: {signal['news_raw']} (-1.0~+1.0)
기술적 점수: {signal['technical_raw']}

긍정 신호: {', '.join(signal['signals_positive']) or '없음'}
부정 신호: {', '.join(signal['signals_negative']) or '없음'}

[기술적 지표 상세]
{json.dumps({k: v for k, v in indicators.items() if k != 'error'}, ensure_ascii=False, indent=2)}

[뉴스 감성 분석]
종합 감성: {sentiment.get('overall_label', 'N/A')} ({sentiment.get('overall_score', 0)})
긍정 요인: {', '.join(sentiment.get('key_positive', [])) or '없음'}
부정 요인: {', '.join(sentiment.get('key_negative', [])) or '없음'}
리스크: {', '.join(sentiment.get('risk_factors', [])) or '없음'}

{news_text}

[수수료/세금 참고]
왕복 비용: {signal.get('fee_info', {}).get('왕복_총비용', 'N/A')}
손익분기: {signal.get('fee_info', {}).get('손익분기_가격', 'N/A')}
{knowledge_text}"""

        if question:
            user_message += f"\n\n[사용자 추가 질문]\n{question}"

        # API 호출
        headers = {
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": MODEL,
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return "".join(
            block["text"] for block in data.get("content", []) if block.get("type") == "text"
        )

    # ----------------------------------------------------------
    # 숫자 포맷 헬퍼
    # ----------------------------------------------------------
    @staticmethod
    def _fmt(value) -> str:
        """숫자면 천단위 콤마, 아니면 그대로 문자열로 반환"""
        if isinstance(value, (int, float)) and value != 0:
            return f"{int(value):,}"
        return str(value) if value else "N/A"

    # ----------------------------------------------------------
    # 추천 이력 저장
    # ----------------------------------------------------------
    def _save_history(self, result: dict):
        """추천 이력을 파일에 저장합니다."""
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            history = []
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)

            # 저장할 핵심 데이터만 추출
            record = {
                "timestamp": result["timestamp"],
                "stock_code": result["stock_code"],
                "stock_name": result["stock_name"],
                "recommendation": result["recommendation"],
                "total_score": result["total_score"],
                "price_at_recommend": result["price"]["current"],
                "news_score": result["signal_detail"]["news_score"],
                "tech_score": result["signal_detail"]["technical_score"],
                # 나중에 성과 추적할 때 채울 필드
                "price_after_3d": None,
                "price_after_7d": None,
                "actual_return": None,
                "was_correct": None,
            }

            history.append(record)

            # 최근 500건만 유지
            history = history[-500:]

            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

        except Exception:
            pass  # 이력 저장 실패는 무시

    # ----------------------------------------------------------
    # 추천 이력 조회
    # ----------------------------------------------------------
    @staticmethod
    def get_history(stock_code: Optional[str] = None, limit: int = 20) -> list[dict]:
        """추천 이력을 조회합니다."""
        try:
            if not HISTORY_FILE.exists():
                return []
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            if stock_code:
                history = [h for h in history if h.get("stock_code") == stock_code]
            return history[-limit:]
        except Exception:
            return []
