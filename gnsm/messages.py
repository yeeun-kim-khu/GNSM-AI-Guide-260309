"""gnsm.messages

이 파일은 LangGraph 에이전트에게 전달할 메시지 목록을 구성합니다.

구성 원칙:
- 시스템 프롬프트는 항상 첫 번째 메시지로 들어갑니다.
- 추천/공지/동선 같은 특정 유형 질문에 대해 추가 시스템 가이드 메시지를 삽입합니다.
- 세션 메모리(관심 주제, 사용자 제공 위치 메모, 간단 RAG 발췌)를 system 메시지로 주입합니다.
"""

from __future__ import annotations

from gnsm.prompt import _get_system_prompt
from gnsm.state import get_interest_topic, get_hall_location_notes
from gnsm.rag import rag_context_text_for
from gnsm import heuristics


def build_messages_for_agent(chat_messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """LangGraph에게 전달할 메시지 포맷: [{"role": "...", "content": "..."}]"""
    msgs = chat_messages or []

    normalized: list[dict[str, str]] = [{"role": "system", "content": _get_system_prompt()}]

    # 최근 사용자 메시지(컨텍스트 주입 기준)
    last_user = ""
    for m in reversed(msgs):
        if m.get("role") == "user" and (m.get("content") or "").strip():
            last_user = str(m.get("content") or "").strip()
            break

    # 관심 주제 / RAG 컨텍스트 / 사용자 위치 메모를 system 메시지로 추가
    if last_user:
        interest = get_interest_topic()
        rag_ctx = rag_context_text_for(last_user)
        hall_notes = get_hall_location_notes()

        parts: list[str] = []
        if interest:
            parts.append(f"[대화 컨텍스트] 사용자가 현재 관심있는 주제: {interest}")
        if rag_ctx:
            parts.append("[대화 컨텍스트] 최근 대화 요약(발췌):\n" + rag_ctx)
        if hall_notes:
            lines: list[str] = []
            for k, v in list(hall_notes.items())[:8]:
                lines.append(f"- {k}: {v}")
            parts.append("[사용자 제공 위치 메모(공식 아님)]\n" + "\n".join(lines))

        if parts:
            normalized.append({"role": "system", "content": "\n\n".join(parts)})

    # 동선 질문
    if last_user and heuristics.looks_like_route_request(last_user):
        normalized.append({
            "role": "system",
            "content": (
                "동선/방문 경로 질문입니다. scipia 공식 페이지의 텍스트/지도/동선 이미지로 확인된 내용만 구체적으로 안내하세요. "
                "근거가 없으면 동선을 만들어내지 말고, '공식 페이지에 동선 안내가 없어 확인이 필요하다'고 말한 뒤 출발지(지하철/주차/동문/서문 등) 1가지만 확인 질문하세요. "
                "사용자가 전시관 위치/랜드마크를 알려준 경우에는 그 정보를 활용해 '사용자 제공 정보 기반'이라고 명시하고 일반 안내(정확한 표지/현장 안내 기준)를 제공합니다. "
                "가능하면 get_*_route_guide 또는 get_scipia_page로 근거를 확보하고, get_scipia_route_images로 동선/지도 이미지 URL을 추출해 "
                "[이미지-1] https://... 형식으로 포함하세요."
            ),
        })

    # 공지/연휴/휴관 질문
    if last_user and heuristics.looks_like_holiday_or_notice_request(last_user):
        normalized.append({
            "role": "system",
            "content": (
                "설/연휴/휴관/운영 안내처럼 공지 기반 확인이 필요한 질문입니다. "
                "가능하면 먼저 공지사항 목록에서 관련 공지를 찾아 확인하세요. "
                "예: search_sciencecenter_notices(query=\"설\") -> get_sciencecenter_notice_page(공지 URL) 순서. "
                "도구로 확인되지 않으면 추측하지 마세요."
            ),
        })

    # 최근 공지 요청
    if last_user and heuristics.looks_like_recent_notices_request(last_user):
        normalized.append({
            "role": "system",
            "content": (
                "사용자가 '최근/최신 공지사항'을 요청했습니다. "
                "반드시 get_recent_sciencecenter_notices(limit=...)로 공지 목록을 먼저 확인하고, "
                "필요하면 중요한 항목 1~2개는 get_sciencecenter_notice_page로 열어 핵심만 요약하세요. "
                "확인 없이 추측하지 마세요."
            ),
        })

    # 기존 대화(유저/assistant) 주입
    for m in msgs:
        role = m.get("role", "")
        content = m.get("content", "")
        if not content:
            continue
        if role not in ("user", "assistant"):
            continue
        normalized.append({"role": role, "content": content})

    return normalized
