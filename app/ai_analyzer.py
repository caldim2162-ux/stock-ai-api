"""
🤖 AI 분석 엔진 v2
- 사용자 커스텀 분석 프롬프트 + 지식 베이스 통합
- 한투 API 데이터를 전문 금융 분석 프레임워크로 처리
"""

import os
import httpx
from typing import Optional

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

# ============================================================
# 🎯 핵심 분석 프롬프트 (사용자 커스텀)
# 이 부분을 수정하면 AI의 분석 방식이 바뀝니다.
# ============================================================
ANALYSIS_FRAMEWORK = """
너는 금융 데이터 분석 전문가 역할을 맡는다.
입력 데이터는 한국투자증권 API를 통해 수집한 주식 시세 및 거래량 데이터이다.
데이터 형식은 JSON이며, 각 항목에는 날짜, 종목 코드, 시가, 종가, 고가, 저가, 거래량이 포함되어 있다.

[분석 프레임워크]

1단계 - 데이터 전처리:
   - 결측치가 있는 항목은 명시하고, 직전 유효 데이터로 보간하거나 제외 처리한다.
   - 이상치(극단적 변동, 거래량 급변)를 식별하고 원인을 추정한다.
   - 가격 데이터가 제공된 경우 정규화(0~1 또는 z-score)를 적용하여 비교 가능하게 만든다.

2단계 - 기술적 지표 계산:
   - 이동평균선(MA): 5일, 10일, 20일, 60일 이동평균을 산출하고 배열 상태(정배열/역배열)를 판단한다.
   - RSI(14일): 과매수(70 이상)/과매도(30 이하) 구간을 판별한다.
   - MACD: MACD 선(12일 EMA - 26일 EMA)과 시그널 선(MACD의 9일 EMA)의 교차 여부를 분석한다.
   - 볼린저 밴드: 20일 기준으로 상단/하단 밴드 대비 현재가 위치를 판단한다.
   - 거래량 분석: 20일 평균 대비 금일 거래량 비율, 거래량 추이(증가/감소)를 분석한다.
   - 제공된 지표 데이터가 있으면 그것을 우선 활용하고, 없는 지표는 가용 데이터로 추정한다.

3단계 - 패턴 탐지:
   - 이동평균선 교차: 골든크로스(단기 > 장기 상향돌파) / 데드크로스(하향돌파) 발생 여부.
   - 추세 판단: 최근 5일, 10일, 20일 기준 상승/하락/횡보 추세 식별.
   - 지지/저항선: 최근 고점/저점 기반으로 주요 가격대를 식별.
   - 거래량 동반 여부: 가격 변동에 거래량이 동반되는지 확인 (거래량 없는 상승은 신뢰도 낮음).
   - 캔들 패턴: 장대양봉, 장대음봉, 도지, 망치형 등 최근 캔들 형태 분석.

4단계 - 결과 요약:
   아래 형식으로 출력한다:

   ## 분석 과정 설명
   (수행한 분석 과정을 간단히 2~3줄로 설명)

   ## 주요 지표 값
   | 지표 | 값 | 판단 |
   |------|-----|------|
   (MA, RSI, MACD 등 핵심 지표를 표로 정리)

   ## 상승/하락 신호 요약
   - 긍정 신호: (구체적으로 나열)
   - 부정 신호: (구체적으로 나열)
   - 종합 판단: (현재 상태에 대한 1줄 요약)

   ## 리스크 요인
   - (시장 전체 리스크, 종목 고유 리스크, 기술적 리스크 등)

   ## 액션 포인트
   - (구체적인 가격대, 조건 등과 함께 제시)

[주의사항]
- 데이터는 한국 주식 시장(KRX) 기준으로 해석한다.
- 예측은 확률적이며, 투자 권유가 아닌 참고용 분석으로 제시한다.
- 분석의 한계점과 불확실성을 반드시 명시한다.
- 한국어로 답변한다.
""".strip()


class AIAnalyzer:
    def __init__(self, knowledge_manager):
        self.knowledge = knowledge_manager

    # ----------------------------------------------------------
    # 주식 분석
    # ----------------------------------------------------------
    async def analyze(
        self,
        ticker: str,
        price_data: dict,
        analysis_type: str,
        question: Optional[str],
        relevant_knowledge: list[dict],
    ) -> dict:
        """지식 베이스 + 분석 프레임워크를 기반으로 주식을 분석합니다."""

        system_prompt = self._build_system_prompt(relevant_knowledge)

        user_message = self._build_analysis_prompt(
            ticker=ticker,
            price_data=price_data,
            analysis_type=analysis_type,
            question=question,
        )

        response = await self._call_api(system_prompt, user_message)

        return {
            "summary": response,
            "ticker": ticker,
            "type": analysis_type,
        }

    # ----------------------------------------------------------
    # 자유 대화
    # ----------------------------------------------------------
    async def chat(
        self,
        message: str,
        context: Optional[str],
        relevant_knowledge: list[dict],
    ) -> str:
        """자유 대화를 수행합니다."""

        system_prompt = self._build_system_prompt(relevant_knowledge)

        user_message = message
        if context:
            user_message = f"[추가 맥락]\n{context}\n\n[질문]\n{message}"

        return await self._call_api(system_prompt, user_message)

    # ----------------------------------------------------------
    # 프롬프트 빌더
    # ----------------------------------------------------------
    def _build_system_prompt(self, relevant_knowledge: list[dict]) -> str:
        """
        시스템 프롬프트 구조:
        1) 분석 프레임워크 (사용자 커스텀 프롬프트)
        2) 나의 투자 지식 베이스 (자동 학습 + 수동 입력 데이터)
        """

        # 파트 1: 분석 프레임워크
        prompt = ANALYSIS_FRAMEWORK

        # 파트 2: 지식 베이스 연결
        prompt += "\n\n" + "=" * 60
        prompt += "\n[나의 투자 지식 베이스]\n"
        prompt += "아래는 사용자가 직접 구축한 투자 철학, 전략, 분석 규칙, 그리고\n"
        prompt += "한투 API에서 자동 수집된 시장 데이터입니다.\n"
        prompt += "반드시 이 지식을 우선적으로 참고하여 분석하고, 어떤 지식을 활용했는지 명시하세요.\n"
        prompt += "=" * 60

        if relevant_knowledge:
            for i, entry in enumerate(relevant_knowledge, 1):
                prompt += f"\n\n--- 지식 #{i}: {entry['title']} [{entry['category']}] ---\n"
                prompt += f"{entry['content']}\n"
                if entry.get("tags"):
                    prompt += f"태그: {', '.join(entry['tags'])}\n"
        else:
            prompt += "\n(아직 등록된 지식이 없습니다.)\n"
            prompt += "지식이 없는 경우에도 위 분석 프레임워크에 따라 최선의 분석을 수행하세요.\n"

        return prompt

    def _build_analysis_prompt(
        self,
        ticker: str,
        price_data: dict,
        analysis_type: str,
        question: Optional[str],
    ) -> str:
        """분석 요청 프롬프트를 생성합니다."""

        type_labels = {
            "comprehensive": "종합 분석 (4단계 프레임워크 전체 적용)",
            "technical": "기술적 분석 (2~3단계 집중: 지표 계산 + 패턴 탐지)",
            "fundamental": "펀더멘털 분석 (PER/PBR/시가총액 중심 + 섹터 분석)",
            "sentiment": "시장 심리 분석 (거래량 패턴 + 투자자 동향 중심)",
        }

        prompt = f"""[분석 요청]
종목: {ticker}
분석 유형: {type_labels.get(analysis_type, analysis_type)}

[한투 API 실시간 데이터 (JSON)]
{self._format_price_data(price_data)}
"""

        if question:
            prompt += f"\n[사용자 질문]\n{question}\n"

        prompt += "\n위 분석 프레임워크의 4단계에 따라 체계적으로 분석하고, 결과 요약 형식에 맞춰 출력하세요.\n"
        prompt += "지식 베이스에 관련 데이터(이전 스냅샷, 기술적 지표 등)가 있으면 시계열 비교도 수행하세요.\n"

        return prompt

    def _format_price_data(self, price_data: dict) -> str:
        if not price_data:
            return "(가격 데이터를 가져올 수 없습니다)"

        lines = []
        for key, value in price_data.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    # ----------------------------------------------------------
    # API 호출
    # ----------------------------------------------------------
    async def _call_api(self, system_prompt: str, user_message: str) -> str:
        """Anthropic Claude API를 호출합니다."""

        if not ANTHROPIC_API_KEY:
            return self._mock_response(user_message)

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

        # 응답에서 텍스트 추출
        return "".join(
            block["text"] for block in data.get("content", []) if block.get("type") == "text"
        )

    def _mock_response(self, user_message: str) -> str:
        """API 키가 없을 때의 데모 응답"""
        return (
            "⚠️ ANTHROPIC_API_KEY가 설정되지 않았습니다.\n\n"
            "실제 AI 분석을 사용하려면:\n"
            "1. https://console.anthropic.com 에서 API 키를 발급받으세요.\n"
            "2. 환경변수를 설정하세요: export ANTHROPIC_API_KEY=sk-ant-...\n"
            "3. 서버를 재시작하세요.\n\n"
            f"[받은 질문 미리보기]\n{user_message[:200]}..."
        )
