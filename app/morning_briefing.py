"""
🌅 매일 아침 시장 브리핑 (텔레그램)
- 전일 시장 요약 (코스피/코스닥)
- 외국인/기관 수급 TOP 5
- AI 추천 관심종목 요약
- 오늘의 주요 이벤트
"""

import asyncio
from datetime import datetime, timedelta
from app.krx_data import KRXDataFetcher
from app.accumulation_scanner import AccumulationScanner, SCAN_STOCKS
from app.telegram_bot import TelegramBot


class MorningBriefing:
    """매일 아침 시장 브리핑"""

    def __init__(self, telegram: TelegramBot):
        self.telegram = telegram
        self.krx = KRXDataFetcher()
        self.scanner = AccumulationScanner()

    async def generate_briefing(self) -> dict:
        """브리핑 생성"""
        now = datetime.now()
        briefing = {
            "날짜": now.strftime("%Y년 %m월 %d일 (%A)"),
            "생성시간": now.strftime("%H:%M"),
        }

        # 1) 주요 종목 수급 스캔 (빠른 스캔)
        try:
            quick_stocks = {
                "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER",
                "005380": "현대차", "000270": "기아", "068270": "셀트리온",
                "051910": "LG화학", "006400": "삼성SDI", "105560": "KB금융",
                "207940": "삼성바이오", "005490": "POSCO홀딩스", "009540": "HD한국조선해양",
                "042660": "한화오션", "034020": "두산에너빌리티", "138040": "메리츠금융",
            }
            scan_result = self.scanner.scan_all(days=5, min_consecutive=2, stocks=quick_stocks)
            briefing["수급_스캔"] = scan_result
        except Exception as e:
            briefing["수급_스캔"] = {"error": str(e)}

        return briefing

    async def send_briefing(self) -> dict:
        """텔레그램으로 브리핑 전송"""
        if not self.telegram.is_configured:
            return {"status": "error", "message": "텔레그램 미설정"}

        briefing = await self.generate_briefing()
        msg = self._format_message(briefing)

        try:
            await self.telegram.send(msg)
            return {"status": "success", "message": "브리핑 전송 완료", "data": briefing}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _format_message(self, briefing: dict) -> str:
        """텔레그램 메시지 포맷팅"""
        lines = []
        lines.append(f"🌅 <b>시장 브리핑</b>")
        lines.append(f"📅 {briefing['날짜']}")
        lines.append("")

        # 수급 스캔 결과
        scan = briefing.get("수급_스캔", {})
        if not scan.get("error"):
            # 외국인 연속매수
            foreign_top = scan.get("외국인_연속매수_TOP", [])[:5]
            if foreign_top:
                lines.append("🟢 <b>외국인 연속매수</b>")
                for s in foreign_top:
                    days = s['외국인_연속매수일']
                    fire = '🔥' if days >= 5 else ''
                    trend = '↑' if s['외국인_추세'] == '가속' else '→'
                    lines.append(f"  • {s['종목명']} — {days}일 연속 {fire} ({s['기간_수익률']}) {trend}")
                lines.append("")

            # 기관 연속매수
            organ_top = scan.get("기관_연속매수_TOP", [])[:5]
            if organ_top:
                lines.append("🔵 <b>기관 연속매수</b>")
                for s in organ_top:
                    days = s['기관_연속매수일']
                    fire = '🔥' if days >= 5 else ''
                    trend = '↑' if s['기관_추세'] == '가속' else '→'
                    lines.append(f"  • {s['종목명']} — {days}일 연속 {fire} ({s['기간_수익률']}) {trend}")
                lines.append("")

            # 동시 매집
            both = scan.get("외국인+기관_동시매집", [])[:3]
            if both:
                lines.append("🟡 <b>외국인+기관 동시매집</b>")
                for s in both:
                    lines.append(f"  • {s['종목명']} — 외 {s['외국인_연속매수일']}일 + 기 {s['기관_연속매수일']}일 ({s['기간_수익률']})")
                lines.append("")

            # 외국인 누적 TOP 5
            foreign_cum = scan.get("외국인_누적매수_TOP", [])[:5]
            if foreign_cum:
                lines.append("📊 <b>외국인 누적매수 TOP 5</b>")
                for i, s in enumerate(foreign_cum):
                    lines.append(f"  {i+1}. {s['종목명']} — {s['외국인_누적순매수']:,}주 ({s['기간_수익률']})")
                lines.append("")

        lines.append(f"⏰ {briefing['생성시간']} 생성")
        lines.append("💡 대시보드에서 상세 분석하세요")

        return "\n".join(lines)
