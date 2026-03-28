"""
🧠 뉴스 감성 분석기
- Claude API로 뉴스 기사의 감성을 분석합니다.
- 비용 절약: 기사 제목들을 묶어서 1번의 API 호출로 처리합니다.
- 결과: 종목별 감성 점수 (-1.0 ~ +1.0) + 핵심 키워드 + 영향 요약
"""

import os
import json
import httpx
from typing import Optional

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"


class NewsSentimentAnalyzer:
    """뉴스 기사의 감성을 분석합니다."""

    # ----------------------------------------------------------
    # 메인: 뉴스 감성 분석
    # ----------------------------------------------------------
    async def analyze(
        self,
        articles: list[dict],
        stock_name: str,
        stock_code: str,
    ) -> dict:
        """
        수집된 뉴스 기사들의 감성을 분석합니다.

        Args:
            articles: 뉴스 기사 리스트
            stock_name: 종목명
            stock_code: 종목코드

        Returns:
            {
                "overall_score": 0.45,       # 종합 감성 점수 (-1.0 ~ +1.0)
                "overall_label": "긍정",      # 긍정/부정/중립
                "article_count": 15,
                "positive_count": 8,
                "negative_count": 3,
                "neutral_count": 4,
                "key_topics": ["AI 반도체 수주", "실적 호조"],
                "risk_factors": ["미중 갈등"],
                "summary": "...",
                "articles_detail": [
                    {"title": "...", "score": 0.7, "reason": "..."},
                    ...
                ]
            }
        """
        if not articles:
            return self._empty_result(stock_name)

        if not ANTHROPIC_API_KEY:
            return self._mock_result(articles, stock_name)

        # 비용 절약: 기사들을 묶어서 1번의 API 호출로 분석
        result = await self._batch_analyze(articles, stock_name, stock_code)
        return result

    # ----------------------------------------------------------
    # 배치 감성 분석 (기사 묶어서 1번 호출)
    # ----------------------------------------------------------
    async def _batch_analyze(
        self,
        articles: list[dict],
        stock_name: str,
        stock_code: str,
    ) -> dict:
        """기사들을 묶어서 한 번의 API 호출로 감성 분석합니다."""

        system_prompt = """너는 금융 뉴스 감성 분석 전문가다.
주어진 뉴스 기사 목록을 분석하여, 특정 종목의 주가에 미치는 영향을 판단한다.

규칙:
- 각 기사에 -1.0(매우 부정) ~ +1.0(매우 긍정) 사이의 점수를 부여한다.
- 해당 종목에 직접적 영향이 있는 기사는 가중치를 높게, 간접적(업종/시장 전체)이면 낮게 반영한다.
- "실적이 예상보다 못했지만 선방" 같은 맥락도 정확히 읽어야 한다.
- 한국 주식 시장의 맥락으로 해석한다.

반드시 아래 JSON 형식으로만 응답하라. 다른 텍스트는 절대 포함하지 마라:
{
  "overall_score": 0.0,
  "key_positive": ["긍정 요인1", "긍정 요인2"],
  "key_negative": ["부정 요인1"],
  "risk_factors": ["리스크1"],
  "summary": "종합 요약 2-3줄",
  "articles": [
    {"index": 1, "score": 0.0, "impact": "직접/간접", "reason": "이유 한줄"}
  ]
}"""

        # 기사 목록 텍스트 구성 (비용 절약: 제목 + 요약만)
        article_text = f"분석 대상 종목: {stock_name} ({stock_code})\n\n"
        for i, a in enumerate(articles[:20], 1):  # 최대 20개
            article_text += f"기사 #{i}: {a['title']}\n"
            if a.get("description"):
                article_text += f"  요약: {a['description'][:120]}\n"
            article_text += "\n"

        article_text += "위 기사들을 분석하여 JSON으로 응답하라."

        # API 호출
        response_text = await self._call_api(system_prompt, article_text)

        # JSON 파싱
        try:
            # JSON 블록 추출 (```json ... ``` 또는 순수 JSON)
            json_match = response_text
            if "```" in response_text:
                import re
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
                if match:
                    json_match = match.group(1)

            parsed = json.loads(json_match)

            # 결과 구성
            overall = float(parsed.get("overall_score", 0))
            article_details = parsed.get("articles", [])

            pos = sum(1 for a in article_details if a.get("score", 0) > 0.1)
            neg = sum(1 for a in article_details if a.get("score", 0) < -0.1)
            neu = len(article_details) - pos - neg

            return {
                "stock_name": stock_name,
                "stock_code": stock_code,
                "overall_score": round(overall, 2),
                "overall_label": self._score_to_label(overall),
                "article_count": len(articles),
                "analyzed_count": len(article_details),
                "positive_count": pos,
                "negative_count": neg,
                "neutral_count": neu,
                "key_positive": parsed.get("key_positive", []),
                "key_negative": parsed.get("key_negative", []),
                "risk_factors": parsed.get("risk_factors", []),
                "summary": parsed.get("summary", ""),
                "articles_detail": article_details,
            }

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # JSON 파싱 실패 시 텍스트 기반 응답
            return {
                "stock_name": stock_name,
                "stock_code": stock_code,
                "overall_score": 0.0,
                "overall_label": "분석 실패",
                "article_count": len(articles),
                "summary": f"JSON 파싱 실패. 원본 응답: {response_text[:300]}",
                "error": str(e),
            }

    # ----------------------------------------------------------
    # 점수 → 라벨 변환
    # ----------------------------------------------------------
    @staticmethod
    def _score_to_label(score: float) -> str:
        if score >= 0.5:
            return "매우 긍정"
        elif score >= 0.15:
            return "긍정"
        elif score > -0.15:
            return "중립"
        elif score > -0.5:
            return "부정"
        else:
            return "매우 부정"

    # ----------------------------------------------------------
    # API 호출
    # ----------------------------------------------------------
    async def _call_api(self, system_prompt: str, user_message: str) -> str:
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

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return "".join(
            block["text"] for block in data.get("content", []) if block.get("type") == "text"
        )

    # ----------------------------------------------------------
    # 결과 없음 / 데모
    # ----------------------------------------------------------
    def _empty_result(self, stock_name: str) -> dict:
        return {
            "stock_name": stock_name,
            "overall_score": 0.0,
            "overall_label": "뉴스 없음",
            "article_count": 0,
            "summary": "수집된 뉴스가 없어 감성 분석을 수행할 수 없습니다.",
        }

    def _mock_result(self, articles: list[dict], stock_name: str) -> dict:
        return {
            "stock_name": stock_name,
            "overall_score": 0.0,
            "overall_label": "데모 모드",
            "article_count": len(articles),
            "summary": (
                "ANTHROPIC_API_KEY가 설정되지 않아 데모 모드입니다. "
                f"수집된 기사 {len(articles)}건은 정상적으로 가져왔으나, "
                "감성 분석은 API 키 설정 후 사용 가능합니다."
            ),
            "articles_titles": [a["title"] for a in articles[:5]],
        }
