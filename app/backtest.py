"""
🔬 백테스팅 엔진
- 과거 데이터로 매매 전략을 시뮬레이션합니다.
- 수수료/세금 반영한 실제 수익률을 계산합니다.
- 전략별 승률, 최대 낙폭, 샤프비율 등을 산출합니다.
"""

import json
from datetime import datetime
from typing import Optional
from pathlib import Path

from app.kis_client import KISClient

BACKTEST_HISTORY = Path(__file__).parent.parent / "data" / "backtest_results.json"

# 수수료/세금
BUY_FEE = 0.00015    # 매수 수수료 0.015%
SELL_FEE = 0.00015   # 매도 수수료 0.015%
TAX = 0.0018         # 거래세 0.18%


class BacktestEngine:
    """과거 데이터로 매매 전략을 검증합니다."""

    def __init__(self, kis: KISClient):
        self.kis = kis

    # ----------------------------------------------------------
    # 메인: 백테스트 실행
    # ----------------------------------------------------------
    async def run(
        self,
        stock_code: str,
        strategy: str = "ma_cross",
        initial_capital: int = 1000000,
        days: int = 90,
        params: Optional[dict] = None,
    ) -> dict:
        """
        백테스트를 실행합니다.

        Args:
            stock_code: 종목코드
            strategy: 전략명 (ma_cross, rsi, macd, bollinger, combined)
            initial_capital: 초기 자본금 (원)
            days: 테스트 기간 (거래일 수)
            params: 전략 파라미터 (선택)

        Returns:
            수익률, 승률, 거래 내역 등
        """
        # 일봉 데이터 가져오기
        daily = await self.kis.get_daily_prices(stock_code, count=days)
        if not daily or len(daily) < 20:
            return {"error": "데이터 부족 (최소 20일 필요, 장 운영시간에 시도하세요)"}

        # 종목명 가져오기
        try:
            price_info = await self.kis.get_current_price(stock_code)
            stock_name = price_info.get("종목명", stock_code)
        except Exception:
            stock_name = stock_code

        # 전략 선택
        strategy_func = {
            "ma_cross": self._strategy_ma_cross,
            "rsi": self._strategy_rsi,
            "macd": self._strategy_macd,
            "bollinger": self._strategy_bollinger,
            "combined": self._strategy_combined,
        }.get(strategy, self._strategy_ma_cross)

        # 시뮬레이션 실행
        trades, equity_curve = self._simulate(
            daily=daily,
            strategy_func=strategy_func,
            initial_capital=initial_capital,
            params=params or {},
        )

        # 통계 계산
        stats = self._calculate_stats(
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=initial_capital,
            daily=daily,
        )

        result = {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "strategy": strategy,
            "기간": f"{daily[0]['날짜']} ~ {daily[-1]['날짜']}",
            "거래일수": len(daily),
            "초기자본": f"{initial_capital:,}원",
            "stats": stats,
            "trades": trades,
            "equity_curve": equity_curve[-20:],  # 최근 20일 자산 추이
            "timestamp": datetime.now().isoformat(),
        }

        # 결과 저장
        self._save_result(result)

        return result

    # ----------------------------------------------------------
    # 시뮬레이션 엔진
    # ----------------------------------------------------------
    def _simulate(
        self,
        daily: list[dict],
        strategy_func,
        initial_capital: int,
        params: dict,
    ) -> tuple[list[dict], list[dict]]:
        """매매 시뮬레이션을 실행합니다."""
        capital = initial_capital
        holding = 0          # 보유 수량
        buy_price = 0        # 매수 평균가
        trades = []          # 거래 내역
        equity_curve = []    # 자산 추이

        closes = [d["종가"] for d in daily]
        highs = [d["고가"] for d in daily]
        lows = [d["저가"] for d in daily]
        volumes = [d["거래량"] for d in daily]

        for i in range(20, len(daily)):  # 최소 20일 이후부터
            price = closes[i]
            date = daily[i]["날짜"]

            # 전략 신호 생성
            signal = strategy_func(
                closes=closes[:i+1],
                highs=highs[:i+1],
                lows=lows[:i+1],
                volumes=volumes[:i+1],
                params=params,
            )

            # 매수 신호 + 미보유 상태
            if signal == "BUY" and holding == 0 and capital > 0:
                # 매수 수량 계산 (전액 투자)
                fee = int(capital * BUY_FEE)
                available = capital - fee
                holding = available // price
                if holding > 0:
                    cost = holding * price + fee
                    capital -= cost
                    buy_price = price
                    trades.append({
                        "날짜": date,
                        "유형": "매수",
                        "가격": price,
                        "수량": holding,
                        "금액": f"{cost:,}원",
                        "수수료": f"{fee:,}원",
                    })

            # 매도 신호 + 보유 상태
            elif signal == "SELL" and holding > 0:
                revenue = holding * price
                sell_fee = int(revenue * SELL_FEE)
                tax = int(revenue * TAX)
                net = revenue - sell_fee - tax
                capital += net

                profit = net - (holding * buy_price)
                profit_pct = (price - buy_price) / buy_price * 100

                trades.append({
                    "날짜": date,
                    "유형": "매도",
                    "가격": price,
                    "수량": holding,
                    "금액": f"{net:,}원",
                    "수수료": f"{sell_fee + tax:,}원",
                    "수익": f"{profit:,}원",
                    "수익률": f"{profit_pct:+.2f}%",
                })
                holding = 0
                buy_price = 0

            # 자산 추이 기록
            total_value = capital + (holding * price)
            equity_curve.append({
                "날짜": date,
                "자산": total_value,
                "현금": capital,
                "주식가치": holding * price,
                "수익률": round((total_value - initial_capital) / initial_capital * 100, 2),
            })

        # 마지막에 보유 중이면 평가
        if holding > 0:
            final_price = closes[-1]
            total_value = capital + (holding * final_price)
        else:
            total_value = capital

        return trades, equity_curve

    # ----------------------------------------------------------
    # 전략들
    # ----------------------------------------------------------
    def _strategy_ma_cross(self, closes, highs, lows, volumes, params):
        """이동평균 교차 전략 (골든크로스/데드크로스)"""
        short_p = params.get("short", 5)
        long_p = params.get("long", 20)
        if len(closes) < long_p + 1:
            return "HOLD"

        ma_short = sum(closes[-short_p:]) / short_p
        ma_long = sum(closes[-long_p:]) / long_p
        prev_short = sum(closes[-short_p-1:-1]) / short_p
        prev_long = sum(closes[-long_p-1:-1]) / long_p

        if prev_short <= prev_long and ma_short > ma_long:
            return "BUY"
        elif prev_short >= prev_long and ma_short < ma_long:
            return "SELL"
        return "HOLD"

    def _strategy_rsi(self, closes, highs, lows, volumes, params):
        """RSI 전략"""
        period = params.get("period", 14)
        buy_level = params.get("buy", 30)
        sell_level = params.get("sell", 70)
        if len(closes) < period + 1:
            return "HOLD"

        gains, losses = [], []
        for i in range(-period, 0):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            rsi = 100
        else:
            rsi = 100 - (100 / (1 + avg_gain / avg_loss))

        if rsi <= buy_level:
            return "BUY"
        elif rsi >= sell_level:
            return "SELL"
        return "HOLD"

    def _strategy_macd(self, closes, highs, lows, volumes, params):
        """MACD 전략"""
        if len(closes) < 27:
            return "HOLD"

        def ema(data, period):
            multiplier = 2 / (period + 1)
            val = sum(data[:period]) / period
            for d in data[period:]:
                val = (d - val) * multiplier + val
            return val

        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        macd = ema12 - ema26

        prev_closes = closes[:-1]
        prev_ema12 = ema(prev_closes, 12)
        prev_ema26 = ema(prev_closes, 26)
        prev_macd = prev_ema12 - prev_ema26

        if prev_macd <= 0 and macd > 0:
            return "BUY"
        elif prev_macd >= 0 and macd < 0:
            return "SELL"
        return "HOLD"

    def _strategy_bollinger(self, closes, highs, lows, volumes, params):
        """볼린저 밴드 전략"""
        period = params.get("period", 20)
        if len(closes) < period:
            return "HOLD"

        recent = closes[-period:]
        mean = sum(recent) / period
        std = (sum((x - mean) ** 2 for x in recent) / period) ** 0.5
        upper = mean + 2 * std
        lower = mean - 2 * std
        price = closes[-1]

        if price <= lower:
            return "BUY"
        elif price >= upper:
            return "SELL"
        return "HOLD"

    def _strategy_combined(self, closes, highs, lows, volumes, params):
        """복합 전략 (MA + RSI + 거래량)"""
        signals = []
        signals.append(self._strategy_ma_cross(closes, highs, lows, volumes, params))
        signals.append(self._strategy_rsi(closes, highs, lows, volumes, params))

        # 거래량 확인 (20일 평균 대비 1.5배 이상이면 신호 강화)
        if len(volumes) >= 20:
            avg_vol = sum(volumes[-20:]) / 20
            vol_surge = volumes[-1] > avg_vol * 1.5
        else:
            vol_surge = False

        buy_count = signals.count("BUY")
        sell_count = signals.count("SELL")

        # 2개 이상 매수 신호 또는 1개 + 거래량 급증
        if buy_count >= 2 or (buy_count >= 1 and vol_surge):
            return "BUY"
        elif sell_count >= 2 or (sell_count >= 1 and vol_surge):
            return "SELL"
        return "HOLD"

    # ----------------------------------------------------------
    # 통계 계산
    # ----------------------------------------------------------
    def _calculate_stats(self, trades, equity_curve, initial_capital, daily):
        """백테스트 결과 통계 (PPT 설계 KPI 추가)"""
        if not equity_curve:
            return {"error": "거래 없음"}

        import math

        final_value = equity_curve[-1]["자산"]
        total_return = (final_value - initial_capital) / initial_capital * 100

        # 거래 통계
        sell_trades = [t for t in trades if t["유형"] == "매도"]
        wins = [t for t in sell_trades if "수익률" in t and float(t["수익률"].replace("%", "").replace("+", "")) > 0]
        losses = [t for t in sell_trades if "수익률" in t and float(t["수익률"].replace("%", "").replace("+", "")) <= 0]

        win_rate = len(wins) / len(sell_trades) * 100 if sell_trades else 0

        # 최대 낙폭 (MDD)
        peak = initial_capital
        max_dd = 0
        for eq in equity_curve:
            if eq["자산"] > peak:
                peak = eq["자산"]
            dd = (peak - eq["자산"]) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # 바이앤홀드 비교
        buy_hold = (daily[-1]["종가"] - daily[0]["종가"]) / daily[0]["종가"] * 100 if daily else 0

        # 평균 수익/손실
        avg_win = sum(float(t["수익률"].replace("%", "").replace("+", "")) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(float(t["수익률"].replace("%", "").replace("+", "")) for t in losses) / len(losses) if losses else 0

        # ===== PPT 설계 추가 KPI =====

        # 일별 수익률 계산
        daily_returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i-1]["자산"]
            curr = equity_curve[i]["자산"]
            if prev > 0:
                daily_returns.append((curr - prev) / prev)

        # Sharpe Ratio (연환산)
        sharpe = 0
        if daily_returns:
            mean_ret = sum(daily_returns) / len(daily_returns)
            std_ret = (sum((r - mean_ret)**2 for r in daily_returns) / len(daily_returns)) ** 0.5
            sharpe = (mean_ret / (std_ret + 1e-9)) * (252 ** 0.5)

        # Sortino Ratio (하방 변동성만)
        sortino = 0
        if daily_returns:
            mean_ret = sum(daily_returns) / len(daily_returns)
            neg_rets = [r for r in daily_returns if r < 0]
            down_std = (sum(r**2 for r in neg_rets) / max(len(neg_rets), 1)) ** 0.5
            sortino = (mean_ret / (down_std + 1e-9)) * (252 ** 0.5)

        # Calmar Ratio (수익률 / MDD)
        calmar = total_return / max_dd if max_dd > 0 else 0

        # Profit Factor (총이익 / 총손실)
        total_profit = sum(float(t["수익률"].replace("%", "").replace("+", "")) for t in wins) if wins else 0
        total_loss = abs(sum(float(t["수익률"].replace("%", "").replace("+", "")) for t in losses)) if losses else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else (999 if total_profit > 0 else 0)

        # 손익비 (Risk/Reward Ratio)
        rrr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # CAGR (연환산 수익률)
        trading_days = len(equity_curve)
        years = trading_days / 252 if trading_days > 0 else 1
        cagr = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0

        return {
            "최종자산": f"{final_value:,}원",
            "총수익률": f"{total_return:+.2f}%",
            "CAGR": f"{cagr:+.2f}%",
            "총거래횟수": len(sell_trades),
            "승리": len(wins),
            "패배": len(losses),
            "승률": f"{win_rate:.1f}%",
            "평균_수익": f"{avg_win:+.2f}%",
            "평균_손실": f"{avg_loss:+.2f}%",
            "손익비_RRR": f"1:{rrr:.1f}",
            "Profit_Factor": round(profit_factor, 2),
            "Sharpe_Ratio": round(sharpe, 2),
            "Sortino_Ratio": round(sortino, 2),
            "Calmar_Ratio": round(calmar, 2),
            "최대낙폭_MDD": f"{max_dd:.2f}%",
            "바이앤홀드_수익률": f"{buy_hold:+.2f}%",
            "전략_vs_바이앤홀드": f"{total_return - buy_hold:+.2f}%p",
            "수수료_포함": "예 (매수0.015% + 매도0.015% + 거래세0.18%)",
        }

    # ----------------------------------------------------------
    # 전략 비교 (여러 전략 한번에)
    # ----------------------------------------------------------
    async def compare_strategies(
        self,
        stock_code: str,
        initial_capital: int = 1000000,
        days: int = 90,
    ) -> dict:
        """모든 전략을 한 종목에 대해 비교합니다."""
        strategies = ["ma_cross", "rsi", "macd", "bollinger", "combined"]
        results = {}
        for s in strategies:
            try:
                r = await self.run(stock_code, s, initial_capital, days)
                results[s] = {
                    "총수익률": r["stats"].get("총수익률", "-"),
                    "승률": r["stats"].get("승률", "-"),
                    "거래횟수": r["stats"].get("총거래횟수", 0),
                    "최대낙폭": r["stats"].get("최대낙폭_MDD", "-"),
                    "vs_바이앤홀드": r["stats"].get("전략_vs_바이앤홀드", "-"),
                }
            except Exception as e:
                results[s] = {"error": str(e)}

        return {
            "stock_code": stock_code,
            "기간": f"{days}거래일",
            "초기자본": f"{initial_capital:,}원",
            "strategies": results,
        }

    # ----------------------------------------------------------
    # 저장
    # ----------------------------------------------------------
    def _save_result(self, result: dict):
        try:
            BACKTEST_HISTORY.parent.mkdir(parents=True, exist_ok=True)
            history = []
            if BACKTEST_HISTORY.exists():
                with open(BACKTEST_HISTORY, "r", encoding="utf-8") as f:
                    history = json.load(f)
            history.append({
                "timestamp": result["timestamp"],
                "stock": result["stock_name"],
                "strategy": result["strategy"],
                "수익률": result["stats"].get("총수익률", "-"),
                "승률": result["stats"].get("승률", "-"),
            })
            history = history[-50:]
            with open(BACKTEST_HISTORY, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def get_strategy_list() -> dict:
        return {
            "ma_cross": {"name": "이동평균 교차", "설명": "5일선이 20일선을 상향돌파하면 매수, 하향돌파하면 매도", "params": {"short": 5, "long": 20}},
            "rsi": {"name": "RSI", "설명": "RSI 30 이하면 매수, 70 이상이면 매도", "params": {"period": 14, "buy": 30, "sell": 70}},
            "macd": {"name": "MACD", "설명": "MACD가 0선 상향돌파하면 매수, 하향돌파하면 매도", "params": {}},
            "bollinger": {"name": "볼린저 밴드", "설명": "하단 밴드 터치하면 매수, 상단 밴드 터치하면 매도", "params": {"period": 20}},
            "combined": {"name": "복합 전략", "설명": "MA + RSI + 거래량 신호를 종합하여 판단", "params": {}},
        }
