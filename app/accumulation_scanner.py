"""
🔍 수급 스캐너 (외국인/기관 매집 종목 발굴)
- 네이버 금융에서 여러 종목의 수급 데이터를 스캔
- 외국인/기관 연속 매수, 누적 매수 상위 종목 자동 발굴
"""

import time
from typing import Optional
from .krx_data import KRXDataFetcher
from .theme_scanner import ThemeScanner
# 코스피/코스닥 주요 종목 100개
SCAN_STOCKS = {
    # 코스피 대형주
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER",
    "035720": "카카오", "005380": "현대차", "068270": "셀트리온",
    "051910": "LG화학", "006400": "삼성SDI", "055550": "신한지주",
    "105560": "KB금융", "003670": "포스코퓨처엠", "006800": "미래에셋증권",
    "003490": "대한항공", "066570": "LG전자", "028260": "삼성물산",
    "207940": "삼성바이오로직스", "005490": "POSCO홀딩스", "012330": "현대모비스",
    "373220": "LG에너지솔루션", "096770": "SK이노베이션",
    "034730": "SK", "015760": "한국전력", "032830": "삼성생명",
    "003550": "LG", "009150": "삼성전기", "033780": "KT&G",
    "086790": "하나금융지주", "011200": "HMM", "010130": "고려아연",
    "030200": "KT", "316140": "우리금융지주", "017670": "SK텔레콤",
    "000270": "기아", "034020": "두산에너빌리티", "009540": "HD한국조선해양",
    "004020": "현대제철", "010950": "S-Oil", "036460": "한국가스공사",
    "024110": "기업은행", "000810": "삼성화재", "029780": "삼성카드",
    "001570": "금양", "005830": "DB손해보험", "138040": "메리츠금융지주",
    "090430": "아모레퍼시픽", "047050": "포스코인터내셔널",
    "018260": "삼성에스디에스", "161390": "한국타이어앤테크놀로지",
    "010140": "삼성중공업", "042660": "한화오션",
    # 코스닥 대형주
    "247540": "에코프로비엠", "196170": "알테오젠", "028300": "HLB",
    "041510": "에스엠", "263750": "펄어비스", "293490": "카카오게임즈",
    "036570": "엔씨소프트", "403870": "HPSP", "086520": "에코프로",
    "352820": "하이브", "145020": "휴젤", "357780": "솔브레인",
    "005290": "동진쎄미켐", "058470": "리노공업", "328130": "루닛",
    "112040": "위메이드", "000990": "DB하이텍", "039030": "이오테크닉스",
    "091990": "셀트리온헬스케어", "035900": "JYP Ent.",
}


class AccumulationScanner:
    """외국인/기관 매집 종목 스캐너"""

    def __init__(self):
        self.krx = KRXDataFetcher()

    def scan_all(self, days: int = 10, min_consecutive: int = 3, stocks: dict = None) -> dict:
        """
        전체 종목 수급 스캔 (주도주 자동 포함)
        """
        # 1. 고정 관심 종목 세팅 (딕셔너리 복사)
        target_stocks = stocks.copy() if stocks else SCAN_STOCKS.copy()

        # 2. === 당일 주도주(시총 5000억 이하) 자동으로 가져와서 합치기 ===
        print("\n[시스템] 당일 주도 테마 스캔을 시작합니다...")
        try:
            theme_scanner = ThemeScanner()
            # 상위 3개 테마에서 시총 5000억 이하 10개씩 가져오기
            leading_stocks = theme_scanner.get_small_cap_theme_stocks(top_n_themes=3, max_cap=5000, stocks_per_theme=10)
            
            # 기존 종목 리스트에 주도주 리스트 합치기
            target_stocks.update(leading_stocks)
            print(f"✅ 주도주 포함 총 {len(target_stocks)}개 종목 수급 분석을 시작합니다!\n")
        except Exception as e:
            print(f"⚠️ 테마 스캔 에러 (기본 종목만 진행): {e}")

        results = []
        errors = []

        for code, name in target_stocks.items():
            try:
                data = self.krx.get_investor_daily(code, days)
                if not data or len(data) < 3:
                    continue

                analysis = self._analyze_accumulation(code, name, data)
                if analysis:
                    results.append(analysis)

                # 네이버 금융 과부하 방지
                time.sleep(0.3)

            except Exception as e:
                errors.append({"code": code, "name": name, "error": str(e)})
                continue

        # 랭킹 정렬
        foreign_rank = sorted(
            [r for r in results if r["외국인_연속매수일"] >= min_consecutive],
            key=lambda x: x["외국인_누적순매수"], reverse=True
        )
        organ_rank = sorted(
            [r for r in results if r["기관_연속매수일"] >= min_consecutive],
            key=lambda x: x["기관_누적순매수"], reverse=True
        )
        both_rank = sorted(
            [r for r in results if r["외국인_연속매수일"] >= min_consecutive and r["기관_연속매수일"] >= min_consecutive],
            key=lambda x: x["외국인_누적순매수"] + x["기관_누적순매수"], reverse=True
        )

        # 외국인 누적 TOP
        foreign_cum_rank = sorted(
            [r for r in results if r["외국인_누적순매수"] > 0],
            key=lambda x: x["외국인_누적순매수"], reverse=True
        )[:20]

        # 기관 누적 TOP
        organ_cum_rank = sorted(
            [r for r in results if r["기관_누적순매수"] > 0],
            key=lambda x: x["기관_누적순매수"], reverse=True
        )[:20]

        return {
            "스캔_종목수": len(target_stocks),
            "분석_완료": len(results),
            "분석_기간": f"{days}일",
            "최소_연속매수일": min_consecutive,
            "외국인_연속매수_TOP": foreign_rank[:10],
            "기관_연속매수_TOP": organ_rank[:10],
            "외국인+기관_동시매집": both_rank[:10],
            "외국인_누적매수_TOP": foreign_cum_rank[:10],
            "기관_누적매수_TOP": organ_cum_rank[:10],
            "errors": errors[:5] if errors else None,
        }

    def scan_single(self, stock_code: str, stock_name: str = "", days: int = 14) -> dict:
        """단일 종목 매집 분석"""
        data = self.krx.get_investor_daily(stock_code, days)
        if not data:
            return {"error": "데이터 없음"}

        name = stock_name or stock_code
        analysis = self._analyze_accumulation(stock_code, name, data)
        if not analysis:
            return {"error": "분석 실패", "data_count": len(data)}

        # 매집 판단
        verdict = []
        if analysis["외국인_연속매수일"] >= 5:
            verdict.append(f"외국인 {analysis['외국인_연속매수일']}일 연속 매수 (강한 매집)")
        elif analysis["외국인_연속매수일"] >= 3:
            verdict.append(f"외국인 {analysis['외국인_연속매수일']}일 연속 매수 (매집 진행)")

        if analysis["기관_연속매수일"] >= 5:
            verdict.append(f"기관 {analysis['기관_연속매수일']}일 연속 매수 (강한 매집)")
        elif analysis["기관_연속매수일"] >= 3:
            verdict.append(f"기관 {analysis['기관_연속매수일']}일 연속 매수 (매집 진행)")

        if analysis["외국인_누적순매수"] > 0 and analysis["기관_누적순매수"] > 0:
            verdict.append("외국인+기관 동시 순매수 (수급 긍정)")

        if analysis["외국인_매수비율"] >= 70:
            verdict.append(f"외국인 매수일 비율 {analysis['외국인_매수비율']}% (압도적 매수)")

        if not verdict:
            if analysis["외국인_누적순매수"] < 0 and analysis["기관_누적순매수"] < 0:
                verdict.append("외국인+기관 모두 순매도 (수급 부정)")
            else:
                verdict.append("뚜렷한 매집 패턴 없음")

        analysis["판단"] = verdict
        return analysis

    def _analyze_accumulation(self, code: str, name: str, data: list) -> Optional[dict]:
        """수급 데이터에서 매집 패턴 분석"""
        if not data or len(data) < 2:
            return None

        # 외국인 분석
        foreign_nets = [d.get("외국인_순매수", 0) for d in data]
        foreign_total = sum(foreign_nets)
        foreign_consecutive = self._count_consecutive_buy(foreign_nets)
        foreign_buy_days = sum(1 for n in foreign_nets if n > 0)
        foreign_buy_ratio = round(foreign_buy_days / len(foreign_nets) * 100) if foreign_nets else 0

        # 기관 분석
        organ_nets = [d.get("기관_순매수", 0) for d in data]
        organ_total = sum(organ_nets)
        organ_consecutive = self._count_consecutive_buy(organ_nets)
        organ_buy_days = sum(1 for n in organ_nets if n > 0)
        organ_buy_ratio = round(organ_buy_days / len(organ_nets) * 100) if organ_nets else 0

        # 최근 추세 (최근 5일 vs 이전 5일)
        recent_5_f = sum(foreign_nets[:5]) if len(foreign_nets) >= 5 else sum(foreign_nets)
        prev_5_f = sum(foreign_nets[5:10]) if len(foreign_nets) >= 10 else 0
        foreign_accel = "가속" if recent_5_f > prev_5_f and recent_5_f > 0 else "감속" if recent_5_f < prev_5_f else "유지"

        recent_5_o = sum(organ_nets[:5]) if len(organ_nets) >= 5 else sum(organ_nets)
        prev_5_o = sum(organ_nets[5:10]) if len(organ_nets) >= 10 else 0
        organ_accel = "가속" if recent_5_o > prev_5_o and recent_5_o > 0 else "감속" if recent_5_o < prev_5_o else "유지"

        # 종가 추이
        closes = [d.get("종가", 0) for d in data if d.get("종가", 0) > 0]
        price_change = 0
        if len(closes) >= 2 and closes[-1] > 0:
            price_change = round((closes[0] - closes[-1]) / closes[-1] * 100, 2)

        return {
            "종목코드": code,
            "종목명": name,
            "분석_기간": f"{len(data)}일",
            "현재가": closes[0] if closes else 0,
            "기간_수익률": f"{price_change:+.1f}%",
            "외국인_누적순매수": foreign_total,
            "외국인_연속매수일": foreign_consecutive,
            "외국인_매수비율": foreign_buy_ratio,
            "외국인_추세": foreign_accel,
            "기관_누적순매수": organ_total,
            "기관_연속매수일": organ_consecutive,
            "기관_매수비율": organ_buy_ratio,
            "기관_추세": organ_accel,
            "외국인_보유율": data[0].get("외국인_보유율", "") if data else "",
        }

    @staticmethod
    def _count_consecutive_buy(nets: list) -> int:
        """최근부터 연속 순매수 일수"""
        count = 0
        for n in nets:
            if n > 0:
                count += 1
            else:
                break
        return count
