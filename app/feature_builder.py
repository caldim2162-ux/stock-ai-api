"""
🧬 고급 Feature Engineering (PPT 설계 기반)
- Trend: SMA, EMA, MACD, ADX, SuperTrend
- Momentum: RSI, Stochastic, CCI, ROC, Williams %R
- Volatility: ATR, Bollinger, Historical Vol
- Volume: OBV, MFI, CMF, VWAP, Volume Ratio
- Price Derived: Returns, Gap, Candle Patterns, Support/Resistance
- Market Regime: 상승장/하락장/횡보장 감지
"""

import math
from typing import Optional


class FeatureBuilder:
    """PPT 설계 기반 고급 피처 엔지니어링"""

    def build(self, daily: list[dict], accumulation: dict = None) -> dict:
        """전체 피처 계산 파이프라인"""
        if not daily or len(daily) < 5:
            return {"error": "데이터 부족"}

        closes = [d["종가"] for d in daily]
        highs = [d["고가"] for d in daily]
        lows = [d["저가"] for d in daily]
        opens = [d["시가"] for d in daily]
        volumes = [d["거래량"] for d in daily]

        f = {}

        # === TREND ===
        f.update(self._trend(closes, highs, lows))

        # === MOMENTUM ===
        f.update(self._momentum(closes, highs, lows))

        # === VOLATILITY ===
        f.update(self._volatility(closes, highs, lows))

        # === VOLUME ===
        f.update(self._volume(closes, highs, lows, volumes))

        # === PRICE DERIVED ===
        f.update(self._price_derived(closes, highs, lows, opens, volumes, daily))

        # === 수급 데이터 반영 (추가됨) ===
        if accumulation:
            f["외인_연속매수"] = accumulation.get("외국인_연속매수일", 0)
            f["기관_연속매수"] = accumulation.get("기관_연속매수일", 0)

        # === MARKET REGIME ===
        f.update(self._regime(closes, highs, lows, volumes, f))

        # === 종합 스코어 ===
        f.update(self._composite_score(f))

        return f

    # ----------------------------------------------------------
    # TREND 피처 (PPT Slide 03)
    # ----------------------------------------------------------
    def _trend(self, closes, highs, lows) -> dict:
        f = {}
        n = len(closes)

        # SMA
        for p in [5, 10, 20, 50, 100, 200]:
            if n >= p:
                f[f"SMA_{p}"] = round(sum(closes[-p:]) / p)

        # EMA
        for p in [9, 12, 26, 50, 200]:
            if n >= p:
                f[f"EMA_{p}"] = round(self._ema(closes, p))

        # 이격도 (Close / SMA20 - 1)
        if f.get("SMA_20"):
            f["이격도_20"] = round((closes[-1] / f["SMA_20"] - 1) * 100, 2)

        # MACD
        if n >= 26:
            ema12 = self._ema(closes, 12)
            ema26 = self._ema(closes, 26)
            macd = ema12 - ema26
            # MACD 히스토리 계산
            macd_hist = []
            for i in range(26, n):
                e12 = self._ema(closes[:i+1], 12)
                e26 = self._ema(closes[:i+1], 26)
                macd_hist.append(e12 - e26)
            signal = self._ema(macd_hist, 9) if len(macd_hist) >= 9 else macd
            histogram = macd - signal
            f["MACD"] = round(macd, 2)
            f["MACD_signal"] = round(signal, 2)
            f["MACD_hist"] = round(histogram, 2)
            f["MACD_판단"] = "상승 모멘텀" if histogram > 0 else "하락 모멘텀"

            # MACD 크로스
            if len(macd_hist) >= 2:
                prev_hist = macd_hist[-2] - (signal if len(macd_hist) < 9 else self._ema(macd_hist[:-1], 9))
                if prev_hist <= 0 and histogram > 0:
                    f["MACD_크로스"] = "골든크로스"
                elif prev_hist >= 0 and histogram < 0:
                    f["MACD_크로스"] = "데드크로스"

        # ADX (14일)
        if n >= 15:
            adx, adx_pos, adx_neg = self._calc_adx(highs, lows, closes, 14)
            f["ADX"] = round(adx, 1)
            f["ADX_pos"] = round(adx_pos, 1)
            f["ADX_neg"] = round(adx_neg, 1)
            if adx > 25:
                f["ADX_판단"] = "강한 추세" + (" (상승)" if adx_pos > adx_neg else " (하락)")
            else:
                f["ADX_판단"] = "약한 추세 (횡보)"

        # SuperTrend (10, 3.0)
        if n >= 15:
            st_dir = self._supertrend(highs, lows, closes, 10, 3.0)
            f["SuperTrend_방향"] = "상승" if st_dir > 0 else "하락"

        # 이평선 배열
        if f.get("SMA_5") and f.get("SMA_20") and f.get("SMA_50"):
            if f["SMA_5"] > f["SMA_20"] > f["SMA_50"]:
                f["이평선_상태"] = "완전 정배열 (강한 상승)"
            elif f["SMA_5"] > f["SMA_20"]:
                f["이평선_상태"] = "정배열 (상승 추세)"
            elif f["SMA_5"] < f["SMA_20"] < f["SMA_50"]:
                f["이평선_상태"] = "완전 역배열 (강한 하락)"
            elif f["SMA_5"] < f["SMA_20"]:
                f["이평선_상태"] = "역배열 (하락 추세)"

        # 골든/데드 크로스 (5일/20일)
        if n >= 21 and f.get("SMA_5") and f.get("SMA_20"):
            prev_ma5 = sum(closes[-6:-1]) / 5
            prev_ma20 = sum(closes[-21:-1]) / 20
            if prev_ma5 <= prev_ma20 and f["SMA_5"] > f["SMA_20"]:
                f["크로스_신호"] = "골든크로스 발생!"
            elif prev_ma5 >= prev_ma20 and f["SMA_5"] < f["SMA_20"]:
                f["크로스_신호"] = "데드크로스 발생!"

        return f

    # ----------------------------------------------------------
    # MOMENTUM 피처 (PPT Slide 04)
    # ----------------------------------------------------------
    def _momentum(self, closes, highs, lows) -> dict:
        f = {}
        n = len(closes)

        # RSI (7, 14, 21)
        for period in [7, 14, 21]:
            if n >= period + 1:
                rsi = self._calc_rsi(closes, period)
                f[f"RSI_{period}"] = round(rsi, 1)

        if f.get("RSI_14"):
            rsi = f["RSI_14"]
            if rsi >= 70:
                f["RSI_판단"] = "과매수 구간 (매도 주의)"
            elif rsi <= 30:
                f["RSI_판단"] = "과매도 구간 (매수 기회)"
            else:
                f["RSI_판단"] = "중립 구간"

        # Stochastic (14, 3)
        if n >= 14:
            k, d = self._calc_stochastic(closes, highs, lows, 14, 3)
            f["Stoch_K"] = round(k, 1)
            f["Stoch_D"] = round(d, 1)
            if k > 80:
                f["Stoch_판단"] = "과매수"
            elif k < 20:
                f["Stoch_판단"] = "과매도"
            if k > d:
                f["Stoch_크로스"] = "K>D (매수 신호)"
            else:
                f["Stoch_크로스"] = "K<D (매도 신호)"

        # CCI (20일)
        if n >= 20:
            cci = self._calc_cci(closes, highs, lows, 20)
            f["CCI_20"] = round(cci, 1)
            if cci > 100:
                f["CCI_판단"] = "과매수"
            elif cci < -100:
                f["CCI_판단"] = "과매도"
            else:
                f["CCI_판단"] = "중립"

        # ROC (5, 10, 20)
        for period in [5, 10, 20]:
            if n >= period + 1:
                roc = (closes[-1] - closes[-period-1]) / closes[-period-1] * 100
                f[f"ROC_{period}"] = round(roc, 2)

        # Williams %R (14)
        if n >= 14:
            h14 = max(highs[-14:])
            l14 = min(lows[-14:])
            willr = (h14 - closes[-1]) / (h14 - l14) * -100 if h14 != l14 else -50
            f["WilliamsR_14"] = round(willr, 1)
            if willr > -20:
                f["WilliamsR_판단"] = "과매수"
            elif willr < -80:
                f["WilliamsR_판단"] = "과매도"

        # Momentum (10, 20)
        for period in [10, 20]:
            if n >= period + 1:
                f[f"MOM_{period}"] = closes[-1] - closes[-period-1]

        return f

    # ----------------------------------------------------------
    # VOLATILITY 피처 (PPT Slide 05)
    # ----------------------------------------------------------
    def _volatility(self, closes, highs, lows) -> dict:
        f = {}
        n = len(closes)

        # ATR (7, 14, 21)
        for period in [7, 14, 21]:
            if n >= period + 1:
                atr = self._calc_atr(closes, highs, lows, period)
                f[f"ATR_{period}"] = round(atr, 1)
                f[f"ATR_{period}_pct"] = round(atr / closes[-1] * 100, 2)  # 비율 ATR

        # Bollinger Bands (20, 2)
        if n >= 20:
            bb_mean = sum(closes[-20:]) / 20
            bb_std = (sum((x - bb_mean)**2 for x in closes[-20:]) / 20) ** 0.5
            bb_upper = bb_mean + 2 * bb_std
            bb_lower = bb_mean - 2 * bb_std
            bb_width = (bb_upper - bb_lower) / bb_mean * 100
            bb_pct = (closes[-1] - bb_lower) / (bb_upper - bb_lower) * 100 if bb_upper != bb_lower else 50

            f["BB_upper"] = round(bb_upper)
            f["BB_mid"] = round(bb_mean)
            f["BB_lower"] = round(bb_lower)
            f["BB_width"] = round(bb_width, 2)
            f["BB_pct"] = round(bb_pct, 1)

            if closes[-1] >= bb_upper:
                f["BB_판단"] = "상단 밴드 돌파 (과매수)"
            elif closes[-1] <= bb_lower:
                f["BB_판단"] = "하단 밴드 돌파 (과매도)"
            else:
                f["BB_판단"] = f"밴드 내 {bb_pct:.0f}% 위치"

            # BB Squeeze (최근 125일 기준)
            if n >= 125:
                widths = []
                for i in range(max(n-125, 20), n):
                    m = sum(closes[i-20:i]) / 20
                    s = (sum((x-m)**2 for x in closes[i-20:i]) / 20) ** 0.5
                    widths.append((m + 2*s - (m - 2*s)) / m * 100)
                if bb_width < min(widths) * 1.05:
                    f["BB_Squeeze"] = "스퀴즈 감지! (폭발적 움직임 전조)"

        # Historical Volatility (10, 20, 30)
        for period in [10, 20, 30]:
            if n >= period + 1:
                log_rets = [math.log(closes[i]/closes[i-1]) for i in range(-period, 0)]
                mean = sum(log_rets) / period
                var = sum((r - mean)**2 for r in log_rets) / period
                hv = (var ** 0.5) * (252 ** 0.5) * 100
                f[f"HV_{period}"] = round(hv, 1)

        # 변동성 비율 (단기/장기)
        if f.get("HV_10") and f.get("HV_30"):
            f["HV_ratio"] = round(f["HV_10"] / f["HV_30"], 2) if f["HV_30"] > 0 else 1.0
            if f["HV_ratio"] > 1.5:
                f["변동성_판단"] = "변동성 급증 (주의)"
            elif f["HV_ratio"] < 0.7:
                f["변동성_판단"] = "변동성 축소 (스퀴즈 가능)"
            else:
                f["변동성_판단"] = "변동성 보통"

        return f

    # ----------------------------------------------------------
    # VOLUME 피처 (PPT Slide 06)
    # ----------------------------------------------------------
    def _volume(self, closes, highs, lows, volumes) -> dict:
        f = {}
        n = len(closes)

        # Volume SMA & Ratio
        if n >= 20:
            vol_sma20 = sum(volumes[-20:]) / 20
            vol_ratio = volumes[-1] / vol_sma20 if vol_sma20 > 0 else 1
            f["Vol_SMA20"] = round(vol_sma20)
            f["Vol_ratio"] = round(vol_ratio, 2)
            f["Vol_spike"] = vol_ratio > 2.0

            if vol_ratio > 2:
                f["거래량_판단"] = "거래량 급증 (강한 매매 신호)"
            elif vol_ratio > 1.5:
                f["거래량_판단"] = "거래량 증가 (관심 상승)"
            elif vol_ratio < 0.5:
                f["거래량_판단"] = "거래량 극감 (관망세)"
            else:
                f["거래량_판단"] = "보통 수준"

        # OBV (On-Balance Volume)
        if n >= 2:
            obv = 0
            obv_list = [0]
            for i in range(1, n):
                if closes[i] > closes[i-1]:
                    obv += volumes[i]
                elif closes[i] < closes[i-1]:
                    obv -= volumes[i]
                obv_list.append(obv)
            f["OBV"] = obv
            # OBV 기울기 (5일)
            if len(obv_list) >= 5:
                f["OBV_slope"] = obv_list[-1] - obv_list[-5]
                # OBV 다이버전스
                if closes[-1] > closes[-5] and f["OBV_slope"] < 0:
                    f["OBV_다이버전스"] = "약세 다이버전스 (가격↑ OBV↓)"
                elif closes[-1] < closes[-5] and f["OBV_slope"] > 0:
                    f["OBV_다이버전스"] = "강세 다이버전스 (가격↓ OBV↑)"

        # MFI (Money Flow Index, 14일)
        if n >= 15:
            mfi = self._calc_mfi(closes, highs, lows, volumes, 14)
            f["MFI_14"] = round(mfi, 1)
            if mfi > 80:
                f["MFI_판단"] = "과매수"
            elif mfi < 20:
                f["MFI_판단"] = "과매도"

        # CMF (Chaikin Money Flow, 20일)
        if n >= 20:
            cmf = self._calc_cmf(closes, highs, lows, volumes, 20)
            f["CMF_20"] = round(cmf, 4)
            f["CMF_판단"] = "매수 압력" if cmf > 0 else "매도 압력"

        return f

    # ----------------------------------------------------------
    # PRICE DERIVED 피처 (PPT Slide 07)
    # ----------------------------------------------------------
    def _price_derived(self, closes, highs, lows, opens, volumes, daily) -> dict:
        f = {}
        n = len(closes)

        # 수익률
        for period in [1, 5, 10, 20]:
            if n >= period + 1:
                ret = (closes[-1] - closes[-period-1]) / closes[-period-1] * 100
                f[f"수익률_{period}일"] = round(ret, 2)

        # 캔들 패턴 (최근 1일)
        if n >= 1:
            o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
            body = abs(c - o)
            total_range = h - l
            if total_range > 0:
                body_pct = body / total_range
                upper_wick = h - max(o, c)
                lower_wick = min(o, c) - l
                f["캔들_body_pct"] = round(body_pct, 2)
                f["캔들_양봉"] = c > o

                if body_pct < 0.05:
                    f["캔들_패턴"] = "도지 (추세 전환 가능)"
                elif body_pct > 0.7 and c > o:
                    f["캔들_패턴"] = "장대양봉 (강한 매수세)"
                elif body_pct > 0.7 and c < o:
                    f["캔들_패턴"] = "장대음봉 (강한 매도세)"
                elif lower_wick > 2 * body and c > o:
                    f["캔들_패턴"] = "망치형 (반등 가능)"
                elif upper_wick > 2 * body and c < o:
                    f["캔들_패턴"] = "유성형 (하락 가능)"
                elif n >= 2:
                    prev_body = abs(closes[-2] - opens[-2])
                    if body > prev_body and c > o and closes[-2] < opens[-2]:
                        f["캔들_패턴"] = "강세 장악형 (반전 신호)"
                    elif body > prev_body and c < o and closes[-2] > opens[-2]:
                        f["캔들_패턴"] = "약세 장악형 (반전 신호)"

        # 갭
        if n >= 2:
            gap = (opens[-1] - closes[-2]) / closes[-2] * 100
            f["갭"] = round(gap, 2)
            if gap > 0.5:
                f["갭_판단"] = "갭 상승"
            elif gap < -0.5:
                f["갭_판단"] = "갭 하락"

        # 지지/저항선 (피봇 포인트)
        if n >= 1:
            pivot = (highs[-1] + lows[-1] + closes[-1]) / 3
            r1 = 2 * pivot - lows[-1]
            s1 = 2 * pivot - highs[-1]
            f["Pivot"] = round(pivot)
            f["R1"] = round(r1)
            f["S1"] = round(s1)
            f["R1까지_거리"] = round((r1 - closes[-1]) / closes[-1] * 100, 2)
            f["S1까지_거리"] = round((closes[-1] - s1) / closes[-1] * 100, 2)

        # 52주 위치
        if n >= 60:
            high_max = max(highs[-min(252, n):])
            low_min = min(lows[-min(252, n):])
            if high_max != low_min:
                pos = (closes[-1] - low_min) / (high_max - low_min) * 100
                f["52주_위치"] = round(pos, 1)
                f["52주_고가"] = high_max
                f["52주_저가"] = low_min

        # 추세 판단
        for period in [5, 10, 20]:
            if n >= period:
                change = (closes[-1] - closes[-period]) / closes[-period] * 100
                if change > 3:
                    f[f"{period}일_추세"] = f"상승 ({change:+.1f}%)"
                elif change < -3:
                    f[f"{period}일_추세"] = f"하락 ({change:+.1f}%)"
                else:
                    f[f"{period}일_추세"] = f"횡보 ({change:+.1f}%)"

        return f

    # ----------------------------------------------------------
    # MARKET REGIME 피처 (PPT Slide 08) + HMM 대체 통계 기반
    # ----------------------------------------------------------
    def _regime(self, closes, highs, lows, volumes, features) -> dict:
        f = {}
        n = len(closes)

        # ADX 기반 Regime
        adx = features.get("ADX", 0)
        adx_pos = features.get("ADX_pos", 0)
        adx_neg = features.get("ADX_neg", 0)

        # === HMM 대체: 통계 기반 Regime Detection ===
        # 3가지 상태: Bull(상승), Bear(하락), Sideways(횡보)
        regime_score = 0  # -100 ~ +100

        # (1) 추세 방향 (가중치 35%)
        if adx > 25 and adx_pos > adx_neg:
            regime_score += 35
        elif adx > 25 and adx_neg > adx_pos:
            regime_score -= 35
        # ADX 약하면 횡보 (0점)

        # (2) 이동평균 위치 (가중치 25%)
        sma20 = features.get("SMA_20", 0)
        sma50 = features.get("SMA_50", 0)
        if sma20 and sma50 and closes[-1]:
            if closes[-1] > sma20 > sma50:
                regime_score += 25
            elif closes[-1] < sma20 < sma50:
                regime_score -= 25
            elif closes[-1] > sma20:
                regime_score += 10
            elif closes[-1] < sma20:
                regime_score -= 10

        # (3) 모멘텀 방향 (가중치 20%)
        rsi = features.get("RSI_14", 50)
        macd_hist = features.get("MACD_hist", 0)
        if rsi > 55 and macd_hist > 0:
            regime_score += 20
        elif rsi < 45 and macd_hist < 0:
            regime_score -= 20
        elif rsi > 50:
            regime_score += 5
        elif rsi < 50:
            regime_score -= 5

        # (4) 거래량 확인 (가중치 10%)
        vol_ratio = features.get("Vol_ratio", 1)
        if vol_ratio > 1.5 and regime_score > 0:
            regime_score += 10  # 상승 + 거래량 증가 = 신뢰
        elif vol_ratio > 1.5 and regime_score < 0:
            regime_score -= 10  # 하락 + 거래량 증가 = 투매

        # (5) 변동성 상태 (가중치 10%)
        hv_ratio = features.get("HV_ratio", 1.0)
        bb_squeeze = features.get("BB_Squeeze")

        f["Regime_점수"] = round(regime_score, 1)

        # 상태 분류
        if regime_score >= 30:
            f["시장_Regime"] = "강한 상승 (Strong Bull)"
            f["Regime_전략"] = "추세 추종 매수 + 비중 확대"
            f["Regime_신뢰도"] = "높음"
        elif regime_score >= 10:
            f["시장_Regime"] = "약한 상승 (Weak Bull)"
            f["Regime_전략"] = "소량 매수 + 분할 진입"
            f["Regime_신뢰도"] = "보통"
        elif regime_score <= -30:
            f["시장_Regime"] = "강한 하락 (Strong Bear)"
            f["Regime_전략"] = "매도 또는 현금 비중 확대"
            f["Regime_신뢰도"] = "높음"
        elif regime_score <= -10:
            f["시장_Regime"] = "약한 하락 (Weak Bear)"
            f["Regime_전략"] = "관망 + 반등 시 소량 매도"
            f["Regime_신뢰도"] = "보통"
        elif bb_squeeze:
            f["시장_Regime"] = "스퀴즈 (Squeeze)"
            f["Regime_전략"] = "돌파 방향 대기 + 소량만"
            f["Regime_신뢰도"] = "낮음 (방향 미정)"
        else:
            f["시장_Regime"] = "횡보 (Sideways)"
            f["Regime_전략"] = "밴드 하단 매수 / 상단 매도"
            f["Regime_신뢰도"] = "낮음"

        # 변동성 Regime
        if hv_ratio > 1.5:
            f["변동성_Regime"] = "고변동성 (포지션 50% 축소 권장)"
        elif hv_ratio > 1.2:
            f["변동성_Regime"] = "변동성 증가 (포지션 20% 축소 권장)"
        elif hv_ratio < 0.7:
            f["변동성_Regime"] = "저변동성 (포지션 확대 가능)"
        else:
            f["변동성_Regime"] = "보통 변동성"

        # 변동성 조정 계수 (Position Sizing에 사용)
        if hv_ratio > 1.5:
            f["변동성_조정계수"] = 0.5
        elif hv_ratio > 1.2:
            f["변동성_조정계수"] = 0.8
        elif hv_ratio < 0.7:
            f["변동성_조정계수"] = 1.2
        else:
            f["변동성_조정계수"] = 1.0

        # Rolling Sharpe (20일)
        if n >= 21:
            rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(-20, 0)]
            mean_ret = sum(rets) / 20
            std_ret = (sum((r - mean_ret)**2 for r in rets) / 20) ** 0.5
            sharpe = (mean_ret / (std_ret + 1e-9)) * (252 ** 0.5)
            f["Rolling_Sharpe_20"] = round(sharpe, 2)

        # ATR 기반 손절폭 (Risk Management용)
        atr_14 = features.get("ATR_14", 0)
        if atr_14 and closes[-1]:
            f["ATR_손절폭"] = round(atr_14 * 2, 0)  # ATR x 2 = 손절폭
            f["ATR_손절률"] = round(atr_14 * 2 / closes[-1] * 100, 2)  # %
            f["ATR_익절폭"] = round(atr_14 * 3, 0)  # ATR x 3 = 익절폭
            f["ATR_익절률"] = round(atr_14 * 3 / closes[-1] * 100, 2)  # %

        return f

    # ----------------------------------------------------------
    # 종합 스코어 (PPT Signal Generation 기반)
    # ----------------------------------------------------------
    def _composite_score(self, f) -> dict:
        """모든 지표를 종합하여 -100 ~ +100 스코어 계산"""
        score = 0
        signals_pos = []
        signals_neg = []

        # Trend 신호 (가중치 30%)
        trend_score = 0
        if "이평선_상태" in f:
            if "완전 정배열" in f["이평선_상태"]:
                trend_score += 30; signals_pos.append("완전 정배열")
            elif "정배열" in f["이평선_상태"]:
                trend_score += 15; signals_pos.append("정배열")
            elif "완전 역배열" in f["이평선_상태"]:
                trend_score -= 30; signals_neg.append("완전 역배열")
            elif "역배열" in f["이평선_상태"]:
                trend_score -= 15; signals_neg.append("역배열")

        if f.get("MACD_hist", 0) > 0:
            trend_score += 10; signals_pos.append("MACD 양수")
        elif f.get("MACD_hist", 0) < 0:
            trend_score -= 10; signals_neg.append("MACD 음수")

        if f.get("크로스_신호") == "골든크로스 발생!":
            trend_score += 20; signals_pos.append("골든크로스")
        elif f.get("크로스_신호") == "데드크로스 발생!":
            trend_score -= 20; signals_neg.append("데드크로스")

        if f.get("SuperTrend_방향") == "상승":
            trend_score += 10; signals_pos.append("SuperTrend 상승")
        else:
            trend_score -= 10; signals_neg.append("SuperTrend 하락")

        # Momentum 신호 (가중치 30%)
        mom_score = 0
        rsi = f.get("RSI_14", 50)
        if rsi <= 30:
            mom_score += 20; signals_pos.append(f"RSI 과매도({rsi})")
        elif rsi >= 70:
            mom_score -= 20; signals_neg.append(f"RSI 과매수({rsi})")
        elif rsi < 45:
            mom_score += 5
        elif rsi > 55:
            mom_score -= 5

        stoch_k = f.get("Stoch_K", 50)
        if stoch_k < 20:
            mom_score += 15; signals_pos.append("Stoch 과매도")
        elif stoch_k > 80:
            mom_score -= 15; signals_neg.append("Stoch 과매수")

        cci = f.get("CCI_20", 0)
        if cci < -100:
            mom_score += 10; signals_pos.append("CCI 과매도")
        elif cci > 100:
            mom_score -= 10; signals_neg.append("CCI 과매수")

        mfi = f.get("MFI_14", 50)
        if mfi < 20:
            mom_score += 10; signals_pos.append("MFI 과매도")
        elif mfi > 80:
            mom_score -= 10; signals_neg.append("MFI 과매수")

        # Volume 신호 (가중치 15%)
        vol_score = 0
        vol_ratio = f.get("Vol_ratio", 1)
        if vol_ratio > 2:
            # 거래량 급증 + 양봉 = 강한 매수 신호
            if f.get("캔들_양봉"):
                vol_score += 20; signals_pos.append("거래량 급증 + 양봉")
            else:
                vol_score -= 10; signals_neg.append("거래량 급증 + 음봉")

        if f.get("CMF_20", 0) > 0.05:
            vol_score += 10; signals_pos.append("CMF 매수 압력")
        elif f.get("CMF_20", 0) < -0.05:
            vol_score -= 10; signals_neg.append("CMF 매도 압력")

        if f.get("OBV_다이버전스", "").startswith("강세"):
            vol_score += 15; signals_pos.append("OBV 강세 다이버전스")
        elif f.get("OBV_다이버전스", "").startswith("약세"):
            vol_score -= 15; signals_neg.append("OBV 약세 다이버전스")

        # Volatility 신호 (가중치 10%)
        vol_adj = 0
        bb_pct = f.get("BB_pct", 50)
        if bb_pct <= 0:
            vol_adj += 15; signals_pos.append("BB 하단 돌파 (반등 기대)")
        elif bb_pct >= 100:
            vol_adj -= 15; signals_neg.append("BB 상단 돌파 (조정 가능)")

        if f.get("BB_Squeeze"):
            signals_pos.append("볼린저 스퀴즈 (폭발 전조)")

        # Price Derived (가중치 15%)
        price_score = 0
        pos_52w = f.get("52주_위치", 50)
        if pos_52w < 20:
            price_score += 10; signals_pos.append(f"52주 저점 부근({pos_52w}%)")
        elif pos_52w > 80:
            price_score -= 10; signals_neg.append(f"52주 고점 부근({pos_52w}%)")

        if f.get("캔들_패턴", "").endswith("(반등 가능)") or f.get("캔들_패턴", "").endswith("(반전 신호)"):
            if "강세" in f.get("캔들_패턴", ""):
                price_score += 10; signals_pos.append(f["캔들_패턴"])

        # 종합 (가중치 적용)
        total = (
            trend_score * 0.30 +
            mom_score * 0.30 +
            vol_score * 0.15 +
            vol_adj * 0.10 +
            price_score * 0.15
        )

        # === 수급 가중치 추가 (추가됨) ===
        acc_score = 0
        if f.get("외인_연속매수", 0) >= 3:
            acc_score += 10
            signals_pos.append(f"외인 {f['외인_연속매수']}일 연속매집")
        if f.get("기관_연속매수", 0) >= 3:
            acc_score += 10
            signals_pos.append(f"기관 {f['기관_연속매수']}일 연속매집")
            
        # 하락장이면 수급 점수 반감
        if "Bear" in f.get("시장_Regime", ""):
            acc_score *= 0.5
            
        total += acc_score
        
        # -100 ~ 100 범위 고정
        total = max(-100, min(100, total))

        return {
            "기술_종합점수": round(total, 1),
            "긍정_신호": signals_pos,
            "부정_신호": signals_neg,
            "신호_강도": "강" if abs(total) > 30 else "중" if abs(total) > 15 else "약",
        }
    # ----------------------------------------------------------
    # 계산 헬퍼 함수들
    # ----------------------------------------------------------
    @staticmethod
    def _ema(data, period):
        if len(data) < period:
            return sum(data) / len(data)
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for val in data[period:]:
            ema = (val - ema) * multiplier + ema
        return ema

    @staticmethod
    def _calc_rsi(closes, period):
        gains, losses = [], []
        for i in range(-period, 0):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100
        return 100 - (100 / (1 + avg_gain / avg_loss))

    @staticmethod
    def _calc_stochastic(closes, highs, lows, k_period, d_period):
        if len(closes) < k_period:
            return 50, 50
        # %K
        k_vals = []
        for i in range(max(len(closes) - k_period - d_period, k_period), len(closes)):
            h = max(highs[i-k_period+1:i+1])
            l = min(lows[i-k_period+1:i+1])
            k = ((closes[i] - l) / (h - l) * 100) if h != l else 50
            k_vals.append(k)
        # %D = SMA of %K
        d = sum(k_vals[-d_period:]) / d_period if len(k_vals) >= d_period else k_vals[-1]
        return k_vals[-1], d

    @staticmethod
    def _calc_cci(closes, highs, lows, period):
        tps = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(-period, 0)]
        tp_mean = sum(tps) / period
        md = sum(abs(tp - tp_mean) for tp in tps) / period
        if md == 0:
            return 0
        return (tps[-1] - tp_mean) / (0.015 * md)

    @staticmethod
    def _calc_atr(closes, highs, lows, period):
        trs = []
        for i in range(-period, 0):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        return sum(trs) / period

    @staticmethod
    def _calc_mfi(closes, highs, lows, volumes, period):
        pos_flow, neg_flow = 0, 0
        for i in range(-period, 0):
            tp = (highs[i] + lows[i] + closes[i]) / 3
            prev_tp = (highs[i-1] + lows[i-1] + closes[i-1]) / 3
            mf = tp * volumes[i]
            if tp > prev_tp:
                pos_flow += mf
            else:
                neg_flow += mf
        if neg_flow == 0:
            return 100
        mfr = pos_flow / neg_flow
        return 100 - (100 / (1 + mfr))

    @staticmethod
    def _calc_cmf(closes, highs, lows, volumes, period):
        cmf_num, cmf_den = 0, 0
        for i in range(-period, 0):
            hl = highs[i] - lows[i]
            if hl > 0:
                mfm = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl
            else:
                mfm = 0
            cmf_num += mfm * volumes[i]
            cmf_den += volumes[i]
        return cmf_num / cmf_den if cmf_den > 0 else 0

    def _calc_adx(self, highs, lows, closes, period):
        n = len(closes)
        if n < period + 1:
            return 0, 0, 0

        # +DM, -DM
        plus_dm, minus_dm, tr_list = [], [], []
        for i in range(1, n):
            up = highs[i] - highs[i-1]
            down = lows[i-1] - lows[i]
            plus_dm.append(up if up > down and up > 0 else 0)
            minus_dm.append(down if down > up and down > 0 else 0)
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_list.append(tr)

        # Smoothed averages
        atr = sum(tr_list[:period]) / period
        plus_di_s = sum(plus_dm[:period]) / period
        minus_di_s = sum(minus_dm[:period]) / period

        for i in range(period, len(tr_list)):
            atr = (atr * (period - 1) + tr_list[i]) / period
            plus_di_s = (plus_di_s * (period - 1) + plus_dm[i]) / period
            minus_di_s = (minus_di_s * (period - 1) + minus_dm[i]) / period

        plus_di = (plus_di_s / atr * 100) if atr > 0 else 0
        minus_di = (minus_di_s / atr * 100) if atr > 0 else 0
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0

        return dx, plus_di, minus_di

    def _supertrend(self, highs, lows, closes, period, multiplier):
        atr = self._calc_atr(closes, highs, lows, period)
        hl2 = (highs[-1] + lows[-1]) / 2
        upper = hl2 + multiplier * atr
        lower = hl2 - multiplier * atr
        return 1 if closes[-1] > lower else -1
