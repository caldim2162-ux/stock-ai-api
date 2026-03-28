"""
한국투자증권 REST API 클라이언트
- OAuth 토큰 발급/관리
- 현재가/호가/일봉/분봉/투자자동향 조회
- 실전/모의 투자 환경 지원

사전 준비:
  1. https://apiportal.koreainvestment.com 에서 API 신청
  2. AppKey, AppSecret 발급
  3. .env 파일에 설정
"""

import os
import time
import httpx
from datetime import datetime, timedelta

KIS_BASE_URL = os.getenv("KIS_BASE_URL", "https://openapivts.koreainvestment.com:29443")
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")
KIS_ACCOUNT_PRODUCT = os.getenv("KIS_ACCOUNT_PRODUCT", "01")

_token_cache = {"access_token": "", "expires_at": 0}


class KISClient:
    def __init__(self):
        self.base_url = KIS_BASE_URL
        self.app_key = KIS_APP_KEY
        self.app_secret = KIS_APP_SECRET
        self.account_no = KIS_ACCOUNT_NO
        self.account_product = KIS_ACCOUNT_PRODUCT
        if not self.app_key or not self.app_secret:
            raise ValueError("KIS_APP_KEY, KIS_APP_SECRET 환경변수를 설정하세요.")

    async def get_access_token(self) -> str:
        global _token_cache
        if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
            return _token_cache["access_token"]

        url = f"{self.base_url}/oauth2/tokenP"
        payload = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 86400) - 3600
        return _token_cache["access_token"]

    async def get_ws_approval_key(self) -> str:
        url = f"{self.base_url}/oauth2/Approval"
        payload = {"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.app_secret}
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["approval_key"]

    async def _headers(self, tr_id: str) -> dict:
        token = await self.get_access_token()
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": tr_id,
        }

    async def get_current_price(self, stock_code: str) -> dict:
        """현재가 시세 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = await self._headers("FHKST01010100")
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            raise Exception(f"API 오류: {data.get('msg1')}")
        o = data["output"]
        return {
            "종목코드": stock_code, "종목명": o.get("hts_kor_isnm", ""),
            "현재가": int(o.get("stck_prpr", 0)), "전일대비": int(o.get("prdy_vrss", 0)),
            "전일대비율": float(o.get("prdy_ctrt", 0)), "누적거래량": int(o.get("acml_vol", 0)),
            "누적거래대금": int(o.get("acml_tr_pbmn", 0)),
            "시가": int(o.get("stck_oprc", 0)), "고가": int(o.get("stck_hgpr", 0)),
            "저가": int(o.get("stck_lwpr", 0)),
            "52주최고": int(o.get("stck_dryy_hgpr", 0)), "52주최저": int(o.get("stck_dryy_lwpr", 0)),
            "PER": float(o.get("per", 0)), "PBR": float(o.get("pbr", 0)),
            "시가총액": o.get("hts_avls", ""), "조회시간": datetime.now().isoformat(),
        }

    async def get_orderbook(self, stock_code: str) -> dict:
        """호가(매수/매도 10단계) 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
        headers = await self._headers("FHKST01010200")
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            raise Exception(f"API 오류: {data.get('msg1')}")
        o = data["output1"]
        asks, bids = [], []
        for i in range(1, 11):
            asks.append({"가격": int(o.get(f"askp{i}", 0)), "잔량": int(o.get(f"askp_rsqn{i}", 0))})
            bids.append({"가격": int(o.get(f"bidp{i}", 0)), "잔량": int(o.get(f"bidp_rsqn{i}", 0))})
        return {
            "종목코드": stock_code, "매도호가": asks, "매수호가": bids,
            "총매도잔량": int(o.get("total_askp_rsqn", 0)),
            "총매수잔량": int(o.get("total_bidp_rsqn", 0)),
            "조회시간": datetime.now().isoformat(),
        }

    async def get_daily_prices(self, stock_code: str, period: str = "D", count: int = 90) -> list[dict]:
        """일봉/주봉/월봉 차트"""
        # 방법 1: inquire-daily-itemchartprice (FHKST03010100)
        apis = [
            {"tr_id": "FHKST03010100", "url": "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
             "params": {
                 "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code,
                 "FID_INPUT_DATE_1": (datetime.now() - timedelta(days=count * 2)).strftime("%Y%m%d"),
                 "FID_INPUT_DATE_2": datetime.now().strftime("%Y%m%d"),
                 "FID_PERIOD_DIV_CODE": period, "FID_ORG_ADJ_PRC": "0",
             }},
            {"tr_id": "FHKST01010400", "url": "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
             "params": {
                 "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code,
                 "FID_INPUT_DATE_1": (datetime.now() - timedelta(days=count * 2)).strftime("%Y%m%d"),
                 "FID_INPUT_DATE_2": datetime.now().strftime("%Y%m%d"),
                 "FID_PERIOD_DIV_CODE": period, "FID_ORG_ADJ_PRC": "0",
             }},
        ]
        for api in apis:
            try:
                url = f"{self.base_url}{api['url']}"
                headers = await self._headers(api["tr_id"])
                async with httpx.AsyncClient(verify=False, timeout=10) as client:
                    resp = await client.get(url, headers=headers, params=api["params"])
                    resp.raise_for_status()
                    data = resp.json()
                if data.get("rt_cd") != "0":
                    continue
                output = data.get("output2", []) or data.get("output", [])
                if not output:
                    continue
                records = []
                for item in output[:count]:
                    date = item.get("stck_bsop_date", "")
                    close = int(item.get("stck_clpr", 0) or 0)
                    if not date or close == 0:
                        continue
                    records.append({
                        "date": date,
                        "open": int(item.get("stck_oprc", 0) or 0),
                        "high": int(item.get("stck_hgpr", 0) or 0),
                        "low": int(item.get("stck_lwpr", 0) or 0),
                        "close": close,
                        "volume": int(item.get("acml_vol", 0) or 0),
                        # 한글 키도 유지 (다른 기능에서 사용)
                        "날짜": date,
                        "시가": int(item.get("stck_oprc", 0) or 0),
                        "고가": int(item.get("stck_hgpr", 0) or 0),
                        "저가": int(item.get("stck_lwpr", 0) or 0),
                        "종가": close,
                        "거래량": int(item.get("acml_vol", 0) or 0),
                    })
                if records:
                    return records
            except Exception:
                continue
        return []

    async def get_minute_prices(self, stock_code: str) -> list[dict]:
        """분봉 차트"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = await self._headers("FHKST03010200")
        now = datetime.now().strftime("%H%M%S")
        params = {
            "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": now, "FID_PW_DATA_INCU_YN": "N",
        }
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            raise Exception(f"API 오류: {data.get('msg1')}")
        return [
            {
                "시간": item.get("stck_cntg_hour", ""),
                "현재가": int(item.get("stck_prpr", 0)),
                "시가": int(item.get("stck_oprc", 0)), "고가": int(item.get("stck_hgpr", 0)),
                "저가": int(item.get("stck_lwpr", 0)), "거래량": int(item.get("cntg_vol", 0)),
            }
            for item in data.get("output2", [])
        ]

    async def get_investor_trend(self, stock_code: str) -> dict:
        """외인기관 추정가집계 (장중 하루 4번 업데이트)"""
        # 방법 1: FHKST01010300 - 종목별 외인기관 추정가집계
        apis = [
            {"tr_id": "FHKST01010300", "url": "/uapi/domestic-stock/v1/quotations/investor-trend-estimate", "params": {"MKSC_SHRN_ISCD": stock_code, "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}},
            {"tr_id": "FHKST01010600", "url": "/uapi/domestic-stock/v1/quotations/inquire-investor", "params": {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}},
        ]
        for api in apis:
            try:
                url = f"{self.base_url}{api['url']}"
                headers = await self._headers(api["tr_id"])
                async with httpx.AsyncClient(verify=False, timeout=10) as client:
                    resp = await client.get(url, headers=headers, params=api["params"])
                    data = resp.json()
                if data.get("rt_cd") != "0":
                    continue
                # output2 형식 (FHKST01010300)
                output2 = data.get("output2", [])
                if output2:
                    latest = output2[-1] if isinstance(output2, list) else output2
                    frgn = int(latest.get("frgn_fake_ntby_qty", 0) or 0)
                    orgn = int(latest.get("orgn_fake_ntby_qty", 0) or 0)
                    if frgn != 0 or orgn != 0:
                        return {
                            "외국인": {"순매수량": frgn},
                            "기관계": {"순매수량": orgn},
                            "개인": {"순매수량": -(frgn + orgn)},
                            "소스": api["tr_id"],
                        }
                # output 형식 (FHKST01010600 등)
                output = data.get("output", [])
                if output:
                    inv_map = {"1": "개인", "2": "외국인", "3": "기관계", "4": "금융투자",
                               "5": "보험", "6": "투신", "7": "기타금융", "8": "은행", "9": "연기금"}
                    result = {}
                    for item in output:
                        name = inv_map.get(item.get("invr_cd", ""), "기타")
                        net = int(item.get("ntby_qty", 0) or item.get("total_ntby_qty", 0) or 0)
                        if name in ["외국인", "기관계", "개인"] and net != 0:
                            result[name] = {"순매수량": net}
                    if result:
                        result["소스"] = api["tr_id"]
                        return result
            except Exception:
                continue
        return {}

    async def _get_investor_trend_v2(self, stock_code: str) -> dict:
        """투자자별 매매동향 일별 (FHKST01010600)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-investor"
        headers = await self._headers("FHKST01010600")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        }
        try:
            async with httpx.AsyncClient(verify=False, timeout=10) as client:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
            if data.get("rt_cd") != "0":
                return {}
            inv_map = {"1": "개인", "2": "외국인", "3": "기관계", "4": "금융투자",
                        "5": "보험", "6": "투신", "7": "기타금융", "8": "은행", "9": "연기금"}
            result = {}
            for item in data.get("output", []):
                name = inv_map.get(item.get("invr_cd", ""), "기타")
                result[name] = {
                    "순매수량": int(item.get("ntby_qty", 0) or 0),
                    "매수거래량": int(item.get("total_seln_qty", 0) or item.get("seln_qty", 0) or 0),
                    "매도거래량": int(item.get("total_shnu_qty", 0) or item.get("shnu_qty", 0) or 0),
                }
            return result
        except Exception:
            return {}

    async def get_foreign_daily(self, stock_code: str, days: int = 20) -> list[dict]:
        """외국인/기관 일별 매매동향 (최근 N일)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-trade-volume"
        headers = await self._headers("FHKST01010800")
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
        }
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            return []
        records = []
        for item in data.get("output", data.get("output1", []))[:days]:
            records.append({
                "날짜": item.get("stck_bsop_date", ""),
                "종가": int(item.get("stck_clpr", 0)),
                "거래량": int(item.get("acml_vol", 0)),
                "외국인_순매수": int(item.get("frgn_ntby_qty", 0)),
                "기관_순매수": int(item.get("orgn_ntby_qty", 0)),
                "개인_순매수": int(item.get("prsn_ntby_qty", 0)),
                "외국인_지분율": float(item.get("frgn_shnu_rt", 0)),
            })
        return records

    async def get_short_selling(self, stock_code: str, days: int = 20) -> list[dict]:
        """공매도 일별 추이 (최근 N일)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-short-selling"
        headers = await self._headers("FHKST03060100")
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
        }
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            return []
        records = []
        for item in data.get("output", data.get("output1", []))[:days]:
            total_vol = int(item.get("acml_vol", 1)) or 1
            short_vol = int(item.get("ssts_vol", 0))
            records.append({
                "날짜": item.get("stck_bsop_date", ""),
                "종가": int(item.get("stck_clpr", 0)),
                "공매도량": short_vol,
                "총거래량": total_vol,
                "공매도_비중": round(short_vol / total_vol * 100, 2),
                "공매도_대금": int(item.get("ssts_tr_pbmn", 0)),
            })
        return records

    # ----------------------------------------------------------
    # 주문 (매수/매도)
    # ----------------------------------------------------------
    async def buy_order(self, stock_code: str, quantity: int, price: int = 0) -> dict:
        """
        매수 주문
        price=0이면 시장가 주문, price>0이면 지정가 주문
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "TTTC0802U"  # 실전 매수
        if "vts" in self.base_url:
            tr_id = "VTTC0802U"  # 모의 매수

        headers = await self._headers(tr_id)
        body = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_product,
            "PDNO": stock_code,
            "ORD_DVSN": "01" if price > 0 else "06",  # 01: 지정가, 06: 시장가
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price) if price > 0 else "0",
        }

        async with httpx.AsyncClient(verify=False, timeout=15) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        if data.get("rt_cd") != "0":
            raise Exception(f"매수 주문 실패: {data.get('msg1', '알 수 없는 오류')}")

        return {
            "status": "주문 완료",
            "종목코드": stock_code,
            "유형": "매수",
            "수량": quantity,
            "가격": "시장가" if price == 0 else f"{price:,}원",
            "주문번호": data.get("output", {}).get("ODNO", ""),
            "시간": datetime.now().isoformat(),
        }

    async def sell_order(self, stock_code: str, quantity: int, price: int = 0) -> dict:
        """
        매도 주문
        price=0이면 시장가 주문, price>0이면 지정가 주문
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "TTTC0801U"  # 실전 매도
        if "vts" in self.base_url:
            tr_id = "VTTC0801U"  # 모의 매도

        headers = await self._headers(tr_id)
        body = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_product,
            "PDNO": stock_code,
            "ORD_DVSN": "01" if price > 0 else "06",
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price) if price > 0 else "0",
        }

        async with httpx.AsyncClient(verify=False, timeout=15) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        if data.get("rt_cd") != "0":
            raise Exception(f"매도 주문 실패: {data.get('msg1', '알 수 없는 오류')}")

        return {
            "status": "주문 완료",
            "종목코드": stock_code,
            "유형": "매도",
            "수량": quantity,
            "가격": "시장가" if price == 0 else f"{price:,}원",
            "주문번호": data.get("output", {}).get("ODNO", ""),
            "시간": datetime.now().isoformat(),
        }

    # ----------------------------------------------------------
    # 국내 선물 (코스피200 야간선물 등)
    # ----------------------------------------------------------
    async def get_futures_price(self, futures_code: str = "A01606") -> dict:
        """
        국내 선물 현재가 조회
        코스피200 선물 코드:
          - A01606: 코스피200 선물 (2026.06)
          - A01609: 코스피200 선물 (2026.09)
          - A05606: 미니코스피200 선물 (2026.06)
          - A06606: 코스닥150 선물 (2026.06)
        """
        url = f"{self.base_url}/uapi/domestic-futureoption/v1/quotations/inquire-price"
        headers = await self._headers("FHMIF10000000")
        params = {
            "FID_COND_MRKT_DIV_CODE": "F",
            "FID_INPUT_ISCD": futures_code,
        }
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            raise Exception(f"선물 API 오류: {data.get('msg1')}")
        o = data.get("output1", data.get("output", {}))
        return {
            "종목코드": futures_code,
            "종목명": o.get("hts_kor_isnm", futures_code),
            "현재가": float(o.get("futs_prpr", 0) or 0),
            "전일대비": float(o.get("futs_prdy_vrss", 0) or 0),
            "등락률": f"{o.get('futs_prdy_ctrt', '0')}%",
            "거래량": int(o.get("acml_vol", 0) or 0),
            "시가": float(o.get("futs_oprc", 0) or 0),
            "고가": float(o.get("futs_hgpr", 0) or 0),
            "저가": float(o.get("futs_lwpr", 0) or 0),
            "기준가": float(o.get("futs_sdpr", 0) or 0),
            "조회시간": datetime.now().isoformat(),
        }

    async def get_futures_daily(self, futures_code: str = "A01606", days: int = 20) -> list[dict]:
        """국내 선물 일별 시세"""
        url = f"{self.base_url}/uapi/domestic-futureoption/v1/quotations/inquire-daily-fuop-price"
        headers = await self._headers("FHMIF10010000")
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        params = {
            "FID_COND_MRKT_DIV_CODE": "F",
            "FID_INPUT_ISCD": futures_code,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
        }
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            return []
        records = []
        for item in data.get("output2", data.get("output", []))[:days]:
            if not item.get("stck_bsop_date"):
                continue
            records.append({
                "날짜": item.get("stck_bsop_date", ""),
                "종가": float(item.get("stck_clpr", 0) or 0),
                "시가": float(item.get("stck_oprc", 0) or 0),
                "고가": float(item.get("stck_hgpr", 0) or 0),
                "저가": float(item.get("stck_lwpr", 0) or 0),
                "거래량": int(item.get("acml_vol", 0) or 0),
            })
        return records

    # ----------------------------------------------------------
    # 해외 선물 (원자재: 금, 원유, 천연가스 등)
    # ----------------------------------------------------------
    async def get_overseas_futures_price(self, symbol: str, exchange: str = "NYM") -> dict:
        """
        해외 선물 현재가 조회

        주요 종목코드 (2026년 기준):
          금(Gold):     1OZJ26  (COMEX, exchange=CMX)
          은(Silver):   1SIK26  (COMEX, exchange=CMX)
          원유(WTI):    CLK26   (NYMEX, exchange=NYM)
          천연가스:     NGJ26   (NYMEX, exchange=NYM)
          구리:         HGK26   (COMEX, exchange=CMX)
          나스닥100:    NQM26   (CME, exchange=CME)
          S&P500:       ESM26   (CME, exchange=CME)

        ※ 종목코드 뒤 알파벳+숫자는 만기월 (J=4월, K=5월, M=6월 등)
        """
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/quotations/inquire-price"
        headers = await self._headers("HHDFS76200200")
        params = {
            "EXCD": exchange,
            "SYMB": symbol,
        }
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            raise Exception(f"해외선물 API 오류: {data.get('msg1')}")
        o = data.get("output", {})
        return {
            "종목코드": symbol,
            "거래소": exchange,
            "종목명": o.get("prdt_name", symbol),
            "현재가": float(o.get("last", 0) or 0),
            "전일대비": float(o.get("diff", 0) or 0),
            "등락률": f"{o.get('rate', '0')}%",
            "거래량": int(o.get("tvol", 0) or 0),
            "시가": float(o.get("open", 0) or 0),
            "고가": float(o.get("high", 0) or 0),
            "저가": float(o.get("low", 0) or 0),
            "조회시간": datetime.now().isoformat(),
        }

    async def get_overseas_futures_daily(self, symbol: str, exchange: str = "NYM", days: int = 20) -> list[dict]:
        """해외 선물 일별 시세"""
        url = f"{self.base_url}/uapi/overseas-futureoption/v1/quotations/inquire-dailyprice"
        headers = await self._headers("HHDFS76240000")
        params = {
            "EXCD": exchange,
            "SYMB": symbol,
            "GUBN": "0",
            "BYMD": "",
            "MODP": "0",
        }
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("rt_cd") != "0":
            return []
        records = []
        for item in data.get("output2", data.get("output", []))[:days]:
            records.append({
                "날짜": item.get("xymd", ""),
                "종가": float(item.get("clos", 0) or 0),
                "시가": float(item.get("open", 0) or 0),
                "고가": float(item.get("high", 0) or 0),
                "저가": float(item.get("low", 0) or 0),
                "거래량": int(item.get("tvol", 0) or 0),
            })
        return records
