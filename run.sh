#!/bin/bash
echo "========================================="
echo "  📈 주식 분석 AI API v2.0"
echo "========================================="
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
    echo "✅ .env 로드 완료"
fi
[ -z "$ANTHROPIC_API_KEY" ] && echo "⚠️  ANTHROPIC_API_KEY 미설정 (데모 모드)"
[ -z "$KIS_APP_KEY" ] && echo "⚠️  KIS_APP_KEY 미설정 (한투 API 비활성)"
pip install -r requirements.txt -q 2>/dev/null
echo ""
echo "🚀 서버: http://localhost:8000"
echo "📖 API 문서: http://localhost:8000/docs"
echo "========================================="
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
