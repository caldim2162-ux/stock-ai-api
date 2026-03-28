"""
🤖 ML 예측 엔진 (XGBoost)
- Google Colab에서 학습한 모델을 로드하여 매수/관망/매도 예측
- 기존 규칙 기반 + 뉴스 감성 + ML 예측 = 3중 판단
"""

import json
import os
import math
from typing import Optional


class MLPredictor:
    """학습된 XGBoost 모델로 매매 예측"""

    def __init__(self, data_dir: str = None):
        self.model = None
        self.model_info = None
        self.feature_cols = []
        self.loaded = False
        # 프로젝트 루트 기준 data/ 폴더
        if data_dir is None:
            self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        else:
            self.data_dir = data_dir
        self._load_model()

    def _load_model(self):
        """모델 파일 로드"""
        model_path = os.path.join(self.data_dir, "stock_xgb_model.json")
        info_path = os.path.join(self.data_dir, "model_info.json")

        if not os.path.exists(model_path) or not os.path.exists(info_path):
            print("⚠️ ML 모델 파일 없음 (data/stock_xgb_model.json)")
            return

        try:
            import xgboost as xgb
            self.model = xgb.XGBClassifier()
            self.model.load_model(model_path)

            with open(info_path, "r", encoding="utf-8") as f:
                self.model_info = json.load(f)

            self.feature_cols = self.model_info.get("feature_columns", [])
            self.loaded = True
            print(f"✅ ML 모델 로드 완료 (피처 {len(self.feature_cols)}개, 정확도 {self.model_info.get('accuracy', 0)*100:.1f}%)")
        except ImportError:
            print("⚠️ xgboost 미설치. pip install xgboost 실행하세요.")
        except Exception as e:
            print(f"⚠️ ML 모델 로드 실패: {e}")

    def predict(self, daily: list[dict]) -> dict:
        """
        일봉 데이터로 매매 예측

        Returns:
            {
                "prediction": "매수" / "관망" / "매도",
                "confidence": 0.73,
                "probabilities": {"매수": 0.73, "관망": 0.20, "매도": 0.07},
                "available": True
            }
        """
        if not self.loaded or not daily:
            return {"available": False, "reason": "모델 미로드 또는 데이터 없음"}

        try:
            features = self._build_features(daily)
            if features is None:
                return {"available": False, "reason": "피처 생성 실패 (데이터 부족)"}

            # 예측
            import numpy as np
            X = np.array([features])
            pred = self.model.predict(X)[0]
            proba = self.model.predict_proba(X)[0]

            labels = {0: "매도", 1: "관망", 2: "매수"}
            prediction = labels.get(int(pred), "관망")
            confidence = float(max(proba))

            return {
                "available": True,
                "prediction": prediction,
                "confidence": round(confidence, 3),
                "probabilities": {
                    "매도": round(float(proba[0]), 3),
                    "관망": round(float(proba[1]), 3),
                    "매수": round(float(proba[2]), 3),
                },
                "forward_days": self.model_info.get("forward_days", 3),
                "model_accuracy": round(self.model_info.get("accuracy", 0) * 100, 1),
            }
        except Exception as e:
            return {"available": False, "reason": str(e)}

    def _build_features(self, daily: list[dict]) -> Optional[list]:
        """일봉 데이터 → 피처 벡터 생성"""
        if len(daily) < 60:
            return None

        closes = [d["종가"] for d in daily]
        highs = [d["고가"] for d in daily]
        lows = [d["저가"] for d in daily]
        opens = [d["시가"] for d in daily]
        volumes = [d["거래량"] for d in daily]
        n = len(closes)

        f = {}

        # === TREND ===
        for p in [5, 10, 20, 50]:
            if n >= p:
                f[f'sma_{p}'] = sum(closes[-p:]) / p
                f[f'ema_{p}'] = self._ema(closes, p)
                f[f'close_sma_{p}_ratio'] = closes[-1] / (sum(closes[-p:]) / p)

        # MACD
        if n >= 26:
            ema12 = self._ema(closes, 12)
            ema26 = self._ema(closes, 26)
            f['macd'] = ema12 - ema26
            macd_hist = []
            for i in range(26, n):
                e12 = self._ema(closes[:i+1], 12)
                e26 = self._ema(closes[:i+1], 26)
                macd_hist.append(e12 - e26)
            f['macd_signal'] = self._ema(macd_hist, 9) if len(macd_hist) >= 9 else f['macd']
            f['macd_hist'] = f['macd'] - f['macd_signal']

        # ADX
        if n >= 15:
            adx, adx_pos, adx_neg = self._calc_adx(highs, lows, closes, 14)
            f['adx'] = adx
            f['adx_pos'] = adx_pos
            f['adx_neg'] = adx_neg

        # === MOMENTUM ===
        for p in [7, 14, 21]:
            if n >= p + 1:
                f[f'rsi_{p}'] = self._calc_rsi(closes, p)

        if n >= 14:
            k, d = self._calc_stochastic(closes, highs, lows, 14, 3)
            f['stoch_k'] = k
            f['stoch_d'] = d

        if n >= 20:
            f['cci_20'] = self._calc_cci(closes, highs, lows, 20)

        if n >= 14:
            h14 = max(highs[-14:])
            l14 = min(lows[-14:])
            f['willr_14'] = (h14 - closes[-1]) / (h14 - l14) * -100 if h14 != l14 else -50

        for p in [5, 10, 20]:
            if n >= p + 1:
                f[f'roc_{p}'] = (closes[-1] - closes[-p-1]) / closes[-p-1] * 100
                f[f'mom_{p}'] = closes[-1] - closes[-p-1]

        # === VOLATILITY ===
        for p in [7, 14, 21]:
            if n >= p + 1:
                atr = self._calc_atr(closes, highs, lows, p)
                f[f'atr_{p}'] = atr
                f[f'atr_{p}_pct'] = atr / closes[-1] * 100

        # Bollinger
        if n >= 20:
            bb_mean = sum(closes[-20:]) / 20
            bb_std = (sum((x - bb_mean)**2 for x in closes[-20:]) / 20) ** 0.5
            bb_upper = bb_mean + 2 * bb_std
            bb_lower = bb_mean - 2 * bb_std
            f['bb_width'] = (bb_upper - bb_lower) / bb_mean
            f['bb_pct'] = (closes[-1] - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

        # HV
        for p in [10, 20, 30]:
            if n >= p + 1:
                log_rets = [math.log(closes[i]/closes[i-1]) for i in range(-p, 0)]
                mean = sum(log_rets) / p
                var = sum((r - mean)**2 for r in log_rets) / p
                f[f'hv_{p}'] = (var ** 0.5) * (252 ** 0.5) * 100

        f['hv_ratio'] = f.get('hv_10', 0) / (f.get('hv_30', 1) + 1e-9)

        # === VOLUME ===
        if n >= 20:
            vol_sma20 = sum(volumes[-20:]) / 20
            f['vol_sma20'] = vol_sma20
            f['vol_ratio'] = volumes[-1] / (vol_sma20 + 1)

        # OBV
        obv = 0
        obv_list = [0]
        for i in range(1, n):
            if closes[i] > closes[i-1]:
                obv += volumes[i]
            elif closes[i] < closes[i-1]:
                obv -= volumes[i]
            obv_list.append(obv)
        f['obv'] = obv
        f['obv_slope'] = obv_list[-1] - obv_list[-5] if len(obv_list) >= 5 else 0

        # MFI
        if n >= 15:
            f['mfi_14'] = self._calc_mfi(closes, highs, lows, volumes, 14)

        # CMF
        if n >= 20:
            f['cmf_20'] = self._calc_cmf(closes, highs, lows, volumes, 20)

        # === PRICE DERIVED ===
        for p in [1, 5, 10, 20]:
            if n >= p + 1:
                f[f'ret_{p}'] = (closes[-1] - closes[-p-1]) / closes[-p-1]

        if n >= 2:
            f['log_ret'] = math.log(closes[-1] / closes[-2])
            f['gap'] = (opens[-1] - closes[-2]) / closes[-2]

        # 캔들
        body = abs(closes[-1] - opens[-1])
        total_range = highs[-1] - lows[-1]
        f['body_pct'] = body / (total_range + 1e-9)
        f['upper_wick'] = highs[-1] - max(closes[-1], opens[-1])
        f['lower_wick'] = min(closes[-1], opens[-1]) - lows[-1]
        f['is_bull'] = 1 if closes[-1] > opens[-1] else 0

        # 52주 위치
        if n >= 60:
            h_max = max(highs[-min(252, n):])
            l_min = min(lows[-min(252, n):])
            f['pos_52w'] = (closes[-1] - l_min) / (h_max - l_min + 1e-9)

        # 피봇
        f['pivot'] = (highs[-1] + lows[-1] + closes[-1]) / 3
        r1 = 2 * f['pivot'] - lows[-1]
        s1 = 2 * f['pivot'] - highs[-1]
        f['dist_r1'] = (r1 - closes[-1]) / closes[-1]
        f['dist_s1'] = (closes[-1] - s1) / closes[-1]

        # Regime
        f['regime_trend'] = 1 if f.get('adx', 0) > 25 else 0
        f['regime_bull'] = 1 if f.get('adx', 0) > 25 and f.get('adx_pos', 0) > f.get('adx_neg', 0) else 0

        # Rolling Sharpe
        if n >= 21:
            rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(-20, 0)]
            mean_ret = sum(rets) / 20
            std_ret = (sum((r - mean_ret)**2 for r in rets) / 20) ** 0.5
            f['rolling_sharpe'] = (mean_ret / (std_ret + 1e-9)) * (252 ** 0.5)

        # 피처 벡터 생성 (학습 시 사용한 순서대로)
        vector = []
        for col in self.feature_cols:
            vector.append(f.get(col, 0))

        return vector

    # === 계산 헬퍼 ===
    @staticmethod
    def _ema(data, period):
        if len(data) < period:
            return sum(data) / len(data)
        m = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for val in data[period:]:
            ema = (val - ema) * m + ema
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
        if avg_loss == 0: return 100
        return 100 - (100 / (1 + avg_gain / avg_loss))

    @staticmethod
    def _calc_stochastic(closes, highs, lows, k_period, d_period):
        if len(closes) < k_period: return 50, 50
        k_vals = []
        for i in range(max(len(closes) - k_period - d_period, k_period), len(closes)):
            h = max(highs[i-k_period+1:i+1])
            l = min(lows[i-k_period+1:i+1])
            k = ((closes[i] - l) / (h - l) * 100) if h != l else 50
            k_vals.append(k)
        d = sum(k_vals[-d_period:]) / d_period if len(k_vals) >= d_period else k_vals[-1]
        return k_vals[-1], d

    @staticmethod
    def _calc_cci(closes, highs, lows, period):
        tps = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(-period, 0)]
        tp_mean = sum(tps) / period
        md = sum(abs(tp - tp_mean) for tp in tps) / period
        if md == 0: return 0
        return (tps[-1] - tp_mean) / (0.015 * md)

    @staticmethod
    def _calc_atr(closes, highs, lows, period):
        trs = []
        for i in range(-period, 0):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        return sum(trs) / period

    @staticmethod
    def _calc_mfi(closes, highs, lows, volumes, period):
        pos_flow, neg_flow = 0, 0
        for i in range(-period, 0):
            tp = (highs[i] + lows[i] + closes[i]) / 3
            prev_tp = (highs[i-1] + lows[i-1] + closes[i-1]) / 3
            mf = tp * volumes[i]
            if tp > prev_tp: pos_flow += mf
            else: neg_flow += mf
        if neg_flow == 0: return 100
        return 100 - (100 / (1 + pos_flow / neg_flow))

    @staticmethod
    def _calc_cmf(closes, highs, lows, volumes, period):
        num, den = 0, 0
        for i in range(-period, 0):
            hl = highs[i] - lows[i]
            mfm = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl if hl > 0 else 0
            num += mfm * volumes[i]
            den += volumes[i]
        return num / den if den > 0 else 0

    def _calc_adx(self, highs, lows, closes, period):
        n = len(closes)
        if n < period + 1: return 0, 0, 0
        plus_dm, minus_dm, tr_list = [], [], []
        for i in range(1, n):
            up = highs[i] - highs[i-1]
            down = lows[i-1] - lows[i]
            plus_dm.append(up if up > down and up > 0 else 0)
            minus_dm.append(down if down > up and down > 0 else 0)
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_list.append(tr)
        atr = sum(tr_list[:period]) / period
        pdi_s = sum(plus_dm[:period]) / period
        mdi_s = sum(minus_dm[:period]) / period
        for i in range(period, len(tr_list)):
            atr = (atr * (period - 1) + tr_list[i]) / period
            pdi_s = (pdi_s * (period - 1) + plus_dm[i]) / period
            mdi_s = (mdi_s * (period - 1) + minus_dm[i]) / period
        pdi = (pdi_s / atr * 100) if atr > 0 else 0
        mdi = (mdi_s / atr * 100) if atr > 0 else 0
        dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
        return dx, pdi, mdi
