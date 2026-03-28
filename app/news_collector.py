"""
📰 뉴스 수집기
- 네이버 뉴스 검색 API로 종목 관련 뉴스를 수집합니다.
- RSS/웹 검색 기반 백업 수집도 지원합니다.

사전 준비:
  네이버 개발자센터 (https://developers.naver.com)
  → 애플리케이션 등록 → 검색 API 사용 신청
  → Client ID, Client Secret 발급
"""

import os
import re
import html
import httpx
from datetime import datetime, timedelta
from typing import Optional


NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")


class NewsCollector:
    """종목 관련 뉴스를 수집합니다."""

    # 종목코드 → 검색어 매핑 (자주 쓰는 종목)
    STOCK_NAMES = {
        "005930": "삼성전자",
        "000660": "SK하이닉스",
        "035420": "NAVER",
        "035720": "카카오",
        "006400": "삼성SDI",
        "051910": "LG화학",
        "005380": "현대차",
        "068270": "셀트리온",
        "003670": "포스코퓨처엠",
        "247540": "에코프로비엠",
        "373220": "LG에너지솔루션",
        "207940": "삼성바이오로직스",
        "005490": "POSCO홀딩스",
        "055550": "신한지주",
        "105560": "KB금융",
    }

    def __init__(self):
        self.client_id = NAVER_CLIENT_ID
        self.client_secret = NAVER_CLIENT_SECRET

    # ----------------------------------------------------------
    # 메인: 종목 뉴스 수집
    # ----------------------------------------------------------
    async def collect(
        self,
        stock_code: str,
        stock_name: str = "",
        max_articles: int = 20,
    ) -> list[dict]:
        """
        종목 관련 뉴스를 수집합니다.

        Args:
            stock_code: 종목코드 6자리
            stock_name: 종목명 (미입력 시 자동 매핑)
            max_articles: 수집할 기사 수 (최대 100)

        Returns:
            [{"title": ..., "description": ..., "link": ..., "pub_date": ..., "source": ...}, ...]
        """
        # 종목명 결정
        name = stock_name or self.STOCK_NAMES.get(stock_code, "")
        if not name:
            raise ValueError(
                f"종목코드 {stock_code}의 종목명을 알 수 없습니다. "
                f"stock_name 파라미터를 직접 입력해주세요."
            )

        articles = []

        # 방법 1: 네이버 뉴스 검색 API (권장)
        if self.client_id and self.client_secret:
            articles = await self._search_naver_api(name, max_articles)
        else:
            # 방법 2: 네이버 뉴스 RSS (API 키 없을 때 백업)
            articles = await self._search_naver_rss(name, max_articles)

        # 중복 제거 (같은 제목)
        seen_titles = set()
        unique = []
        for a in articles:
            clean_title = re.sub(r"\s+", "", a["title"])
            if clean_title not in seen_titles:
                seen_titles.add(clean_title)
                unique.append(a)

        return unique[:max_articles]

    # ----------------------------------------------------------
    # 네이버 뉴스 검색 API
    # ----------------------------------------------------------
    async def _search_naver_api(self, query: str, count: int) -> list[dict]:
        """네이버 뉴스 검색 API를 사용합니다."""
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }

        # 주식 관련 뉴스만 나오도록 검색어 보강
        search_query = f"{query} 주식"

        params = {
            "query": search_query,
            "display": min(count, 100),
            "start": 1,
            "sort": "date",  # 최신순
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        articles = []
        for item in data.get("items", []):
            articles.append({
                "title": self._clean_html(item.get("title", "")),
                "description": self._clean_html(item.get("description", "")),
                "link": item.get("originallink") or item.get("link", ""),
                "pub_date": self._parse_naver_date(item.get("pubDate", "")),
                "source": self._extract_source(item.get("originallink", "")),
            })

        return articles

    # ----------------------------------------------------------
    # 네이버 RSS 백업 (API 키 없을 때)
    # ----------------------------------------------------------
    async def _search_naver_rss(self, query: str, count: int) -> list[dict]:
        """
        네이버 뉴스 RSS를 사용합니다.
        API 키가 없을 때의 백업 방법입니다.
        """
        url = "https://news.google.com/rss/search"
        params = {
            "q": f"{query} 주식",
            "hl": "ko",
            "gl": "KR",
            "ceid": "KR:ko",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                text = resp.text

            # 간단한 XML 파싱 (의존성 최소화)
            articles = []
            items = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)

            for item_xml in items[:count]:
                title = self._extract_xml_tag(item_xml, "title")
                link = self._extract_xml_tag(item_xml, "link")
                pub_date = self._extract_xml_tag(item_xml, "pubDate")
                source = self._extract_xml_tag(item_xml, "source")

                if title:
                    articles.append({
                        "title": self._clean_html(title),
                        "description": "",
                        "link": link,
                        "pub_date": pub_date,
                        "source": source,
                    })

            return articles

        except Exception:
            # 모든 외부 수집 실패 시 빈 리스트
            return []

    # ----------------------------------------------------------
    # 뉴스 요약 (AI 분석에 넣기 좋은 형태로)
    # ----------------------------------------------------------
    def format_for_analysis(self, articles: list[dict], max_articles: int = 15) -> str:
        """
        수집된 기사들을 AI 분석에 넣기 좋은 텍스트로 변환합니다.
        비용 절약을 위해 제목 + 요약만 사용합니다.
        """
        if not articles:
            return "(수집된 뉴스 없음)"

        lines = [f"[최근 뉴스 {len(articles[:max_articles])}건]"]
        for i, a in enumerate(articles[:max_articles], 1):
            date_str = a.get("pub_date", "날짜 불명")
            source = a.get("source", "출처 불명")
            lines.append(f"\n기사 #{i} [{date_str}] ({source})")
            lines.append(f"제목: {a['title']}")
            if a.get("description"):
                lines.append(f"요약: {a['description'][:150]}")

        return "\n".join(lines)

    # ----------------------------------------------------------
    # 유틸리티
    # ----------------------------------------------------------
    @staticmethod
    def _clean_html(text: str) -> str:
        """HTML 태그와 엔티티를 제거합니다."""
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = re.sub(r"&[a-zA-Z]+;", "", text)
        return text.strip()

    @staticmethod
    def _parse_naver_date(date_str: str) -> str:
        """네이버 API 날짜를 파싱합니다."""
        try:
            # "Mon, 15 Mar 2026 10:30:00 +0900" 형태
            dt = datetime.strptime(date_str[:25], "%a, %d %b %Y %H:%M:%S")
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return date_str

    @staticmethod
    def _extract_source(url: str) -> str:
        """URL에서 뉴스 출처를 추출합니다."""
        try:
            domain = re.findall(r"https?://(?:www\.)?([^/]+)", url)
            if domain:
                name = domain[0].split(".")[0]
                source_map = {
                    "hankyung": "한국경제",
                    "mk": "매일경제",
                    "mt": "머니투데이",
                    "sedaily": "서울경제",
                    "edaily": "이데일리",
                    "etnews": "전자신문",
                    "chosun": "조선일보",
                    "donga": "동아일보",
                    "joongang": "중앙일보",
                    "hani": "한겨레",
                    "yna": "연합뉴스",
                    "newsis": "뉴시스",
                    "news1": "뉴스1",
                    "bloter": "블로터",
                    "zdnet": "ZDNet",
                    "infostock": "인포스탁",
                    "thebell": "더벨",
                }
                return source_map.get(name, domain[0])
        except Exception:
            pass
        return "출처 불명"

    @staticmethod
    def _extract_xml_tag(xml_str: str, tag: str) -> str:
        """XML 텍스트에서 태그 내용을 추출합니다."""
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml_str, re.DOTALL)
        if match:
            content = match.group(1).strip()
            # CDATA 처리
            cdata = re.search(r"<!\[CDATA\[(.*?)\]\]>", content, re.DOTALL)
            if cdata:
                return cdata.group(1).strip()
            return content
        return ""
