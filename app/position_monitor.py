"""
📊 보유 종목 자동 모니터링
- 매수한 종목의 현재가를 주기적으로 체크
- 목표가/손절가 도달 시 텔레그램 알림
- Trailing Stop 자동 갱신
- AI 점수 급변 시 알림
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.kis_client import KISClient
from app.telegram_bot import TelegramBot

POSITIONS_FILE = Path(__file__).parent.parent / "data" / "positions.json"


class PositionMonitor:
    """보유 종목 자동 모니터링"""

    def __init__(self, kis: KISClient, telegram: TelegramBot):
        self.kis = kis
        self.telegram = telegram
        self.positions = self._load_positions()

    # ----------------------------------------------------------
    # 포지션 관리
    # ----------------------------------------------------------
    def add_position(self, stock_code: str, stock_name: str, entry_price: int,
                     quantity: int, target_price: int = 0, stop_price: int = 0) -> dict:
        """매수 후 포지션 등록"""
        self.positions[stock_code] = {
            "종목명": stock_name,
            "진입가": entry_price,
            "수량": quantity,
            "목표가": target_price,
            "손절가": stop_price,
            "최고가": entry_price,
            "진입일": datetime.now().isoformat(),
            "알림_목표": False,
            "알림_손절": False,
            "알림_trailing": False,
        }
        self._save_positions()
        return {"status": "등록", "종목": stock_name, "진입가": entry_price,
                "목표가": target_price, "손절가": stop_price}

    def remove_position(self, stock_code: str) -> dict:
        """매도 후 포지션 해제"""
        pos = self.positions.pop(stock_code, None)
        if not pos:
            return {"status": "없음"}
        self._save_positions()
        return {"status": "해제", "종목": pos["종목명"]}

    def get_positions(self) -> dict:
        """현재 보유 포지션 목록"""
        return self.positions

    def update_target(self, stock_code: str, target_price: int, stop_price: int = 0) -> dict:
        """목표가/손절가 수동 변경"""
        pos = self.positions.get(stock_code)
        if not pos:
            return {"status": "없음"}
        if target_price:
            pos["목표가"] = target_price
        if stop_price:
            pos["손절가"] = stop_price
        pos["알림_목표"] = False
        pos["알림_손절"] = False
        self._save_positions()
        return {"status": "수정", "종목": pos["종목명"],
                "목표가": pos["목표가"], "손절가": pos["손절가"]}

    # ----------------------------------------------------------
    # 자동 모니터링 (메인 로직)
    # ----------------------------------------------------------
    async def monitor_all(self) -> dict:
        """
        모든 보유 종목 현재가 체크 + 알림
        장중에 주기적으로 호출 (1~2시간마다)
        """
        if not self.positions:
            return {"status": "포지션 없음", "alerts": []}

        alerts = []
        pending_sells = []

        for code, pos in self.positions.items():
            try:
                # 현재가 조회
                price_data = await self.kis.get_price(code)
                current_price = int(price_data.get("stck_prpr", 0) or 0)
                if current_price == 0:
                    continue

                entry_price = pos["진입가"]
                target_price = pos.get("목표가", 0)
                stop_price = pos.get("손절가", 0)
                high_price = pos.get("최고가", entry_price)
                name = pos["종목명"]
                quantity = pos.get("수량", 0)
                pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)

                # 최고가 갱신
                if current_price > high_price:
                    pos["최고가"] = current_price
                    self._save_positions()

                # 1) 목표가 도달
                if target_price > 0 and current_price >= target_price and not pos.get("알림_목표"):
                    alert = {
                        "type": "target",
                        "code": code,
                        "name": name,
                        "current": current_price,
                        "target": target_price,
                        "pnl": f"{pnl_pct:+.1f}%",
                        "message": f"🎯 목표가 도달! {name} {current_price:,}원 (수익 {pnl_pct:+.1f}%)",
                    }
                    alerts.append(alert)
                    pending_sells.append({"code": code, "name": name, "price": current_price, "quantity": quantity, "reason": "목표가 도달"})
                    pos["알림_목표"] = True
                    self._save_positions()

                    if self.telegram.is_configured:
                        msg = (
                            f"🎯 <b>목표가 도달!</b>\n\n"
                            f"종목: {name} ({code})\n"
                            f"현재가: {current_price:,}원\n"
                            f"목표가: {target_price:,}원\n"
                            f"진입가: {entry_price:,}원\n"
                            f"수익률: {pnl_pct:+.1f}%\n"
                            f"수량: {quantity}주\n\n"
                            f"익절 매도하시겠습니까?"
                        )
                        buttons = [[
                            {"text": "✅ 익절 매도", "callback_data": f"sell_{code}"},
                            {"text": "❌ 계속 보유", "callback_data": f"hold_{code}"},
                        ]]
                        await self.telegram.send_with_buttons(msg, buttons)

                # 2) 손절가 도달
                elif stop_price > 0 and current_price <= stop_price and not pos.get("알림_손절"):
                    alert = {
                        "type": "stop",
                        "code": code,
                        "name": name,
                        "current": current_price,
                        "stop": stop_price,
                        "pnl": f"{pnl_pct:+.1f}%",
                        "message": f"🚨 손절가 도달! {name} {current_price:,}원 (손실 {pnl_pct:+.1f}%)",
                    }
                    alerts.append(alert)
                    pending_sells.append({"code": code, "name": name, "price": current_price, "quantity": quantity, "reason": "손절가 도달"})
                    pos["알림_손절"] = True
                    self._save_positions()

                    if self.telegram.is_configured:
                        msg = (
                            f"🚨 <b>손절가 도달!</b>\n\n"
                            f"종목: {name} ({code})\n"
                            f"현재가: {current_price:,}원\n"
                            f"손절가: {stop_price:,}원\n"
                            f"진입가: {entry_price:,}원\n"
                            f"손실률: {pnl_pct:+.1f}%\n\n"
                            f"손절 매도하시겠습니까?"
                        )
                        buttons = [[
                            {"text": "✅ 손절 매도", "callback_data": f"sell_{code}"},
                            {"text": "❌ 계속 보유", "callback_data": f"hold_{code}"},
                        ]]
                        await self.telegram.send_with_buttons(msg, buttons)

                # 3) Trailing Stop (최고가 대비 -3%)
                elif high_price > entry_price:
                    drop_from_high = (high_price - current_price) / high_price * 100
                    if drop_from_high >= 3.0 and not pos.get("알림_trailing"):
                        alert = {
                            "type": "trailing",
                            "code": code,
                            "name": name,
                            "current": current_price,
                            "high": high_price,
                            "drop": f"-{drop_from_high:.1f}%",
                            "pnl": f"{pnl_pct:+.1f}%",
                            "message": f"⚠️ Trailing Stop! {name} 최고 {high_price:,}→{current_price:,} (-{drop_from_high:.1f}%)",
                        }
                        alerts.append(alert)
                        pos["알림_trailing"] = True
                        self._save_positions()

                        if self.telegram.is_configured:
                            msg = (
                                f"⚠️ <b>Trailing Stop 경고!</b>\n\n"
                                f"종목: {name} ({code})\n"
                                f"최고가: {high_price:,}원\n"
                                f"현재가: {current_price:,}원\n"
                                f"하락폭: -{drop_from_high:.1f}%\n"
                                f"진입가 대비: {pnl_pct:+.1f}%\n\n"
                                f"매도하시겠습니까?"
                            )
                            buttons = [[
                                {"text": "✅ 매도", "callback_data": f"sell_{code}"},
                                {"text": "❌ 보유", "callback_data": f"hold_{code}"},
                            ]]
                            await self.telegram.send_with_buttons(msg, buttons)
                else:
                    # 정상 범위 — Trailing 알림 리셋
                    if pos.get("알림_trailing"):
                        pos["알림_trailing"] = False
                        self._save_positions()

            except Exception as e:
                alerts.append({"type": "error", "code": code, "message": str(e)})

        # 보유현황 요약
        summary = []
        for code, pos in self.positions.items():
            try:
                price_data = await self.kis.get_price(code)
                cur = int(price_data.get("stck_prpr", 0) or 0)
                entry = pos["진입가"]
                pnl = round((cur - entry) / entry * 100, 2) if entry else 0
                days = (datetime.now() - datetime.fromisoformat(pos.get("진입일", datetime.now().isoformat()))).days
                summary.append({
                    "종목": pos["종목명"],
                    "코드": code,
                    "진입가": entry,
                    "현재가": cur,
                    "수익률": f"{pnl:+.1f}%",
                    "보유일": days,
                    "목표가": pos.get("목표가", 0),
                    "손절가": pos.get("손절가", 0),
                })
            except Exception:
                pass

        return {
            "status": "success",
            "보유_종목수": len(self.positions),
            "알림_발생": len(alerts),
            "alerts": alerts,
            "보유현황": summary,
        }

    # ----------------------------------------------------------
    # 스캔 알림 (자동 스캔 결과 기반)
    # ----------------------------------------------------------
    async def send_scan_alert(self, stock_code: str, stock_name: str,
                               score: int, price: int, recommendation: str,
                               indicators: dict = None) -> dict:
        """스캔 결과 매수/매도 알림 (3단계)"""
        if not self.telegram.is_configured:
            return {"sent": False}

        atr_stop = indicators.get("ATR_손절폭", 0) if indicators else 0
        atr_target = indicators.get("ATR_익절폭", 0) if indicators else 0
        stop_price = int(price - atr_stop) if atr_stop else 0
        target_price = int(price + atr_target) if atr_target else 0

        if score >= 70:
            emoji = "🔥"
            level = "강력 매수"
            color = "매우 강함"
        elif score >= 50:
            emoji = "🟢"
            level = "적극 매수"
            color = "강함"
        elif score >= 30:
            emoji = "🟡"
            level = "매수 고려"
            color = "보통"
        elif score <= -50:
            emoji = "🔴"
            level = "적극 매도"
            color = "강한 매도"
        elif score <= -30:
            emoji = "🟠"
            level = "매도 고려"
            color = "매도"
        else:
            return {"sent": False, "reason": "알림 기준 미달"}

        stop_info = f"\n손절가: {stop_price:,}원\n목표가: {target_price:,}원" if stop_price else ""

        msg = (
            f"{emoji} <b>{level}</b> — {stock_name}\n\n"
            f"종목: {stock_name} ({stock_code})\n"
            f"현재가: {price:,}원\n"
            f"AI 점수: {score}/100 ({color})\n"
            f"추천: {recommendation}{stop_info}\n"
        )

        if score >= 30:
            buttons = [[
                {"text": f"✅ 매수 ({stock_name})", "callback_data": f"buy_{stock_code}"},
                {"text": "❌ 패스", "callback_data": f"pass_{stock_code}"},
            ]]
            await self.telegram.send_with_buttons(msg, buttons)
        else:
            await self.telegram.send(msg)

        return {"sent": True, "level": level, "score": score}

    # ----------------------------------------------------------
    # 파일 관리
    # ----------------------------------------------------------
    def _load_positions(self) -> dict:
        try:
            if POSITIONS_FILE.exists():
                with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_positions(self):
        try:
            POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.positions, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
