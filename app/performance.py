"""
📊 성과 추적기
- 과거 추천 이력의 실제 성과를 자동 추적합니다.
- 추천 후 3일/7일/30일 뒤 주가를 확인하여 적중 여부를 기록합니다.
- 적중률 통계를 산출하고, 뉴스 vs 기술 분석의 정확도를 비교합니다.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.kis_client import KISClient

HISTORY_FILE = Path(__file__).parent.parent / "data" / "recommendation_history.json"


class PerformanceTracker:
    """추천 성과를 추적하고 통계를 산출합니다."""

    def __init__(self, kis: KISClient):
        self.kis = kis

    # ----------------------------------------------------------
    # 1) 성과 업데이트: 과거 추천의 현재가를 확인하여 기록
    # ----------------------------------------------------------
    async def update_performance(self) -> dict:
        """
        모든 미완료 추천의 성과를 업데이트합니다.
        추천 후 3일/7일/30일이 지난 항목의 현재가를 확인합니다.
        """
        history = self._load_history()
        if not history:
            return {"status": "empty", "message": "추천 이력이 없습니다."}

        updated_count = 0
        errors = []
        now = datetime.now()

        for record in history:
            try:
                rec_time = datetime.fromisoformat(record["timestamp"])
                days_passed = (now - rec_time).days
                stock_code = record["stock_code"]
                rec_price = record.get("price_at_recommend", 0)

                if not rec_price or rec_price == 0:
                    continue

                # 현재가 조회
                current_price = None
                try:
                    price_data = await self.kis.get_current_price(stock_code)
                    current_price = price_data.get("현재가", 0)
                except Exception:
                    continue

                if not current_price:
                    continue

                changed = False

                # 3일 경과 체크
                if days_passed >= 3 and record.get("price_after_3d") is None:
                    record["price_after_3d"] = current_price
                    record["return_3d"] = round((current_price - rec_price) / rec_price * 100, 2)
                    changed = True

                # 7일 경과 체크
                if days_passed >= 7 and record.get("price_after_7d") is None:
                    record["price_after_7d"] = current_price
                    record["return_7d"] = round((current_price - rec_price) / rec_price * 100, 2)
                    changed = True

                # 30일 경과 체크
                if days_passed >= 30 and record.get("price_after_30d") is None:
                    record["price_after_30d"] = current_price
                    record["return_30d"] = round((current_price - rec_price) / rec_price * 100, 2)
                    changed = True

                # 아직 기간이 안 지났으면 현재 수익률만 업데이트
                if days_passed < 30:
                    record["current_price"] = current_price
                    record["current_return"] = round((current_price - rec_price) / rec_price * 100, 2)
                    changed = True

                # 적중 여부 판단 (7일 기준)
                if record.get("return_7d") is not None and record.get("was_correct") is None:
                    rec = record.get("recommendation", "")
                    ret = record["return_7d"]
                    if "매수" in rec:
                        record["was_correct"] = ret > 0
                    elif "매도" in rec:
                        record["was_correct"] = ret < 0
                    else:  # 관망
                        record["was_correct"] = abs(ret) < 3  # 3% 이내면 관망 적중
                    changed = True

                if changed:
                    updated_count += 1

            except Exception as e:
                errors.append(f"{record.get('stock_code', '?')}: {str(e)}")

        self._save_history(history)

        return {
            "status": "success",
            "total_records": len(history),
            "updated": updated_count,
            "errors": errors if errors else None,
        }

    # ----------------------------------------------------------
    # 2) 종합 통계
    # ----------------------------------------------------------
    def get_stats(self) -> dict:
        """
        전체 추천 성과 통계를 산출합니다.
        """
        history = self._load_history()
        if not history:
            return {"status": "empty", "message": "추천 이력이 없습니다."}

        total = len(history)
        evaluated = [h for h in history if h.get("was_correct") is not None]
        correct = [h for h in evaluated if h["was_correct"]]

        # 추천 유형별 통계
        buy_recs = [h for h in evaluated if "매수" in h.get("recommendation", "")]
        sell_recs = [h for h in evaluated if "매도" in h.get("recommendation", "")]
        hold_recs = [h for h in evaluated if "관망" in h.get("recommendation", "")]

        buy_correct = sum(1 for h in buy_recs if h["was_correct"])
        sell_correct = sum(1 for h in sell_recs if h["was_correct"])
        hold_correct = sum(1 for h in hold_recs if h["was_correct"])

        # 평균 수익률
        returns_3d = [h["return_3d"] for h in history if h.get("return_3d") is not None]
        returns_7d = [h["return_7d"] for h in history if h.get("return_7d") is not None]
        returns_30d = [h["return_30d"] for h in history if h.get("return_30d") is not None]

        # 뉴스 점수 높았을 때 vs 낮았을 때 비교
        high_news = [h for h in history if h.get("news_score", 0) > 15 and h.get("return_7d") is not None]
        low_news = [h for h in history if h.get("news_score", 0) < -15 and h.get("return_7d") is not None]

        # 최고/최악 추천
        if returns_7d:
            all_with_7d = [h for h in history if h.get("return_7d") is not None]
            best = max(all_with_7d, key=lambda h: h["return_7d"])
            worst = min(all_with_7d, key=lambda h: h["return_7d"])
        else:
            best = worst = None

        return {
            "총_추천수": total,
            "평가_완료": len(evaluated),
            "전체_적중률": f"{len(correct)/len(evaluated)*100:.1f}%" if evaluated else "데이터 부족",
            "적중": len(correct),
            "오답": len(evaluated) - len(correct),
            "유형별": {
                "매수_추천": {
                    "횟수": len(buy_recs),
                    "적중": buy_correct,
                    "적중률": f"{buy_correct/len(buy_recs)*100:.1f}%" if buy_recs else "-",
                },
                "매도_추천": {
                    "횟수": len(sell_recs),
                    "적중": sell_correct,
                    "적중률": f"{sell_correct/len(sell_recs)*100:.1f}%" if sell_recs else "-",
                },
                "관망_추천": {
                    "횟수": len(hold_recs),
                    "적중": hold_correct,
                    "적중률": f"{hold_correct/len(hold_recs)*100:.1f}%" if hold_recs else "-",
                },
            },
            "평균_수익률": {
                "3일": f"{sum(returns_3d)/len(returns_3d):.2f}%" if returns_3d else "데이터 부족",
                "7일": f"{sum(returns_7d)/len(returns_7d):.2f}%" if returns_7d else "데이터 부족",
                "30일": f"{sum(returns_30d)/len(returns_30d):.2f}%" if returns_30d else "데이터 부족",
            },
            "뉴스_신호_정확도": {
                "뉴스_긍정일때_평균수익률": f"{sum(h['return_7d'] for h in high_news)/len(high_news):.2f}%" if high_news else "데이터 부족",
                "뉴스_부정일때_평균수익률": f"{sum(h['return_7d'] for h in low_news)/len(low_news):.2f}%" if low_news else "데이터 부족",
            },
            "최고_추천": {
                "종목": best.get("stock_name", ""),
                "수익률": f"{best['return_7d']}%",
                "날짜": best.get("timestamp", "")[:10],
            } if best else None,
            "최악_추천": {
                "종목": worst.get("stock_name", ""),
                "수익률": f"{worst['return_7d']}%",
                "날짜": worst.get("timestamp", "")[:10],
            } if worst else None,
        }

    # ----------------------------------------------------------
    # 3) 개별 추천 이력 + 성과
    # ----------------------------------------------------------
    def get_history_with_performance(
        self,
        stock_code: Optional[str] = None,
        limit: int = 30,
    ) -> list[dict]:
        """성과가 포함된 추천 이력을 조회합니다."""
        history = self._load_history()

        if stock_code:
            history = [h for h in history if h.get("stock_code") == stock_code]

        # 최신순 정렬
        history.sort(key=lambda h: h.get("timestamp", ""), reverse=True)

        result = []
        for h in history[:limit]:
            rec_price = h.get("price_at_recommend", 0)
            entry = {
                "날짜": h.get("timestamp", "")[:16],
                "종목": h.get("stock_name", h.get("stock_code", "")),
                "종목코드": h.get("stock_code", ""),
                "추천": h.get("recommendation", ""),
                "종합점수": h.get("total_score", 0),
                "추천가": f"{rec_price:,}원" if rec_price else "-",
                "뉴스점수": h.get("news_score", 0),
                "기술점수": h.get("tech_score", 0),
            }

            # 현재 수익률
            if h.get("current_return") is not None:
                ret = h["current_return"]
                entry["현재수익률"] = f"{ret:+.2f}%"
                entry["현재가"] = f"{h.get('current_price', 0):,}원"

            # 3일 성과
            if h.get("return_3d") is not None:
                entry["3일수익률"] = f"{h['return_3d']:+.2f}%"

            # 7일 성과
            if h.get("return_7d") is not None:
                entry["7일수익률"] = f"{h['return_7d']:+.2f}%"

            # 30일 성과
            if h.get("return_30d") is not None:
                entry["30일수익률"] = f"{h['return_30d']:+.2f}%"

            # 적중 여부
            if h.get("was_correct") is not None:
                entry["적중"] = "O" if h["was_correct"] else "X"

            result.append(entry)

        return result

    # ----------------------------------------------------------
    # 4) 가중치 추천 (성과 기반)
    # ----------------------------------------------------------
    def suggest_weights(self, auto_apply: bool = False) -> dict:
        """
        과거 성과를 분석하여 뉴스/기술 분석 가중치를 추천합니다.
        auto_apply=True이면 자동으로 가중치를 저장하여 다음 분석부터 적용됩니다.
        """
        history = self._load_history()
        evaluated = [h for h in history if h.get("return_7d") is not None]

        if len(evaluated) < 5:
            return {
                "status": "데이터 부족",
                "message": f"최소 5건의 평가된 추천이 필요합니다. (현재 {len(evaluated)}건)",
                "현재_가중치": self._load_current_weights(),
            }

        # 뉴스 점수와 실제 수익률의 상관관계
        news_correct = 0
        tech_correct = 0
        total = len(evaluated)

        for h in evaluated:
            ret = h["return_7d"]
            news = h.get("news_score", 0)
            tech = h.get("tech_score", 0)

            if (news > 0 and ret > 0) or (news < 0 and ret < 0) or (abs(news) < 5 and abs(ret) < 2):
                news_correct += 1
            if (tech > 0 and ret > 0) or (tech < 0 and ret < 0) or (abs(tech) < 5 and abs(ret) < 2):
                tech_correct += 1

        news_accuracy = news_correct / total
        tech_accuracy = tech_correct / total
        total_accuracy = news_accuracy + tech_accuracy

        if total_accuracy > 0:
            suggested_news = round(news_accuracy / total_accuracy, 2)
            suggested_tech = round(tech_accuracy / total_accuracy, 2)
        else:
            suggested_news = 0.4
            suggested_tech = 0.6

        # 극단적 가중치 방지 (최소 15%, 최대 85%)
        suggested_news = max(0.15, min(0.85, suggested_news))
        suggested_tech = 1.0 - suggested_news

        current = self._load_current_weights()
        applied = False

        if auto_apply and total >= 5:
            self._save_weights(suggested_news, suggested_tech)
            applied = True

        return {
            "status": "success",
            "분석_건수": total,
            "뉴스_적중률": f"{news_accuracy*100:.1f}%",
            "기술_적중률": f"{tech_accuracy*100:.1f}%",
            "이전_가중치": current,
            "추천_가중치": {
                "뉴스": f"{suggested_news*100:.0f}%",
                "기술": f"{suggested_tech*100:.0f}%",
            },
            "자동_적용": applied,
            "설명": (
                f"뉴스 적중률({news_accuracy*100:.0f}%) vs 기술 적중률({tech_accuracy*100:.0f}%) "
                f"기반으로 가중치를 조정하면 정확도가 개선될 수 있습니다."
            ),
        }

    def _save_weights(self, news: float, tech: float):
        """최적화된 가중치를 파일에 저장"""
        import json
        weights_file = Path(__file__).parent.parent / "data" / "optimized_weights.json"
        weights_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "news": round(news, 2),
            "technical": round(tech, 2),
            "updated_at": datetime.now().isoformat(),
        }
        with open(weights_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_current_weights(self) -> dict:
        """현재 적용 중인 가중치 로드"""
        import json
        weights_file = Path(__file__).parent.parent / "data" / "optimized_weights.json"
        try:
            if weights_file.exists():
                with open(weights_file, "r", encoding="utf-8") as f:
                    w = json.load(f)
                return {"뉴스": f"{w['news']*100:.0f}%", "기술": f"{w['technical']*100:.0f}%", "소스": "자동최적화"}
        except Exception:
            pass
        return {"뉴스": "40%", "기술": "60%", "소스": "기본값"}

    # ----------------------------------------------------------
    # 파일 I/O
    # ----------------------------------------------------------
    def _load_history(self) -> list[dict]:
        try:
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save_history(self, history: list[dict]):
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
