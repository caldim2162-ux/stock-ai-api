"""
🔥 주도 테마 & 중소형주 자동 스캐너
네이버 금융에서 당일 거래대금이 터지는 상위 테마를 찾고, 
그 안에서 시가총액이 가벼운(max_cap 이하) 종목만 쏙쏙 골라냅니다.
"""

import requests
from bs4 import BeautifulSoup
import time

class ThemeScanner:
    def __init__(self):
        self.base_url = "https://finance.naver.com/sise/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def get_market_cap(self, stock_code: str) -> int:
        """특정 종목의 시가총액(억원)을 크롤링합니다."""
        try:
            url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
            res = requests.get(url, headers=self.headers)
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 시가총액 데이터 추출
            cap_em = soup.select_one("#_market_sum")
            if cap_em:
                cap_str = cap_em.text.replace("\t", "").replace("\n", "").replace(",", "")
                if "조" in cap_str:
                    parts = cap_str.split("조")
                    trillion = int(parts[0].strip()) * 10000
                    billion = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 0
                    return trillion + billion
                else:
                    return int(cap_str.strip())
            return 999999  # 조회 실패 시 무거운 주식으로 취급하여 제외
        except Exception as e:
            return 999999

    def get_small_cap_theme_stocks(self, top_n_themes: int = 3, max_cap: int = 5000, stocks_per_theme: int = 10) -> dict:
        """
        주도 테마에서 시가총액이 'max_cap(억원)' 이하인 가벼운 종목만 골라냅니다.
        """
        print(f"🔍 [테마 스캔] 상위 {top_n_themes}개 테마 중 시총 {max_cap}억 이하 스캔 중...")
        small_cap_stocks = {}

        try:
            res = requests.get(self.base_url + "theme.naver", headers=self.headers)
            soup = BeautifulSoup(res.text, "html.parser")
            themes = soup.select(".type_1.theme tr")
            
            valid_themes = []
            for t in themes:
                a_tag = t.select_one("a")
                if a_tag:
                    valid_themes.append((a_tag.text, a_tag["href"]))

            for i in range(min(top_n_themes, len(valid_themes))):
                theme_name, theme_link = valid_themes[i]
                print(f"\n▶ {i+1}위 테마 분석 중: {theme_name}")
                
                t_res = requests.get("https://finance.naver.com" + theme_link, headers=self.headers)
                t_soup = BeautifulSoup(t_res.text, "html.parser")
                stocks = t_soup.select("table.type_5 tbody tr")
                
                added_count = 0
                for s in stocks:
                    name_tag = s.select_one("td.name a")
                    if name_tag:
                        stock_name = name_tag.text
                        stock_code = name_tag["href"].split("code=")[-1]
                        
                        # 시가총액 확인
                        market_cap = self.get_market_cap(stock_code)
                        
                        # 시가총액이 기준치 이하(예: 5000억 이하)일 때만 딕셔너리에 추가
                        if market_cap <= max_cap:
                            small_cap_stocks[stock_code] = stock_name
                            print(f"  ✔️ 발견: {stock_name} (시총: {market_cap:,}억)")
                            added_count += 1
                            
                        # 네이버 서버 차단 방지용 약간의 휴식
                        time.sleep(0.2)
                        
                        if added_count >= stocks_per_theme:
                            break

            print(f"\n✅ 조건에 맞는 주도 테마주 {len(small_cap_stocks)}개 발굴 완료!")
            return small_cap_stocks

        except Exception as e:
            print(f"❌ 스캔 에러: {e}")
            return {}

# ==========================================================
# 이 파일을 직접 실행했을 때 작동하는 테스트 코드입니다.
# ==========================================================
if __name__ == "__main__":
    scanner = ThemeScanner()
    # 상위 3개 테마에서, 시가총액 5000억 이하인 주식을 테마당 5개씩 뽑아봅니다.
    stocks = scanner.get_small_cap_theme_stocks(top_n_themes=3, max_cap=5000, stocks_per_theme=5)
    
    print("\n최종 추출된 종목 딕셔너리:")
    print(stocks)