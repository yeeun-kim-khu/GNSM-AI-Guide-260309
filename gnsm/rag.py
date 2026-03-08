"""gnsm.rag

이 파일은 '세션 내 대화 내용'을 간단한 벡터 스토어로 저장/검색하는 기능을 제공합니다.

목적:
- 사용자가 직전에 한 말과 유사한 과거 대화를 찾아 system 메시지로 주입하여
  에이전트가 문맥을 잃지 않도록 돕습니다.

특징/주의:
- Streamlit 세션(st.session_state) 안에만 저장되는 '가벼운 RAG'입니다.
- 임베딩은 OpenAI Embeddings를 사용하며, OPENAI_API_KEY가 없으면 자동으로 비활성화됩니다.
- 너무 긴 텍스트는 비용/노이즈를 줄이기 위해 잘라서 저장합니다.
"""

from __future__ import annotations

import math
import os
from typing import Any, Optional

import streamlit as st

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

from gnsm.state import RAG_STORE_KEY


# ---------------------------------------------------------
# 1) 임베딩/유사도
# ---------------------------------------------------------

def _embed_text(text: str) -> Optional[list[float]]:
    """OpenAI embeddings로 텍스트를 임베딩합니다(RAG용)."""
    if OpenAI is None:
        return None
    if not os.getenv("OPENAI_API_KEY"):
        return None

    t = (text or "").strip()
    if not t:
        return None

    try:
        client = OpenAI()
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input=t[:4000],
        )
        return list(resp.data[0].embedding)
    except Exception:
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0

    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)

    if na <= 0.0 or nb <= 0.0:
        return -1.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# ---------------------------------------------------------
# 2) 세션 스토어
# ---------------------------------------------------------

def _ensure_rag_store() -> list[dict[str, Any]]:
    if RAG_STORE_KEY not in st.session_state:
        st.session_state[RAG_STORE_KEY] = []
    return st.session_state[RAG_STORE_KEY]


def rag_add(role: str, text: str) -> None:
    """대화 내용을 (임베딩 포함) 세션 내 벡터스토어에 저장합니다."""
    t = (text or "").strip()
    if not t:
        return

    store = _ensure_rag_store()

    # 너무 긴 답변은 비용/노이즈가 커서 제외
    if len(t) > 1500:
        t = t[:1500]

    emb = _embed_text(t)
    if emb is None:
        return

    store.append({"role": role, "text": t, "emb": emb})

    # 최근 N개만 유지
    if len(store) > 30:
        del store[:-30]


def _rag_retrieve(query: str, k: int = 5) -> list[dict[str, Any]]:
    store = _ensure_rag_store()
    if not store:
        return []

    qemb = _embed_text(query)
    if qemb is None:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    q = (query or "").strip()

    for item in store:
        try:
            if (item.get("text") or "").strip() == q:
                continue
            sim = _cosine_similarity(qemb, item.get("emb") or [])
            scored.append((sim, item))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[: max(0, int(k))]]


def rag_context_text_for(query: str, k: int = 4) -> str:
    """최근 대화 중 query와 유사한 내용을 짧게 요약해 system 메시지로 주입하기 위한 텍스트."""
    items = _rag_retrieve(query, k=k)
    if not items:
        return ""

    lines: list[str] = []
    for it in items:
        role = str(it.get("role") or "").strip() or "unknown"
        text = str(it.get("text") or "").strip()
        if not text:
            continue

        text = text.replace("\n", " ").strip()
        if len(text) > 180:
            text = text[:180] + "…"

        lines.append(f"- ({role}) {text}")

    return "\n".join(lines)
