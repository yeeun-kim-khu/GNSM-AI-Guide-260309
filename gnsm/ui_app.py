"""gnsm.ui_app

이 파일은 Streamlit 앱의 '메인 화면(채팅 UI)'을 담당합니다.

역할:
- 기존 `app.py`에서 호출되는 단일 엔트리 함수 `run_chat_assistant()` 제공
- 세션 메시지 렌더링 / 사용자 입력 수집
- 추천/공지/동선 등 UX 분기 처리
- LangGraph 에이전트 호출 및 결과 표시(출처 버튼/이미지 렌더링)

설명 포인트(나중에 발표/설명할 때):
- UI는 여기, 에이전트 런타임은 `gnsm.agent_runtime`, 메시지 빌드는 `gnsm.messages`,
  휴리스틱은 `gnsm.heuristics`, 출처/이미지는 `gnsm.ui_render`로 분리되어 있습니다.
"""

from __future__ import annotations

import re
import streamlit as st

from gnsm import heuristics
from gnsm.agent_runtime import ensure_agent, invoke_agent_safely
from gnsm.hall_notes import maybe_capture_hall_location_note
from gnsm.messages import build_messages_for_agent
from gnsm.notice_summary import build_notice_summary_answer
from gnsm.rag import rag_add
from gnsm.state import (
    get_chat_sessions,
    get_current_chat_id,
    get_interest_topic,
    get_messages,
    new_chat_session,
    persist_current_chat_session,
    set_interest_topic,
    switch_chat_session,
)
from gnsm.text_parsing import clean_assistant_display_text, escape_tildes, parse_sources_from_text
from gnsm.ui_render import render_inline_images, render_source_buttons


def _render_reset_button() -> None:
    if not hasattr(st, "sidebar"):
        return

    with st.sidebar:
        # 언어 선택
        st.markdown("### 🌐 Language / 언어")
        current_language = st.session_state.get("language", "한국어")
        language = st.selectbox(
            "언어 선택",
            ["한국어", "English"],
            index=0 if current_language == "한국어" else 1,
            key="language_selector",
            label_visibility="collapsed"
        )
        
        # 언어 변경 시 즉시 페이지 재로드
        if language != current_language:
            st.session_state["language"] = language
            st.rerun()
        
        st.markdown("---")
        
        # 버튼 텍스트 다국어 지원
        if language == "English":
            quick_q_title = "### 🎯 Quick Questions"
            btn_hours = "🕐 Hours"
            btn_admission = "🎫 Admission"
            btn_directions = "🚗 Directions"
            btn_faq = "❓ FAQ"
            recent_notices_title = "### 📢 Recent Announcements"
            # chat_history_title = "### 💬 My Chat History"  # 숨김 처리
        else:
            quick_q_title = "### 🎯 빠른 질문"
            btn_hours = "🕐 운영시간"
            btn_admission = "🎫 관람료"
            btn_directions = "🚗 오시는 길"
            btn_faq = "❓ FAQ"
            recent_notices_title = "### 📢 최근 공지사항"
            # chat_history_title = "### 💬 내 채팅이력"  # 숨김 처리
        
        st.markdown(quick_q_title)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button(btn_hours, use_container_width=True, key="sidebar_hours"):
                st.session_state["faq_query"] = "과학관 운영시간"
                st.rerun()
            if st.button(btn_directions, use_container_width=True, key="sidebar_directions"):
                st.session_state["faq_query"] = "과학관으로 오시는 길"
                st.rerun()
        
        with col2:
            if st.button(btn_admission, use_container_width=True, key="sidebar_admission"):
                st.session_state["faq_query"] = "과학관 관람료"
                st.rerun()
            if st.button(btn_faq, use_container_width=True, key="sidebar_faq"):
                st.session_state["faq_query"] = "과학관 자주 묻는 질문(FAQ)"
                st.rerun()
        
        st.markdown("---")
        
        st.markdown(recent_notices_title)
        
        # 최근 공지사항 5개 가져오기
        try:
            from gnsm import notice_summary
            recent_notices = notice_summary.get_recent_notices_for_sidebar(limit=5)
            
            if recent_notices:
                for idx, notice in enumerate(recent_notices):
                    notice_title = notice.get("title", "제목 없음")
                    notice_url = notice.get("url", "")
                    
                    # 제목 길이 제한 (15자) - 한줄로 표시
                    display_title = notice_title[:15] + "..." if len(notice_title) > 15 else notice_title
                    
                    if st.button(display_title, use_container_width=True, key=f"notice_{idx}"):
                        # 공지사항 제목으로 질문 (URL은 숨김)
                        st.session_state["faq_query"] = f"'{notice_title}' 공지사항에 대해 안내해줘"
                        # URL은 별도로 저장하여 에이전트가 사용
                        if notice_url:
                            st.session_state["notice_url_hint"] = notice_url
                        st.rerun()
            else:
                loading_msg = "Loading announcements..." if language == "English" else "공지사항을 불러오는 중..."
                st.info(loading_msg)
        except Exception as e:
            error_msg = "Unable to load announcements." if language == "English" else "공지사항을 불러올 수 없습니다."
            st.warning(error_msg)
        
        st.markdown("---")
        
        # '대화/에이전트 초기화' 버튼 숨김 (기능은 유지)
        # if st.button("대화/에이전트 초기화", use_container_width=True):
        if False:  # 버튼 비활성화
            # 채팅/메모리 관련 세션 키를 명시적으로 제거
            for k in [
                "messages",
                "gnsm_agent",
                "gnsm_thread_id",
                "gnsm_tools",
                "gnsm_rag_store",
                "gnsm_interest_topic",
                "gnsm_hall_location_notes",
                "last_scope_area",
                "last_intent",
                "recent_notice_items",
                "faq_query",
            ]:
                st.session_state.pop(k, None)
            st.rerun()


def _render_chat_history_sidebar() -> None:
    if not hasattr(st, "sidebar"):
        return

    sessions = get_chat_sessions()
    current_id = get_current_chat_id()

    def _label(s: dict) -> str:
        title = str(s.get("title") or "새 대화")
        # (chat~~~숫자) 패턴 제거
        import re
        title = re.sub(r'\(chat[^\)]*\)', '', title).strip()
        return title

    # 채팅이력 섹션 숨김 처리
    if False:  # 채팅이력 비활성화
        with st.sidebar:
            language = st.session_state.get("language", "한국어")
            chat_history_label = "💬 My Chat History" if language == "English" else "💬 내 채팅이력"
            st.markdown(f"<div style='font-weight:700; margin:0 0 0.25rem 0;'>{chat_history_label}</div>", unsafe_allow_html=True)

            search_placeholder = "Search chats..." if language == "English" else "채팅을 검색해보세요"
            q = st.text_input(
                label="chat_search",
                value=str(st.session_state.get("gnsm_chat_search", "")),
                placeholder=search_placeholder,
                label_visibility="collapsed",
            )
            st.session_state["gnsm_chat_search"] = q

            filtered_sessions = sessions
            qq = " ".join((q or "").strip().split()).lower()
            if qq:
                def _match(s: dict) -> bool:
                    try:
                        return qq in str(s.get("title") or "").lower()
                    except Exception:
                        return False
                filtered_sessions = [s for s in (sessions or []) if _match(s)]

        if filtered_sessions:
            options = [str(s.get("id") or "") for s in filtered_sessions]
            default_idx = 0
            if current_id in options:
                default_idx = options.index(current_id)

            selected = st.selectbox(
                "chat_select",
                options=options,
                index=default_idx,
                format_func=lambda cid: _label(next((x for x in filtered_sessions if str(x.get("id") or "") == cid), {})),
                label_visibility="collapsed",
            )

            if selected and selected != current_id:
                persist_current_chat_session()
                ok = switch_chat_session(selected)
                if ok:
                    st.rerun()


# ---------------------------------------------------------
# 1) 추천/탐색 UX용 출력
# ---------------------------------------------------------

def _interest_topics_prompt_intro() -> str:
    return heuristics.interest_topics_prompt_intro()


def _interest_topics_prompt_list(core_topics: list[str] | None = None) -> str:
    return heuristics.interest_topics_prompt_list(core_topics)


# ---------------------------------------------------------
# 2) 공지/연휴 요약(도구 기반) 보조
# ---------------------------------------------------------

def _summarize_notices_from_search(raw_search: str, details_blob_parts: list[str], title_prefix: str) -> str:
    items = parse_sources_from_text(raw_search)

    print("=== DEBUG NOTICE ===")
    print("items len:", len(items or []))
    print("details_blob_parts len:", len(details_blob_parts or []))
    for i, blob in enumerate(details_blob_parts or []):
        print(f"\n[details_blob_parts[{i}]]")
        print(f"  type: {type(blob)}")
        s = blob if isinstance(blob, str) else str(blob)
        print(f"  length: {len(s)}")
        print(f"  preview(300): {s[:300]}")
        
        # 내용 키워드 체크
        has_content = any(k in s for k in ["안내", "개최", "신청", "모집", "운영", "예약", "관람", "무료"])
        has_noise = any(k in s for k in ["과학관소식", "고객서비스", "공지/공고 상세"])
        print(f"  has_content: {has_content}, has_noise: {has_noise}")
    print("====================")

    return build_notice_summary_answer(items=items, details_texts=details_blob_parts, title_prefix=title_prefix)


# ---------------------------------------------------------
# 3) 메인 엔트리
# ---------------------------------------------------------

def run_chat_assistant() -> None:
    """Streamlit 메인 챗봇 UI + 에이전트 실행 (app.py에서는 이 함수만 호출)."""

    _render_reset_button()
    _render_chat_history_sidebar()

    st.markdown(
        """
<style>
/* slightly smaller typography */
.stMarkdown, .stMarkdown p, .stMarkdown li { font-size: 0.95rem; line-height: 1.45; }
.stMarkdown h1 { font-size: 1.35rem; }
.stMarkdown h2 { font-size: 1.20rem; }
.stMarkdown h3 { font-size: 1.05rem; }
div[data-testid="stChatMessage"] .stMarkdown, 
div[data-testid="stChatMessage"] .stMarkdown p,
div[data-testid="stChatMessage"] .stMarkdown li { font-size: 0.95rem; line-height: 1.45; }
button[kind="secondary"], button[kind="primary"] { font-size: 0.95rem; }
</style>
""",
        unsafe_allow_html=True,
    )

    # (A) 에이전트 준비
    agent = ensure_agent()
    if agent is None:
        return

    # (B) FAQ 버튼은 사이드바로 이동

    # (C) 기존 대화 렌더링
    for msg in get_messages():
        role = msg.get("role", "assistant")
        content = msg.get("content", "")
        if not content:
            continue

        if hasattr(st, "chat_message"):
            with st.chat_message(role):
                st.markdown(escape_tildes(content))
        else:
            st.markdown(f"**{role}**: {escape_tildes(content)}")

    # (D) 사용자 입력
    preset = st.session_state.pop("gnsm_preset_user_input", "") if "gnsm_preset_user_input" in st.session_state else ""
    faq_query = st.session_state.pop("faq_query", "") if "faq_query" in st.session_state else ""
    notice_url_hint = st.session_state.pop("notice_url_hint", "") if "notice_url_hint" in st.session_state else ""
    
    # 입력창 placeholder 다국어 지원
    language = st.session_state.get("language", "한국어")
    if language == "English":
        input_placeholder = "Ask me anything about the museum's operations, programs, events, or facilities :)"
    else:
        input_placeholder = "국립과천과학관 운영/전시/행사 등 무엇이든 물어보세요 :)"
    
    typed_input = st.chat_input(input_placeholder)
    user_input = typed_input or faq_query or preset
    if not user_input:
        return

    get_messages().append({"role": "user", "content": user_input})
    persist_current_chat_session()

    # (D) 관심 주제 업데이트(짧은 입력 '곤충' 등)
    topic = heuristics.resolve_interest_topic(user_input)
    if topic:
        set_interest_topic(topic)

    # (E) 언어 설정 추가
    language = st.session_state.get("language", "한국어")
    language_instruction = ""
    if language == "English":
        language_instruction = "\n\n[IMPORTANT: Please respond in English. Translate all Korean content to natural English.]"
    
    # 사용자 입력에 언어 설정 추가
    user_input_with_lang = user_input + language_instruction
    
    # (F) 세션 RAG 저장(사용자 발화)
    rag_add("user", user_input)

    # (G) 사용자가 제공한 전시관 위치 메모 저장
    saved_hall = maybe_capture_hall_location_note(user_input)
    saved_prefix = f"알려주신 **{saved_hall}** 위치 정보를 메모해둘게요." if saved_hall else ""

    # 입력 메시지 출력
    if hasattr(st, "chat_message"):
        with st.chat_message("user"):
            st.markdown(escape_tildes(user_input))
    else:
        st.markdown(f"**user**: {escape_tildes(user_input)}")

    # (G) 스코프 점수 계산 + 세션 저장(출처 버튼 기본 제공에 사용)
    scope_info = heuristics.scope_match_score(user_input)
    best_area = scope_info.get("best_area")
    if best_area:
        st.session_state["last_scope_area"] = best_area

    # (H) 인텐트(추천/확정 안내) 저장
    st.session_state["last_intent"] = "recommend" if heuristics.looks_like_recommendation_request(user_input) else "other"

    # (I-1) notice_url_hint가 있으면 UI 레벨에서 직접 처리
    if notice_url_hint:
        st.session_state["last_scope_area"] = "main_page"
        st.session_state["last_intent"] = "other"
        
        # 단일 공지사항 크롤링
        detail = ""
        try:
            from gnsm import tools as _tools
            if getattr(_tools, "fetch_sciencecenter_page_selenium", None):
                txt = _tools.fetch_sciencecenter_page_selenium(notice_url_hint)
                if txt and ("[크롤링 실패]" not in str(txt)):
                    detail = txt
        except Exception:
            pass
        
        # 크롤링 실패 시 일반 크롤링으로 재시도
        if not detail or ("[크롤링 실패]" in str(detail)):
            try:
                from gnsm import tools as _tools
                if getattr(_tools, "get_sciencecenter_notice_page", None):
                    result = _tools.get_sciencecenter_notice_page.invoke({"url": notice_url_hint})
                    if result and ("[크롤링 실패]" not in str(result)):
                        detail = result
            except Exception:
                pass
        
        # 답변 생성
        if detail:
            # 제목 추출
            title = user_input.strip().strip("'")
            
            # 내용 포맷팅 (notice_summary의 _format_notice_content 함수 사용)
            try:
                from gnsm.notice_summary import _format_notice_content
                formatted_detail = _format_notice_content(detail)
            except Exception:
                formatted_detail = detail
            
            answer = f"**{title}**\n\n{formatted_detail}\n\n📎 [출처 바로가기]({notice_url_hint})"
        else:
            answer = f"죄송합니다. 공지사항의 상세 내용을 불러올 수 없습니다."
        
        display_answer = clean_assistant_display_text(answer)
        
        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                st.markdown(escape_tildes(display_answer))
                render_source_buttons(f"[출처] {notice_url_hint}")
        else:
            st.markdown(f"**assistant**: {escape_tildes(display_answer)}")
            render_source_buttons(f"[출처] {notice_url_hint}")
        
        get_messages().append({
            "role": "assistant",
            "content": display_answer,
            "scope_area": "main_page",
            "intent": "other",
            "sources_blob": f"[출처] {notice_url_hint}",
            "image_blob": "",
        })
        persist_current_chat_session()
        rag_add("assistant", display_answer)
        return
    
    # (I) 공지/연휴/휴관 등 전관 기준 질문은 스코프 main_page로 리셋
    if st.session_state.get("last_intent") != "recommend" and heuristics.looks_like_holiday_or_notice_request(user_input):
        st.session_state["last_scope_area"] = "main_page"

    # (J) 운영/요금/예약/공지 등 사실확인인데 스코프가 없으면 main_page로
    if (
        st.session_state.get("last_intent") != "recommend"
        and (not best_area)
        and heuristics.looks_like_fact_or_ops_request(user_input)
    ):
        st.session_state["last_scope_area"] = "main_page"

    # -----------------------------------------------------
    # (UI) 운영시간 질문은 '이용안내' 페이지를 우선 확인
    # -----------------------------------------------------
    t_ops = (user_input or "").strip().lower()
    if any(k in t_ops for k in [
        "운영시간",
        "운영 시간",
        "영업시간",
        "개관",
        "폐관",
        "몇시",
        "몇 시",
        "다음 운영일",
        "다음 운영",
        "다음 개관",
        "언제 열",
        "언제 여",
    ]):
        try:
            from gnsm import tools as _tools
            guide_url = ""
            if getattr(_tools, "comp_scipia_ssot_url", None):
                guide_url = _tools.comp_scipia_ssot_url("이용안내") or ""
            if (not guide_url) and getattr(_tools, "MUSEUM_BASE_URL", None):
                guide_url = f"{_tools.MUSEUM_BASE_URL}/scipia/guide/totalGuide"

            raw_guide = ""
            if guide_url and getattr(_tools, "fetch_sciencecenter_page", None):
                raw_guide = _tools.fetch_sciencecenter_page(guide_url, timeout=15)
            elif guide_url and getattr(_tools, "get_scipia_page", None):
                raw_guide = _tools.get_scipia_page.invoke({"url": guide_url})

            from datetime import datetime, time, timedelta
            try:
                from zoneinfo import ZoneInfo
            except Exception:  # pragma: no cover
                ZoneInfo = None

            def _is_time_line(s: str) -> bool:
                if not s:
                    return False
                if re.search(r"\b\d{1,2}:\d{2}\b", s):
                    return True
                if ("오전" in s or "오후" in s) and any(ch.isdigit() for ch in s):
                    return True
                return False

            def _parse_ampm_hhmm(s: str) -> time | None:
                m = re.search(r"(오전|오후)?\s*(\d{1,2}):(\d{2})", s)
                if not m:
                    return None
                ampm = (m.group(1) or "").strip()
                hh = int(m.group(2))
                mm = int(m.group(3))
                if ampm == "오후" and hh < 12:
                    hh += 12
                if ampm == "오전" and hh == 12:
                    hh = 0
                try:
                    return time(hour=hh, minute=mm)
                except Exception:
                    return None

            def _parse_open_close(s: str) -> tuple[time | None, time | None]:
                # 예: "오전 9:30 ~ 오후 5:30" 형태 우선
                parts = re.split(r"~|～|–|-", s)
                if len(parts) >= 2:
                    t1 = _parse_ampm_hhmm(parts[0])
                    t2 = _parse_ampm_hhmm(parts[1])
                    if t1 or t2:
                        return t1, t2
                # fallback: 첫 2개의 시간 토큰
                toks = re.findall(r"(오전|오후)?\s*\d{1,2}:\d{2}", s)
                if len(toks) >= 2:
                    t1 = _parse_ampm_hhmm(toks[0])
                    t2 = _parse_ampm_hhmm(toks[1])
                    return t1, t2
                return None, None

            def _parse_mmdd_tokens(text: str) -> set[tuple[int, int]]:
                out: set[tuple[int, int]] = set()
                for mmx, ddx in re.findall(r"(\d{1,2})\.\s*(\d{1,2})", text or ""):
                    try:
                        out.add((int(mmx), int(ddx)))
                    except Exception:
                        continue
                return out

            def _parse_regular_monday_exceptions(text: str) -> set[tuple[int, int]]:
                # '(정기 휴관) 매주 월요일(단, 2. 16., 3.2., ... 제외)' 형태에서 '단, ... 제외' 구간만 예외(운영)로 취급
                m = re.search(r"단\s*,?\s*([^\)]{0,200}?)\s*제외", text or "")
                if not m:
                    return set()
                return _parse_mmdd_tokens(m.group(1))

            def _parse_specific_closed_days_from_regular_block(text: str) -> set[tuple[int, int]]:
                # 신정/설날/추석 등 명시 휴관일은 정기휴관 블록 안에 함께 나올 수 있어 별도 추출
                if not any(k in (text or "") for k in ["신정", "설날", "추석"]):
                    return set()
                return _parse_mmdd_tokens(text or "")

            def _is_closed_on(d: datetime, regular_ex: set[tuple[int, int]], reg_specific_closed: set[tuple[int, int]], alt_days: set[tuple[int, int]]) -> bool:
                md = (d.month, d.day)
                if md in alt_days:
                    return True
                if md in reg_specific_closed:
                    return True
                # 월요일 정기휴관(예외일 제외)
                if d.weekday() == 0 and (md not in regular_ex):
                    return True
                return False

            picked: list[str] = []
            seen = set()
            lines = []
            for ln in (raw_guide or "").splitlines():
                s = " ".join(((ln or "").strip()).split())
                if not s:
                    continue
                if s.startswith("Observation") or s.startswith("[출처"):
                    continue
                lines.append(s)

            def _merge_following(i: int, n: int = 6) -> str:
                base = (lines[i] or "").strip()
                out = base
                for j in range(1, n + 1):
                    if i + j >= len(lines):
                        break
                    nxt = (lines[i + j] or "").strip()
                    if not nxt:
                        continue
                    out2 = (out + " " + nxt).strip()
                    out = out2
                    if _is_time_line(out) and ("~" in out or "～" in out):
                        break
                    if "발권" in out or "마감" in out:
                        break
                return out

            def _rebuild_time_line_from_lines() -> str:
                # '(관람 시간)' 라벨이 따로 있고 실제 시간이 다음 줄(들)에 있는 경우를 복구
                label_idx = None
                for i, s in enumerate(lines):
                    if re.search(r"\(\s*관람\s*시간\s*\)", s):
                        label_idx = i
                        break
                if label_idx is None:
                    return ""

                blob = _merge_following(label_idx, n=10)
                # 시간 토큰 2개 이상이면 open~close로 볼 수 있음
                toks = re.findall(r"(오전|오후)?\s*\d{1,2}:\d{2}", blob)
                if len(toks) < 2:
                    # 숫자 시간만 있는 경우도 고려
                    toks2 = re.findall(r"\b\d{1,2}:\d{2}\b", blob)
                    if len(toks2) < 2:
                        return blob
                return blob

            def _rebuild_labeled_block_from_lines(label_rx: "re.Pattern[str]") -> str:
                idx = None
                for i, s in enumerate(lines):
                    if label_rx.search(s or ""):
                        idx = i
                        break
                if idx is None:
                    return ""
                out_parts: list[str] = []
                for j in range(0, 11):
                    if idx + j >= len(lines):
                        break
                    cur = (lines[idx + j] or "").strip()
                    if not cur:
                        continue
                    if j > 0:
                        if cur.startswith("※"):
                            break
                        if cur.startswith("###"):
                            break
                        if cur.startswith("(") and (not label_rx.search(cur)):
                            break
                        if any(x in cur for x in ["관람료", "상설전시", "세부 정보 보기", "요금안내"]):
                            break
                    out_parts.append(cur)
                blob = " ".join(out_parts).strip()
                blob = " ".join((blob or "").split()).strip()
                blob = re.sub(r"※\s*월요일이.*$", "", blob).strip()
                blob = re.sub(r"「관공서의 공휴일에 관한 규정」.*$", "", blob).strip()
                blob = re.sub(r"「국경일에 관한 법」.*$", "", blob).strip()
                return blob

            for i, s in enumerate(lines):
                if any(x in s for x in ["(관람 시간)", "관람 시간", "(정기 휴관)", "(대체 휴관)", "발권마감", "휴관"]):
                    ss = s
                    if ("(관람 시간)" in ss or "관람 시간" in ss) and (not _is_time_line(ss)):
                        ss = _merge_following(i)
                    if ss in seen:
                        continue
                    seen.add(ss)
                    picked.append(ss)
                if len(picked) >= 30:
                    break

            def _first_match(substrs: list[str]) -> str:
                for s in picked:
                    if any(x in s for x in substrs):
                        return s
                return ""

            def _first_in_lines(substrs: list[str]) -> str:
                for s in lines:
                    ss = (s or "").strip()
                    if not ss:
                        continue
                    if any(x in ss for x in substrs):
                        return ss
                return ""

            def _first_match_filtered(substrs: list[str], reject_exact: set[str] | None = None) -> str:
                rx = reject_exact or set()
                for s in picked:
                    ss = (s or "").strip()
                    if not ss:
                        continue
                    if ss in rx:
                        continue
                    if any(x in ss for x in substrs):
                        return ss
                return ""

            def _first_re(rx: "re.Pattern[str]") -> str:
                for s in picked:
                    ss = (s or "").strip()
                    if not ss:
                        continue
                    if rx.search(ss):
                        return ss
                return ""

            time_line = ""
            ticket_line = ""
            closed_main = ""
            alt_closed = ""

            for s in picked:
                if ("(관람 시간)" in s) or ("관람 시간" in s):
                    time_line = s
                    if not _is_time_line(time_line):
                        # 안전장치: picked에 병합이 실패했거나 다른 경로로 들어온 경우
                        try:
                            idx = lines.index(s)
                            time_line = _merge_following(idx)
                        except Exception:
                            pass
                    break
            if not time_line:
                for s in picked:
                    if _is_time_line(s) and any(x in s for x in ["관람", "운영", "시간"]):
                        time_line = s
                        break
            if not time_line:
                for s in lines:
                    if _is_time_line(s) and ("~" in s or "～" in s):
                        time_line = s
                        break

            if time_line and (not _is_time_line(time_line)):
                rebuilt = _rebuild_time_line_from_lines()
                if rebuilt:
                    time_line = rebuilt

            if (not time_line) or (not _is_time_line(time_line)):
                rebuilt = _rebuild_time_line_from_lines()
                if rebuilt:
                    time_line = rebuilt

            if time_line and ("발권" in time_line or "마감" in time_line):
                m_ticket = re.search(r"발권\s*마감\s*[:：]?\s*(오전|오후)?\s*\d{1,2}:\d{2}", time_line)
                if m_ticket:
                    ticket_line = m_ticket.group(0)
            if (not ticket_line) and time_line:
                # '(관람 시간)' 라인과 분리된 경우도 있어 time_line 전체에서 한번 더 찾기
                m_ticket2 = re.search(r"발권\s*마감\s*[:：]?\s*(오전|오후)?\s*\d{1,2}:\d{2}", time_line)
                if m_ticket2:
                    ticket_line = m_ticket2.group(0)
            if not ticket_line:
                # time_line을 못 잡았거나 분리된 경우: 전체 lines에서 발권마감 라인을 직접 찾기
                cand = ""
                for s in lines:
                    ss = (s or "").strip()
                    if not ss:
                        continue
                    if ("발권" in ss and "마감" in ss) and re.search(r"\d{1,2}:\d{2}", ss):
                        cand = ss
                        break
                if cand:
                    m_ticket3 = re.search(r"발권\s*마감\s*[:：]?\s*(오전|오후)?\s*\d{1,2}:\d{2}", cand)
                    ticket_line = m_ticket3.group(0) if m_ticket3 else cand

            for s in picked:
                if "(정기 휴관)" in s and "매주" in s:
                    closed_main = s
                    break
            if not closed_main:
                closed_main = _first_match_filtered(
                    ["(정기 휴관)"],
                    reject_exact={"휴관일", "휴관", "(정기 휴관)", "(대체 휴관)"},
                )
            if not closed_main:
                closed_main = _first_in_lines(["(정기 휴관)", "정기 휴관", "정기휴관"]).strip()

            # 라벨만 잡힌 경우(예: '(정기 휴관)')는 다음 줄까지 병합해 실제 문장 복구
            if closed_main.strip() in ("(정기 휴관)", "정기 휴관", "정기휴관") or (
                closed_main and ("매주" not in closed_main) and (not re.search(r"\d{1,2}\.\s*\d{1,2}", closed_main))
            ):
                rebuilt_closed = _rebuild_labeled_block_from_lines(re.compile(r"\(\s*정기\s*휴관\s*\)"))
                if rebuilt_closed and ("매주" in rebuilt_closed or re.search(r"\d{1,2}\.\s*\d{1,2}", rebuilt_closed)):
                    closed_main = rebuilt_closed

            alt_closed = _first_match_filtered(
                ["(대체 휴관)"],
                reject_exact={"휴관일", "휴관", "(정기 휴관)", "(대체 휴관)"},
            )
            if not alt_closed:
                alt_closed = _first_in_lines(["(대체 휴관)", "대체 휴관", "대체휴관"]).strip()

            if alt_closed.strip() in ("(대체 휴관)", "대체 휴관", "대체휴관") or (
                alt_closed and (not re.search(r"\d{1,2}\.\s*\d{1,2}", alt_closed))
            ):
                rebuilt_alt = _rebuild_labeled_block_from_lines(re.compile(r"\(\s*대체\s*휴관\s*\)"))
                if rebuilt_alt and re.search(r"\d{1,2}\.\s*\d{1,2}", rebuilt_alt):
                    alt_closed = rebuilt_alt
            extra_closed: list[str] = []
            for s in picked:
                if s in (closed_main, alt_closed):
                    continue
                if s.strip() in ("휴관일", "휴관", "(정기 휴관)", "(대체 휴관)"):
                    continue
                ss2 = (s or "").strip()
                if ss2.startswith("※"):
                    continue
                if any(x in ss2 for x in ["관공서의 공휴일", "국경일", "대체 휴관"]):
                    # 법령/정의 안내 문구는 요약에 불필요(정기/대체 라인에 이미 포함)
                    continue
                if any(x in s for x in ["휴관", "휴무"]):
                    extra_closed.append(s)
            extra_closed = extra_closed[:2]

            if picked:
                parts: list[str] = []
                # 현재 시각(한국시간) 기준 상태 안내
                now = None
                try:
                    now = datetime.now(ZoneInfo("Asia/Seoul")) if ZoneInfo else datetime.now()
                except Exception:
                    now = datetime.now()
                regular_ex = _parse_regular_monday_exceptions(closed_main or "")
                reg_specific_closed = _parse_specific_closed_days_from_regular_block(closed_main or "")
                alt_days = _parse_mmdd_tokens(alt_closed or "")

                today_is_closed = _is_closed_on(now, regular_ex, reg_specific_closed, alt_days)

                open_t, close_t = _parse_open_close(time_line or "")
                ticket_t = _parse_ampm_hhmm(ticket_line or "")

                status_line = ""
                if today_is_closed:
                    status_line = "오늘은 **휴관일**일 가능성이 높아요."
                elif open_t and close_t:
                    if now.time() < open_t:
                        status_line = f"오늘은 운영일이며, 지금은 **오픈 전**입니다. (오늘 {open_t.strftime('%H:%M')}부터 입장 가능)"
                    elif now.time() > close_t:
                        status_line = f"오늘은 운영일이지만, 지금은 **운영시간이 종료**되었습니다. 다음 운영일에 방문해 주세요. (오늘 {close_t.strftime('%H:%M')} 종료)"
                    else:
                        if ticket_t and (now.time() > ticket_t):
                            status_line = "오늘은 운영 중이지만, 현재 시각 기준으로 **발권 마감 시간이 지난 상태**일 수 있어요. 현장 상황에 따라 달라질 수 있으니 방문 전 확인을 권장합니다."
                        else:
                            status_line = "오늘은 운영일이며, 지금은 **운영 중**입니다."

                # 다음 운영일 계산
                next_open_dt: datetime | None = None
                if open_t and close_t:
                    if (not today_is_closed) and (now.time() <= close_t):
                        # 오늘 운영 중/오픈 전이면 오늘이 다음 운영일
                        next_open_dt = now.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
                        if now.time() > close_t:
                            next_open_dt = None
                    if next_open_dt is None:
                        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
                        for k in range(1, 15):
                            cand = base + timedelta(days=k)
                            if _is_closed_on(cand, regular_ex, reg_specific_closed, alt_days):
                                continue
                            next_open_dt = cand.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
                            break

                def _wk_ko(d: datetime) -> str:
                    ws = ["월", "화", "수", "목", "금", "토", "일"]
                    try:
                        return ws[int(d.weekday())]
                    except Exception:
                        return ""

                wants_next_open = any(k in t_ops for k in ["다음 운영", "다음 운영일", "다음 개관", "언제 열", "언제 여"])
                wants_hours_detail = any(k in t_ops for k in ["관람시간", "관람 시간", "운영시간", "운영 시간", "영업시간", "발권", "마감", "휴관", "휴무", "몇시", "몇 시", "폐관", "개관"])
                next_open_only = wants_next_open and (not wants_hours_detail)

                def _clean_time_line_for_display() -> str:
                    td = " ".join((time_line or "").split()).strip()
                    td = re.sub(r"^[\-\s]+", "", td)
                    td = re.sub(r"^\(\s*관람\s*시간\s*\)\s*", "", td)
                    td = re.sub(r"\s*※\s*발권\s*마감\s*[:：].*$", "", td).strip()
                    return td or (" ".join((time_line or "").split()).strip())

                def _clean_ticket_line_for_display() -> str:
                    tl2 = " ".join((ticket_line or "").split()).strip()
                    tl2 = re.sub(r"^[※*\-\s]*", "", tl2)
                    tl2 = re.sub(r"^발권\s*마감\s*[:：]?\s*", "", tl2)
                    return tl2

                if next_open_only:
                    parts.append("다음 운영일을 **운영안내 기준으로 계산**해서 알려드릴게요.")
                    # 현재 상태(다음 운영일 맥락에 맞춘 짧은 요약)
                    cur_state = ""
                    try:
                        if today_is_closed:
                            cur_state = "오늘은 휴관일로 보여요."
                        elif open_t and close_t:
                            if now.time() < open_t:
                                cur_state = "오늘은 운영일이지만 아직 오픈 전이에요."
                            elif now.time() > close_t:
                                cur_state = "오늘 운영시간은 이미 종료됐어요."
                            else:
                                cur_state = "지금은 운영 중이에요."
                    except Exception:
                        cur_state = ""
                    if cur_state:
                        parts.append(f"\n{cur_state}")
                    if next_open_dt is not None:
                        parts.append(
                            f"\n- **다음 운영일**: {next_open_dt.strftime('%Y-%m-%d')}({_wk_ko(next_open_dt)}) {next_open_dt.strftime('%H:%M')} 오픈"
                        )
                    else:
                        parts.append("\n- **다음 운영일**: 운영시간을 정확히 파악하지 못해 계산할 수 없습니다.")
                    if time_line:
                        parts.append(f"\n- **관람시간**: {_clean_time_line_for_display()}")
                    if ticket_line:
                        parts.append(f"- **발권 마감**: {_clean_ticket_line_for_display()}")
                    answer = "\n".join(parts).strip()
                else:
                    parts.append("국립과천과학관 **관람시간/휴관 안내**(이용안내 페이지 기준)입니다.")
                    if status_line:
                        parts.append(f"\n{status_line}")
                    if wants_next_open:
                        if next_open_dt is not None:
                            parts.append(
                                f"\n- **다음 운영일**: {next_open_dt.strftime('%Y-%m-%d')}({_wk_ko(next_open_dt)}) {next_open_dt.strftime('%H:%M')} 오픈"
                            )
                        else:
                            parts.append("\n- **다음 운영일**: 운영시간을 정확히 파악하지 못해 계산할 수 없습니다.")
                    if time_line:
                        parts.append(f"\n- **관람시간**: {_clean_time_line_for_display()}")
                    if ticket_line:
                        parts.append(f"- **발권 마감**: {_clean_ticket_line_for_display()}")
                    if closed_main:
                        cm = " ".join((closed_main or "").split()).strip()
                        cm = re.sub(r"^\(\s*정기\s*휴관\s*\)\s*", "", cm).strip()
                        if cm and cm not in ("(정기 휴관)", "정기 휴관", "정기휴관"):
                            parts.append(f"- **정기 휴관**: {cm}")
                    if alt_closed:
                        ac = " ".join((alt_closed or "").split()).strip()
                        ac = re.sub(r"^\(\s*대체\s*휴관\s*\)\s*", "", ac).strip()
                        if ac and ac not in ("(대체 휴관)", "대체 휴관", "대체휴관"):
                            parts.append(f"- **대체 휴관**: {ac}")
                    for s in extra_closed:
                        parts.append(f"- {s}")
                    answer = "\n".join(parts).strip()
            else:
                answer = "국립과천과학관 운영시간 정보를 이용안내 페이지에서 추출하지 못했습니다. 잠시 후 다시 시도해 주세요."

            display_answer = clean_assistant_display_text(answer)

            if hasattr(st, "chat_message"):
                with st.chat_message("assistant"):
                    st.markdown(escape_tildes(display_answer))
            else:
                st.markdown(f"**assistant**: {escape_tildes(display_answer)}")

            get_messages().append({
                "role": "assistant",
                "content": display_answer,
                "scope_area": "main_page",
                "intent": "other",
                "sources_blob": "",
                "image_blob": "",
            })
            persist_current_chat_session()
            rag_add("assistant", display_answer)
            return
        except Exception:
            pass

    # -----------------------------------------------------
    # (UI) 방문 가능 시간 질문(예: '내일 10시에 가면 돼?')은 즉시 판정
    # -----------------------------------------------------
    t_visit = (user_input or "").strip().lower()
    if any(k in t_visit for k in ["가면", "가도", "가도 돼", "가도되", "방문", "입장", "들어가", "가능"]) and (
        ("내일" in t_visit) or ("모레" in t_visit) or ("오늘" in t_visit) or re.search(r"\d{1,2}\s*월\s*\d{1,2}\s*일", t_visit)
    ) and (re.search(r"\b\d{1,2}\s*시(\s*\d{1,2}\s*분)?\b", t_visit) or re.search(r"\b\d{1,2}:\d{2}\b", t_visit)):
        try:
            from gnsm import tools as _tools
            guide_url = ""
            if getattr(_tools, "comp_scipia_ssot_url", None):
                guide_url = _tools.comp_scipia_ssot_url("이용안내") or ""
            if (not guide_url) and getattr(_tools, "MUSEUM_BASE_URL", None):
                guide_url = f"{_tools.MUSEUM_BASE_URL}/scipia/guide/totalGuide"

            raw_guide = _tools.fetch_sciencecenter_page(guide_url, timeout=15) if guide_url and getattr(_tools, "fetch_sciencecenter_page", None) else ""
            glines = [" ".join((ln or "").split()).strip() for ln in (raw_guide or "").splitlines() if (ln or "").strip()]

            from datetime import datetime, timedelta
            try:
                from zoneinfo import ZoneInfo
            except Exception:  # pragma: no cover
                ZoneInfo = None

            now = datetime.now(ZoneInfo("Asia/Seoul")) if ZoneInfo else datetime.now()

            # 날짜
            target_date = now.date()
            if "내일" in t_visit:
                target_date = (now + timedelta(days=1)).date()
            elif "모레" in t_visit:
                target_date = (now + timedelta(days=2)).date()

            m_md = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", t_visit)
            if m_md:
                mm = int(m_md.group(1))
                dd = int(m_md.group(2))
                try:
                    target_date = target_date.replace(month=mm, day=dd)
                except Exception:
                    # 잘못된 날짜면 선처리 포기(에이전트로 넘김)
                    target_date = None

            if target_date is not None:
                # 시간
                hh = None
                mm2 = 0
                m_hm = re.search(r"\b(\d{1,2})\s*시\s*(\d{1,2})?\s*분?\b", t_visit)
                if m_hm:
                    hh = int(m_hm.group(1))
                    mm2 = int(m_hm.group(2) or 0)
                else:
                    m_colon = re.search(r"\b(\d{1,2}):(\d{2})\b", t_visit)
                    if m_colon:
                        hh = int(m_colon.group(1))
                        mm2 = int(m_colon.group(2))

                # 운영시간/휴관 규칙
                time_line = next((s for s in glines if "(관람 시간)" in s), "")
                m_oc = re.search(r"(오전|오후)?\s*(\d{1,2}):(\d{2}).*~\s*(오전|오후)?\s*(\d{1,2}):(\d{2})", time_line)
                def _to_24(ampm: str | None, h: int) -> int:
                    a = (ampm or "").strip()
                    if a == "오후" and h < 12:
                        return h + 12
                    if a == "오전" and h == 12:
                        return 0
                    return h

                open_h = open_m = close_h = close_m = None
                if m_oc:
                    open_h = _to_24(m_oc.group(1), int(m_oc.group(2)))
                    open_m = int(m_oc.group(3))
                    close_h = _to_24(m_oc.group(4), int(m_oc.group(5)))
                    close_m = int(m_oc.group(6))

                regular_line = next((s for s in glines if "(정기 휴관)" in s), "")
                alt_line = next((s for s in glines if "(대체 휴관)" in s), "")
                # 정기휴관 예외(월요일인데도 운영): '단, 2. 16., 3.2., ... 제외'
                regular_ex = set()
                for mmx, ddx in re.findall(r"(\d{1,2})\.\s*(\d{1,2})", regular_line or ""):
                    regular_ex.add((int(mmx), int(ddx)))
                # 대체휴관(추가 휴관일)
                alt_days = set()
                for mmx, ddx in re.findall(r"(\d{1,2})\.\s*(\d{1,2})", alt_line or ""):
                    alt_days.add((int(mmx), int(ddx)))

                md = (target_date.month, target_date.day)
                is_closed = False
                if md in alt_days:
                    is_closed = True
                elif target_date.weekday() == 0 and (md not in regular_ex):
                    is_closed = True

                answer = ""
                if is_closed:
                    answer = f"{target_date.isoformat()} 방문 기준으로는 **휴관일**일 가능성이 높습니다. (이용안내 페이지 기준)"
                elif (open_h is not None) and (hh is not None):
                    after_open = (hh, mm2) >= (open_h, open_m or 0)
                    before_close = (hh, mm2) <= (close_h, close_m or 0)
                    if after_open and before_close:
                        answer = f"{target_date.isoformat()} {hh:02d}:{mm2:02d} 기준으로는 **방문 가능 시간대**입니다. (이용안내 페이지 기준)"
                    else:
                        answer = f"{target_date.isoformat()} {hh:02d}:{mm2:02d} 기준으로는 **운영시간 밖**입니다. 운영시간 내에 방문해 주세요. (이용안내 페이지 기준)"
                else:
                    answer = f"{target_date.isoformat()} 방문 가능 여부를 운영시간으로 판정하려면 관람시간 정보를 더 정확히 읽어야 합니다. 이용안내 페이지를 확인해 주세요."

                display_answer = clean_assistant_display_text(answer)
                merged = display_answer
                if guide_url:
                    merged = merged + "\n\n" + f"[출처] {guide_url}"

                if hasattr(st, "chat_message"):
                    with st.chat_message("assistant"):
                        st.markdown(escape_tildes(display_answer))
                        render_source_buttons(merged)
                else:
                    st.markdown(f"**assistant**: {escape_tildes(display_answer)}")
                    render_source_buttons(merged)

                get_messages().append({
                    "role": "assistant",
                    "content": display_answer,
                    "scope_area": "main_page",
                    "intent": "other",
                    "sources_blob": merged,
                    "image_blob": "",
                })
                persist_current_chat_session()
                rag_add("assistant", display_answer)
                return
        except Exception:
            pass

    # (K) 추천 의도인데 특정 키워드가 없으면 main_page
    if (st.session_state["last_intent"] == "recommend") and (scope_info.get("best_area") is None):
        st.session_state["last_scope_area"] = "main_page"

    # -----------------------------------------------------
    # (UX) 추천/탐색 질문은 관심 주제부터 좁히기
    # -----------------------------------------------------
    known_interest = get_interest_topic()
    if (st.session_state.get("last_intent") == "recommend") and (not known_interest):
        answer = _interest_topics_prompt_intro() + _interest_topics_prompt_list()
        display_answer = clean_assistant_display_text(answer)

        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                st.markdown(escape_tildes(display_answer))
                render_source_buttons(display_answer)
                render_inline_images(display_answer)
        else:
            st.markdown(f"**assistant**: {escape_tildes(display_answer)}")
            render_source_buttons(display_answer)
            render_inline_images(display_answer)

        get_messages().append({"role": "assistant", "content": display_answer})
        persist_current_chat_session()
        rag_add("assistant", display_answer)
        return

    # -----------------------------------------------------
    # (NLP) 최근 공지는 UI 레벨에서 선처리(빠른 요약)
    # 공지 특정 질문은 모두 에이전트로 전달 (상세 내용 크롤링)
    # notice_url_hint가 있으면 이 로직도 건너뜀
    # -----------------------------------------------------
    if (not notice_url_hint) and heuristics.looks_like_recent_notices_request(user_input) and (not heuristics.looks_like_notice_specific_inquiry(user_input)):
        st.session_state["last_scope_area"] = "main_page"
        st.session_state["last_intent"] = "other"

        kw = heuristics.extract_notice_search_keyword(user_input)
        if heuristics.looks_like_holiday_or_notice_request(user_input):
            kw = heuristics.extract_holiday_keyword(user_input) or kw

        raw_search = ""
        try:
            from gnsm import tools as _tools
            if getattr(_tools, "search_sciencecenter_notices", None):
                raw_search = _tools.search_sciencecenter_notices.invoke({"query": kw, "limit": 6})
        except Exception:
            raw_search = ""

        items = parse_sources_from_text(raw_search)
        try:
            st.session_state["recent_notice_items"] = list(items or [])
        except Exception:
            pass
        notice_urls: list[str] = []
        for it in (items or []):
            u = str(it.get("url") or "").strip()
            if u and ("/scipia/introduce/notice/" in u):
                notice_urls.append(u)
        notice_urls = notice_urls[:5]

        # 검색 결과가 빈 경우: 최근 공지 목록으로 fallback
        if not notice_urls:
            try:
                from gnsm import tools as _tools
                if getattr(_tools, "get_recent_sciencecenter_notices", None):
                    raw_recent = _tools.get_recent_sciencecenter_notices.invoke({"limit": 6})
                    items2 = parse_sources_from_text(raw_recent)
                    for it in (items2 or []):
                        u = str(it.get("url") or "").strip()
                        if u and ("/scipia/introduce/notice/" in u):
                            notice_urls.append(u)
                    notice_urls = notice_urls[:5]
                    if raw_recent:
                        raw_search = (raw_search or "") + "\n\n" + raw_recent
            except Exception:
                pass

        details_blob_parts: list[str] = []
        try:
            from gnsm import tools as _tools
            for u in notice_urls[:5]:
                if getattr(_tools, "get_sciencecenter_notice_page", None):
                    try:
                        details_blob_parts.append(_tools.get_sciencecenter_notice_page.invoke({"url": u}))
                    except Exception:
                        continue
        except Exception:
            pass

        context_blob = (raw_search or "")
        if details_blob_parts:
            context_blob = context_blob + "\n\n" + "\n\n---\n\n".join(details_blob_parts)

        sources_lines = []
        try:
            from gnsm import tools as _tools
            notice_list_url = ""
            if getattr(_tools, "comp_scipia_ssot_url", None):
                notice_list_url = _tools.comp_scipia_ssot_url("공지사항") or ""
            if notice_list_url:
                sources_lines.append(f"[출처] {notice_list_url}")
        except Exception:
            pass
        sources_blob = "\n".join(sources_lines).strip()

        answer = _summarize_notices_from_search(
            raw_search=raw_search,
            details_blob_parts=details_blob_parts,
            title_prefix="공지사항을 확인해 정리했습니다.",
        )

        display_answer = clean_assistant_display_text(answer)
        context_for_buttons = (context_blob or "")
        if context_for_buttons:
            context_for_buttons = "\n".join(
                ln for ln in context_for_buttons.splitlines() if not ln.strip().startswith("[출처")
            ).strip()

        merged = display_answer + "\n\n" + (context_for_buttons or "")
        if sources_blob:
            merged = merged + "\n\n" + sources_blob

        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                st.markdown(escape_tildes(display_answer))
                render_source_buttons(merged)
        else:
            st.markdown(f"**assistant**: {escape_tildes(display_answer)}")
            render_source_buttons(merged)

        get_messages().append({
            "role": "assistant",
            "content": display_answer,
            "scope_area": "main_page",
            "intent": "other",
            "sources_blob": (context_blob + "\n\n" + sources_blob).strip() if sources_blob else context_blob,
            "image_blob": "",
        })
        persist_current_chat_session()
        rag_add("assistant", display_answer)
        return

    if heuristics.looks_like_recent_notices_request(user_input):
        st.session_state["last_scope_area"] = "main_page"
        st.session_state["last_intent"] = "other"

        raw = ""
        try:
            from gnsm import tools as _tools
            if getattr(_tools, "get_recent_sciencecenter_notices", None):
                raw = _tools.get_recent_sciencecenter_notices.invoke({"limit": 6})
        except Exception:
            raw = ""

        items = parse_sources_from_text(raw)
        try:
            st.session_state["recent_notice_items"] = list(items or [])
        except Exception:
            pass
        notice_urls: list[str] = []
        for it in items:
            u = str(it.get("url") or "").strip()
            if u and ("/scipia/introduce/notice/" in u):
                notice_urls.append(u)
        notice_urls = notice_urls[:3]

        details_blob_parts: list[str] = []
        try:
            from gnsm import tools as _tools
            for u in notice_urls[:3]:
                if getattr(_tools, "get_sciencecenter_notice_page", None):
                    try:
                        details_blob_parts.append(_tools.get_sciencecenter_notice_page.invoke({"url": u}))
                    except Exception:
                        continue
        except Exception:
            pass

        context_blob = (raw or "")
        if details_blob_parts:
            context_blob = context_blob + "\n\n" + "\n\n---\n\n".join(details_blob_parts)

        sources_lines = []
        try:
            from gnsm import tools as _tools
            notice_list_url = ""
            if getattr(_tools, "comp_scipia_ssot_url", None):
                notice_list_url = _tools.comp_scipia_ssot_url("공지사항") or ""
            if notice_list_url:
                sources_lines.append(f"[출처] {notice_list_url}")
        except Exception:
            pass
        sources_blob = "\n".join(sources_lines).strip()

        print("=== DEBUG NOTICE (recent) ===")
        print("items len:", len(items or []))
        print("details_blob_parts len:", len(details_blob_parts or []))
        for i, blob in enumerate(details_blob_parts or []):
            print(f"\n[details_blob_parts[{i}]]")
            print(f"  type: {type(blob)}")
            s = blob if isinstance(blob, str) else str(blob)
            print(f"  length: {len(s)}")
            print(f"  preview(300): {s[:300]}")
            
            has_content = any(k in s for k in ["신청", "모집", "무료관람", "첨부파일", "조회수", "등록일", "작성자", "접수", "선착순", "대상자", "참가비", "문의처", "담당자", "연락처", "이메일", "세부내용", "상세안내"])
            has_noise = any(k in s for k in ["과학관소식", "고객서비스", "공지/공고 상세"])
            print(f"  has_content: {has_content}, has_noise: {has_noise}")
        print("====================")

        answer = build_notice_summary_answer(
            items=items,
            details_texts=details_blob_parts,
            title_prefix="최근 공지사항을 확인해 정리했습니다.",
        )

        display_answer = clean_assistant_display_text(answer)
        context_for_buttons = (context_blob or "")
        if context_for_buttons:
            context_for_buttons = "\n".join(
                ln for ln in context_for_buttons.splitlines() if not ln.strip().startswith("[출처")
            ).strip()

        merged = display_answer + "\n\n" + (context_for_buttons or "")
        if sources_blob:
            merged = merged + "\n\n" + sources_blob

        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                st.markdown(escape_tildes(display_answer))
                render_source_buttons(merged)
        else:
            st.markdown(f"**assistant**: {escape_tildes(display_answer)}")
            render_source_buttons(merged)

        get_messages().append({
            "role": "assistant",
            "content": display_answer,
            "scope_area": "main_page",
            "intent": "other",
            "sources_blob": (context_blob + "\n\n" + sources_blob).strip() if sources_blob else context_blob,
            "image_blob": "",
        })
        persist_current_chat_session()
        rag_add("assistant", display_answer)
        return

    # notice_url_hint가 있으면 기존 공지사항 매칭 로직 건너뛰기
    if notice_url_hint:
        recent_items = None
    else:
        try:
            recent_items = st.session_state.get("recent_notice_items")
        except Exception:
            recent_items = None

    if recent_items and isinstance(recent_items, list):
        t = " ".join((user_input or "").strip().split()).lower()
        best = None
        best_score = 0
        best_long_tok_hit = False
        for it in recent_items[:10]:
            try:
                title = str((it or {}).get("desc") or "").strip()
                url = str((it or {}).get("url") or "").strip()
            except Exception:
                continue
            if not title or not url:
                continue
            if "/scipia/introduce/notice/" not in url:
                continue

            tl = title.lower()
            score = 0
            if tl and (tl in t):
                score += 5
            # 제목 토큰 일부 매칭(너무 짧은 토큰은 제외)
            long_tok_hit = False
            for tok in [x for x in tl.replace("[", " ").replace("]", " ").split() if len(x) >= 2]:
                if tok in t:
                    score += 1
                    if len(tok) >= 3:
                        long_tok_hit = True
            if score > best_score:
                best_score = score
                best = {"title": title, "url": url}
                best_long_tok_hit = long_tok_hit

        if best and ((best_score >= 2) or (best_score >= 1 and best_long_tok_hit)):
            st.session_state["last_scope_area"] = "main_page"
            st.session_state["last_intent"] = "other"

            detail = ""
            try:
                from gnsm import tools as _tools
                if getattr(_tools, "get_sciencecenter_notice_page", None):
                    detail = _tools.get_sciencecenter_notice_page.invoke({"url": best["url"]})
            except Exception:
                detail = ""

            # 상세 크롤링 실패 시 timeout 증가로 1회 재시도
            if (not detail) or ("[크롤링 실패]" in str(detail)):
                try:
                    from gnsm import tools as _tools
                    if getattr(_tools, "fetch_sciencecenter_page", None):
                        txt = _tools.fetch_sciencecenter_page(best["url"], timeout=20)
                        if txt and ("[크롤링 실패]" not in str(txt)):
                            detail = "Observation:\n\n" + f"[출처] {best['url']}\n\n" + str(txt)
                except Exception:
                    pass

            answer = build_notice_summary_answer(
                items=[{"url": best["url"], "desc": best["title"], "label": "출처"}],
                details_texts=[detail] if detail else [],
                title_prefix=f"'{best['title']}' 공지 내용을 확인해 정리했습니다.",
            )
            display_answer = clean_assistant_display_text(answer)

            merged = display_answer
            try:
                from gnsm import tools as _tools
                notice_list_url = _tools.comp_scipia_ssot_url("공지사항") if getattr(_tools, "comp_scipia_ssot_url", None) else ""
            except Exception:
                notice_list_url = ""
            if notice_list_url:
                merged = merged + "\n\n" + f"[출처] {notice_list_url}"

            if hasattr(st, "chat_message"):
                with st.chat_message("assistant"):
                    st.markdown(escape_tildes(display_answer))
                    render_source_buttons(merged)
            else:
                st.markdown(f"**assistant**: {escape_tildes(display_answer)}")
                render_source_buttons(merged)

            get_messages().append({
                "role": "assistant",
                "content": display_answer,
                "scope_area": "main_page",
                "intent": "other",
                "sources_blob": merged,
                "image_blob": "",
            })
            persist_current_chat_session()
            rag_add("assistant", display_answer)
            return
    image_blob = ""
    if heuristics.looks_like_route_request(user_input):
        try:
            from gnsm import tools as _tools

            url = ""
            # 1) 전시관명이 있으면 SSOT
            try:
                hall = _tools.resolve_hall_label(user_input) if getattr(_tools, "resolve_hall_label", None) else ""
            except Exception:
                hall = ""
            if hall and getattr(_tools, "comp_scipia_ssot_url", None):
                try:
                    url = _tools.comp_scipia_ssot_url(hall)
                except Exception:
                    url = ""

            # 2) 없으면 스코프 area로 대표 페이지
            if not url:
                area = best_area or st.session_state.get("last_scope_area")
                if area == "planetarium" and getattr(_tools, "url_planetarium_intro", None):
                    url = _tools.url_planetarium_intro()
                elif area == "observatory" and getattr(_tools, "url_observatory_page", None):
                    url = _tools.url_observatory_page()
                elif area == "space_analog" and getattr(_tools, "url_space_analog_page", None):
                    url = _tools.url_space_analog_page()
                elif area == "star_road" and getattr(_tools, "url_star_road_exhibition", None):
                    url = _tools.url_star_road_exhibition()

            if url and getattr(_tools, "get_scipia_route_images", None):
                image_blob = _tools.get_scipia_route_images(url, limit=4)

            # hall 페이지에 동선 이미지가 없으면, 교통안내(지도)에서 한 번 더 시도
            if (not image_blob) and getattr(_tools, "comp_scipia_ssot_url", None) and getattr(_tools, "get_scipia_route_images", None):
                try:
                    loc_url = _tools.comp_scipia_ssot_url("교통안내")
                    image_blob = _tools.get_scipia_route_images(loc_url, limit=4)
                except Exception:
                    pass
        except Exception:
            image_blob = ""

    # -----------------------------------------------------
    # (L) 에이전트 호출
    # -----------------------------------------------------
    answer = ""
    sources_blob = ""

    # 언어 설정이 포함된 메시지 생성
    messages_with_lang = get_messages().copy()
    if language == "English" and messages_with_lang:
        # 마지막 사용자 메시지에 언어 설정 추가
        messages_with_lang[-1] = {
            **messages_with_lang[-1],
            "content": user_input_with_lang
        }
    
    messages_for_agent = build_messages_for_agent(messages_with_lang)

    if hasattr(st, "chat_message"):
        with st.chat_message("assistant"):
            with st.spinner("생각 중입니다..."):
                answer, sources_blob = invoke_agent_safely(agent, messages_for_agent)

            if saved_prefix:
                answer = saved_prefix + "\n\n" + (answer or "")

            display_answer = clean_assistant_display_text(answer)
            st.markdown(escape_tildes(display_answer))

            merged = display_answer + "\n\n" + (sources_blob or "") + "\n\n" + (image_blob or "")
            render_source_buttons(merged)
            render_inline_images(merged)
    else:
        answer, sources_blob = invoke_agent_safely(agent, messages_for_agent)
        if saved_prefix:
            answer = saved_prefix + "\n\n" + (answer or "")

        display_answer = clean_assistant_display_text(answer)
        st.markdown(f"**assistant**: {escape_tildes(display_answer)}")

        merged = display_answer + "\n\n" + (sources_blob or "") + "\n\n" + (image_blob or "")
        render_source_buttons(merged)
        render_inline_images(merged)

    # (M) 세션 저장
    final_display = display_answer if "display_answer" in locals() else clean_assistant_display_text(answer)

    get_messages().append({
        "role": "assistant",
        "content": final_display,
        "scope_area": "main_page",
        "intent": "other",
        "sources_blob": sources_blob or "",
        "image_blob": image_blob or "",
    })
    persist_current_chat_session()
    rag_add("assistant", final_display)
