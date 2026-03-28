"""
📈 개인 주식 분석 AI API v3 (뉴스 + 매매 추천)
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from pathlib import Path

from app.knowledge_manager import KnowledgeManager
from app.ai_analyzer import AIAnalyzer
from app.kis_client import KISClient
from app.auto_learner import AutoLearner
from app.news_collector import NewsCollector
from app.news_sentiment import NewsSentimentAnalyzer
from app.signal_engine import SignalEngine
from app.recommendation import RecommendationEngine
from app.performance import PerformanceTracker
from app.telegram_bot import TelegramBot
from app.scanner import StockScanner
from app.backtest import BacktestEngine
from app.auto_trader import AutoTrader
from app.krx_data import KRXDataFetcher
from app.ml_predictor import MLPredictor
from app.accumulation_scanner import AccumulationScanner
from app.morning_briefing import MorningBriefing
from app.position_monitor import PositionMonitor

app = FastAPI(
    title="📈 나만의 주식 매매 추천 AI API",
    description="한투 API + 뉴스 감성 분석 + 기술적 분석 → AI 매매 추천 + 텔레그램 알림",
    version="3.2.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

knowledge = KnowledgeManager()
analyzer = AIAnalyzer(knowledge)
kis = KISClient()
learner = AutoLearner(kis, knowledge)
news_collector = NewsCollector()
sentiment_analyzer = NewsSentimentAnalyzer()
signal_engine = SignalEngine()
recommender = RecommendationEngine(kis, knowledge, learner)
tracker = PerformanceTracker(kis)
telegram = TelegramBot()
scanner = StockScanner(kis, knowledge, learner, telegram)
backtester = BacktestEngine(kis)
trader = AutoTrader(kis, telegram)
krx = KRXDataFetcher()
ml = MLPredictor()
acc_scanner = AccumulationScanner()
morning = MorningBriefing(telegram)
pos_monitor = PositionMonitor(kis, telegram)


# ============================================================
# 📱 텔레그램 명령어 처리 (백그라운드)
# ============================================================
import asyncio

_tg_offset = 0
_tg_running = False

async def telegram_polling_loop():
    """텔레그램 메시지/버튼 클릭을 계속 감시합니다."""
    global _tg_offset, _tg_running
    if not telegram.is_configured:
        return
    _tg_running = True

    # 시작 시 기존 메시지 건너뛰기
    _, _tg_offset = await telegram.get_callback_updates(0)

    while _tg_running:
        try:
            events, _tg_offset = await telegram.get_callback_updates(_tg_offset)

            for event in events:
                # 버튼 클릭 (승인/거부)
                if event["type"] == "callback":
                    data = event["data"]
                    cb_id = event.get("callback_id", "")

                    if data.startswith("approve_"):
                        order_id = data.replace("approve_", "")
                        result = await trader.approve_order(order_id)
                        await telegram.answer_callback(cb_id, "✅ 승인됨!")
                        if result.get("action") == "매수완료":
                            await telegram.send(f"✅ 주문이 체결되었습니다!\n{result.get('detail', {}).get('종목코드', '')} {result.get('detail', {}).get('수량', '')}주")
                        elif "실패" in str(result.get("action", "")):
                            await telegram.send(f"❌ 주문 실패: {result.get('detail', '')}")

                    elif data.startswith("reject_"):
                        order_id = data.replace("reject_", "")
                        trader.reject_order(order_id)
                        await telegram.answer_callback(cb_id, "❌ 거부됨")
                        await telegram.send("❌ 주문이 거부되었습니다.")

                # 텍스트 메시지 명령어
                elif event["type"] == "message":
                    text = event["text"].lower().strip()
                    await handle_telegram_command(text)

        except Exception:
            pass

        await asyncio.sleep(2)  # 2초마다 체크


async def handle_telegram_command(text: str):
    """텔레그램 텍스트 명령어를 처리합니다."""
    # 승인 (가장 최근 대기 주문)
    if text in ("ㅇ", "승인", "y", "yes", "ok"):
        pending = trader.get_pending_orders()
        if pending:
            order_id = pending[-1]["order_id"]
            result = await trader.approve_order(order_id)
            await telegram.send(f"✅ 주문 승인!\n{result.get('detail', '')}")
        else:
            await telegram.send("대기 중인 주문이 없습니다.")

    # 거부
    elif text in ("ㄴ", "거부", "n", "no"):
        pending = trader.get_pending_orders()
        if pending:
            order_id = pending[-1]["order_id"]
            trader.reject_order(order_id)
            await telegram.send("❌ 주문이 거부되었습니다.")
        else:
            await telegram.send("대기 중인 주문이 없습니다.")

    # 긴급 중지
    elif text in ("중지", "stop", "긴급중지"):
        trader.emergency_stop()
        await telegram.send("🚨 긴급 중지! 모든 대기 주문 취소, 자동 매매 꺼짐.")

    # 상태 확인
    elif text in ("상태", "status"):
        config = trader.get_config()
        enabled = config.get("enabled", False)
        mode = "자동" if config.get("mode") == "auto" else "확인"
        spent = config.get("today_spent", 0)
        limit = config.get("daily_limit", 0)
        pending = len(trader.get_pending_orders())
        msg = (
            f"📊 <b>현재 상태</b>\n\n"
            f"자동 매매: {'✅ 켜짐 (' + mode + ')' if enabled else '⬜ 꺼짐'}\n"
            f"오늘 사용: {spent:,}원 / {limit:,}원\n"
            f"대기 주문: {pending}건"
        )
        await telegram.send(msg)

    # 대기 주문 확인
    elif text in ("대기", "pending", "주문"):
        pending = trader.get_pending_orders()
        if not pending:
            await telegram.send("대기 중인 주문이 없습니다.")
        else:
            for p in pending:
                tp = "매수" if p.get("type") == "buy" else "매도"
                await telegram.send(
                    f"{'🟢' if tp == '매수' else '🔴'} {tp}: {p.get('stock_name', '')} "
                    f"{p.get('quantity', 0)}주 {p.get('amount', 0):,}원\n"
                    f"ㅇ → 승인 / ㄴ → 거부"
                )

    # 도움말
    elif text in ("도움", "help", "?", "명령어"):
        await telegram.send(
            "📱 <b>사용 가능한 명령어</b>\n\n"
            "<b>ㅇ</b> — 대기 주문 승인\n"
            "<b>ㄴ</b> — 대기 주문 거부\n"
            "<b>스캔</b> — 지금 즉시 스캔 실행\n"
            "<b>상태</b> — 현재 상태 확인\n"
            "<b>대기</b> — 대기 주문 목록\n"
            "<b>중지</b> — 긴급 중지\n"
            "<b>도움</b> — 이 메시지"
        )

    # 수동 스캔
    elif text in ("스캔", "scan", "분석"):
        await telegram.send("🔍 스캔 시작합니다...")
        asyncio.create_task(run_scheduled_scan("수동"))


@app.on_event("startup")
async def start_telegram_polling():
    """서버 시작 시 텔레그램 폴링과 자동 스캔 스케줄러를 시작합니다."""
    if telegram.is_configured:
        asyncio.create_task(telegram_polling_loop())
    asyncio.create_task(scheduled_scan_loop())


# ============================================================
# ⏰ 자동 스캔 스케줄러 (9:30, 14:30)
# ============================================================
SCAN_TIMES = [(9, 30), (14, 30)]  # (시, 분)
_scan_done_today = set()  # 오늘 이미 실행한 시간 기록


async def scheduled_scan_loop():
    """매일 정해진 시간에 자동 스캔 → 매매 트리거"""
    global _scan_done_today

    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # 날짜 바뀌면 리셋
        for key in list(_scan_done_today):
            if not key.startswith(today):
                _scan_done_today.discard(key)

        # 스캔 시간 체크
        for hour, minute in SCAN_TIMES:
            scan_key = f"{today}_{hour}:{minute}"
            if scan_key in _scan_done_today:
                continue

            # 지정 시간이 되었는지 (±2분 여유)
            if now.hour == hour and abs(now.minute - minute) <= 2:
                _scan_done_today.add(scan_key)
                asyncio.create_task(run_scheduled_scan(f"{hour}:{minute:02d}"))

        await asyncio.sleep(30)  # 30초마다 체크


async def run_scheduled_scan(time_label: str):
    """스캔 실행 + 매매 트리거"""
    try:
        if telegram.is_configured:
            await telegram.send(f"⏰ <b>{time_label} 자동 스캔 시작</b>\n관심 종목 분석 중...")

        # 관심 종목 + 인기 종목 합치기 (중복 제거)
        watchlist = scanner.get_watchlist()
        popular = scanner.get_default_stocks()
        seen = set()
        stocks = []
        for s in watchlist + popular:
            code = s.get("code", "")
            if code and code not in seen:
                seen.add(code)
                stocks.append(s)

        # 빠른 스캔으로 후보 필터
        quick = await scanner.quick_scan(stocks)
        all_results = quick.get("all_results", [])

        # 신호 있는 종목만 추출 (점수 절대값 10 이상)
        candidates = [r for r in all_results if abs(r.get("tech_score", 0)) >= 10]
        if not candidates:
            candidates = all_results[:5]  # 신호 약해도 상위 5개

        buy_signals = []
        sell_signals = []

        # 후보 종목만 풀 분석 → 자동 매매 트리거
        for stock in candidates[:3]:  # 최대 3개 (크레딧 절약)
            try:
                result = await recommender.recommend(
                    stock_code=stock["stock_code"],
                    stock_name=stock.get("stock_name", ""),
                )

                score = result.get("total_score", 0)
                rec = result.get("recommendation", "")

                if score >= 30:
                    buy_signals.append(result)
                elif score <= -30:
                    sell_signals.append(result)

                # 자동 매매 트리거 (켜져있으면)
                if trader.config.get("enabled"):
                    await trader.process_recommendation(result)

                await asyncio.sleep(1)  # API 제한 방지

            except Exception:
                continue

        # 결과 텔레그램 알림
        if telegram.is_configured:
            msg = f"⏰ <b>{time_label} 스캔 완료</b>\n\n"
            msg += f"총 {len(stocks)}개 → 후보 {len(candidates)}개 분석\n"

            if buy_signals:
                msg += f"\n🟢 매수 신호 {len(buy_signals)}개:\n"
                for r in buy_signals[:3]:
                    msg += f"  • {r.get('stock_name', '')} (점수 {r.get('total_score', 0)})\n"

            if sell_signals:
                msg += f"\n🔴 매도 신호 {len(sell_signals)}개:\n"
                for r in sell_signals[:3]:
                    msg += f"  • {r.get('stock_name', '')} (점수 {r.get('total_score', 0)})\n"

            if not buy_signals and not sell_signals:
                msg += "\n📊 뚜렷한 매매 신호 없음 (관망)"

            if trader.config.get("enabled"):
                msg += "\n\n🤖 자동 매매 활성 — 신호 종목은 텔레그램으로 확인 요청됩니다."

            await telegram.send(msg)

    except Exception as e:
        if telegram.is_configured:
            await telegram.send(f"⏰ 자동 스캔 오류: {str(e)[:200]}")


# === 요청 모델 ===
class StockCodeRequest(BaseModel):
    stock_code: str = Field(..., description="종목코드 6자리 (예: 005930)")

class WatchlistRequest(BaseModel):
    stock_codes: list[str] = Field(..., description="종목코드 목록")

class AnalysisRequest(BaseModel):
    stock_code: str = Field(..., description="종목코드 6자리")
    question: Optional[str] = Field(None, description="구체적인 질문")
    analysis_type: str = Field(default="comprehensive")

class KnowledgeEntry(BaseModel):
    category: str
    title: str
    content: str
    tags: list[str] = Field(default=[])

class KnowledgeBulkEntry(BaseModel):
    entries: list[KnowledgeEntry]

class ChatRequest(BaseModel):
    message: str
    context: Optional[str] = None

class DailyPriceRequest(BaseModel):
    stock_code: str
    start_date: str = ""
    end_date: str = ""
    period: str = "D"

class RecommendRequest(BaseModel):
    stock_code: str = Field(..., description="종목코드 6자리")
    stock_name: str = Field(default="", description="종목명 (미입력 시 자동)")
    question: Optional[str] = Field(None, description="추가 질문 (예: '단기 매매 관점에서 어때?')")
    force_refresh: bool = Field(default=False, description="True면 캐시 무시하고 새로 분석 (크레딧 사용)")

class NewsRequest(BaseModel):
    stock_code: str = Field(..., description="종목코드 6자리")
    stock_name: str = Field(default="", description="종목명")
    max_articles: int = Field(default=20, description="수집할 기사 수")


# ============================================================
# 🎯 매매 추천 (핵심 기능!)
# ============================================================
@app.post("/recommend", tags=["🎯 매매 추천"])
async def get_recommendation(request: RecommendRequest):
    """
    🎯 종합 매매 추천 (3중 판단)
    규칙 기반 + 뉴스 감성 + ML 예측(XGBoost) → AI가 매수/매도/관망을 추천합니다.
    같은 종목은 1시간 이내 재검색 시 캐시 결과를 반환합니다 (크레딧 미사용).
    """
    try:
        result = await recommender.recommend(
            stock_code=request.stock_code,
            stock_name=request.stock_name,
            question=request.question,
            force_refresh=request.force_refresh,
        )

        # ML 예측 추가 (캐시가 아닌 새 분석일 때만)
        if not result.get("cached") and ml.loaded:
            try:
                daily = await kis.get_daily_prices(request.stock_code)
                ml_result = ml.predict(daily)
                result["ml_prediction"] = ml_result
            except Exception:
                result["ml_prediction"] = {"available": False, "reason": "ML 예측 실패"}
        elif result.get("cached"):
            pass  # 캐시된 결과에 이미 ML 예측 포함
        else:
            result["ml_prediction"] = {"available": False, "reason": "모델 미로드"}

        # 텔레그램 알림 자동 전송 (캐시가 아닌 새 분석일 때만)
        if telegram.is_configured and not result.get("cached"):
            await telegram.send_recommendation(result)
        # 자동 매매 처리
        trade_result = None
        if not result.get("cached"):
            try:
                trade_result = await trader.process_recommendation(result)
            except Exception:
                trade_result = {"action": "에러", "detail": "자동 매매 처리 실패"}
        if trade_result:
            result["auto_trade"] = trade_result
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recommend/history", tags=["🎯 매매 추천"])
async def get_recommendation_history(stock_code: Optional[str] = None, limit: int = 20):
    """추천 이력을 조회합니다. 성과 추적에 사용합니다."""
    history = RecommendationEngine.get_history(stock_code=stock_code, limit=limit)
    return {"status": "success", "count": len(history), "history": history}


@app.get("/ml/predict/{stock_code}", tags=["🤖 ML 예측"])
async def ml_predict(stock_code: str):
    """
    🤖 XGBoost ML 모델로 매수/관망/매도 예측
    Google Colab에서 학습한 모델 사용 (승률 59.1%, 평균 수익률 +2.34%)
    """
    if not ml.loaded:
        return {"status": "error", "message": "ML 모델이 로드되지 않았습니다. data/ 폴더에 모델 파일을 넣어주세요."}
    try:
        daily = await kis.get_daily_prices(stock_code)
        result = ml.predict(daily)
        return {"status": "success", "stock_code": stock_code, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ml/status", tags=["🤖 ML 예측"])
async def ml_status():
    """ML 모델 상태 확인"""
    return {
        "loaded": ml.loaded,
        "model_info": ml.model_info if ml.loaded else None,
    }


# ============================================================
# 🔍 수급 매집 스캐너
# ============================================================
@app.get("/accumulation/scan", tags=["🔍 매집 스캐너"])
async def scan_accumulation(days: int = 10, min_consecutive: int = 3):
    """
    🔍 외국인/기관 매집 종목 스캔 (70개 종목)
    - 외국인 연속 매수 TOP 10
    - 기관 연속 매수 TOP 10
    - 외국인+기관 동시 매집 종목
    - 누적 순매수 TOP
    ⚠️ 70개 스캔에 약 30초 소요 (네이버 금융 크롤링)
    """
    try:
        result = acc_scanner.scan_all(days=days, min_consecutive=min_consecutive)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/accumulation/stock/{stock_code}", tags=["🔍 매집 스캐너"])
async def scan_single_accumulation(stock_code: str, days: int = 14):
    """
    🔍 단일 종목 매집 분석
    외국인/기관 연속 매수일, 누적 순매수, 매수 비율, 추세 가속/감속
    """
    try:
        name = ""
        # 종목명 찾기
        from app.accumulation_scanner import SCAN_STOCKS
        name = SCAN_STOCKS.get(stock_code, stock_code)
        result = acc_scanner.scan_single(stock_code, name, days)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/accumulation/quick", tags=["🔍 매집 스캐너"])
async def quick_accumulation(top_n: int = 5):
    """
    ⚡ 빠른 매집 스캔 (상위 20개 대형주만)
    삼성전자, SK하이닉스 등 주요 대형주만 빠르게 스캔
    """
    try:
        quick_stocks = {
            "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER",
            "035720": "카카오", "005380": "현대차", "068270": "셀트리온",
            "051910": "LG화학", "006400": "삼성SDI", "055550": "신한지주",
            "105560": "KB금융", "000270": "기아", "207940": "삼성바이오로직스",
            "005490": "POSCO홀딩스", "012330": "현대모비스", "003490": "대한항공",
            "066570": "LG전자", "009540": "HD한국조선해양", "042660": "한화오션",
            "138040": "메리츠금융지주", "086790": "하나금융지주",
        }
        result = acc_scanner.scan_all(days=10, min_consecutive=2, stocks=quick_stocks)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 📈 성과 추적
# ============================================================
@app.post("/performance/update", tags=["📈 성과 추적"])
async def update_performance():
    """
    📈 성과 업데이트
    과거 추천의 현재가를 확인하여 3일/7일/30일 수익률을 기록합니다.
    업데이트 후 가중치를 자동 최적화합니다.
    """
    try:
        result = await tracker.update_performance()
        # 성과 업데이트 후 자동으로 가중치 최적화
        weight_result = tracker.suggest_weights(auto_apply=True)
        result["가중치_최적화"] = weight_result
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/performance/stats", tags=["📈 성과 추적"])
async def get_performance_stats():
    """
    📊 전체 통계
    적중률, 평균 수익률, 유형별 성과, 뉴스 vs 기술 분석 비교
    """
    return {"status": "success", "data": tracker.get_stats()}


@app.get("/performance/history", tags=["📈 성과 추적"])
async def get_performance_history(stock_code: Optional[str] = None, limit: int = 30):
    """
    📋 성과 포함 이력
    추천 + 실제 수익률이 함께 표시됩니다.
    """
    history = tracker.get_history_with_performance(stock_code=stock_code, limit=limit)
    return {"status": "success", "count": len(history), "data": history}


@app.get("/performance/weights", tags=["📈 성과 추적"])
async def suggest_weights(auto_apply: bool = False):
    """
    ⚖️ 가중치 추천/적용
    과거 성과를 분석하여 뉴스/기술 분석 최적 가중치를 추천합니다.
    auto_apply=true 이면 즉시 적용됩니다.
    """
    return {"status": "success", "data": tracker.suggest_weights(auto_apply=auto_apply)}


# ============================================================
# 📱 텔레그램 알림
# ============================================================
@app.get("/telegram/test", tags=["📱 텔레그램"])
async def test_telegram():
    """텔레그램 봇 연결을 테스트합니다."""
    result = await telegram.test()
    return {"status": "success", "data": result}


@app.post("/telegram/send", tags=["📱 텔레그램"])
async def send_telegram(message: str = "테스트 메시지입니다."):
    """텔레그램으로 직접 메시지를 보냅니다."""
    success = await telegram.send(message)
    return {"status": "success" if success else "failed"}


@app.post("/briefing/morning", tags=["📱 텔레그램"])
async def morning_briefing_send():
    """
    🌅 아침 시장 브리핑 (텔레그램 전송)
    외국인/기관 수급 TOP + 매집 종목을 텔레그램으로 보냅니다.
    매일 아침 장 시작 전에 실행하세요.
    """
    result = await morning.send_briefing()
    return result


@app.get("/briefing/preview", tags=["📱 텔레그램"])
async def morning_briefing_preview():
    """
    🌅 브리핑 미리보기 (전송 없이 내용만 확인)
    """
    briefing = await morning.generate_briefing()
    msg = morning._format_message(briefing)
    return {"status": "success", "message": msg, "data": briefing}


# ============================================================
# 📊 보유 종목 모니터링
# ============================================================
class PositionAddRequest(BaseModel):
    stock_code: str = Field(..., description="종목코드")
    stock_name: str = Field(..., description="종목명")
    entry_price: int = Field(..., description="진입가")
    quantity: int = Field(..., description="수량")
    target_price: int = Field(0, description="목표가 (0이면 ATR 자동)")
    stop_price: int = Field(0, description="손절가 (0이면 ATR 자동)")


@app.post("/monitor/add", tags=["📊 보유 모니터링"])
async def add_monitor_position(request: PositionAddRequest):
    """
    📊 보유 종목 등록
    매수 후 목표가/손절가를 설정하고 자동 모니터링을 시작합니다.
    목표가/손절가를 0으로 두면 ATR 기반 자동 설정됩니다.
    """
    target = request.target_price
    stop = request.stop_price

    # ATR 자동 설정
    if target == 0 or stop == 0:
        try:
            daily = await kis.get_daily_prices(request.stock_code, "D")
            if daily and len(daily) >= 14:
                highs = [d.get("high", d.get("고가", 0)) for d in daily[:14]]
                lows = [d.get("low", d.get("저가", 0)) for d in daily[:14]]
                closes = [d.get("close", d.get("종가", 0)) for d in daily[:14]]
                trs = []
                for i in range(1, len(highs)):
                    tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                    trs.append(tr)
                atr = sum(trs) / len(trs) if trs else 0
                if stop == 0:
                    stop = int(request.entry_price - atr * 2)
                if target == 0:
                    target = int(request.entry_price + atr * 3)
        except Exception:
            pass

    result = pos_monitor.add_position(
        request.stock_code, request.stock_name,
        request.entry_price, request.quantity, target, stop
    )

    if telegram.is_configured:
        await telegram.send(
            f"📊 <b>포지션 등록</b>\n\n"
            f"종목: {request.stock_name} ({request.stock_code})\n"
            f"진입가: {request.entry_price:,}원 × {request.quantity}주\n"
            f"목표가: {target:,}원 ({round((target-request.entry_price)/request.entry_price*100,1):+.1f}%)\n"
            f"손절가: {stop:,}원 ({round((stop-request.entry_price)/request.entry_price*100,1):+.1f}%)"
        )

    return {"status": "success", "data": result}


@app.delete("/monitor/{stock_code}", tags=["📊 보유 모니터링"])
async def remove_monitor_position(stock_code: str):
    """보유 종목 해제"""
    return {"status": "success", "data": pos_monitor.remove_position(stock_code)}


@app.get("/monitor/positions", tags=["📊 보유 모니터링"])
async def get_monitor_positions():
    """현재 보유 종목 목록"""
    return {"status": "success", "data": pos_monitor.get_positions()}


@app.post("/monitor/check", tags=["📊 보유 모니터링"])
async def check_positions():
    """
    🔍 보유 종목 모니터링 실행
    모든 보유 종목의 현재가를 체크하고 목표가/손절가 도달 시 알림을 보냅니다.
    장중에 1~2시간마다 실행하세요.
    """
    result = await pos_monitor.monitor_all()
    return result


@app.put("/monitor/{stock_code}/target", tags=["📊 보유 모니터링"])
async def update_monitor_target(stock_code: str, target_price: int = 0, stop_price: int = 0):
    """목표가/손절가 수동 변경"""
    return {"status": "success", "data": pos_monitor.update_target(stock_code, target_price, stop_price)}


class ScanRequest(BaseModel):
    stock_codes: list[str] = Field(default=[], description="스캔할 종목코드 목록 (비우면 관심종목 또는 인기종목)")

class WatchlistAddRequest(BaseModel):
    stock_code: str = Field(..., description="종목코드 6자리")
    stock_name: str = Field(..., description="종목명")


# ============================================================
# 🔍 자동 스캔
# ============================================================
@app.post("/scan/quick", tags=["🔍 자동 스캔"])
async def quick_scan(request: ScanRequest):
    """
    ⚡ 빠른 스캔 (크레딧 무료!)
    현재가 + 기술적 지표만으로 빠르게 스캔합니다.
    뉴스 분석 없이 기술적 신호만 확인하므로 크레딧이 안 듭니다.
    """
    try:
        stocks = None
        if request.stock_codes:
            stocks = [{"code": c, "name": ""} for c in request.stock_codes]
        result = await scanner.quick_scan(stocks)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scan/full", tags=["🔍 자동 스캔"])
async def full_scan(request: ScanRequest):
    """
    🔍 풀 스캔 (뉴스 + 기술 + 텔레그램 알림)
    빠른 스캔으로 후보를 먼저 걸러낸 뒤, 유망 종목만 뉴스 분석합니다.
    30점+ 매수고려 / 50점+ 적극매수 / 70점+ 강력매수 알림!
    """
    try:
        stocks = None
        if request.stock_codes:
            stocks = [{"code": c, "name": ""} for c in request.stock_codes]
        result = await scanner.full_scan(stocks)

        # 30점 이상 종목 텔레그램 알림
        alerts_sent = 0
        for item in result.get("results", []):
            score = item.get("total_score", 0)
            if score >= 30 or score <= -30:
                try:
                    await pos_monitor.send_scan_alert(
                        stock_code=item.get("stock_code", ""),
                        stock_name=item.get("stock_name", ""),
                        score=score,
                        price=item.get("price", {}).get("current", 0),
                        recommendation=item.get("recommendation", ""),
                        indicators=item.get("indicators", {}),
                    )
                    alerts_sent += 1
                except Exception:
                    pass
        result["alerts_sent"] = alerts_sent

        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scan/popular", tags=["🔍 자동 스캔"])
async def get_popular_stocks():
    """인기 종목 목록을 조회합니다."""
    return {"status": "success", "data": StockScanner.get_default_stocks()}


@app.post("/scan/auto", tags=["🔍 자동 스캔"])
async def auto_scan():
    """
    🤖 전체 자동 스캔 (보유종목 + 신규 종목)
    1. 보유 종목 모니터링 (목표가/손절가 체크)
    2. 인기 종목 빠른 스캔
    3. 30점 이상 종목 텔레그램 알림
    장중에 1~2시간마다 실행하세요.
    """
    results = {}

    # 1) 보유 종목 모니터링
    try:
        monitor_result = await pos_monitor.monitor_all()
        results["보유종목_모니터링"] = monitor_result
    except Exception as e:
        results["보유종목_모니터링"] = {"error": str(e)}

    # 2) 빠른 스캔
    try:
        scan_result = await scanner.quick_scan(None)
        results["신규종목_스캔"] = {
            "스캔_수": len(scan_result.get("results", [])),
            "매수_신호": len([r for r in scan_result.get("results", []) if r.get("total_score", 0) >= 30]),
            "매도_신호": len([r for r in scan_result.get("results", []) if r.get("total_score", 0) <= -30]),
        }

        # 30점 이상 알림
        for item in scan_result.get("results", []):
            score = item.get("total_score", 0)
            if score >= 30 or score <= -30:
                try:
                    await pos_monitor.send_scan_alert(
                        stock_code=item.get("stock_code", ""),
                        stock_name=item.get("stock_name", ""),
                        score=score,
                        price=item.get("price", {}).get("current", 0),
                        recommendation=item.get("recommendation", ""),
                        indicators=item.get("indicators", {}),
                    )
                except Exception:
                    pass
    except Exception as e:
        results["신규종목_스캔"] = {"error": str(e)}

    return {"status": "success", "data": results}


# ============================================================
# ⭐ 관심 종목 관리
# ============================================================
@app.get("/watchlist", tags=["⭐ 관심 종목"])
async def get_watchlist():
    """내 관심 종목 목록을 조회합니다."""
    watchlist = scanner.get_watchlist()
    return {"status": "success", "count": len(watchlist), "data": watchlist}


@app.post("/watchlist", tags=["⭐ 관심 종목"])
async def add_watchlist(request: WatchlistAddRequest):
    """관심 종목을 추가합니다."""
    watchlist = scanner.add_to_watchlist(request.stock_code, request.stock_name)
    return {"status": "success", "count": len(watchlist), "data": watchlist}


@app.delete("/watchlist/{stock_code}", tags=["⭐ 관심 종목"])
async def remove_watchlist(stock_code: str):
    """관심 종목을 제거합니다."""
    watchlist = scanner.remove_from_watchlist(stock_code)
    return {"status": "success", "count": len(watchlist), "data": watchlist}


# ============================================================
# 📰 뉴스 분석
# ============================================================
@app.post("/news/collect", tags=["📰 뉴스 분석"])
async def collect_news(request: NewsRequest):
    """종목 관련 뉴스를 수집합니다."""
    try:
        articles = await news_collector.collect(
            stock_code=request.stock_code,
            stock_name=request.stock_name,
            max_articles=request.max_articles,
        )
        return {"status": "success", "count": len(articles), "articles": articles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/news/sentiment", tags=["📰 뉴스 분석"])
async def analyze_news_sentiment(request: NewsRequest):
    """뉴스를 수집하고 감성 분석을 수행합니다."""
    try:
        articles = await news_collector.collect(
            stock_code=request.stock_code,
            stock_name=request.stock_name,
            max_articles=request.max_articles,
        )
        sentiment = await sentiment_analyzer.analyze(
            articles=articles,
            stock_name=request.stock_name or request.stock_code,
            stock_code=request.stock_code,
        )
        return {"status": "success", "data": sentiment}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 🧠 자동 학습 (핵심 기능!)
# ============================================================
@app.post("/learn/stock", tags=["🧠 자동 학습"])
async def learn_stock(request: StockCodeRequest):
    """한투 API에서 종목 데이터 → 기술적 지표 계산 → 지식 베이스 등록"""
    try:
        result = await learner.learn_stock_snapshot(request.stock_code)
        return {"status": "success", "message": f"{result['stock']} 학습 완료", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/learn/trend", tags=["🧠 자동 학습"])
async def learn_trend(request: StockCodeRequest):
    """거래량/투자자 동향을 학습합니다."""
    try:
        result = await learner.learn_investor_trend(request.stock_code)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/learn/portfolio", tags=["🧠 자동 학습"])
async def learn_portfolio():
    """내 계좌 보유 종목을 학습합니다."""
    try:
        result = await learner.learn_portfolio()
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/learn/watchlist", tags=["🧠 자동 학습"])
async def learn_watchlist(request: WatchlistRequest):
    """관심 종목을 일괄 학습합니다. 매일 실행하면 데이터가 축적됩니다."""
    try:
        results = await learner.learn_watchlist(request.stock_codes)
        ok = sum(1 for r in results if r.get("status") == "learned")
        return {"status": "success", "message": f"{ok}/{len(request.stock_codes)}개 학습 완료", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 📊 AI 분석
# ============================================================
@app.post("/analyze", tags=["📊 AI 분석"])
async def analyze_stock(request: AnalysisRequest):
    """학습된 지식 기반으로 종목을 분석합니다."""
    try:
        price_data = await kis.get_current_price(request.stock_code)
        stock_name = price_data.get("종목명", request.stock_code)

        query = f"{stock_name} {request.stock_code} {request.question or ''}"
        relevant = knowledge.search(query=query, category=_map(request.analysis_type))

        result = await analyzer.analyze(
            ticker=f"{stock_name}({request.stock_code})",
            price_data=price_data,
            analysis_type=request.analysis_type,
            question=request.question,
            relevant_knowledge=relevant,
        )
        return {
            "status": "success", "stock": stock_name,
            "timestamp": datetime.now().isoformat(),
            "analysis": result, "knowledge_used": len(relevant),
            "realtime_price": price_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat", tags=["📊 AI 분석"])
async def chat_with_ai(request: ChatRequest):
    """지식 베이스를 참고하여 자유 대화합니다."""
    try:
        relevant = knowledge.search(query=request.message)
        result = await analyzer.chat(message=request.message, context=request.context, relevant_knowledge=relevant)
        return {"status": "success", "response": result, "knowledge_used": len(relevant)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 📉 한투 데이터 직접 조회
# ============================================================
@app.get("/stock/name/{stock_code}", tags=["📉 한투 데이터"])
async def get_stock_name(stock_code: str):
    """종목코드로 종목명 조회 (로컬 딕셔너리 → KIS API 순서로 시도)"""
    from app.accumulation_scanner import SCAN_STOCKS
    name = SCAN_STOCKS.get(stock_code)
    if name:
        return {"status": "success", "name": name}
    try:
        data = await kis.get_current_price(stock_code)
        name = data.get("종목명", "")
        if name:
            return {"status": "success", "name": name}
    except Exception:
        pass
    return {"status": "success", "name": ""}


@app.get("/kis/price/{stock_code}", tags=["📉 한투 데이터"])
async def get_kis_price(stock_code: str):
    """실시간 현재가 조회"""
    try:
        return {"status": "success", "data": await kis.get_current_price(stock_code)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/kis/daily", tags=["📉 한투 데이터"])
async def get_kis_daily(request: DailyPriceRequest):
    """일봉/주봉/월봉 데이터 조회"""
    try:
        data = await kis.get_daily_prices(request.stock_code, request.period)
        return {"status": "success", "count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/kis/chart/{stock_code}", tags=["📉 한투 데이터"])
async def get_chart_data(stock_code: str, days: int = 60):
    """📈 차트용 일봉 데이터 (캔들차트)"""
    try:
        data = await kis.get_daily_prices(stock_code, "D")
        return {"status": "success", "count": len(data[:days]), "data": data[:days]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/kis/minute/{stock_code}", tags=["📉 한투 데이터"])
async def get_kis_minute(stock_code: str):
    """당일 분봉 데이터 조회"""
    try:
        return {"status": "success", "data": await kis.get_minute_prices(stock_code)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/kis/balance", tags=["📉 한투 데이터"])
async def get_kis_balance():
    """계좌 잔고 조회"""
    try:
        return {"status": "success", "data": await kis.get_balance()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/kis/investor/{stock_code}", tags=["📉 한투 데이터"])
async def get_investor_trend(stock_code: str):
    """투자자별 매매동향 (당일 외국인/기관/개인)"""
    try:
        return {"status": "success", "data": await kis.get_investor_trend(stock_code)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/kis/foreign/{stock_code}", tags=["📉 한투 데이터"])
async def get_foreign_daily(stock_code: str, days: int = 14):
    """외국인/기관 일별 매매동향 (KRX 직접 조회)"""
    try:
        data = krx.get_investor_daily(stock_code, days)
        if data:
            foreign_total = sum(d.get("외국인_순매수", 0) for d in data)
            organ_total = sum(d.get("기관_순매수", 0) for d in data)
            summary = {
                "기간": f"최근 {len(data)}일",
                "외국인_누적순매수": foreign_total,
                "외국인_추세": "순매수" if foreign_total > 0 else "순매도",
                "기관_누적순매수": organ_total,
                "기관_추세": "순매수" if organ_total > 0 else "순매도",
            }
        else:
            summary = {"message": "데이터 없음"}
        return {"status": "success", "summary": summary, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/kis/short/{stock_code}", tags=["📉 한투 데이터"])
async def get_short_selling(stock_code: str, days: int = 14):
    """공매도 일별 추이 (KRX 직접 조회)"""
    try:
        data = krx.get_short_selling(stock_code, days)
        if data:
            avg_ratio = sum(d.get("공매도_비중", 0) for d in data) / len(data)
            latest = data[0] if data else {}
            summary = {
                "기간": f"최근 {len(data)}일",
                "평균_공매도_비중": f"{avg_ratio:.2f}%",
                "최근_공매도_비중": f"{latest.get('공매도_비중', 0)}%",
                "최근_공매도량": latest.get("공매도량", 0),
                "판단": "공매도 과열 주의" if avg_ratio > 10 else "공매도 보통 수준" if avg_ratio > 3 else "공매도 적음",
            }
        else:
            summary = {"message": "데이터 없음"}
        return {"status": "success", "summary": summary, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/kis/supply/{stock_code}", tags=["📉 한투 데이터"])
async def get_supply_analysis(stock_code: str):
    """
    📊 종합 수급 분석
    당일: 한투 API (실시간) / 과거 2주: KRX 거래소 (확정 데이터)
    """
    try:
        # 1) 당일 실시간 투자자별 동향 (한투 API)
        today_investor = {}
        try:
            today_investor = await kis.get_investor_trend(stock_code)
        except Exception:
            pass

        # 2) 과거 2주 수급 + 공매도 (KRX 거래소)
        krx_result = krx.get_supply_analysis(stock_code)

        return {
            "status": "success",
            "stock_code": stock_code,
            "당일_실시간": today_investor,
            "analysis": krx_result["analysis"],
            "외국인_일별": krx_result["외국인_일별"],
            "공매도_일별": krx_result["공매도_일별"],
            "errors": None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 🔬 백테스팅
# ============================================================
class BacktestRequest(BaseModel):
    stock_code: str = Field(..., description="종목코드 6자리")
    strategy: str = Field(default="combined", description="전략: ma_cross, rsi, macd, bollinger, combined")
    initial_capital: int = Field(default=1000000, description="초기 자본금 (원)")
    days: int = Field(default=90, description="테스트 기간 (거래일)")

@app.get("/backtest/strategies", tags=["🔬 백테스팅"])
async def list_strategies():
    """사용 가능한 전략 목록을 조회합니다."""
    return {"status": "success", "data": BacktestEngine.get_strategy_list()}

@app.post("/backtest/run", tags=["🔬 백테스팅"])
async def run_backtest(request: BacktestRequest):
    """
    🔬 백테스트 실행
    과거 데이터로 전략을 시뮬레이션하고 수익률/승률을 계산합니다.
    수수료+세금 포함, 바이앤홀드 대비 성과도 비교합니다.
    """
    try:
        result = await backtester.run(
            stock_code=request.stock_code,
            strategy=request.strategy,
            initial_capital=request.initial_capital,
            days=request.days,
        )
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backtest/compare", tags=["🔬 백테스팅"])
async def compare_strategies(request: BacktestRequest):
    """
    📊 전략 비교
    5가지 전략을 한 종목에 대해 동시에 실행하고 결과를 비교합니다.
    """
    try:
        result = await backtester.compare_strategies(
            stock_code=request.stock_code,
            initial_capital=request.initial_capital,
            days=request.days,
        )
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 🤖 자동 매매
# ============================================================
class TradeConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None              # "confirm" or "auto"
    daily_limit: Optional[int] = None       # 1일 최대 (원)
    per_stock_limit: Optional[int] = None   # 1종목 최대 (원)
    min_score: Optional[int] = None         # 매수 최소 점수
    sell_score: Optional[int] = None        # 매도 기준 점수
    stop_loss: Optional[float] = None       # 손절 %
    take_profit: Optional[float] = None     # 익절 %

class ManualOrderRequest(BaseModel):
    stock_code: str = Field(...)
    quantity: int = Field(...)
    price: int = Field(default=0, description="0이면 시장가")
    order_type: str = Field(default="buy", description="buy 또는 sell")


@app.get("/trade/config", tags=["🤖 자동 매매"])
async def get_trade_config():
    """자동 매매 설정을 조회합니다."""
    return {"status": "success", "data": trader.get_config()}


@app.post("/trade/config", tags=["🤖 자동 매매"])
async def update_trade_config(config: TradeConfigUpdate):
    """
    자동 매매 설정을 변경합니다.
    enabled: true/false, mode: confirm/auto, daily_limit 등
    """
    updates = {k: v for k, v in config.model_dump().items() if v is not None}
    result = trader.update_config(updates)
    return {"status": "success", "data": result}


@app.post("/trade/enable", tags=["🤖 자동 매매"])
async def enable_auto_trade():
    """자동 매매를 켭니다. (확인 모드로 시작)"""
    trader.update_config({"enabled": True, "mode": "confirm", "emergency_stop": False})
    if telegram.is_configured:
        await telegram.send("🤖 자동 매매가 켜졌습니다! (확인 모드)\n매수/매도 신호 시 텔레그램으로 확인 요청이 옵니다.")
    return {"status": "success", "message": "자동 매매 활성화 (확인 모드)"}


@app.post("/trade/disable", tags=["🤖 자동 매매"])
async def disable_auto_trade():
    """자동 매매를 끕니다."""
    trader.update_config({"enabled": False})
    return {"status": "success", "message": "자동 매매 비활성화"}


@app.post("/trade/emergency-stop", tags=["🤖 자동 매매"])
async def emergency_stop():
    """🚨 긴급 중지 — 모든 대기 주문 취소, 자동 매매 끔"""
    result = trader.emergency_stop()
    if telegram.is_configured:
        await telegram.send("🚨 <b>긴급 중지!</b>\n모든 대기 주문이 취소되고 자동 매매가 꺼졌습니다.")
    return {"status": "success", "data": result}


@app.post("/trade/resume", tags=["🤖 자동 매매"])
async def resume_trading():
    """긴급 중지 해제, 자동 매매 재개"""
    result = trader.resume()
    return {"status": "success", "data": result}


@app.get("/trade/pending", tags=["🤖 자동 매매"])
async def get_pending_orders():
    """승인 대기 중인 주문 목록"""
    return {"status": "success", "data": trader.get_pending_orders()}


@app.post("/trade/approve/{order_id}", tags=["🤖 자동 매매"])
async def approve_order(order_id: str):
    """대기 중인 주문을 승인하여 실행합니다. ⚠️ 실제 주문이 나갑니다!"""
    result = await trader.approve_order(order_id)
    return {"status": "success", "data": result}


@app.post("/trade/reject/{order_id}", tags=["🤖 자동 매매"])
async def reject_order(order_id: str):
    """대기 중인 주문을 거부합니다."""
    result = trader.reject_order(order_id)
    return {"status": "success", "data": result}


@app.get("/trade/risk", tags=["🤖 자동 매매"])
async def get_risk_status():
    """📊 리스크 상태 — 포지션, Trailing Stop, 일일 손익, Circuit Breaker"""
    return {"status": "success", "data": trader.get_risk_status()}


@app.get("/trade/positions", tags=["🤖 자동 매매"])
async def get_positions():
    """보유 포지션 목록 (Trailing Stop 추적용)"""
    return {"status": "success", "data": trader.get_positions()}


@app.post("/trade/position/{stock_code}", tags=["🤖 자동 매매"])
async def register_position(stock_code: str, price: int, quantity: int):
    """수동으로 포지션 등록 (이미 보유 중인 종목을 Trailing Stop 추적에 추가)"""
    result = trader.register_position(stock_code, price, quantity)
    return {"status": "success", "data": result}


@app.delete("/trade/position/{stock_code}", tags=["🤖 자동 매매"])
async def remove_position(stock_code: str, exit_price: int = 0):
    """포지션 해제 (매도 후 추적 제거)"""
    result = trader.remove_position(stock_code, exit_price)
    return {"status": "success", "data": result}


@app.post("/trade/manual", tags=["🤖 자동 매매"])
async def manual_order(request: ManualOrderRequest):
    """
    수동 주문 — 직접 매수/매도 주문을 넣습니다.
    ⚠️ 실제 주문이 나갑니다!
    """
    try:
        if request.order_type == "buy":
            result = await kis.buy_order(request.stock_code, request.quantity, request.price)
        elif request.order_type == "sell":
            result = await kis.sell_order(request.stock_code, request.quantity, request.price)
        else:
            raise Exception("order_type은 buy 또는 sell")
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trade/log", tags=["🤖 자동 매매"])
async def get_order_log(limit: int = 30):
    """주문 실행 이력을 조회합니다."""
    return {"status": "success", "data": trader.get_order_log(limit)}


# ============================================================
# 📈 선물 / 원자재 조회
# ============================================================

# 자주 쓰는 선물 코드 매핑
# 선물 만기월 자동 계산
def _get_futures_code(base: str, exchange: str, quarterly_only: bool = False) -> str:
    """현재 날짜 기준 활성 선물 코드 자동 생성"""
    from datetime import datetime
    now = datetime.now()
    year = now.year
    month = now.month

    # 월 코드: F=1,G=2,H=3,J=4,K=5,M=6,N=7,Q=8,U=9,V=10,X=11,Z=12
    month_codes = {1:'F',2:'G',3:'H',4:'J',5:'K',6:'M',7:'N',8:'Q',9:'U',10:'V',11:'X',12:'Z'}

    if now.day > 15:
        month += 1
        if month > 12:
            month = 1
            year += 1

    # 분기물만 있는 상품 (나스닥, S&P, 러셀 등) → H,M,U,Z
    if quarterly_only:
        quarterly = [3, 6, 9, 12]
        for q in quarterly:
            if month <= q:
                month = q
                break
        else:
            month = 3
            year += 1

    code = month_codes[month]
    yr = str(year)[-2:]
    return f"{base}{code}{yr}"


def _build_futures_map():
    """현재 날짜 기준 선물 코드 자동 생성"""
    return {
        "kospi200": {"code": "A01606", "name": "코스피200 선물", "type": "domestic"},
        "kospi200_next": {"code": "A01609", "name": "코스피200 선물(차월)", "type": "domestic"},
        "mini_kospi": {"code": "A05606", "name": "미니코스피200", "type": "domestic"},
        "kosdaq150": {"code": "A06606", "name": "코스닥150 선물", "type": "domestic"},
        "gold": {"code": _get_futures_code("1OZ", "CMX"), "exchange": "CMX", "name": "금(Gold)", "type": "overseas"},
        "silver": {"code": _get_futures_code("1SI", "CMX"), "exchange": "CMX", "name": "은(Silver)", "type": "overseas"},
        "oil": {"code": _get_futures_code("CL", "NYM"), "exchange": "NYM", "name": "WTI 원유", "type": "overseas"},
        "gas": {"code": _get_futures_code("NG", "NYM"), "exchange": "NYM", "name": "천연가스", "type": "overseas"},
        "copper": {"code": _get_futures_code("HG", "CMX"), "exchange": "CMX", "name": "구리", "type": "overseas"},
        "nasdaq": {"code": _get_futures_code("NQ", "CME", quarterly_only=True), "exchange": "CME", "name": "나스닥100", "type": "overseas"},
        "sp500": {"code": _get_futures_code("ES", "CME", quarterly_only=True), "exchange": "CME", "name": "S&P500", "type": "overseas"},
    }

FUTURES_MAP = _build_futures_map()


@app.get("/futures/list", tags=["📈 선물/원자재"])
async def list_futures():
    """조회 가능한 선물/원자재 목록"""
    return {
        "status": "success",
        "국내선물": {k: v["name"] for k, v in FUTURES_MAP.items() if v["type"] == "domestic"},
        "해외원자재": {k: v["name"] for k, v in FUTURES_MAP.items() if v["type"] == "overseas" and k in ["gold", "silver", "oil", "gas", "copper"]},
        "해외지수선물": {k: v["name"] for k, v in FUTURES_MAP.items() if v["type"] == "overseas" and k in ["nasdaq", "sp500"]},
        "사용법": "/futures/{키워드} 예: /futures/kospi200, /futures/gold, /futures/oil",
    }


@app.get("/futures/{keyword}", tags=["📈 선물/원자재"])
async def get_futures(keyword: str):
    """
    선물/원자재 현재가 조회
    키워드: kospi200, gold, silver, oil, gas, copper, nasdaq, sp500
    """
    info = FUTURES_MAP.get(keyword.lower())
    if not info:
        raise HTTPException(status_code=404, detail=f"'{keyword}' 못 찾음. /futures/list 에서 확인하세요.")
    try:
        if info["type"] == "domestic":
            price = await kis.get_futures_price(info["code"])
        else:
            price = await kis.get_overseas_futures_price(info["code"], info["exchange"])
        price["keyword"] = keyword
        price["display_name"] = info["name"]
        return {"status": "success", "data": price}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/futures/{keyword}/daily", tags=["📈 선물/원자재"])
async def get_futures_daily(keyword: str, days: int = 20):
    """선물/원자재 일별 시세 (최근 N일)"""
    info = FUTURES_MAP.get(keyword.lower())
    if not info:
        raise HTTPException(status_code=404, detail=f"'{keyword}' 못 찾음.")
    try:
        if info["type"] == "domestic":
            data = await kis.get_futures_daily(info["code"], days)
        else:
            data = await kis.get_overseas_futures_daily(info["code"], info["exchange"], days)
        return {"status": "success", "name": info["name"], "count": len(data), "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/futures/dashboard/all", tags=["📈 선물/원자재"])
async def get_all_futures():
    """
    🌍 전체 선물/원자재 한눈에 보기
    코스피200 야간선물 + 금 + 원유 + 나스닥 등 주요 선물을 한번에 조회합니다.
    """
    results = {}
    for keyword, info in FUTURES_MAP.items():
        try:
            if info["type"] == "domestic":
                price = await kis.get_futures_price(info["code"])
            else:
                price = await kis.get_overseas_futures_price(info["code"], info["exchange"])
            results[keyword] = {
                "name": info["name"],
                "현재가": price.get("현재가", 0),
                "등락률": price.get("등락률", ""),
                "전일대비": price.get("전일대비", 0),
            }
        except Exception as e:
            results[keyword] = {"name": info["name"], "error": str(e)}

    return {
        "status": "success",
        "조회시간": datetime.now().isoformat(),
        "data": results,
    }


# ============================================================
# 📚 지식 베이스
# ============================================================
@app.post("/knowledge", tags=["📚 지식 베이스"])
async def add_knowledge(entry: KnowledgeEntry):
    return {"status": "success", "entry": knowledge.add(entry.model_dump())}

@app.post("/knowledge/bulk", tags=["📚 지식 베이스"])
async def add_knowledge_bulk(data: KnowledgeBulkEntry):
    results = [knowledge.add(e.model_dump()) for e in data.entries]
    return {"status": "success", "count": len(results)}

@app.get("/knowledge", tags=["📚 지식 베이스"])
async def list_knowledge(category: Optional[str] = None):
    entries = knowledge.list_all(category=category)
    return {"total": len(entries), "categories": knowledge.get_categories_summary(), "entries": entries}

@app.get("/knowledge/search", tags=["📚 지식 베이스"])
async def search_knowledge(q: str, category: Optional[str] = None):
    results = knowledge.search(query=q, category=category)
    return {"total": len(results), "results": results}

@app.delete("/knowledge/{entry_id}", tags=["📚 지식 베이스"])
async def delete_knowledge(entry_id: str):
    if not knowledge.delete(entry_id):
        raise HTTPException(status_code=404, detail="해당 지식을 찾을 수 없습니다.")
    return {"status": "success"}


# ============================================================
# 시스템
# ============================================================
@app.get("/", tags=["시스템"])
async def root():
    kis_ok = bool(kis.app_key and kis.app_secret)
    news_ok = bool(news_collector.client_id and news_collector.client_secret)
    ai_ok = bool(os.getenv("ANTHROPIC_API_KEY", ""))
    tg_ok = telegram.is_configured
    return {
        "name": "나만의 주식 매매 추천 AI API v3.2",
        "연결_상태": {
            "한투API": "연결됨" if kis_ok else "미설정",
            "네이버뉴스API": "연결됨" if news_ok else "미설정 (RSS로 동작)",
            "Claude_AI": "연결됨" if ai_ok else "미설정",
            "텔레그램": "연결됨" if tg_ok else "미설정 → TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID",
        },
        "knowledge_base": knowledge.get_categories_summary(),
        "핵심_사용법": {
            "매매 추천": "POST /recommend {stock_code: '005930'} ← 이것만 쓰면 됩니다!",
            "뉴스만 보기": "POST /news/collect {stock_code: '005930'}",
            "감성 분석만": "POST /news/sentiment {stock_code: '005930'}",
            "기술 분석 학습": "POST /learn/stock {stock_code: '005930'}",
            "추천 이력": "GET /recommend/history",
            "API 문서": "GET /docs",
        },
    }

import os

@app.get("/dashboard", response_class=HTMLResponse, tags=["시스템"])
async def dashboard():
    """보기 편한 웹 대시보드"""
    html_path = Path(__file__).parent / "dashboard.html"
    return html_path.read_text(encoding="utf-8")

def _map(t: str) -> Optional[str]:
    return {"technical": "indicator", "fundamental": "sector", "sentiment": "pattern"}.get(t)
