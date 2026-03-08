"""gnsm.hall_notes

이 파일은 사용자가 채팅 중에 알려준 '전시관 위치 메모'를
세션에 저장하는 기능을 담당합니다.

중요:
- 이 메모는 공식(sciencecenter.go.kr/scipia) 근거가 아닌 '사용자 제공 정보'입니다.
- 따라서 에이전트에게는 참고용으로만 전달하고, 단정 표현을 피해야 합니다.
"""

from __future__ import annotations

import re

from gnsm import heuristics
from gnsm.state import set_hall_location_note


def looks_like_route_request(text: str) -> bool:
    """동선 질문은 '위치 메모'로 오해하지 않도록 분리합니다."""
    return heuristics.looks_like_route_request(text)


def maybe_capture_hall_location_note(user_text: str) -> str:
    """사용자 입력에서 '전시관 위치 메모'를 추출/저장하고, 저장된 전시관 라벨을 반환합니다."""
    t = (user_text or "").strip()
    if not t:
        return ""

    # 너무 일반적인 동선 질문은 위치 메모로 취급하지 않음
    if looks_like_route_request(t) and ("위치" not in t):
        return ""

    # 명시적 저장 명령: "위치등록: 전시관=..." / "위치 메모: 전시관: ..."
    if any(k in t for k in ["위치등록", "위치 등록", "위치메모", "위치 메모", "위치 저장"]):
        m = re.search(r"[:：]\s*(.+)$", t)
        payload = (m.group(1) if m else "").strip()
        if payload:
            m2 = re.search(r"^(.+?)[=:=：]\s*(.+)$", payload)
            if m2:
                hall_guess = (m2.group(1) or "").strip()
                note = (m2.group(2) or "").strip()

                hall = ""
                try:
                    from gnsm import tools as _tools
                    if getattr(_tools, "resolve_hall_label", None):
                        hall = _tools.resolve_hall_label(hall_guess)
                except Exception:
                    hall = ""

                if hall and note:
                    set_hall_location_note(hall, note)
                    return hall
        return ""

    # 자연어 형태: "자연사관 위치는 1층 ..." 같은 입력
    if "위치" in t:
        hall = ""
        try:
            from gnsm import tools as _tools
            if getattr(_tools, "resolve_hall_label", None):
                hall = _tools.resolve_hall_label(t)
        except Exception:
            hall = ""

        if hall:
            m = re.search(r"위치(?:는|은|:|：)?\s*(.+)$", t)
            note = (m.group(1) if m else "").strip()
            if note and len(note) >= 3:
                set_hall_location_note(hall, note)
                return hall

    return ""
