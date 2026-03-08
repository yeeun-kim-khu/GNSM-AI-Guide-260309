"""gnsm.ui_render

이 파일은 Streamlit UI에 출력되는 '부가 요소' 렌더링을 담당합니다.

- 출처 링크 버튼(항상 최소 1개 이상)
- 답변 내 [이미지-n] URL을 실제 이미지로 렌더링

핵심 목표:
- UI에 URL을 길게 노출하지 않고 버튼/이미지로 제공
- 동일 URL 중복 제거
- 스코프(last_scope_area)에 맞는 기본 출처를 자동 포함
"""

from __future__ import annotations

import re
import requests
import streamlit as st

from gnsm.text_parsing import parse_sources_from_text, parse_image_urls_from_text


# ---------------------------------------------------------
# 1) 기본 출처(답변에 링크가 없더라도, 매 답변마다 최소 1~3개 버튼 제공)
# ---------------------------------------------------------

DEFAULT_SOURCE_URLS_BY_AREA = {
    "planetarium": [
        {"label": "천체투영관", "url": "https://www.sciencecenter.go.kr/scipia/display/planetarium", "desc": "천체투영관 자세히보기"},
    ],
    "observatory": [
        {"label": "천문대", "url": "https://www.sciencecenter.go.kr/scipia/display/planetarium/observation", "desc": "천문대 자세히보기"},
    ],
    "space_analog": [
        {"label": "스페이스 아날로그", "url": "https://www.sciencecenter.go.kr/scipia/display/planetarium/spaceAnalog", "desc": "스페이스 아날로그 자세히보기"},
    ],
    "star_road": [
        {"label": "별에게로 가는 길", "url": "https://www.sciencecenter.go.kr/scipia/display/planetarium/starRoad", "desc": "별에게로 가는 길 자세히보기"},
    ],
    "main_page": [
        {"label": "홈페이지", "url": "https://www.sciencecenter.go.kr/scipia/", "desc": "홈페이지 살펴보기"},
    ],
    "scipia": [
        {"label": "홈페이지", "url": "https://www.sciencecenter.go.kr/scipia/", "desc": "홈페이지 살펴보기"},
    ],
}


# ---------------------------------------------------------
# 2) 출처 버튼 렌더링
# ---------------------------------------------------------

def _normalize_url(u: str) -> str:
    return (u or "").strip().rstrip("/ ")


def _emoji_for_source(ssot_label: str, url: str) -> str:
    label = (ssot_label or "").strip()
    u = _normalize_url(url)

    by_label = {
        "홈페이지": "🏠",
        "공지사항": "📢",
        "공지": "📢",
        "이용안내": "ℹ️",
        "주차안내": "🅿️",
        "주차 안내": "🅿️",
        "교통안내": "🚌",
        "연간회원": "🎫",
        "연간 회원": "🎫",
        "단체관람": "👥",
        "단체 관람": "👥",
        "추천관람코스": "🧭",
        "추천 관람코스": "🧭",
        "전시해설": "🗣️",
        "전시해설 프로그램": "🗣️",
        "체험전시물 예약": "🧪",
        "상설전시관 체험 프로그램": "🧪",
        "행사": "🎉",
        "공연": "🎭",
        "특별기획전": "🖼️",
    }

    if label in by_label:
        return by_label[label]

    if "introduce/parking" in u:
        return "🅿️"
    if "guide/paidMember" in u:
        return "🎫"
    if "guide/groupTours" in u:
        return "👥"
    if "guide/recommendCourse" in u:
        return "🧭"
    if "display/displayExperience" in u:
        return "🧪"
    if "display/displayExplanation" in u:
        return "🗣️"
    if "/introduce/notice" in u:
        return "📢"
    if "/events/" in u:
        return "🎉"

    return "🔗"


def render_source_buttons(answer_text_for_parsing: str) -> None:
    """assistant 답변 아래에 출처 링크 버튼을 렌더링합니다."""
    sources = parse_sources_from_text(answer_text_for_parsing)

    # 공지사항 요약/검색에서는 '공지사항 목록' 1개만 버튼으로 제공(홈페이지/기타 기본 출처 추가 방지)
    # 단, 공지 상세 URL이 출처에 포함된 경우에는 키워드 판정과 무관하게 상세 URL을 우선 제공
    answer_lower = (answer_text_for_parsing or "").lower()
    is_notice_related = any(k in answer_lower for k in ["공지", "안내", "모집", "행사", "특별", "관측회", "무료관람"])
    is_faq_related = any(k in answer_lower for k in ["자주 묻는 질문", "faq", "큐앤에이", "q&a"])
    
    notice_list_sources: list[dict] = []
    notice_detail_sources: list[dict] = []
    other_sources: list[dict] = []
    
    for s in (sources or []):
        try:
            u = _normalize_url(str((s or {}).get("url") or ""))
        except Exception:
            u = ""
        if not u:
            continue

        # 상세 URL: /introduce/notice/<id> (우선순위 높음)
        if re.search(r"/scipia/introduce/notice/\d{4,}", u):
            notice_detail_sources.append(s)
            continue
        # 목록 URL: /introduce/notice 또는 /introduce/notice?page=... 형태
        if re.search(r"/scipia/introduce/notice(?:\?|$)", u):
            notice_list_sources.append(s)
            continue
        
        # 공지 URL이 아닌 경우
        other_sources.append(s)

    # 상세 URL이 출처에 포함되면 공지 관련 응답으로 간주
    if notice_detail_sources or notice_list_sources:
        is_notice_related = True

    # 상세 URL이 여러 개 있으면 가장 마지막에 언급된 URL 사용 (가장 최근 검색 결과)
    has_notice_detail = bool(notice_detail_sources)
    
    if notice_detail_sources:
        # 가장 마지막 URL이 사용자가 질문한 공지일 가능성이 높음
        sources = [notice_detail_sources[-1]]
    elif notice_list_sources:
        sources = [notice_list_sources[0]]
    else:
        sources = other_sources

    # 언어 설정 가져오기 - 마지막 사용자 메시지의 언어 감지
    language = st.session_state.get("language", "한국어")
    
    # 마지막 사용자 메시지가 한글인지 영어인지 감지
    try:
        messages = st.session_state.get("messages", [])
        if messages:
            last_user_msg = None
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "")
                    break
            
            if last_user_msg:
                # 한글 문자가 있으면 한국어, 없으면 영어
                has_korean = any('\uac00' <= c <= '\ud7a3' for c in last_user_msg)
                if has_korean:
                    language = "한국어"
                else:
                    # 영어 알파벳이 많으면 영어
                    has_english = any('a' <= c.lower() <= 'z' for c in last_user_msg)
                    if has_english:
                        language = "English"
    except Exception:
        pass
    
    # URL → SSOT 라벨 매핑(버튼명이 '출처'로 뭉개지는 문제 완화)
    url_to_label: dict[str, str] = {}
    try:
        from gnsm import tools as _tools_module

        if hasattr(_tools_module, "comp_scipia_ssot_urls"):
            ssot = _tools_module.comp_scipia_ssot_urls()
            for k, v in (ssot or {}).items():
                if v:
                    url_to_label[str(v).strip()] = str(k).strip()

        if language == "English":
            url_to_label["https://www.sciencecenter.go.kr/scipia"] = "Homepage"
            url_to_label["https://www.sciencecenter.go.kr/scipia/"] = "Homepage"
        else:
            url_to_label["https://www.sciencecenter.go.kr/scipia"] = "홈페이지"
            url_to_label["https://www.sciencecenter.go.kr/scipia/"] = "홈페이지"
    except Exception:
        url_to_label = {}

    # 추천(탐색) 응답은 메인 페이지만 기본 제공
    if st.session_state.get("last_intent") == "recommend":
        if language == "English":
            sources = [{
                "label": "Homepage",
                "url": "https://www.sciencecenter.go.kr/scipia/",
                "desc": "Visit Homepage",
            }]
        else:
            sources = [{
                "label": "홈페이지",
                "url": "https://www.sciencecenter.go.kr/scipia/",
                "desc": "홈페이지 살펴보기",
            }]

    # 추천이 아니면 스코프에 맞는 기본 출처 추가
    # FAQ 답변에는 기본 출처를 추가하지 않음 (FAQ URL만 표시)
    if (st.session_state.get("last_intent") != "recommend") and (not notice_list_sources) and (not has_notice_detail) and (not is_faq_related):
        last_area = st.session_state.get("last_scope_area")
        related = list(DEFAULT_SOURCE_URLS_BY_AREA.get(last_area, []) or [])
        if related:
            sources = list(sources or []) + related

        # dedupe
        deduped: list[dict] = []
        seen_urls = set()
        for s in (sources or []):
            u = _normalize_url(str((s or {}).get("url") or ""))
            if not u:
                continue
            if u in seen_urls:
                continue
            seen_urls.add(u)
            deduped.append(s)
        sources = deduped

    # 텍스트에 출처가 없으면, 마지막 스코프 기반 기본 출처를 최소 1개 제공
    if (not sources) and (not notice_list_sources) and (not has_notice_detail):
        last_area = st.session_state.get("last_scope_area")
        if last_area and last_area in DEFAULT_SOURCE_URLS_BY_AREA:
            sources = list(DEFAULT_SOURCE_URLS_BY_AREA[last_area])
        else:
            sources = list(DEFAULT_SOURCE_URLS_BY_AREA["main_page"])

    st.markdown("")

    cols = st.columns(min(3, len(sources)))
    for i, s in enumerate(sources):
        url = (s.get("url", "") or "").strip()
        if not url:
            continue

        desc = (s.get("desc") or "").strip()
        ssot_label = url_to_label.get(url, "")
        normalized = _normalize_url(url)

        if normalized in ("https://www.sciencecenter.go.kr/scipia", "https://www.sciencecenter.go.kr"):
            if language == "English":
                ssot_label = "Homepage"
                btn_text = "Homepage"
            else:
                ssot_label = "홈페이지"
                btn_text = "홈페이지 살펴보기"
        elif "/scipia/introduce/notice" in normalized:
            if language == "English":
                ssot_label = "Announcements"
                btn_text = "Announcements"
            else:
                ssot_label = "공지사항"
                btn_text = "공지사항"
        elif "/scipia/communication/faq" in normalized:
            if language == "English":
                ssot_label = "Exhibition FAQ"
                btn_text = "Exhibition FAQ"
            else:
                ssot_label = "전시관람 FAQ"
                btn_text = "전시관람 FAQ"
        else:
            btn_text = desc or ssot_label or (s.get("label") or "") or ("Homepage" if language == "English" else "홈페이지 살펴보기")

        emoji = _emoji_for_source(ssot_label, url)
        if emoji:
            btn_text = f"{emoji} {btn_text}"

        with cols[i % len(cols)]:
            if hasattr(st, "link_button"):
                st.link_button(btn_text, url)
            else:
                st.markdown(f"🔗 [{btn_text}]({url})")


# ---------------------------------------------------------
# 3) 이미지 렌더링
# ---------------------------------------------------------

def render_inline_images(answer_text_for_parsing: str) -> None:
    imgs = parse_image_urls_from_text(answer_text_for_parsing)
    if not imgs:
        return

    for it in imgs[:6]:
        url = (it.get("url") or "").strip()
        if not url:
            continue

        caption = (it.get("desc") or "").strip() or None

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)",
                "Referer": "https://www.sciencecenter.go.kr/scipia/",
            }
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            st.image(resp.content, caption=caption)
        except Exception:
            continue
