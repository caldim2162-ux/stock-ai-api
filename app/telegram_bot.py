"""
📱 텔레그램 알림 봇
- 매매 추천 결과를 텔레그램으로 전송합니다.
- 관심 종목 자동 스캔 후 신호가 나오면 알림을 보냅니다.
"""

import os
import httpx
from typing import Optional


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramBot:
    """텔레그램으로 알림을 보냅니다."""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    # ----------------------------------------------------------
    # 메시지 전송
    # ----------------------------------------------------------
    async def send(self, text: str) -> bool:
        """텔레그램으로 메시지를 보냅니다."""
        if not self.is_configured:
            return False

        url = TELEGRAM_API.format(token=self.token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False

    # ----------------------------------------------------------
    # 추천 결과 → 텔레그램 메시지로 변환
    # ----------------------------------------------------------
    async def send_recommendation(self, data: dict) -> bool:
        """추천 결과를 보기 좋게 변환하여 전송합니다."""

        rec = data.get("recommendation", "관망")
        score = data.get("total_score", 0)
        stock = data.get("stock_name", "")
        code = data.get("stock_code", "")
        price = data.get("price", {}).get("current", 0)
        confidence = data.get("confidence", "")

        # 이모지 결정
        if "매수" in rec:
            emoji = "🟢"
        elif "매도" in rec:
            emoji = "🔴"
        else:
            emoji = "🟡"

        # 뉴스 요약
        news = data.get("news_summary", {})
        sentiment = news.get("overall_sentiment", "")
        pos_topics = news.get("key_positive", [])
        neg_topics = news.get("key_negative", [])

        # 기술적 신호
        tech = data.get("technical_signals", {})
        pos_signals = tech.get("positive", [])
        neg_signals = tech.get("negative", [])

        # 수수료
        fee = data.get("fee_info", {})
        fee_text = fee.get("왕복_총비용", "")

        # AI 분석에서 목표가/손절가 추출
        ai = data.get("ai_analysis", "")
        target = ""
        stop = ""
        import re
        t_match = re.search(r"목표가[:\s]*([0-9,]+)", ai)
        s_match = re.search(r"손절가[:\s]*([0-9,]+)", ai)
        if t_match:
            target = t_match.group(1) + "원"
        if s_match:
            stop = s_match.group(1) + "원"

        # 메시지 구성
        msg = f"""{emoji} <b>{stock} ({code})</b>

<b>추천: {rec}</b> | 점수: {score}/100 | 신뢰도: {confidence}
현재가: {price:,}원

📰 뉴스 감성: {sentiment}
"""

        if pos_topics:
            msg += "✅ " + ", ".join(pos_topics[:3]) + "\n"
        if neg_topics:
            msg += "⚠️ " + ", ".join(neg_topics[:3]) + "\n"

        if pos_signals or neg_signals:
            msg += "\n📊 기술적 신호:\n"
            for s in pos_signals[:3]:
                msg += f"  ✅ {s}\n"
            for s in neg_signals[:3]:
                msg += f"  ❌ {s}\n"

        if target or stop:
            msg += f"\n🎯 목표가: {target or '-'} | 손절가: {stop or '-'}"

        if fee_text:
            msg += f"\n💰 거래비용: {fee_text}"

        msg += "\n\n⚠️ 참고용 분석이며 투자 책임은 본인에게 있습니다."

        return await self.send(msg)

    # ----------------------------------------------------------
    # 관심 종목 스캔 결과 알림
    # ----------------------------------------------------------
    async def send_scan_alert(self, results: list[dict]) -> bool:
        """여러 종목 스캔 결과 중 신호가 있는 것만 알림합니다."""

        alerts = []
        for r in results:
            score = r.get("total_score", 0)
            rec = r.get("recommendation", "")
            # 관망이 아닌 것만 알림
            if "매수" in rec or "매도" in rec:
                stock = r.get("stock_name", r.get("stock_code", ""))
                emoji = "🟢" if "매수" in rec else "🔴"
                alerts.append(f"{emoji} {stock}: {rec} (점수 {score})")

        if not alerts:
            return True  # 알릴 게 없으면 성공으로 처리

        msg = f"📋 <b>일일 종목 스캔 결과</b>\n"
        msg += f"({len(results)}개 종목 중 {len(alerts)}개 신호 감지)\n\n"
        msg += "\n".join(alerts)
        msg += "\n\n자세한 분석은 대시보드에서 확인하세요."

        return await self.send(msg)

    # ----------------------------------------------------------
    # 성과 업데이트 알림
    # ----------------------------------------------------------
    async def send_performance_update(self, stats: dict) -> bool:
        """성과 통계를 알림으로 보냅니다."""

        msg = f"📊 <b>성과 리포트</b>\n\n"
        msg += f"총 추천: {stats.get('총_추천수', 0)}건\n"
        msg += f"적중률: {stats.get('전체_적중률', '-')}\n"

        avg = stats.get("평균_수익률", {})
        msg += f"7일 평균수익률: {avg.get('7일', '-')}\n"
        msg += f"30일 평균수익률: {avg.get('30일', '-')}\n"

        best = stats.get("최고_추천")
        worst = stats.get("최악_추천")
        if best:
            msg += f"\n🏆 최고: {best['종목']} ({best['수익률']})"
        if worst:
            msg += f"\n💀 최악: {worst['종목']} ({worst['수익률']})"

        return await self.send(msg)

    # ----------------------------------------------------------
    # 연결 테스트
    # ----------------------------------------------------------
    async def test(self) -> dict:
        """봇 연결을 테스트합니다."""
        if not self.is_configured:
            return {
                "status": "미설정",
                "message": "TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 .env에 설정하세요.",
            }

        success = await self.send("✅ 주식 AI 텔레그램 알림이 연결되었습니다!\n\n사용 가능한 명령어:\nㅇ / 승인 → 대기 주문 승인\nㄴ / 거부 → 대기 주문 거부\n중지 → 긴급 중지\n상태 → 현재 상태 확인\n대기 → 대기 주문 확인")
        return {
            "status": "성공" if success else "실패",
            "bot_token": self.token[:10] + "...",
            "chat_id": self.chat_id,
        }

    # ----------------------------------------------------------
    # 텔레그램 메시지 수신 (폴링)
    # ----------------------------------------------------------
    async def get_updates(self, offset: int = 0) -> tuple[list[dict], int]:
        """새 메시지를 가져옵니다."""
        if not self.is_configured:
            return [], offset

        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {"offset": offset, "timeout": 5, "limit": 10}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                data = resp.json()

            messages = []
            new_offset = offset
            for update in data.get("result", []):
                new_offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # 본인 chat_id에서 온 메시지만 처리
                if chat_id == self.chat_id and text:
                    messages.append(text)

            return messages, new_offset
        except Exception:
            return [], offset

    # ----------------------------------------------------------
    # 버튼이 있는 메시지 전송
    # ----------------------------------------------------------
    async def send_with_buttons(self, text: str, buttons: list[list[dict]]) -> bool:
        """인라인 키보드 버튼이 있는 메시지를 보냅니다."""
        if not self.is_configured:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": buttons},
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False

    async def answer_callback(self, callback_query_id: str, text: str = "") -> bool:
        """콜백 쿼리에 응답합니다."""
        url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(url, json={"callback_query_id": callback_query_id, "text": text})
            return True
        except Exception:
            return False

    async def get_callback_updates(self, offset: int = 0) -> tuple[list[dict], int]:
        """콜백 쿼리(버튼 클릭)를 포함한 업데이트를 가져옵니다."""
        if not self.is_configured:
            return [], offset

        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {"offset": offset, "timeout": 5, "limit": 10}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                data = resp.json()

            events = []
            new_offset = offset
            for update in data.get("result", []):
                new_offset = update["update_id"] + 1

                # 일반 메시지
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if chat_id == self.chat_id and text:
                    events.append({"type": "message", "text": text})

                # 버튼 클릭 콜백
                cb = update.get("callback_query", {})
                cb_data = cb.get("data", "")
                cb_chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                cb_id = cb.get("id", "")
                if cb_chat == self.chat_id and cb_data:
                    events.append({"type": "callback", "data": cb_data, "callback_id": cb_id})

            return events, new_offset
        except Exception:
            return [], offset
