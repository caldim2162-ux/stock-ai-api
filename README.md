# 📈 나만의 주식 분석 AI API v2.0 — 한투 실시간 연동

한국투자증권 Open API의 **실시간 시세(WebSocket)**를 수신하면서, 내가 직접 구축한 **지식 베이스를 기반으로 AI가 자동 분석**하는 개인 API입니다.

## 🏗️ 구조

```
stock-ai-api/
├── app/
│   ├── main.py               # FastAPI 메인 서버 (모든 엔드포인트)
│   ├── kis_client.py          # 한투 REST API (인증, 현재가, 일봉, 호가)
│   ├── kis_realtime.py        # 한투 WebSocket 실시간 체결/호가 스트리밍
│   ├── realtime_analyzer.py   # 실시간 분석 엔진 (조건 트리거 → AI 분석)
│   ├── knowledge_manager.py   # 지식 베이스 CRUD + 검색
│   ├── ai_analyzer.py         # Claude AI 분석 엔진
│   └── stock_data.py          # yfinance 보조 데이터 (한투 미연결 시 대체)
├── knowledge_base/            # 저장된 지식 (자동 생성)
├── data/sample_knowledge.json
├── requirements.txt
├── .env.example
└── run.sh
```

## 🚀 시작하기

### 1단계: API 키 준비

두 가지 API 키가 필요합니다:

| API | 발급처 | 용도 |
|-----|--------|------|
| **Anthropic** | https://console.anthropic.com | AI 분석 |
| **한투 Open API** | https://apiportal.koreainvestment.com | 실시간 시세 |

한투 API 발급 과정:
1. 한국투자증권 계좌 개설 (모의투자 계좌도 가능)
2. KIS Developers 포탈 가입
3. 앱 등록 → AppKey, AppSecret 발급
4. HTS ID 등록 (실시간 WebSocket에 필요)

### 2단계: 설치 & 설정

```bash
cd stock-ai-api
pip install -r requirements.txt

# .env 파일 생성
cp .env.example .env

# .env 편집 — 본인의 키 입력
nano .env
```

`.env` 내용:
```env
ANTHROPIC_API_KEY=sk-ant-...
KIS_APP_KEY=PSxxxxxxxx...
KIS_APP_SECRET=RR0sxxxxxxxx...
KIS_ACCOUNT_NO=50012345-01
KIS_HTS_ID=myid
KIS_IS_VIRTUAL=true
```

### 3단계: 서버 실행

```bash
bash run.sh
# 또는
uvicorn app.main:app --reload --port 8000
```

→ http://localhost:8000/docs 에서 Swagger UI로 테스트

---

## 📖 사용법 (순서대로)

### Step 1: 지식 학습시키기

```bash
# 내 투자 전략 입력
curl -X POST http://localhost:8000/knowledge \
  -H "Content-Type: application/json" \
  -d '{
    "category": "strategy",
    "title": "단타 모멘텀 전략",
    "content": "체결강도 120 이상 + 거래량 전일대비 3배 급증 시 진입. RSI 70 이상이면 1차 익절(50%), 나머지 트레일링 스탑(-3%). 손절은 -5% 무조건.",
    "tags": ["단타", "모멘텀", "체결강도", "RSI"]
  }'

# 샘플 데이터 한번에 넣기
curl -X POST http://localhost:8000/knowledge/bulk \
  -H "Content-Type: application/json" \
  -d @data/sample_knowledge.json
```

### Step 2: 한투 API로 시세 확인

```bash
# 삼성전자 현재가
curl http://localhost:8000/kis/price/005930

# SK하이닉스 일봉 (최근 20일)
curl "http://localhost:8000/kis/daily/000660?count=20"

# 삼성전자 호가
curl http://localhost:8000/kis/orderbook/005930
```

### Step 3: 실시간 모니터링 시작

```bash
# 삼성전자 + SK하이닉스 실시간 체결가 수신 시작
curl -X POST http://localhost:8000/realtime/start \
  -H "Content-Type: application/json" \
  -d '{"stock_codes": ["005930", "000660"]}'

# 추가 종목 구독
curl -X POST http://localhost:8000/realtime/subscribe \
  -H "Content-Type: application/json" \
  -d '{"stock_codes": ["035420"]}'
```

### Step 4: 실시간 분석 결과 받기 (SSE)

```bash
# 터미널에서 SSE 스트림 구독
curl -N http://localhost:8000/realtime/events
```

또는 JavaScript:
```javascript
const es = new EventSource('http://localhost:8000/realtime/events');
es.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`🔔 ${data.stock_code}: ${data.triggers.join(', ')}`);
  console.log(`📊 분석: ${data.analysis}`);
};
```

### Step 5: 분석 조건 커스터마이징

```bash
# 현재 조건 확인
curl http://localhost:8000/realtime/condition

# 공격적으로 변경 (더 자주 알림)
curl -X POST http://localhost:8000/realtime/condition \
  -H "Content-Type: application/json" \
  -d '{"preset": "aggressive"}'

# 세부 조건 직접 설정
curl -X POST http://localhost:8000/realtime/condition \
  -H "Content-Type: application/json" \
  -d '{
    "price_change_pct": 2.0,
    "trade_strength_high": 115,
    "volume_spike_ratio": 2.5,
    "cooldown_seconds": 120
  }'
```

### Step 6: 수동 AI 분석

```bash
# 한투 데이터 기반 종합 분석
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "stock_code": "005930",
    "question": "현재 체결강도와 호가잔량을 보고 단기 방향성을 판단해줘"
  }'
```

---

## ⚡ 실시간 분석 트리거 조건

AI 분석이 자동으로 실행되는 조건:

| 조건 | 설명 | 기본값(normal) |
|------|------|---------------|
| 등락률 | 현재가 등락률 임계값 | ±3% |
| 체결강도 | 매수/매도 체결 비율 | >120 또는 <80 |
| 거래량 급증 | 직전 평균 대비 배수 | 3배 이상 |
| 매수/매도 불균형 | 잔량 비율 | 2배 이상 |
| 쿨다운 | 동일 종목 재분석 간격 | 300초 |

프리셋: `aggressive`(민감) / `normal`(보통) / `conservative`(보수적)

---

## 🔧 확장 가이드

### 벡터 검색으로 지식 검색 강화
현재는 키워드 매칭입니다. 더 정확하게 하려면:
```bash
pip install chromadb sentence-transformers
```
`knowledge_manager.py`의 `search()` 메서드를 임베딩 기반으로 교체

### 자동매매 연동
한투 API는 주문 기능도 제공합니다. AI 분석 결과를 기반으로 자동 주문을 넣으려면 `kis_client.py`에 주문 API를 추가하세요. (주의: 실전투자 시 반드시 충분한 테스트 필요)

### 대시보드 UI
SSE 이벤트를 받아서 웹 대시보드를 만들 수 있습니다. React + Chart.js 조합 추천.

---

## 📌 종목코드 참고

| 종목 | 코드 |
|------|------|
| 삼성전자 | 005930 |
| SK하이닉스 | 000660 |
| NAVER | 035420 |
| 카카오 | 035720 |
| LG에너지솔루션 | 373220 |
| 삼성바이오로직스 | 207940 |
| 현대차 | 005380 |
| 기아 | 000270 |

---

## ⚠️ 주의사항

- **투자 참고용**이며, 모든 투자 판단의 책임은 본인에게 있습니다
- 모의투자로 충분히 테스트한 후 실전 적용하세요
- 한투 API는 초당 호출 제한이 있으니 주의하세요 (REST: 초당 20건)
- WebSocket은 HTS ID당 최대 40종목까지 실시간 구독 가능합니다
