"""
📊 수급/공매도 조회 (네이버 금융)
- 네이버 금융에서 외국인/기관 수급, 공매도 데이터를 가져옵니다.
- 추가 라이브러리 설치 불필요 (requests + lxml)
"""

import requests
from lxml import html
from datetime import datetime


class KRXDataFetcher:
    """네이버 금융에서 수급/공매도 데이터를 가져옵니다."""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    # ----------------------------------------------------------
    # 외국인/기관 일별 매매 동향
    # ----------------------------------------------------------
    def get_investor_daily(self, stock_code: str, days: int = 14) -> list[dict]:
        """외국인/기관 일별 순매수 추이 (네이버 금융)"""
        records = []
        pages = (days // 20) + 1

        for page in range(1, pages + 1):
            try:
                url = f"https://finance.naver.com/item/frgn.naver?code={stock_code}&page={page}"
                resp = requests.get(url, headers=self.HEADERS, timeout=10)
                resp.encoding = "euc-kr"
                tree = html.fromstring(resp.text)

                rows = tree.xpath('//table[@class="type2"]//tr')
                for row in rows:
                    tds = row.xpath('td')
                    if len(tds) < 9:
                        continue
                    date_text = tds[0].text_content().strip()
                    if not date_text or '.' not in date_text:
                        continue

                    close = self._to_int(tds[1].text_content())
                    foreign_net = self._to_int(tds[5].text_content())
                    organ_net = self._to_int(tds[6].text_content())
                    foreign_hold = tds[7].text_content().strip()

                    records.append({
                        "날짜": date_text.replace(".", "-"),
                        "종가": close,
                        "외국인_순매수": foreign_net,
                        "기관_순매수": organ_net,
                        "개인_순매수": -(foreign_net + organ_net),
                        "외국인_보유율": foreign_hold,
                    })
            except Exception:
                continue

        return records[:days]

    # ----------------------------------------------------------
    # 공매도 일별 추이
    # ----------------------------------------------------------
    def get_short_selling(self, stock_code: str, days: int = 14) -> list[dict]:
        """공매도 일별 데이터 (네이버 금융 공매도 탭)"""
        records = []
        pages = (days // 20) + 1

        for page in range(1, pages + 1):
            try:
                url = f"https://finance.naver.com/item/short_selling.naver?code={stock_code}&page={page}"
                resp = requests.get(url, headers=self.HEADERS, timeout=10)
                resp.encoding = "euc-kr"
                tree = html.fromstring(resp.text)

                rows = tree.xpath('//table[@class="type2"]//tr')
                for row in rows:
                    tds = row.xpath('td')
                    if len(tds) < 6:
                        continue
                    date_text = tds[0].text_content().strip()
                    if not date_text or '.' not in date_text:
                        continue

                    close = self._to_int(tds[1].text_content())
                    short_vol = self._to_int(tds[3].text_content())
                    total_vol = self._to_int(tds[5].text_content()) or 1
                    ratio_text = tds[4].text_content().strip()

                    try:
                        ratio = float(ratio_text.replace("%", "").strip())
                    except (ValueError, TypeError):
                        ratio = round(short_vol / total_vol * 100, 2) if total_vol > 0 else 0

                    records.append({
                        "날짜": date_text.replace(".", "-"),
                        "종가": close,
                        "공매도량": short_vol,
                        "총거래량": total_vol,
                        "공매도_비중": ratio,
                    })
            except Exception:
                continue

        return records[:days]

    # ----------------------------------------------------------
    # 종합 수급 분석
    # ----------------------------------------------------------
    def get_supply_analysis(self, stock_code: str) -> dict:
        """외국인+기관+공매도 종합 분석"""
        investor = self.get_investor_daily(stock_code, 14)
        short = self.get_short_selling(stock_code, 14)

        analysis = {"외국인": {}, "기관": {}, "공매도": {}, "종합판단": "", "신호": []}
        signals = []

        if investor:
            f_total = sum(d.get("외국인_순매수", 0) for d in investor)
            o_total = sum(d.get("기관_순매수", 0) for d in investor)
            hold_rate = investor[0].get("외국인_보유율", "") if investor else ""

            analysis["외국인"] = {
                "2주_누적순매수": f_total,
                "추세": "매수 지속" if f_total > 0 else "매도 지속",
                "보유율": hold_rate,
            }
            analysis["기관"] = {
                "2주_누적순매수": o_total,
                "추세": "매수 지속" if o_total > 0 else "매도 지속",
            }

            if f_total > 0:
                signals.append("외국인 2주 순매수 (+)")
            else:
                signals.append("외국인 2주 순매도 (-)")
            if o_total > 0:
                signals.append("기관 2주 순매수 (+)")
            else:
                signals.append("기관 2주 순매도 (-)")

        if short:
            avg_ratio = sum(d.get("공매도_비중", 0) for d in short) / len(short)
            analysis["공매도"] = {
                "평균_비중": f"{avg_ratio:.2f}%",
                "최근_비중": f"{short[0].get('공매도_비중', 0)}%" if short else "N/A",
                "판단": "과열" if avg_ratio > 10 else "주의" if avg_ratio > 5 else "정상",
            }
            if avg_ratio > 5:
                signals.append(f"공매도 비중 높음 ({avg_ratio:.1f}%)")

        pos = sum(1 for s in signals if "+" in s)
        neg = sum(1 for s in signals if "-" in s or "높음" in s)
        if pos > neg:
            analysis["종합판단"] = "수급 긍정적 (외국인/기관 매수 우위)"
        elif neg > pos:
            analysis["종합판단"] = "수급 부정적 (외국인/기관 매도 또는 공매도 증가)"
        else:
            analysis["종합판단"] = "수급 중립"
        analysis["신호"] = signals

        return {
            "analysis": analysis,
            "외국인_일별": investor[:14],
            "공매도_일별": short[:14],
        }

    @staticmethod
    def _to_int(val) -> int:
        try:
            s = str(val).replace(",", "").replace("\t", "").replace("\n", "").strip()
            # 네이버 금융에서 마이너스가 특수문자일 수 있음
            s = s.replace("−", "-").replace("–", "-").replace("\xa0", "")
            if not s or s == "-" or s == "":
                return 0
            # +/- 부호 처리
            return int(float(s))
        except (ValueError, TypeError):
            return 0
