"""
📚 지식 베이스 관리자
- 사용자가 입력한 투자 지식/전략/규칙을 저장하고 검색합니다.
- JSON 파일 기반의 간단한 저장소 (필요시 DB로 업그레이드 가능)
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional


KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge_base")
KNOWLEDGE_FILE = os.path.join(KNOWLEDGE_DIR, "knowledge.json")

# 지원하는 카테고리
CATEGORIES = {
    "strategy": "투자 전략",
    "indicator": "기술적 지표/분석법",
    "sector": "섹터/산업 분석",
    "pattern": "차트 패턴/시장 패턴",
    "rule": "매매 규칙/원칙",
}


class KnowledgeManager:
    def __init__(self):
        os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
        self.entries: list[dict] = self._load()

    # ----------------------------------------------------------
    # CRUD
    # ----------------------------------------------------------
    def add(self, entry: dict) -> dict:
        """지식 항목을 추가합니다."""
        record = {
            "id": str(uuid.uuid4())[:8],
            "category": entry.get("category", "strategy"),
            "title": entry["title"],
            "content": entry["content"],
            "tags": entry.get("tags", []),
            "created_at": datetime.now().isoformat(),
        }
        self.entries.append(record)
        self._save()
        return record

    def delete(self, entry_id: str) -> bool:
        """지식 항목을 삭제합니다."""
        before = len(self.entries)
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        if len(self.entries) < before:
            self._save()
            return True
        return False

    def list_all(self, category: Optional[str] = None) -> list[dict]:
        """전체 지식을 조회합니다."""
        if category:
            return [e for e in self.entries if e["category"] == category]
        return self.entries

    # ----------------------------------------------------------
    # 검색 (키워드 기반, 추후 벡터 검색으로 업그레이드 가능)
    # ----------------------------------------------------------
    def search(self, query: str, category: Optional[str] = None, top_k: int = 5) -> list[dict]:
        """
        지식 베이스를 검색합니다.
        현재: 키워드 매칭 기반
        향후: 임베딩 벡터 유사도 검색으로 업그레이드 가능
        """
        query_lower = query.lower()
        query_tokens = set(query_lower.split())

        scored = []
        for entry in self.entries:
            if category and entry["category"] != category:
                continue

            score = 0
            text = f"{entry['title']} {entry['content']} {' '.join(entry.get('tags', []))}".lower()

            # 전체 쿼리 매칭 (높은 점수)
            if query_lower in text:
                score += 10

            # 개별 토큰 매칭
            for token in query_tokens:
                if len(token) >= 2 and token in text:
                    score += 2

            # 태그 매칭 (보너스)
            for tag in entry.get("tags", []):
                if tag.lower() in query_lower:
                    score += 5

            if score > 0:
                scored.append((score, entry))

        # 점수 높은 순 정렬
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    # ----------------------------------------------------------
    # 통계
    # ----------------------------------------------------------
    def get_categories_summary(self) -> dict:
        summary = {"total": len(self.entries), "categories": {}}
        for cat_key, cat_name in CATEGORIES.items():
            count = sum(1 for e in self.entries if e["category"] == cat_key)
            if count > 0:
                summary["categories"][cat_key] = {
                    "name": cat_name,
                    "count": count,
                }
        return summary

    # ----------------------------------------------------------
    # 파일 I/O
    # ----------------------------------------------------------
    def _load(self) -> list[dict]:
        if os.path.exists(KNOWLEDGE_FILE):
            with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self):
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)
