"""gnsm.agent_runtime

이 파일은 LangGraph ReAct 에이전트를 생성하고 실행하는 런타임 로직을 담당합니다.

역할:
- tools.py의 @tool 들을 '안전하게' 로드(없으면 제외 + 경고)
- langchain_openai / langgraph 버전 차이를 최대한 방어
- agent.invoke 결과에서 최종 답변과 출처 blob을 분리

UI(Streamlit) 코드는 이 파일을 직접 건드리지 않고,
`ensure_agent()`/`invoke_agent_safely()` 같은 함수만 호출하도록 분리합니다.
"""

from __future__ import annotations

import os
import traceback
import uuid
from typing import Any, Optional

import streamlit as st

from gnsm.prompt import _get_system_prompt
from gnsm.text_parsing import collect_sources_blob_from_result
from gnsm import heuristics


# ---------------------------------------------------------
# 1) 패키지/버전 차이 대응 import
# ---------------------------------------------------------

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore

try:
    from langgraph.prebuilt import create_react_agent
except Exception:  # pragma: no cover
    create_react_agent = None  # type: ignore

try:
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover
    MemorySaver = None  # type: ignore


# ---------------------------------------------------------
# 2) 세션 키
# ---------------------------------------------------------

AGENT_KEY = "gnsm_agent"
THREAD_KEY = "gnsm_thread_id"
TOOLS_KEY = "gnsm_tools"


# ---------------------------------------------------------
# 3) tools.py 안전 로딩
# ---------------------------------------------------------

_TOOL_NAMES: list[str] = [
    "get_scipia_homepage",
    "get_scipia_navigation_links",
    "search_scipia_links",
    "get_scipia_page",
    "get_scipia_image_urls",
    "get_scipia_route_images",
    "get_hall_bundle_pages",
    "get_parking_guide_page",
    "get_paid_member_page",
    "get_group_tours_page",
    "get_recommend_course_page",
    "get_display_experience_page",
    "get_winter_exhibition_program_2026_page",
    "get_display_explanation_page",
    "get_sciencecenter_notice_page",
    "get_sciencecenter_faq",
    "get_sciencecenter_faq_entries",
    "search_sciencecenter_faq",
    "search_sciencecenter_notices",
    "get_recent_sciencecenter_notices",
    "get_planetarium_program_notice",
    "get_observatory_official_page",
    "get_space_analog_official_page",
    "get_planetarium_overview",
    "get_observatory_overview",
    "get_space_analog_overview",
    "get_astronomy_hall_overview",
    "get_astronomy_hall_outdoor_layout_guide",
    "get_planetarium_route_guide",
    "get_observatory_route_guide",
    "get_space_analog_route_guide",
    "get_planetarium_operation_info",
    "get_planetarium_opening_hours",
    "get_planetarium_program_list",
    "get_planetarium_programs_by_date",
    "recommend_planetarium_programs_by_age",
    "get_planetarium_exhibition_info",
    "get_star_road_exhibition_info",
    "get_planetarium_group_program_info",
    "get_planetarium_facility_info",
    "get_planetarium_floor_guide",
    "get_planetarium_seat_info",
    "get_planetarium_reservation_info",
    "get_planetarium_visit_tips",
    "get_planetarium_viewing_rules",
    "get_planetarium_booking_and_refund_rules",
    "get_planetarium_fee_info",
    "get_planetarium_program_catalog",
    "get_planetarium_daily_schedule",
    "get_planetarium_schedule",
    "get_planetarium_program_and_schedule",
    "get_observatory_location_info",
    "get_observatory_facility_info",
    "get_observatory_program_list",
    "get_observatory_program_catalog",
    "get_observatory_program_info",
    "get_observatory_program_detail_info",
    "get_observatory_booking_rules",
    "get_observatory_daytime_program_info",
    "get_observatory_nighttime_program_info",
    "get_observatory_radio_program_info",
    "recommend_observatory_programs_by_age",
    "get_observatory_reservation_info",
    "get_observatory_weather_policy",
    "get_observatory_safety_info",
    "get_observatory_accessibility_info",
    "get_observatory_group_visit_info",
    "get_observatory_group_program_info",
    "get_space_analog_info",
    "get_space_analog_zone_info",
    "get_space_analog_program_info",
    "get_space_analog_program_catalog",
    "get_space_analog_fee_and_age_info",
    "get_space_analog_course_list",
    "get_space_analog_booking_info",
    "recommend_space_analog_programs_by_age",
    "get_space_analog_safety_info",
    "get_space_analog_reservation_info",
    "get_space_analog_group_program_info",
    "get_space_analog_visit_tips",
]


def _load_tools_safely() -> list[Any]:
    """gnsm.tools에서 툴을 안전하게 로드합니다."""
    try:
        from gnsm import tools as tools_module
    except Exception as e:
        st.error(
            "gnsm.tools를 불러오지 못했습니다. (파일 문법 오류/의존성 오류 가능)\n\n" + f"오류: {e}"
        )
        st.code(traceback.format_exc())
        return []

    loaded: list[Any] = []
    missing: list[str] = []

    for name in _TOOL_NAMES:
        obj = getattr(tools_module, name, None)
        if obj is None:
            missing.append(name)
            continue
        loaded.append(obj)

    if missing:
        st.warning("일부 툴을 tools.py에서 찾지 못해 제외했습니다.\n" + "\n".join([f"- {m}" for m in missing]))

    if not loaded:
        st.error("사용 가능한 도구가 0개입니다. tools.py의 @tool 정의를 확인해 주세요.")

    return loaded


def _ensure_tools() -> list[Any]:
    if TOOLS_KEY not in st.session_state:
        st.session_state[TOOLS_KEY] = _load_tools_safely()
    return st.session_state[TOOLS_KEY]


# ---------------------------------------------------------
# 4) 에이전트 생성
# ---------------------------------------------------------

def _ensure_thread_id() -> str:
    if THREAD_KEY not in st.session_state:
        st.session_state[THREAD_KEY] = f"gnsm-{uuid.uuid4().hex}"
    return st.session_state[THREAD_KEY]


def _agent_config() -> dict[str, Any]:
    return {"configurable": {"thread_id": _ensure_thread_id()}}


def _build_llm() -> Optional[Any]:
    if ChatOpenAI is None:
        st.error("langchain_openai를 불러오지 못했습니다. 패키지 설치를 확인해 주세요.")
        return None

    if not os.getenv("OPENAI_API_KEY"):
        st.error(
            "OPENAI_API_KEY가 설정되어 있지 않습니다.\n\n"
            "Windows PowerShell 예시:\n"
            "$env:OPENAI_API_KEY='YOUR_KEY'\n\n"
            "macOS/Linux 예시:\n"
            "export OPENAI_API_KEY='YOUR_KEY'"
        )
        return None

    return ChatOpenAI(model="gpt-4.1-mini", temperature=0.2)


def ensure_agent() -> Optional[Any]:
    """세션에 에이전트를 한 번만 생성하고 반환합니다."""
    if AGENT_KEY in st.session_state:
        return st.session_state.get(AGENT_KEY)

    if create_react_agent is None or MemorySaver is None:
        st.error("langgraph를 불러오지 못했습니다. langgraph 설치/버전을 확인해 주세요.")
        return None

    tools_list = _ensure_tools()
    llm = _build_llm()
    if llm is None:
        return None

    memory = MemorySaver()

    agent = None
    last_err: Optional[Exception] = None

    # 1) prompt 인자를 받는 버전
    try:
        agent = create_react_agent(
            model=llm,
            tools=tools_list,
            prompt=_get_system_prompt(),
            checkpointer=memory,
        )
    except TypeError as e:
        last_err = e

    # 2) prompt 인자를 못 받는 버전
    if agent is None:
        try:
            agent = create_react_agent(
                model=llm,
                tools=tools_list,
                checkpointer=memory,
            )
        except Exception as e:
            last_err = e

    if agent is None:
        st.error("ReAct 에이전트 생성에 실패했습니다. (langgraph 버전/시그니처 확인 필요)")
        if last_err:
            st.code(str(last_err))
        return None

    st.session_state[AGENT_KEY] = agent
    return agent


# ---------------------------------------------------------
# 5) 에이전트 호출(방어 + 출처 blob 수집)
# ---------------------------------------------------------

def _format_runtime_error(e: Exception) -> str:
    return (
        "죄송합니다. 일시적인 오류가 발생했습니다.\n\n"
        "아래 내용을 확인해 주세요:\n"
        "- OPENAI_API_KEY 설정 여부\n"
        "- langgraph/langchain_openai 버전 호환\n"
        "- gnsm.tools 문법 오류 또는 누락된 툴 이름\n\n"
        f"오류: `{e}`"
    )


def invoke_agent_safely(agent: Any, messages: list[dict[str, str]]) -> tuple[str, str]:
    """agent.invoke 버전 차이/응답 형태 차이를 최대한 방어합니다."""

    def _do_invoke(msgs: list[dict[str, str]]) -> Any:
        try:
            payload = {"messages": msgs}
            return agent.invoke(payload, config=_agent_config())
        except TypeError:
            return agent.invoke({"messages": msgs}, _agent_config())

    def _looks_like_tool_message_mismatch(err: Exception) -> bool:
        # OpenAI 계열(및 일부 provider)에서 tool_calls가 있는 assistant 메시지 다음에는
        # 반드시 대응되는 tool 메시지가 필요합니다. 이전 실행이 중간에 끊기면 이 불일치가 남아
        # 다음 호출에서 아래와 같은 오류가 날 수 있습니다.
        # "Found AIMessages with tool_calls that do not have a corresponding ToolMessage"
        s = str(err)
        s_low = s.lower()
        return (
            ("toolmessage" in s_low and "corresponding" in s_low)
            or ("do not have a corresponding toolmessage" in s_low)
            or ("found aimessages" in s_low and "tool_calls" in s_low)
        )

    try:
        result = _do_invoke(messages)
    except Exception as e:
        # (자가 복구) 이전 실행에서 tool_calls/ToolMessage 불일치가 남은 경우
        # thread_id + agent(checkpointer 포함)을 리셋하고 1회 재시도합니다.
        if _looks_like_tool_message_mismatch(e):
            try:
                st.session_state.pop(AGENT_KEY, None)
                st.session_state.pop(THREAD_KEY, None)
                agent2 = ensure_agent()
                if agent2 is not None:
                    agent = agent2
                    result = _do_invoke(messages)
                else:
                    return _format_runtime_error(e), ""
            except Exception as e2:
                return _format_runtime_error(e2), ""
        else:
            return _format_runtime_error(e), ""

    sources_blob = collect_sources_blob_from_result(result)

    # 중요 질문인데 출처가 비어있으면 1회 재시도(도구 사용 강제)
    user_text = ""
    try:
        user_text = str(st.session_state.get("messages", [])[-1].get("content", ""))
    except Exception:
        user_text = ""

    holiday_needs_notice = heuristics.looks_like_holiday_or_notice_request(user_text)
    recent_notices_request = heuristics.looks_like_recent_notices_request(user_text)
    has_notice_url = ("/scipia/introduce/notice/" in (sources_blob or ""))

    if (
        (st.session_state.get("last_intent") != "recommend")
        and (
            ((not sources_blob) and heuristics.looks_like_fact_or_ops_request(user_text))
            or (holiday_needs_notice and (not has_notice_url))
            or (recent_notices_request and (not has_notice_url))
        )
    ):
        holiday_kw = ""
        try:
            holiday_kw = heuristics.extract_holiday_keyword(user_text)
        except Exception:
            holiday_kw = ""
        if not holiday_kw:
            holiday_kw = "운영"

        forced_system = {
            "role": "system",
            "content": (
                "중요: 이번 질문은 사실 확인이 필요합니다. 반드시 scipia 공식 페이지를 확인하는 도구를 최소 1회 사용하고, "
                + (
                    f"공휴일/연휴/휴관/운영 안내 관련이면 search_sciencecenter_notices(query=\"{holiday_kw or '운영'}\")로 공지 목록에서 먼저 찾고, "
                    "매칭된 공지 URL을 get_sciencecenter_notice_page로 열어 확인하세요. "
                    if heuristics.looks_like_holiday_or_notice_request(user_text)
                    else ""
                )
                + (
                    "최근/최신 공지사항 요청이면 get_recent_sciencecenter_notices(limit=6)로 공지 목록을 먼저 확인하고, "
                    "필요하면 중요한 공지 URL을 get_sciencecenter_notice_page로 열어 확인하세요. "
                    if heuristics.looks_like_recent_notices_request(user_text)
                    else ""
                )
                + "도구로 확인되지 않으면 추측하지 말고, 확인 질문 또는 확인 가능한 공식 URL 안내만 하세요."
            ),
        }

        try:
            forced_msgs: list[dict[str, str]] = []
            inserted = False
            for m in messages:
                forced_msgs.append(m)
                if (not inserted) and (m.get("role") == "system"):
                    forced_msgs.append(forced_system)
                    inserted = True
            if not inserted:
                forced_msgs.insert(0, forced_system)

            result = _do_invoke(forced_msgs)
            sources_blob = collect_sources_blob_from_result(result)
        except Exception:
            pass

    # 마지막 메시지를 최종 답변으로 가정
    try:
        msgs2 = result.get("messages", None) if isinstance(result, dict) else None
        if msgs2:
            last = msgs2[-1]
            if hasattr(last, "content"):
                return str(last.content), sources_blob
            if isinstance(last, dict) and "content" in last:
                return str(last["content"]), sources_blob
            return str(last), sources_blob
    except Exception:
        pass

    return str(result), sources_blob
