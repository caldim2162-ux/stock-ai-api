"""
🤖 자동 매매 엔진
- AI 추천 기반으로 자동 매수/매도 주문을 실행합니다.
- 안전장치: 일일 한도, 종목별 한도, 확인 모드, 긴급 중지
- 모든 주문은 텔레그램으로 알림이 갑니다.

⚠️ 주의: 실제 돈이 움직입니다. 충분한 테스트 후 사용하세요.
"""

import json
from datetime import datetime, date
from typing import Optional
from pathlib import Path

from app.kis_client import KISClient
from app.telegram_bot import TelegramBot

ORDER_LOG_FILE = Path(__file__).parent.parent / "data" / "order_log.json"
CONFIG_FILE = Path(__file__).parent.parent / "data" / "auto_trade_config.json"


class AutoTrader:
    """AI 추천 기반 자동 매매"""

    def __init__(self, kis: KISClient, telegram: TelegramBot):
        self.kis = kis
        self.telegram = telegram
        self.config = self._load_config()
        self._pending_orders = {}  # 텔레그램 확인 대기 주문

    # ----------------------------------------------------------
    # 설정
    # ----------------------------------------------------------
    def get_config(self) -> dict:
        return self.config

    def update_config(self, new_config: dict) -> dict:
        self.config.update(new_config)
        self._save_config()
        return self.config

    def _default_config(self) -> dict:
        return {
            "enabled": False,                  # 자동 매매 켜짐/꺼짐
            "mode": "confirm",                 # confirm: 텔레그램 확인 후 주문 / auto: 자동 주문
            "daily_limit": 500000,             # 1일 최대 주문 금액 (원)
            "per_stock_limit": 200000,         # 1종목 최대 주문 금액 (원)
            "max_stocks": 5,                   # 최대 보유 종목 수
            "min_score": 50,                   # 최소 추천 점수 (이 이상이어야 매수)
            "sell_score": -30,                 # 이 이하면 매도
            "stop_loss": -7.0,                 # 손절 기준 (%)
            "take_profit": 15.0,               # 익절 기준 (%)
            "order_type": "market",            # market: 시장가 / limit: 지정가
            "today_spent": 0,                  # 오늘 사용한 금액
            "today_date": "",                  # 오늘 날짜
            "emergency_stop": False,           # 긴급 중지
            # === PPT 설계 추가 (Position Sizing) ===
            "position_sizing": "volatility",   # fixed: 고정금액 / volatility: 변동성 기반
            "base_risk_pct": 2.0,              # 계좌 대비 1거래 최대 위험 (%) - Kelly 기반
            "max_position_pct": 20.0,          # 계좌 대비 1종목 최대 비중 (%)
            # === PPT 설계 추가 (Risk Management) ===
            "trailing_stop": True,             # Trailing Stop 활성화
            "trailing_stop_pct": 3.0,          # 최고가 대비 -N% 하락 시 매도
            "daily_loss_limit": -3.0,          # 일일 최대 손실률 (%) - Circuit Breaker
            "today_pnl": 0,                    # 오늘 실현 손익
            "max_holding_days": 20,            # 최대 보유 기간 (일) - Time-based Exit
            "positions": {},                   # 보유 포지션 추적 {종목코드: {진입가, 최고가, 진입일, 수량}}
        }

   # ----------------------------------------------------------
    # 핵심: 추천 결과 기반 자동 매매 실행
    # ----------------------------------------------------------
    async def process_recommendation(self, recommendation: dict) -> dict:
        """
        추천 결과를 받아서 자동 매매를 실행합니다.

        Returns:
            {"action": "매수/매도/관망/대기확인/차단", "detail": ...}
        """
        # 1) 기본 체크
        if not self.config.get("enabled"):
            return {"action": "비활성", "detail": "자동 매매가 꺼져있습니다."}

        if self.config.get("emergency_stop"):
            return {"action": "긴급중지", "detail": "긴급 중지 상태입니다. 해제하려면 설정을 변경하세요."}

        # 날짜 리셋
        today = date.today().isoformat()
        if self.config.get("today_date") != today:
            self.config["today_spent"] = 0
            self.config["today_date"] = today
            self._save_config()

        stock_code = recommendation.get("stock_code", "")
        stock_name = recommendation.get("stock_name", stock_code)
        score = recommendation.get("total_score", 0)
        rec = recommendation.get("recommendation", "관망")
        price = recommendation.get("price", {}).get("current", 0)
        indicators = recommendation.get("indicators", {})

        if not price or price == 0:
            return {"action": "차단", "detail": "현재가를 가져올 수 없습니다."}

        # Trailing Stop 체크 (보유 포지션)
        trailing_result = self._check_trailing_stop(stock_code, price)
        if trailing_result:
            return trailing_result

        # 보유 기간 초과 체크
        time_exit = self._check_time_exit(stock_code)
        if time_exit:
            return time_exit

        # === 시장 상황에 따른 하드 필터링 (추가됨) ===
        regime = indicators.get("시장_Regime", "")
        if "Strong Bear" in regime and "매수" in rec:
            return {"action": "차단", "detail": f"하락장(Strong Bear) 위험으로 매수 자동 차단 (점수: {score})"}

        # 2) 매수 판단
        if score >= self.config["min_score"] and "매수" in rec:
            return await self._handle_buy(stock_code, stock_name, price, score, rec, indicators)

        # 3) 매도 판단
        elif score <= self.config["sell_score"] and "매도" in rec:
            return await self._handle_sell(stock_code, stock_name, price, score, rec)

        # 4) 관망
        return {"action": "관망", "detail": f"점수 {score}, 추천 {rec} → 매매 조건 미충족"}

# ----------------------------------------------------------
    # 매수 처리
    # ----------------------------------------------------------
    async def _handle_buy(self, stock_code, stock_name, price, score, rec, indicators=None) -> dict:
        # 일일 손실 Circuit Breaker 체크
        daily_loss = self.config.get("daily_loss_limit", -3.0)
        today_pnl = self.config.get("today_pnl", 0)
        if daily_loss and today_pnl <= daily_loss:
            if self.telegram.is_configured:
                await self.telegram.send_message(
                    f"🚨 <b>Circuit Breaker 발동!</b>\n일일 손실 {today_pnl:.1f}% → 한도 {daily_loss}% 초과\n오늘 매매 자동 중단"
                )
            return {"action": "차단", "detail": f"일일 손실한도 초과 ({today_pnl:.1f}% / {daily_loss}%)"}

        # 일일 한도 체크
        remaining = self.config["daily_limit"] - self.config["today_spent"]
        if remaining <= 0:
            return {"action": "차단", "detail": f"일일 한도 소진 ({self.config['daily_limit']:,}원)"}

        # === Position Sizing (PPT 설계 기반 + 시장 상황 반영) ===
        if self.config.get("position_sizing") == "volatility" and indicators:
            
            # 시장 상황에 따른 비중 조절 (추가됨)
            regime = indicators.get("시장_Regime", "")
            regime_adj = 1.0
            if "Weak Bull" in regime: 
                regime_adj = 0.8  # 약한 상승장은 비중 80%
            elif "Sideways" in regime or "Squeeze" in regime: 
                regime_adj = 0.5  # 횡보장/스퀴즈는 비중 50%
            elif "Bear" in regime:
                regime_adj = 0.3  # 예외적으로 하락장에서 살 경우 비중 30%

            # 변동성 기반: ATR로 포지션 크기 결정
            atr_stop = indicators.get("ATR_손절률", 3.0)  # ATR 기반 손절률 %
            vol_adj = indicators.get("변동성_조정계수", 1.0)
            risk_pct = self.config.get("base_risk_pct", 2.0)

            # Kelly-like: 위험금액 = 계좌 * risk% / 손절폭%
            # 변동성 및 시장상황(regime_adj) 반영
            if atr_stop > 0:
                risk_amount = self.config["daily_limit"] * (risk_pct / 100)
                max_amount = int((risk_amount / (atr_stop / 100)) * vol_adj * regime_adj)
            else:
                max_amount = int(self.config["per_stock_limit"] * regime_adj)

            max_amount = min(max_amount, remaining, self.config["per_stock_limit"])
            sizing_method = f"변동성 기반 (ATR 손절 {atr_stop}%, 조정계수 {vol_adj}, 시장계수 {regime_adj})"
        else:
            # 고정 금액
            max_amount = min(remaining, self.config["per_stock_limit"])
            sizing_method = "고정 금액"

        quantity = max_amount // price
        if quantity <= 0:
            return {"action": "차단", "detail": f"매수 가능 수량 없음 (가격 {price:,}원, 한도 {max_amount:,}원)"}

        order_amount = quantity * price

        # ATR 기반 손절/익절가 계산
        atr_stop_price = 0
        atr_target_price = 0
        if indicators:
            atr_stop_amt = indicators.get("ATR_손절폭", 0)
            atr_target_amt = indicators.get("ATR_익절폭", 0)
            if atr_stop_amt:
                atr_stop_price = int(price - atr_stop_amt)
                atr_target_price = int(price + atr_target_amt)

        # 확인 모드
        if self.config["mode"] == "confirm":
            order_id = f"{stock_code}_{datetime.now().strftime('%H%M%S')}"
            self._pending_orders[order_id] = {
                "type": "buy",
                "stock_code": stock_code,
                "stock_name": stock_name,
                "price": price,
                "quantity": quantity,
                "amount": order_amount,
                "score": score,
                "sizing_method": sizing_method,
                "atr_stop_price": atr_stop_price,
                "atr_target_price": atr_target_price,
                "created": datetime.now().isoformat(),
            }

            # 텔레그램으로 확인 요청
            if self.telegram.is_configured:
                stop_info = f"\nATR 손절가: {atr_stop_price:,}원\nATR 목표가: {atr_target_price:,}원" if atr_stop_price else ""
                msg = (
                    f"🟢 <b>매수 확인 요청</b>\n\n"
                    f"종목: {stock_name} ({stock_code})\n"
                    f"가격: {price:,}원\n"
                    f"수량: {quantity}주\n"
                    f"금액: {order_amount:,}원\n"
                    f"점수: {score}/100\n"
                    f"포지션: {sizing_method}{stop_info}\n\n"
                    f"<b>ㅇ</b> 입력 → 승인\n"
                    f"<b>ㄴ</b> 입력 → 거부"
                )
                buttons = [[
                    {"text": "✅ 승인", "callback_data": f"approve_{order_id}"},
                    {"text": "❌ 거부", "callback_data": f"reject_{order_id}"},
                ]]
                await self.telegram.send_with_buttons(msg, buttons)

            return {
                "action": "대기확인",
                "order_id": order_id,
                "detail": f"{stock_name} {quantity}주 {order_amount:,}원 매수 확인 대기 중",
                "sizing": sizing_method,
                "atr_stop": atr_stop_price,
                "atr_target": atr_target_price,
            }

        # 자동 모드: 바로 주문
        return await self._execute_buy(stock_code, stock_name, price, quantity, order_amount, score)
    # ----------------------------------------------------------
    # 매도 처리
    # ----------------------------------------------------------
    async def _handle_sell(self, stock_code, stock_name, price, score, rec) -> dict:
        # 보유 여부 확인은 수동으로 해야 함 (실전에서는 잔고 조회 후 판단)
        # 여기서는 주문만 내는 구조

        if self.config["mode"] == "confirm":
            order_id = f"{stock_code}_sell_{datetime.now().strftime('%H%M%S')}"
            self._pending_orders[order_id] = {
                "type": "sell",
                "stock_code": stock_code,
                "stock_name": stock_name,
                "price": price,
                "quantity": 0,  # 전량 매도 시 잔고에서 확인
                "score": score,
                "created": datetime.now().isoformat(),
            }

            if self.telegram.is_configured:
                msg = (
                    f"🔴 <b>매도 확인 요청</b>\n\n"
                    f"종목: {stock_name} ({stock_code})\n"
                    f"현재가: {price:,}원\n"
                    f"점수: {score}/100\n\n"
                    f"<b>ㅇ</b> 입력 → 승인\n"
                    f"<b>ㄴ</b> 입력 → 거부"
                )
                buttons = [[
                    {"text": "✅ 승인", "callback_data": f"approve_{order_id}"},
                    {"text": "❌ 거부", "callback_data": f"reject_{order_id}"},
                ]]
                await self.telegram.send_with_buttons(msg, buttons)

            return {
                "action": "대기확인",
                "order_id": order_id,
                "detail": f"{stock_name} 매도 확인 대기 중",
            }

        # 자동 매도는 위험하므로 항상 확인 모드 사용 권장
        return {"action": "대기확인", "detail": "매도는 확인 모드에서만 실행합니다."}

    # ----------------------------------------------------------
    # 주문 승인 (확인 모드에서 사용)
    # ----------------------------------------------------------
    async def approve_order(self, order_id: str) -> dict:
        """대기 중인 주문을 승인하여 실행합니다."""
        order = self._pending_orders.pop(order_id, None)
        if not order:
            return {"status": "실패", "detail": f"주문 ID {order_id}를 찾을 수 없습니다."}

        if order["type"] == "buy":
            return await self._execute_buy(
                order["stock_code"], order["stock_name"],
                order["price"], order["quantity"], order["amount"], order["score"]
            )
        elif order["type"] == "sell":
            return await self._execute_sell(
                order["stock_code"], order["stock_name"],
                order["price"], order.get("quantity", 0)
            )

        return {"status": "실패", "detail": "알 수 없는 주문 유형"}

    # ----------------------------------------------------------
    # 주문 거부
    # ----------------------------------------------------------
    def reject_order(self, order_id: str) -> dict:
        order = self._pending_orders.pop(order_id, None)
        if not order:
            return {"status": "실패", "detail": f"주문 ID {order_id}를 찾을 수 없습니다."}
        return {"status": "거부", "detail": f"{order['stock_name']} 주문이 거부되었습니다."}

    # ----------------------------------------------------------
    # 대기 주문 목록
    # ----------------------------------------------------------
    def get_pending_orders(self) -> list[dict]:
        return [
            {"order_id": k, **v}
            for k, v in self._pending_orders.items()
        ]

    # ----------------------------------------------------------
    # 실제 매수 실행
    # ----------------------------------------------------------
    async def _execute_buy(self, stock_code, stock_name, price, quantity, amount, score) -> dict:
        try:
            is_market = self.config["order_type"] == "market"
            result = await self.kis.buy_order(
                stock_code=stock_code,
                quantity=quantity,
                price=0 if is_market else price,
            )

            # 일일 사용 금액 업데이트
            self.config["today_spent"] += amount
            self._save_config()

            # 포지션 등록 (Trailing Stop 추적용)
            self.register_position(stock_code, price, quantity)

            # 주문 로그 저장
            self._log_order("매수", stock_code, stock_name, price, quantity, amount, score, result)

            # 텔레그램 알림
            if self.telegram.is_configured:
                msg = (
                    f"✅ <b>매수 주문 완료!</b>\n\n"
                    f"종목: {stock_name}\n"
                    f"수량: {quantity}주\n"
                    f"금액: {amount:,}원\n"
                    f"주문번호: {result.get('주문번호', '')}\n"
                    f"오늘 남은 한도: {self.config['daily_limit'] - self.config['today_spent']:,}원"
                )
                await self.telegram.send(msg)

            return {
                "action": "매수완료",
                "detail": result,
                "남은한도": f"{self.config['daily_limit'] - self.config['today_spent']:,}원",
            }

        except Exception as e:
            if self.telegram.is_configured:
                await self.telegram.send(f"❌ 매수 주문 실패: {stock_name}\n{str(e)}")
            return {"action": "실패", "detail": str(e)}

    # ----------------------------------------------------------
    # 실제 매도 실행
    # ----------------------------------------------------------
    async def _execute_sell(self, stock_code, stock_name, price, quantity) -> dict:
        try:
            # 수량이 0이면 잔고에서 확인 필요
            if quantity <= 0:
                return {"action": "실패", "detail": "매도 수량을 지정해주세요."}

            is_market = self.config["order_type"] == "market"
            result = await self.kis.sell_order(
                stock_code=stock_code,
                quantity=quantity,
                price=0 if is_market else price,
            )

            self._log_order("매도", stock_code, stock_name, price, quantity, quantity * price, 0, result)

            if self.telegram.is_configured:
                msg = (
                    f"✅ <b>매도 주문 완료!</b>\n\n"
                    f"종목: {stock_name}\n"
                    f"수량: {quantity}주\n"
                    f"주문번호: {result.get('주문번호', '')}"
                )
                await self.telegram.send(msg)

            return {"action": "매도완료", "detail": result}

        except Exception as e:
            if self.telegram.is_configured:
                await self.telegram.send(f"❌ 매도 주문 실패: {stock_name}\n{str(e)}")
            return {"action": "실패", "detail": str(e)}

    # ----------------------------------------------------------
    # 긴급 중지
    # ----------------------------------------------------------
    def emergency_stop(self) -> dict:
        self.config["emergency_stop"] = True
        self.config["enabled"] = False
        self._save_config()
        self._pending_orders.clear()
        return {"status": "긴급 중지 완료", "detail": "모든 대기 주문이 취소되고 자동 매매가 꺼졌습니다."}

    def resume(self) -> dict:
        self.config["emergency_stop"] = False
        self.config["enabled"] = True
        self._save_config()
        return {"status": "재개", "detail": "자동 매매가 다시 켜졌습니다."}

    # ----------------------------------------------------------
    # 주문 로그
    # ----------------------------------------------------------
    def _log_order(self, order_type, stock_code, stock_name, price, quantity, amount, score, result):
        try:
            ORDER_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            logs = []
            if ORDER_LOG_FILE.exists():
                with open(ORDER_LOG_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            logs.append({
                "시간": datetime.now().isoformat(),
                "유형": order_type,
                "종목코드": stock_code,
                "종목명": stock_name,
                "가격": price,
                "수량": quantity,
                "금액": amount,
                "점수": score,
                "주문번호": result.get("주문번호", ""),
                "상태": result.get("status", ""),
            })
            logs = logs[-200:]
            with open(ORDER_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_order_log(self, limit: int = 30) -> list[dict]:
        try:
            if ORDER_LOG_FILE.exists():
                with open(ORDER_LOG_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
                return logs[-limit:]
        except Exception:
            pass
        return []

    # ----------------------------------------------------------
    # 설정 파일 관리
    # ----------------------------------------------------------
    def _load_config(self) -> dict:
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                default = self._default_config()
                default.update(saved)
                return default
        except Exception:
            pass
        return self._default_config()

    def _save_config(self):
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ----------------------------------------------------------
    # Trailing Stop (PPT Risk Management)
    # ----------------------------------------------------------
    def _check_trailing_stop(self, stock_code: str, current_price: int) -> Optional[dict]:
        """보유 포지션의 Trailing Stop 체크"""
        if not self.config.get("trailing_stop"):
            return None

        positions = self.config.get("positions", {})
        pos = positions.get(stock_code)
        if not pos:
            return None

        entry_price = pos.get("진입가", 0)
        high_price = pos.get("최고가", entry_price)
        trailing_pct = self.config.get("trailing_stop_pct", 3.0)

        # 최고가 갱신
        if current_price > high_price:
            pos["최고가"] = current_price
            self.config["positions"][stock_code] = pos
            self._save_config()
            return None

        # Trailing Stop 체크: 최고가 대비 N% 하락
        if high_price > 0:
            drop_pct = (high_price - current_price) / high_price * 100
            if drop_pct >= trailing_pct:
                profit_pct = (current_price - entry_price) / entry_price * 100
                return {
                    "action": "trailing_stop",
                    "detail": f"Trailing Stop 발동! 최고가 {high_price:,}원 대비 -{drop_pct:.1f}% 하락 (진입가 대비 {profit_pct:+.1f}%)",
                    "stock_code": stock_code,
                    "trigger": "trailing_stop",
                }

        # 고정 손절 체크: 진입가 대비 N% 하락
        if entry_price > 0:
            loss_pct = (current_price - entry_price) / entry_price * 100
            stop_loss = self.config.get("stop_loss", -7.0)
            if loss_pct <= stop_loss:
                return {
                    "action": "stop_loss",
                    "detail": f"손절 발동! 진입가 {entry_price:,}원 대비 {loss_pct:.1f}% 하락 (한도 {stop_loss}%)",
                    "stock_code": stock_code,
                    "trigger": "stop_loss",
                }

        return None

    # ----------------------------------------------------------
    # Time-based Exit (보유 기간 초과 청산)
    # ----------------------------------------------------------
    def _check_time_exit(self, stock_code: str) -> Optional[dict]:
        """보유 기간 초과 시 매도 신호"""
        positions = self.config.get("positions", {})
        pos = positions.get(stock_code)
        if not pos:
            return None

        max_days = self.config.get("max_holding_days", 20)
        entry_date = pos.get("진입일", "")
        if not entry_date:
            return None

        try:
            entry = datetime.fromisoformat(entry_date)
            holding_days = (datetime.now() - entry).days
            if holding_days >= max_days:
                return {
                    "action": "time_exit",
                    "detail": f"보유 기간 {holding_days}일 → 최대 {max_days}일 초과. 청산 검토 필요.",
                    "stock_code": stock_code,
                    "trigger": "time_exit",
                }
        except Exception:
            pass

        return None

    # ----------------------------------------------------------
    # 포지션 등록/해제
    # ----------------------------------------------------------
    def register_position(self, stock_code: str, entry_price: int, quantity: int) -> dict:
        """매수 체결 후 포지션 등록"""
        if "positions" not in self.config:
            self.config["positions"] = {}
        self.config["positions"][stock_code] = {
            "진입가": entry_price,
            "최고가": entry_price,
            "진입일": datetime.now().isoformat(),
            "수량": quantity,
        }
        self._save_config()
        return {"status": "등록", "stock_code": stock_code, "entry_price": entry_price}

    def remove_position(self, stock_code: str, exit_price: int = 0) -> dict:
        """매도 후 포지션 해제 + 손익 기록"""
        positions = self.config.get("positions", {})
        pos = positions.pop(stock_code, None)
        if not pos:
            return {"status": "없음", "detail": "해당 종목 포지션 없음"}

        # 손익 계산
        entry_price = pos.get("진입가", 0)
        pnl_pct = 0
        if entry_price and exit_price:
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            # 일일 손익 누적
            self.config["today_pnl"] = self.config.get("today_pnl", 0) + pnl_pct

        self.config["positions"] = positions
        self._save_config()
        return {"status": "해제", "stock_code": stock_code, "pnl": f"{pnl_pct:+.1f}%"}

    def get_positions(self) -> dict:
        """현재 보유 포지션 목록"""
        return self.config.get("positions", {})

    # ----------------------------------------------------------
    # Position Sizing 정보 조회
    # ----------------------------------------------------------
    def get_risk_status(self) -> dict:
        """현재 리스크 상태 요약"""
        positions = self.config.get("positions", {})
        return {
            "포지션_수": len(positions),
            "포지션_목록": {k: {
                "진입가": v["진입가"],
                "최고가": v.get("최고가", v["진입가"]),
                "수량": v.get("수량", 0),
                "보유일": (datetime.now() - datetime.fromisoformat(v.get("진입일", datetime.now().isoformat()))).days if v.get("진입일") else 0,
            } for k, v in positions.items()},
            "일일_손익": f"{self.config.get('today_pnl', 0):+.1f}%",
            "일일_손실한도": f"{self.config.get('daily_loss_limit', -3.0)}%",
            "trailing_stop": f"{self.config.get('trailing_stop_pct', 3.0)}%",
            "포지션_사이징": self.config.get("position_sizing", "fixed"),
            "긴급중지": self.config.get("emergency_stop", False),
        }
