"""gnsm.state

이 파일은 Streamlit 세션 상태(st.session_state)에 저장되는 값들을
일관된 키/형태로 관리하기 위한 헬퍼를 제공합니다.

- messages: 채팅 히스토리(사용자/assistant)
- last_scope_area / last_intent: UI에서 출처 버튼 기본값에 활용
- interest topic: 추천 질문(탐색)에서 대화 방향을 잡는 '관심 주제'
- hall location notes: 사용자가 알려준 위치 메모(공식 근거 아님)
"""

from __future__ import annotations

from typing import Any

import streamlit as st

import time


# ---------------------------------------------------------
# 1) 세션 키 상수
# ---------------------------------------------------------

RAG_STORE_KEY = "gnsm_rag_store"
INTEREST_TOPIC_KEY = "gnsm_interest_topic"
HALL_LOCATION_NOTES_KEY = "gnsm_hall_location_notes"

MESSAGES_KEY = "messages"

CHAT_SESSIONS_KEY = "gnsm_chat_sessions"
CURRENT_CHAT_ID_KEY = "gnsm_current_chat_id"


# ---------------------------------------------------------
# 2) 메시지 관리
# ---------------------------------------------------------

def get_messages() -> list[dict[str, str]]:
    """세션의 채팅 메시지 배열을 반환(없으면 생성)"""
    if MESSAGES_KEY not in st.session_state:
        st.session_state[MESSAGES_KEY] = []
    return st.session_state[MESSAGES_KEY]


def _ensure_chat_sessions_initialized() -> None:
    if CHAT_SESSIONS_KEY not in st.session_state:
        st.session_state[CHAT_SESSIONS_KEY] = []
    if CURRENT_CHAT_ID_KEY not in st.session_state:
        st.session_state[CURRENT_CHAT_ID_KEY] = ""
    if MESSAGES_KEY not in st.session_state:
        st.session_state[MESSAGES_KEY] = []


def get_chat_sessions() -> list[dict[str, Any]]:
    _ensure_chat_sessions_initialized()
    return st.session_state[CHAT_SESSIONS_KEY]


def get_current_chat_id() -> str:
    _ensure_chat_sessions_initialized()
    return str(st.session_state.get(CURRENT_CHAT_ID_KEY) or "")


def _ensure_current_chat_session_exists() -> str:
    _ensure_chat_sessions_initialized()
    cid = get_current_chat_id()
    if cid:
        return cid

    msgs = list(get_messages())
    first_user = ""
    for m in msgs:
        if str(m.get("role") or "") == "user":
            first_user = str(m.get("content") or "").strip()
            if first_user:
                break

    if not first_user:
        return ""

    cid = f"chat_{int(time.time() * 1000)}"
    st.session_state[CURRENT_CHAT_ID_KEY] = cid
    st.session_state[CHAT_SESSIONS_KEY].insert(
        0,
        {
            "id": cid,
            "title": _make_chat_title_from_text(first_user),
            "created_ts": float(time.time()),
            "updated_ts": float(time.time()),
            "messages": msgs,
        },
    )
    return cid


def _find_chat_session(chat_id: str) -> dict[str, Any] | None:
    for s in get_chat_sessions():
        if str(s.get("id") or "") == str(chat_id or ""):
            return s
    return None


def _make_chat_title_from_text(text: str) -> str:
    t = " ".join((text or "").strip().split())
    if not t:
        return "새 대화"
    if len(t) > 24:
        t = t[:24].rstrip() + "…"
    return t


def persist_current_chat_session() -> None:
    _ensure_chat_sessions_initialized()
    cid = get_current_chat_id() or _ensure_current_chat_session_exists()
    if not cid:
        return
    s = _find_chat_session(cid)
    if s is None:
        return
    s["messages"] = list(get_messages())
    title = str(s.get("title") or "").strip()
    if (not title) or (title == "새 대화"):
        first_user = ""
        for m in s["messages"]:
            if str(m.get("role") or "") == "user":
                first_user = str(m.get("content") or "").strip()
                if first_user:
                    break
        if first_user:
            s["title"] = _make_chat_title_from_text(first_user)
    s["updated_ts"] = float(time.time())


def new_chat_session(title: str = "새 대화") -> str:
    if CHAT_SESSIONS_KEY not in st.session_state:
        st.session_state[CHAT_SESSIONS_KEY] = []
    cid = f"chat_{int(time.time() * 1000)}"
    st.session_state[CHAT_SESSIONS_KEY].insert(
        0,
        {
            "id": cid,
            "title": (title or "새 대화"),
            "created_ts": float(time.time()),
            "updated_ts": float(time.time()),
            "messages": [],
        },
    )
    st.session_state[CURRENT_CHAT_ID_KEY] = cid
    st.session_state[MESSAGES_KEY] = []
    return cid


def switch_chat_session(chat_id: str) -> bool:
    _ensure_chat_sessions_initialized()
    if not chat_id:
        return False
    s = _find_chat_session(chat_id)
    if s is None:
        return False
    st.session_state[CURRENT_CHAT_ID_KEY] = str(s.get("id") or "")
    st.session_state[MESSAGES_KEY] = list(s.get("messages") or [])
    return True


# ---------------------------------------------------------
# 3) 관심 주제(추천 질문 UX)
# ---------------------------------------------------------

def get_interest_topic() -> str:
    return str(st.session_state.get(INTEREST_TOPIC_KEY) or "").strip()


def set_interest_topic(topic: str) -> None:
    t = (topic or "").strip()
    if t:
        st.session_state[INTEREST_TOPIC_KEY] = t


# ---------------------------------------------------------
# 4) 사용자 제공 위치 메모(공식 아님)
# ---------------------------------------------------------

def get_hall_location_notes() -> dict[str, str]:
    notes = st.session_state.get(HALL_LOCATION_NOTES_KEY)
    if not isinstance(notes, dict):
        notes = {}
        st.session_state[HALL_LOCATION_NOTES_KEY] = notes

    cleaned: dict[str, str] = {}
    for k, v in (notes or {}).items():
        kk = str(k or "").strip()
        vv = str(v or "").strip()
        if kk and vv:
            cleaned[kk] = vv

    st.session_state[HALL_LOCATION_NOTES_KEY] = cleaned
    return cleaned


def set_hall_location_note(hall_label: str, note: str) -> None:
    hall = (hall_label or "").strip()
    n = (note or "").strip()
    if not hall or not n:
        return

    notes = get_hall_location_notes()
    notes[hall] = n
    st.session_state[HALL_LOCATION_NOTES_KEY] = notes


# ---------------------------------------------------------
# 5) 기타 헬퍼
# ---------------------------------------------------------

def set_value(key: str, value: Any) -> None:
    st.session_state[key] = value


def get_value(key: str, default: Any = None) -> Any:
    return st.session_state.get(key, default)
