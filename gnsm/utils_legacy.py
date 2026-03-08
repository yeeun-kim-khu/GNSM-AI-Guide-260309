# utils.py
# 국립과천과학관 전용
# Streamlit + LangGraph ReAct 에이전트 + MemorySaver
# 목표: "툴 프롬프트 길게(도구 docstring) + Observation은 짧은 팩트 카드" 운영에 최적화
# + Streamlit 구동 시 import/버전 차이로 최대한 안 터지게 방어

from __future__ import annotations

from typing import List, Dict, Any, Optional
import os
import uuid
import traceback
import math
import requests

import streamlit as st

import re
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

def _today_kst_str() -> str:
    """KST(Asia/Seoul) 기준 오늘 날짜(YYYY-MM-DD)를 반환합니다."""
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    # fallback: 시스템 로컬 시간(최소한 비어있지 않게)
    return datetime.now().strftime("%Y-%m-%d")

def _escape_tildes(text: str) -> str:
    """마크다운 취소선(~~) 방지를 위해 ~ 를 이스케이프합니다."""
    if not text:
        return text
    return text.replace("~", r"\~")


def _parse_sources_from_text(text: str) -> list[dict]:
    """
    답변 텍스트에서 출처 URL과(가능하면) 출처 설명을 추출합니다.

    인식 패턴:
    - [출처] <URL>
    - [출처-1] <URL>
    - [출처-1-설명] <설명 텍스트>
    """
    sources: list[dict] = []
    if not text:
        return sources

    url_lines = re.findall(r"\[출처(?:-\d+)?\]\s*(https?://\S+)", text)
    # 설명 라인: [출처-1-설명] ... 형태
    desc_pairs = re.findall(r"\[(출처-\d+)-설명\]\s*(.+)", text)
    desc_map = {k: v.strip() for k, v in desc_pairs}

    # [출처]는 key를 '출처'로, [출처-1]은 '출처-1'로 맞춘다
    labeled_urls = re.findall(r"\[(출처(?:-\d+)?)\]\s*(https?://\S+)", text)
    seen = set()
    for label, url in labeled_urls:
        url = url.strip().rstrip(").,]}\"")
        if url in seen:
            continue
        seen.add(url)
        sources.append({
            "label": label,
            "url": url,
            "desc": desc_map.get(label, ""),
        })
    # fallback: labeled_urls 없는데 url_lines만 잡힌 경우
    if not sources and url_lines:
        for url in url_lines:
            url = url.strip().rstrip(").,]}\"")
            if url in seen:
                continue
            seen.add(url)
            sources.append({"label": "출처", "url": url, "desc": ""})
    return sources


def _parse_image_urls_from_text(text: str) -> list[dict]:
    imgs: list[dict] = []
    if not text:
        return imgs

    desc_pairs = re.findall(r"\[(이미지-\d+)-설명\]\s*(.+)", text)
    desc_map = {k: v.strip() for k, v in desc_pairs}
    labeled_urls = re.findall(r"\[(이미지-\d+)\]\s*(https?://\S+)", text)
    seen = set()
    for label, url in labeled_urls:
        url = (url or "").strip().rstrip(").,]}\"")
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        imgs.append({
            "label": label,
            "url": url,
            "desc": desc_map.get(label, ""),
        })
    return imgs


RAG_STORE_KEY = "gnsm_rag_store"
INTEREST_TOPIC_KEY = "gnsm_interest_topic"
HALL_LOCATION_NOTES_KEY = "gnsm_hall_location_notes"


def _resolve_interest_topic(user_text: str) -> str:
    """사용자 입력에서 '관심 주제'를 추출합니다(전시관명 대신 주제).

    예: '곤충' -> '곤충/생태'
    """
    t = (user_text or "").strip().lower()
    if not t:
        return ""

    direct = {
        "첨단기술": "첨단기술",
        "미래과학": "미래과학",
        "천문우주": "천문우주",
        "동물/자연": "동물/자연",
        "공룡": "공룡",
        "곤충/생태": "곤충/생태",
        "유아/어린이": "유아/어린이",
        "전시해설": "전시해설",
        "행사/공연": "행사/공연",
    }
    if t in {k.lower() for k in direct.keys()}:
        for k, v in direct.items():
            if k.lower() == t:
                return v

    # 느슨한 매칭(짧은 단어 입력 대응)
    if any(k in t for k in ["ai", "인공지능", "로봇", "vr", "ar", "메타버스", "첨단", "기술"]):
        return "첨단기술"
    if any(k in t for k in ["미래", "sf", "사이파이", "sci-fi"]):
        return "미래과학"
    if any(k in t for k in ["천문", "우주", "별", "망원경", "관측", "행성", "달"]):
        return "천문우주"
    if any(k in t for k in ["곤충", "나비", "벌레", "생태", "식물"]):
        return "곤충/생태"
    if any(k in t for k in ["공룡", "티라노", "쥬라기"]):
        return "공룡"
    if any(k in t for k in ["동물", "자연", "자연사", "화석"]):
        return "동물/자연"
    if any(k in t for k in ["유아", "어린이", "아이", "유치원", "초등"]):
        return "유아/어린이"
    if any(k in t for k in ["해설", "도슨트", "설명"]):
        return "전시해설"
    if any(k in t for k in ["행사", "이벤트", "공연", "강연", "세미나"]):
        return "행사/공연"
    return ""


def _get_interest_topic() -> str:
    return str(st.session_state.get(INTEREST_TOPIC_KEY) or "").strip()


def _set_interest_topic(topic: str) -> None:
    topic = (topic or "").strip()
    if topic:
        st.session_state[INTEREST_TOPIC_KEY] = topic


def _get_hall_location_notes() -> dict[str, str]:
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


def _set_hall_location_note(hall_label: str, note: str) -> None:
    hall = (hall_label or "").strip()
    n = (note or "").strip()
    if not hall or not n:
        return
    notes = _get_hall_location_notes()
    notes[hall] = n
    st.session_state[HALL_LOCATION_NOTES_KEY] = notes


def _maybe_capture_hall_location_note(user_text: str) -> str:
    t = (user_text or "").strip()
    if not t:
        return ""

    # 너무 일반적인 '오시는 길/가는 길/동선' 질의는 위치 메모로 취급하지 않음
    if _looks_like_route_request(t) and ("위치" not in t):
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
                try:
                    from gnsm import tools as _tools
                    hall = _tools.resolve_hall_label(hall_guess) if getattr(_tools, "resolve_hall_label", None) else ""
                except Exception:
                    hall = ""
                if hall and note:
                    _set_hall_location_note(hall, note)
                    return hall
        return ""

    # 자연어 형태: "자연사관 위치는 1층 ..." 같은 입력
    if "위치" in t:
        try:
            from gnsm import tools as _tools
            hall = _tools.resolve_hall_label(t) if getattr(_tools, "resolve_hall_label", None) else ""
        except Exception:
            hall = ""
        if hall:
            m = re.search(r"위치(?:는|은|:|：)?\s*(.+)$", t)
            note = (m.group(1) if m else "").strip()
            if note and len(note) >= 3:
                _set_hall_location_note(hall, note)
                return hall

    return ""


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


def _ensure_rag_store() -> list[dict[str, Any]]:
    if RAG_STORE_KEY not in st.session_state:
        st.session_state[RAG_STORE_KEY] = []
    return st.session_state[RAG_STORE_KEY]


def _rag_add(role: str, text: str) -> None:
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


def _rag_context_text_for(query: str, k: int = 4) -> str:
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


# 기본 출처(답변에 링크가 없더라도, 매 답변마다 최소 1~3개 버튼을 제공)
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

def _render_source_buttons(answer_text: str) -> None:
    """assistant 답변 아래에 출처 링크 버튼을 항상 렌더링합니다."""
    sources = _parse_sources_from_text(answer_text)

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

        # URL 패턴 fallback
        if u.endswith("/scipia") or u.endswith("/scipia/") or "/scipia" in u and u.endswith("/scipia"):
            return "🏠"
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

    # ✅ URL → 주제 라벨(SSOT) 매핑: 버튼명이 '홈페이지'로 뭉개지는 문제를 완화
    url_to_label: dict[str, str] = {}
    try:
        from gnsm import tools as _tools_module

        if hasattr(_tools_module, "comp_scipia_ssot_urls"):
            ssot = _tools_module.comp_scipia_ssot_urls()
            for k, v in (ssot or {}).items():
                if v:
                    url_to_label[str(v).strip()] = str(k).strip()

        # scipia 메인도 '홈페이지'로 취급
        url_to_label["https://www.sciencecenter.go.kr/scipia"] = "홈페이지"
        url_to_label["https://www.sciencecenter.go.kr/scipia/"] = "홈페이지"
    except Exception:
        url_to_label = {}

    # ✅ 추천(탐색) 응답은 과학관 메인 페이지 1개만 기본 제공
    if st.session_state.get("last_intent") == "recommend":
        sources = [{
            "label": "홈페이지",
            "url": "https://www.sciencecenter.go.kr/scipia/",
            "desc": "홈페이지 살펴보기",
        }]

    if st.session_state.get("last_intent") != "recommend":
        last_area = st.session_state.get("last_scope_area")
        related = list(DEFAULT_SOURCE_URLS_BY_AREA.get(last_area, []) or [])
        if related:
            sources = list(sources or []) + related

        deduped: list[dict] = []
        seen_urls = set()
        for s in (sources or []):
            try:
                u = _normalize_url(str((s or {}).get("url") or ""))
            except Exception:
                u = ""
            if not u:
                continue
            if u in seen_urls:
                continue
            seen_urls.add(u)
            deduped.append(s)
        sources = deduped

    # ✅ 매 답변 기본 포함: 답변 텍스트에 링크가 없으면, 마지막 스코프에 맞는 기본 출처를 붙인다.
    if not sources:
        last_area = st.session_state.get("last_scope_area")  # planetarium/observatory/space_analog/star_road/main_page
        if last_area and last_area in DEFAULT_SOURCE_URLS_BY_AREA:
            sources = list(DEFAULT_SOURCE_URLS_BY_AREA[last_area])
        else:
            # 최소 1개는 제공(범위 밖 질문도 있을 수 있어, 관람안내 페이지로 fallback)
            sources = list(DEFAULT_SOURCE_URLS_BY_AREA["main_page"])

    # 렌더: 섹션 구분선/헤더 없이, 답변 마지막에 한 줄 띄우고 안내 문구만 붙인다.
    st.markdown("")  # 한 줄 띄움

    cols = st.columns(min(3, len(sources)))
    for i, s in enumerate(sources):
        url = (s.get("url", "") or "").strip()
        if not url:
            continue
        desc = (s.get("desc") or "").strip()

        # 버튼 텍스트 우선순위:
        # 1) 명시 desc
        # 2) SSOT 라벨(주차안내/연간회원/단체관람...)
        # 3) 파싱된 label (출처/출처-1)
        # 4) fallback
        ssot_label = url_to_label.get(url, "")
        normalized = _normalize_url(url)

        # scipia 메인/홈페이지 링크는 버튼명을 자연스럽게 강제
        if normalized in ("https://www.sciencecenter.go.kr/scipia", "https://www.sciencecenter.go.kr"):
            ssot_label = "홈페이지"
            btn_text = "홈페이지 살펴보기"
        else:
            btn_text = desc or ssot_label or (s.get("label") or "") or "홈페이지 살펴보기"

        emoji = _emoji_for_source(ssot_label, url)
        if emoji:
            btn_text = f"{emoji} {btn_text}"
        with cols[i % len(cols)]:
            if hasattr(st, "link_button"):
                st.link_button(btn_text, url)
            else:
                st.markdown(f"🔗 [{btn_text}]({url})")


def _render_inline_images(answer_text: str) -> None:
    imgs = _parse_image_urls_from_text(answer_text)
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


def _strip_inline_image_lines(text: str) -> str:
    t = text or ""
    if not t:
        return t
    lines = t.splitlines()
    kept: list[str] = []
    for ln in lines:
        s = (ln or "").strip()
        if not s:
            kept.append(ln)
            continue
        if s.startswith("[이미지-"):
            continue
        if s.startswith("[출처"):
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


def _strip_urls_from_text(text: str) -> str:
    t = text or ""
    if not t:
        return t
    try:
        # 1) Markdown 링크: [텍스트](URL)
        t = re.sub(r"\[[^\]]+\]\((https?://[^\s\)]+)\)", "", t)
        # 2) Raw URL
        t = re.sub(r"https?://[^\s\)\]\}>\"']+", "", t)
        # 2-1) URL 제거 후 남는 링크 안내 문구 라인 제거
        t = re.sub(r"(?im)^\s*(자세히\s*보기|자세히보기|링크|url|바로\s*가기)\s*[:：]\s*$", "", t)
        t = re.sub(r"(?im)^\s*(자세히\s*보기|자세히보기|링크|url|바로\s*가기)\s*$", "", t)
        # 3) 괄호만 남는 케이스 정리
        t = re.sub(r"\(\s*\)", "", t)
        # 4) 과도한 공백 정리
        t = re.sub(r"[ \t]{2,}", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
    except Exception:
        return (text or "")
    return t.strip()


def _clean_assistant_display_text(text: str) -> str:
    # 이미지/출처 라인 제거 -> URL 제거 (버튼만 사용)
    return _strip_urls_from_text(_strip_inline_image_lines(text or ""))


def _pick_notice_snippet(detail_text: str, max_lines: int = 2) -> str:
    t = detail_text or ""
    if not t:
        return ""
    lines = [ln.strip() for ln in t.splitlines()]
    picked: list[str] = []
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("Observation"):
            continue
        if ln.startswith("[출처"):
            continue
        if "sciencecenter.go.kr" in ln:
            continue
        if ln in ("공지사항", "공지", "국립과천과학관"):
            continue
        if len(ln) < 8:
            continue
        picked.append(ln)
        if len(picked) >= max(1, int(max_lines)):
            break
    return " ".join(picked).strip()


def _build_notice_summary_answer(items: list[dict], details_texts: list[str], title_prefix: str) -> str:
    url_to_title: dict[str, str] = {}
    titles_only: list[str] = []
    for it in (items or []):
        u = str(it.get("url") or "").strip()
        d = str(it.get("desc") or "").strip()
        if u and d and u not in url_to_title:
            url_to_title[u] = d
        if d:
            titles_only.append(d)

    summaries: list[str] = []
    for dt in (details_texts or [])[:6]:
        # detail_text에는 [출처] URL 라인이 포함되어 있으므로 거기서 url을 잡아 제목 매핑
        m = re.search(r"\[출처\]\s*(https?://\S+)", dt)
        url = (m.group(1).strip().rstrip(").,]}\"") if m else "")
        title = url_to_title.get(url, "")
        snippet = _pick_notice_snippet(dt, max_lines=2)
        if title and snippet:
            summaries.append(f"- {title}\n  - {snippet}")
        elif title:
            summaries.append(f"- {title}")
        elif snippet:
            summaries.append(f"- {snippet}")

    if summaries:
        return (title_prefix or "공지사항 요약") + "\n\n" + "\n".join(summaries)
    if titles_only:
        uniq: list[str] = []
        seen = set()
        for t in titles_only:
            tt = " ".join((t or "").split())
            if not tt:
                continue
            if tt in seen:
                continue
            seen.add(tt)
            uniq.append(tt)
        uniq = uniq[:6]
        return (title_prefix or "공지사항 요약") + "\n\n" + "\n".join([f"- {t}" for t in uniq])
    return (title_prefix or "공지사항 요약") + "\n\n" + "공지사항을 불러왔지만 요약할 핵심 문장을 추출하지 못했습니다. 버튼에서 확인해 주세요."
# ---------------------------------------------------------
# 1) LLM 준비 (API KEY 없으면 앱이 바로 죽지 않도록 안내)
# ---------------------------------------------------------
try:
    from langchain_openai import ChatOpenAI
except Exception as e:  # pragma: no cover
    ChatOpenAI = None  # type: ignore


# ---------------------------------------------------------
# 2) LangGraph 준비 (버전 차이 대응)
# ---------------------------------------------------------
try:
    from langgraph.prebuilt import create_react_agent
except Exception as e:  # pragma: no cover
    create_react_agent = None  # type: ignore

try:
    from langgraph.checkpoint.memory import MemorySaver
except Exception as e:  # pragma: no cover
    MemorySaver = None  # type: ignore


# ---------------------------------------------------------
# 3) 시스템 프롬프트 (팩트 카드 사용 규칙 강화)
# ---------------------------------------------------------
SYSTEM_PROMPT_GNSM = """
당신은 국립과천과학관 전관(모든 운영/프로그램/행사/공간) 안내자입니다.
공식 기준 사이트: https://www.sciencecenter.go.kr/scipia/

[목표]
- 관람객/직원의 질문에 친절하고 정확하게 안내합니다.
- 운영 정보(요금/연령/회차/좌석/예약·환불/위치/이용 흐름)는 혼동 없이 전달합니다.

[범위]
- 이 앱은 전관 안내를 목표로 하지만, 답변의 확정 근거는 반드시 scipia 공식 페이지(크롤링/도구 결과)에서 가져옵니다.
- 사용자가 질문한 주제가 불명확하면(어느 전시관/어느 프로그램인지), 1개의 확인 질문으로 범위를 먼저 좁힙니다.

[크롤링/도구 사용]
- ‘운영/예약/요금/시간표/회차/운영 여부/위치·동선/이용 규정/행사 일정’처럼 사실 확인이 필요한 질문은,
  답변 전에 공식 scipia 페이지를 확인하는 도구를 우선 사용합니다.
- 전관 탐색이 필요하면 다음 순서를 권장합니다.
  1) get_scipia_homepage
  2) get_scipia_navigation_links 또는 search_scipia_links
  3) get_scipia_page(찾은 URL의 본문 확인)

[사실·운영 정보 원칙]
- 운영 관련 수치/규정(나이, 요금, 시간, 좌석, 예약/환불, 운영 여부)은 반드시 ‘도구 결과(Observation)’에 근거해 안내합니다.
- 도구에 없는 내용은 추측하지 말고, “공식 scipia 최신 안내를 확인해 달라” 또는 “확인 가능한 공식 URL을 안내하겠다”고 응답합니다.
- 숫자나 규정을 새로 만들어내지 않습니다.

[전시관/공간 관계(소속/포함/위치) 금지 규칙]
- “A가 B 안에 있다/소속이다/몇 층이다/어느 건물이다/바로 옆이다”처럼 구조·위치 관계를 단정하지 않습니다.
- 이런 관계는 반드시 scipia 페이지를 도구로 확인한 Observation에 해당 문구/근거가 있을 때만 말합니다.
- Observation에서 명시적으로 확인되지 않으면, “공식 페이지에서 확인이 필요하다”로 답하고 확인 가능한 URL을 안내합니다.

[동선(어떻게 가요?) 응답 UX]
- 동선/방문경로는 추측하지 않습니다. 반드시 scipia 페이지(텍스트/지도/동선 이미지)에서 확인된 근거로만 구체적으로 안내합니다.
- 해당 전시관 페이지에 동선 근거가 없으면 “공식 페이지에 동선 안내가 없어 확인이 필요하다”고 말하고,
  출발지(지하철/주차/동문/서문 등) 1가지만 확인 질문을 합니다.
- 가능하면 scipia의 ‘지도/동선 이미지’를 함께 제공하고, 이미지를 기준으로 안내합니다.

[도구 결과 사용 방식]
- 도구 결과를 그대로 길게 복사하지 말고, 질문에 필요한 핵심만 요약해 자연스럽게 설명합니다.
- 필요 시 여러 도구를 조합해 확인한 뒤 답합니다.

[추천/맞춤 상담 규칙: 최소 질문 → 조건부 확인]
사용자가 “추천/아이랑/인기/재미있는/뭐가 좋아?”처럼 맞춤형 안내를 요청하면,
한 번에 여러 질문을 몰아서 하지 말고 ‘필요한 것만’ 조건부로 확인합니다.

- **단체/개인**: 개인/단체에 따라 안내(예약 방식/인원/주의사항)가 달라질 때만 질문
- **연령**: 대상/연령 제한이 프로그램 선택에 영향을 줄 때만 질문
  - “아이/어린이/유치원생/초등학생/학생”처럼 범주만 말하면 연령이 확정된 것이 아님 → “정확히 만 나이(또는 학년)?” 확인
- **날짜/요일**: 시간표·회차·운영 여부·예약 가능 여부 등 ‘날짜에 따라 달라지는’ 질문일 때만 날짜(또는 평일/주말) 확인
- **공간 선택**: 질문이 모호하면 천체투영관/천문대/스페이스 아날로그 중 어느 공간인지 1회만 확인

[확인 질문 트리거(조건부)]
- 사용자가 '천문우주관(천체투영관/천문대/스페이스 아날로그)' 범위의 질문을 할 때,
  위 항목 중 **답변 정확도에 실제로 필요한 것만** 추가로 질문합니다.
- 스코프 밖 질문(다른 전시관/타 부서 행사 등)에는 단체/나이/날짜 질문 트리를 적용하지 말고,
  먼저 ‘천문우주관 프로그램이 맞는지’ 1개 질문으로 범위를 확인합니다.
- 이미 답을 받은 항목은 반복 질문하지 말고, 누락된 항목만 추가로 질문합니다.

[오늘 날짜]
- 오늘은 {TODAY} (KST, Asia/Seoul) 입니다.
- '이번 주', '내일', '금요일' 같은 상대 날짜는 이 기준으로 계산하세요.


""".strip()

def _get_system_prompt() -> str:
    """오늘 날짜를 포함해 시스템 프롬프트를 최종 문자열로 반환합니다."""
    return SYSTEM_PROMPT_GNSM.format(TODAY=_today_kst_str())



# ---------------------------------------------------------
# 4) tools.py 안전 로딩 (이름이 바뀌어도 앱이 안 죽게)
#    - tools.py의 문법 오류 자체는 여기서도 막을 수 없음(그건 파일 수정 필요)
# ---------------------------------------------------------

# ✅ 확정된 "팩트 카드 tools.py" 기준 툴 이름들
# (없으면 자동 제외 + 화면 경고)
_TOOL_NAMES: List[str] = [
    "get_scipia_homepage",
    "get_scipia_navigation_links",
    "search_scipia_links",
    "get_scipia_page",
    "get_scipia_image_urls",
    "get_scipia_route_images",

    "get_hall_bundle_pages",

    # ✅ scipia SSOT 빠른 확인(전관 공통)
    "get_parking_guide_page",
    "get_paid_member_page",
    "get_group_tours_page",
    "get_recommend_course_page",
    "get_display_experience_page",
    "get_winter_exhibition_program_2026_page",
    "get_display_explanation_page",

    "get_sciencecenter_notice_page",
    "search_sciencecenter_notices",
    "get_recent_sciencecenter_notices",
    "get_planetarium_program_notice",
    "get_observatory_official_page",
    "get_space_analog_official_page",

    # ✅ (추가) 각 공간 개요(overview) 도구
    "get_planetarium_overview",
    "get_observatory_overview",
    "get_space_analog_overview",

    # 공통/천문우주관
    "get_astronomy_hall_overview",
    "get_astronomy_hall_outdoor_layout_guide",

    # ✅ (추가) 동선 전용 도구 3종: 항상 이미지+전화번호가 답변 끝에 붙도록 tools.py에서 강제
    "get_planetarium_route_guide",
    "get_observatory_route_guide",
    "get_space_analog_route_guide",

    # 천체투영관
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

    # 천문대
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

    # 스페이스 아날로그
    "get_space_analog_info",
    #"get_space_analog_floor_guide",
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


def _load_tools_safely() -> List[Any]:
    """
    tools.py에서 툴을 안전하게 로드합니다.
    - 특정 이름의 툴이 없으면 ImportError로 앱이 죽는 대신, 제외하고 경고만 띄웁니다.
    """
    try:
        from gnsm import tools as tools_module
    except Exception as e:
        st.error(
            "tools.py를 불러오지 못했습니다. (파일 문법 오류/의존성 오류 가능)\n\n"
            f"오류: {e}"
        )
        st.code(traceback.format_exc())
        return []

    loaded: List[Any] = []
    missing: List[str] = []

    for name in _TOOL_NAMES:
        obj = getattr(tools_module, name, None)
        if obj is None:
            missing.append(name)
            continue
        loaded.append(obj)

    if missing:
        st.warning(
            "일부 툴을 tools.py에서 찾지 못해 제외했습니다.\n"
            + "\n".join([f"- {m}" for m in missing])
        )

    if not loaded:
        st.error("사용 가능한 도구가 0개입니다. tools.py의 @tool 정의를 확인해 주세요.")
    return loaded


# ---------------------------------------------------------
# 5) LangGraph Agent 초기화 (버전 차이 최대한 대응)
# ---------------------------------------------------------

AGENT_KEY = "gnsm_agent"
THREAD_KEY = "gnsm_thread_id"
TOOLS_KEY = "gnsm_tools"


def _ensure_thread_id() -> str:
    """세션마다 고유 thread_id 생성 (기억 섞임 방지)."""
    if THREAD_KEY not in st.session_state:
        st.session_state[THREAD_KEY] = f"gnsm-{uuid.uuid4().hex}"
    return st.session_state[THREAD_KEY]


def _ensure_tools() -> List[Any]:
    """툴을 한 번만 로드해서 세션에 캐시."""
    if TOOLS_KEY not in st.session_state:
        st.session_state[TOOLS_KEY] = _load_tools_safely()
    return st.session_state[TOOLS_KEY]


def _build_llm() -> Optional[Any]:
    """LLM 생성. API 키/패키지 이슈가 있어도 앱이 죽지 않게 처리."""
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


def _ensure_agent() -> None:
    """
    에이전트를 세션에 한 번만 생성.
    - langgraph 버전 차이(prompt 인자/키워드 등)로 인한 TypeError를 자동 대응.
    """
    if AGENT_KEY in st.session_state:
        return

    if create_react_agent is None or MemorySaver is None:
        st.error("langgraph를 불러오지 못했습니다. langgraph 설치/버전을 확인해 주세요.")
        return

    tools_list = _ensure_tools()
    llm = _build_llm()
    if llm is None:
        return

    memory = MemorySaver()

    agent = None
    last_err = None

    try:
        agent = create_react_agent(
            model=llm,
            tools=tools_list,
            prompt=_get_system_prompt(),
            checkpointer=memory,
        )
    except TypeError as e:
        last_err = e

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
        return

    st.session_state[AGENT_KEY] = agent


def _agent_config() -> Dict[str, Any]:
    """MemorySaver thread_id 설정."""
    return {"configurable": {"thread_id": _ensure_thread_id()}}


# ---------------------------------------------------------
# 6) 메시지 변환/표준화 (튜플 금지, dict로 통일)
# ---------------------------------------------------------

def _get_messages() -> List[Dict[str, str]]:
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    return st.session_state["messages"]


def _looks_like_holiday_or_notice_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    keywords = [
        "설",
        "설날",
        "추석",
        "명절",
        "연휴",
        "휴일",
        "공휴일",
        "신정",
        "삼일절",
        "어린이날",
        "부처님오신날",
        "석가탄신일",
        "석탄일",
        "현충일",
        "광복절",
        "개천절",
        "한글날",
        "성탄절",
        "크리스마스",
        "휴관",
        "임시휴관",
        "정기휴관",
        "대체공휴일",
        "대체휴일",
        "대체 휴일",
        "운영 안내",
        "운영안내",
        "공지",
        "공지사항",
    ]
    return any(k in t for k in keywords)


def _looks_like_notice_specific_inquiry(user_text: str) -> bool:
    t = (user_text or "").lower()
    keywords = [
        "공지 있",
        "공지있",
        "공지 떴",
        "공지떴",
        "공지 확인",
        "공지확인",
        "안내 공지",
        "안내공지",
        "공지 내용",
        "공지내용",
    ]
    if any(k in t for k in keywords):
        return True
    # '공지' 단독 포함도 대부분 공지 문의로 취급
    if "공지" in t and ("공지사항" not in t):
        return True
    return False


def _extract_notice_search_keyword(user_text: str) -> str:
    t = (user_text or "").strip()
    tl = t.lower()
    if "부설" in tl and "주차" in tl:
        return "부설주차장"
    if "주차" in tl:
        return "주차"
    if "환불" in tl:
        return "환불"
    if "취소" in tl:
        return "취소"
    if "예약" in tl or "예매" in tl:
        return "예약"
    if "요금" in tl or "가격" in tl or "무료" in tl or "유료" in tl:
        return "요금"
    # 기본: 한글/영문/숫자 토큰 중 가장 긴 것을 선택
    stop = {
        "공지",
        "공지사항",
        "안내",
        "운영",
        "관련",
        "여부",
        "확인",
        "있나",
        "있나요",
        "있어",
        "있어?",
        "있잖아",
        "알려줘",
        "알려",
        "해줘",
        "해주세요",
        "좀",
        "주세요",
    }
    try:
        toks = re.findall(r"[가-힣A-Za-z0-9]{2,}", t)
        toks2 = [x for x in toks if (x.lower() not in stop) and (x not in stop)]
        toks2.sort(key=lambda x: len(x), reverse=True)
        if toks2:
            return toks2[0]
    except Exception:
        pass
    return "운영"


def _extract_holiday_keyword(user_text: str) -> str:
    t = (user_text or "").lower()
    mapping = [
        ("공휴일", "공휴일"),
        ("휴일", "공휴일"),
        ("휴무", "휴관"),
        ("성탄절", "성탄절"),
        ("크리스마스", "성탄절"),
        ("부처님오신날", "부처님오신날"),
        ("석가탄신일", "부처님오신날"),
        ("석탄일", "부처님오신날"),
        ("삼일절", "삼일절"),
        ("어린이날", "어린이날"),
        ("현충일", "현충일"),
        ("광복절", "광복절"),
        ("개천절", "개천절"),
        ("한글날", "한글날"),
        ("신정", "신정"),
        ("설날", "설"),
        ("설", "설"),
        ("추석", "추석"),
        ("연휴", "연휴"),
        ("휴관", "휴관"),
        ("대체공휴일", "대체공휴일"),
        ("대체휴일", "대체공휴일"),
    ]
    for k, v in mapping:
        if k in t:
            return v
    return "운영"


def _looks_like_recent_notices_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    keywords = [
        "최근 공지",
        "최신 공지",
        "최근공지",
        "최신공지",
        "최근 공지사항",
        "최신 공지사항",
        "최근 소식",
        "최신 소식",
        "최근안내",
        "최신안내",
        "최근 안내",
        "최신 안내",
        "최근 소식 알려",
        "최근 안내 알려",
        "최근 소식 뭐",
        "최근 안내 뭐",
        "공지사항 알려",
        "공지사항 뭐",
        "공지사항 뭐 있어",
        "공지사항 목록",
        "공지사항 리스트",
        "공지사항 확인",
    ]
    if any(k in t for k in keywords):
        return True
    # '공지사항 안내/요약/정리/보여줘' 류는 최근 공지 요약 요청으로 취급
    if ("공지사항" in t or "공지" in t) and any(k in t for k in ["안내", "요약", "정리", "알려", "보여", "목록", "리스트"]):
        return True
    # 공지사항을 '직접 봐달라/못 보겠다' 류
    if ("공지사항" in t or "공지" in t) and any(k in t for k in ["봐", "봐줘", "보여줘", "못봐", "못 봐", "확인해", "확인해줘"]):
        return True
    # 매우 짧은 공지 요청
    if t.strip() in ("공지", "공지사항", "공지 안내", "공지사항 안내", "공지사항좀", "공지좀"):
        return True
    # 느슨한 패턴: '최근'이 들어가고, 소식/안내/공지 계열 단어가 같이 나오면 최근 공지 요약으로 취급
    if ("최근" in t or "최신" in t) and any(k in t for k in ["소식", "안내", "공지", "공지사항", "news"]):
        return True
    return False


def _looks_like_holiday_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    keywords = [
        "설",
        "설날",
        "추석",
        "명절",
        "연휴",
        "휴일",
        "공휴일",
        "신정",
        "삼일절",
        "어린이날",
        "부처님오신날",
        "석가탄신일",
        "석탄일",
        "현충일",
        "광복절",
        "개천절",
        "한글날",
        "성탄절",
        "크리스마스",
        "휴관",
        "임시휴관",
        "정기휴관",
        "대체공휴일",
        "대체휴일",
        "대체 휴일",
    ]
    return any(k in t for k in keywords)


def _messages_for_agent() -> List[Dict[str, str]]:
    """
    LangGraph에게 전달할 메시지 포맷: [{"role": "...", "content": "..."}]
    - 에이전트 생성에서 prompt를 못 넣는 버전도 있어서
      여기서 시스템 메시지를 항상 첫 번째로 주입해 안전하게 운용.
    """
    msgs = _get_messages()
    normalized = [{"role": "system", "content": _get_system_prompt()}]

    # ✅ 관심 주제/대화 RAG 문맥 주입 (early-return으로 LLM을 안 부르는 구간이 있어도 문맥 유지)
    last_user = ""
    for m in reversed(msgs):
        if m.get("role") == "user" and (m.get("content") or "").strip():
            last_user = str(m.get("content") or "").strip()
            if last_user:
                interest = _get_interest_topic()
                rag_ctx = _rag_context_text_for(last_user)
                hall_notes = _get_hall_location_notes()

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
                normalized.append({
                    "role": "system",
                    "content": "\n\n".join(parts),
                })

    # ✅ 동선 질문이면: 근거(공식 페이지/이미지)로만 구체 안내. 없으면 추측 금지.
    if last_user and _looks_like_route_request(last_user):
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

    if last_user and _looks_like_holiday_or_notice_request(last_user):
        normalized.append({
            "role": "system",
            "content": (
                "설/연휴/휴관/운영 안내처럼 공지 기반 확인이 필요한 질문입니다. "
                "가능하면 먼저 공지사항 목록에서 관련 공지를 찾아 확인하세요. "
                "예: search_sciencecenter_notices(query=\"설\") -> get_sciencecenter_notice_page(공지 URL) 순서. "
                "도구로 확인되지 않으면 추측하지 마세요."
            ),
        })

    if last_user and _looks_like_recent_notices_request(last_user):
        normalized.append({
            "role": "system",
            "content": (
                "사용자가 '최근/최신 공지사항'을 요청했습니다. "
                "반드시 get_recent_sciencecenter_notices(limit=...)로 공지 목록을 먼저 확인하고, "
                "필요하면 중요한 항목 1~2개는 get_sciencecenter_notice_page로 열어 핵심만 요약하세요. "
                "확인 없이 추측하지 마세요."
            ),
        })
    for m in msgs:
        role = m.get("role", "")
        content = m.get("content", "")
        if not content:
            continue
        if role not in ("user", "assistant"):
            continue
        normalized.append({"role": role, "content": content})
    return normalized


# ---------------------------------------------------------
# 7-a) 스코프(천문우주관) 바깥 질문 가드
# ---------------------------------------------------------

# ---------------------------------------------------------
# 0) 스코프(어느 공간 이야기인지) 빠른 판별
#    - 키워드가 등장하면 해당 공간 스코프 점수를 올립니다.
#    - 점수가 충분히 높고(명확) 다른 후보 대비 우위이면, 불필요한 확인 질문 없이 바로 안내합니다.
# ---------------------------------------------------------

# 각 공간별 스코프 키워드(가벼운 휴리스틱)
SCOPE_KEYWORDS_BY_AREA = {
    "planetarium": [
        "천체투영관", "투영관", "투영",
        "돔", "돔영상", "돔영화", "돔쇼", "풀돔", "fulldome",
        "상영", "상영시간", "회차", "좌석", "입장",
        "planetarium",
    ],
    "observatory": [
        "천문대", "관측", "천체관측", "관측회",
        "달과별", "공개관측", "별바라기", "스타파인더",
        "망원경", "태양관측", "야간관측",
        "observatory",
    ],
    "space_analog": [
        "스페이스 아날로그", "스아", "아날로그",
        "훈련", "미션", "우주인", "우주비행사",
        "화성", "생존", "시뮬레이션", "체험",
        "space analog",
    ],
    "star_road": [
        "별에게로 가는 길", "별에게로", "star road",
    ],
    # 상위 범주(천문우주관) 식별용
    "main_page": ["국립과천과학관"],
}

# 편의: '천문우주관 스코프'로 간주할 수 있는 전체 키워드 플랫 리스트
SCOPE_KEYWORDS = sorted({k for ks in SCOPE_KEYWORDS_BY_AREA.values() for k in ks}, key=len, reverse=True)

_PROGRAM_KEYWORDS = [
    "프로그램", "체험", "교육", "강연", "행사", "이벤트",
    "예약", "신청", "접수", "시간표", "회차", "요금", "가격",
]

_PROGRAM_KEYWORDS = [
    "프로그램", "체험", "교육", "강연", "행사", "이벤트",
    "예약", "신청", "접수", "시간표", "회차", "요금", "가격",
]

def scope_match_score(user_text: str) -> dict:
    """사용자 텍스트에서 천문우주관 내 '어느 공간' 스코프가 강한지 점수를 계산합니다.

    반환:
      {
        "best_area": "planetarium" | "observatory" | "space_analog" | "star_road" | None,
        "best_score": int,
        "runner_up_area": str | None,
        "runner_up_score": int,
        "matched": {area: [키워드...], ...}
      }
    """
    t = (user_text or "").lower().strip()

    matched: dict = {}
    scores: dict = {}

    # 간단 점수 규칙:
    # - 키워드 포함 시 +1
    # - 2글자 이하 단축어(예: 스아)는 오탐이 있을 수 있어 +0.5로 취급 -> 정수화 위해 *2 방식 사용
    # - '천체투영관/스페이스 아날로그/별에게로 가는 길' 같은 긴 구문은 +2
    def _kw_weight(kw: str) -> int:
        kw = kw.strip()
        if len(kw) >= 6:
            return 4   # +2.0
        if len(kw) <= 2:
            return 1   # +0.5
        return 2       # +1.0

    for area, kws in SCOPE_KEYWORDS_BY_AREA.items():
        area_score2 = 0
        hits = []
        for kw in kws:
            if kw.lower() in t:
                hits.append(kw)
                area_score2 += _kw_weight(kw)
        if hits:
            matched[area] = hits
        scores[area] = area_score2

    # main_page은 상위 범주라 best 후보에서 제외(단, 게이트 판단에 사용)
    candidate_areas = [a for a in scores.keys() if a not in ("main_page",)]
    # best/runner-up
    sorted_areas = sorted(candidate_areas, key=lambda a: scores.get(a, 0), reverse=True)
    best_area = sorted_areas[0] if sorted_areas else None
    runner = sorted_areas[1] if len(sorted_areas) > 1 else None

    best_score2 = scores.get(best_area, 0) if best_area else 0
    runner_score2 = scores.get(runner, 0) if runner else 0

    # 최종 score는 정수(0,1,2...)로 보이게 2배 점수를 2로 나눠 반올림 대신 floor
    best_score = best_score2 // 2
    runner_up_score = runner_score2 // 2

    return {
        "best_area": best_area if best_score2 > 0 else None,
        "best_score": best_score,
        "runner_up_area": runner if runner_score2 > 0 else None,
        "runner_up_score": runner_up_score,
        "matched": matched,
    }

def is_scope_clear(user_text: str, min_score: int = 2, min_gap: int = 1) -> bool:
    """스코프가 충분히 명확한지 판정합니다."""
    s = scope_match_score(user_text)
    if not s.get("best_area"):
        return False
    # 점수 기준 + 2등 대비 격차
    best = int(s.get("best_score") or 0)
    runner = int(s.get("runner_up_score") or 0)
    return (best >= min_score) and ((best - runner) >= min_gap)

def _is_in_astronomy_hall_scope(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(k.lower() in t for k in SCOPE_KEYWORDS)

def _looks_like_program_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(k.lower() in t for k in _PROGRAM_KEYWORDS)

def _has_date_token(t: str) -> bool:
    t = (t or "")
    # 날짜/요일/상대적 날짜 표현
    if re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", t):
        return True
    if re.search(r"\d{1,2}\s*월\s*\d{1,2}\s*일", t):
        return True
    if any(w in t for w in ["월요일","화요일","수요일","목요일","금요일","토요일","일요일","평일","주말","오늘","내일","모레","이번주","다음주","이번 달","다음 달"]):
        return True
    return False

def _looks_like_recommendation_request(user_text: str) -> bool:
    """'추천/뭐가 좋아/어떤 거'처럼 탐색형(비확정) 추천 의도인지 감지합니다."""
    t = (user_text or "").strip()
    if not t:
        return False

    # ✅ 공지/행사/요금/예약 등 '팩트 확인' 질문은 추천 의도로 보지 않음
    if _looks_like_fact_or_ops_request(t):
        return False

    keywords = [
        "추천", "추천해", "추천해줘", "뭐가 좋아", "뭐 보면", "뭐 보면 좋", "뭐가 있", "어떤 프로그램", "프로그램 추천",
        "뭘 하면", "뭘 하면 좋", "코스", "코스 추천", "처음 왔", "처음인데", "처음 방문", "가볼만", "가볼 만"
    ]
    return any(k in t for k in keywords)


def _topic_to_hall_suggestions(user_text: str) -> list[str]:
    """추상 주제 질문을 '관심 주제' 후보로 매핑합니다(가벼운 휴리스틱).

    - 목적: 사용자가 추상적으로 질문해도, 전시관명 대신 '주제'로 대화를 정교하게 유도.
    - 주의: 확정 안내가 아니라 '추가 질문(선택지)'을 만들기 위한 용도.
    """
    t = (user_text or "").strip().lower()
    if not t:
        return []

    # 이미 관 라벨이 명시되면 제안 불필요
    try:
        from gnsm import tools as _tools

        if getattr(_tools, "resolve_hall_label", None):
            if _tools.resolve_hall_label(t):
                return []
    except Exception:
        pass

    suggestions: list[str] = []

    # 미래/첨단기술/AI/SF 계열
    if any(k in t for k in [
        "미래", "미래과학", "미래 과학", "미래기술", "미래 기술",
        "sf", "sci-fi", "사이파이",
        "인공지능", "ai", "로봇", "가상", "vr", "ar", "메타버스",
    ]):
        suggestions.append("미래과학")
        suggestions.append("첨단기술")

    # 천문/우주
    if any(k in t for k in ["우주", "천문", "별", "행성", "달", "망원경", "관측"]):
        suggestions.append("천문우주")

    # 자연/생태
    if any(k in t for k in ["곤충", "벌레", "나비", "생태", "식물"]):
        suggestions.append("곤충/생태")
    if any(k in t for k in ["공룡", "티라노", "쥬라기"]):
        suggestions.append("공룡")
    if any(k in t for k in ["자연", "자연사", "화석", "동물", "식물"]):
        suggestions.append("동물/자연")

    # 유아/어린이
    if any(k in t for k in ["유아", "어린이", "아이", "유치원", "초등"]):
        suggestions.append("유아/어린이")

    # 행사/공연
    if any(k in t for k in ["행사", "공연", "이벤트", "강연", "세미나"]):
        suggestions.append("행사/공연")

    # 중복 제거(순서 유지)
    deduped: list[str] = []
    seen = set()
    for s in suggestions:
        if s in seen:
            continue
        seen.add(s)
        deduped.append(s)
    return deduped


def _topic_suggestion_message(user_text: str) -> str:
    """전시관 제안 메시지를 생성합니다(없으면 빈 문자열)."""
    if _looks_like_fact_or_ops_request(user_text):
        return ""

    t = (user_text or "").strip()
    if not t:
        return ""

    # 너무 짧거나(예: '미래')면 확인 질문 먼저
    if len(t) <= 2:
        return ""

    topics = _topic_to_hall_suggestions(user_text)
    if not topics:
        return ""

    base = _interest_topics_prompt_intro()

    # 탐지된 주제 1~2개를 우선 노출하고, 그 외는 기본 선택지를 붙입니다.
    core = []
    for x in topics[:2]:
        core.append(x)

    # ✅ 1차: 주제에 대한 '안전한' 개요(팩트 단정/수치 없음)
    topic_overview = ""
    if core:
        if core[0] in ("미래과학", "첨단기술"):
            topic_overview = (
                "‘미래과학/첨단기술’은 인공지능·로봇·데이터·가상환경 같은 기술이 "
                "우리 생활과 산업에 어떻게 쓰이는지 체험적으로 이해해보는 방향으로 접근할 수 있어요.\n\n"
            )
        elif core[0] == "천문우주":
            topic_overview = (
                "‘천문우주’는 별·행성·우주 현상을 관찰/시뮬레이션/해설 형태로 접하면서 "
                "우주를 이해하는 체험이 중심이 될 수 있어요.\n\n"
            )
        elif core[0] in ("동물/자연", "곤충/생태", "공룡"):
            topic_overview = (
                "‘자연/생태’ 주제는 생물·환경·진화 같은 내용을 관찰하고, "
                "아이들도 흥미롭게 볼 수 있는 요소가 많아요.\n\n"
            )
        elif core[0] == "유아/어린이":
            topic_overview = (
                "‘유아/어린이’ 중심이라면 난이도와 동선, 체험 방식(손으로 해보는 활동 위주)을 기준으로 "
                "추천을 구성하는 게 좋아요.\n\n"
            )
        elif core[0] == "행사/공연":
            topic_overview = (
                "‘행사/공연’은 날짜/시간에 따라 열리는 프로그램이 달라질 수 있어서, "
                "원하시는 방문 날짜가 정해지면 공식 페이지로 최신 일정부터 확인하는 게 정확해요.\n\n"
            )

    return topic_overview + base + _interest_topics_prompt_list(core)


def _interest_topics_prompt_intro() -> str:
    """추상/추천 질문에서 공통으로 쓰는 '1차(안전한 일반 안내) + 2차(주제 선택 질문)' 서문."""
    return (
        "국립과천과학관은 우리가 만날 수 있는 다양한 주제에 대해서 "
        "직접 보고·듣고·체험하면서 과학을 이해할 수 있게 구성된 공간이에요. "
        "실내 상설전시(기초과학/첨단기술), 천문·우주, 야외 생태·공원 전시, "
        "시기별 특별 프로그램/행사 등이 함께 운영돼요.\n\n"
        "관심있는 주제를 알려주시면 더 정확한 안내를 도와드릴게요! 어떤 주제에 관심 있으세요?\n\n"
    )


def _interest_topics_prompt_list(core_topics: Optional[list[str]] = None) -> str:
    """관심 주제 리스트를 출력합니다(핵심 후보를 앞에 배치)."""
    defaults = [
        "첨단기술",
        "미래과학",
        "천문우주",
        "동물/자연",
        "공룡",
        "곤충/생태",
        "유아/어린이",
        "전시해설",
        "행사/공연",
    ]

    merged: list[str] = []
    seen = set()
    for x in (core_topics or []) + defaults:
        if x in seen:
            continue
        seen.add(x)
        merged.append(x)
    return "\n".join([f"- {x}" for x in merged[:9]])


# ✅ 범위 밖(천문우주관 외) 주제 힌트: 스코프 키워드가 없고 아래 단서가 있으면 ‘천문우주관 외’로 우선 판단
_OUT_OF_SCOPE_HINTS = [
    "장영실", "로봇", "생물", "곤충", "화학", "물리", "수학", "코딩", "메이커",
    "다른 전시관", "전시관", "교육", "행사", "강연", "세미나", "공연", "체험부스",
    "기획전", "특별전",
]

def _looks_like_out_of_scope_topic(user_text: str) -> bool:
    """천문우주관 스코프 키워드가 없고, 과학관 타 전시관/교육·행사/다른 주제 단서가 있으면 True."""
    t = (user_text or "").lower()
    if any(k.lower() in t for k in SCOPE_KEYWORDS):
        return False
    return any(h.lower() in t for h in _OUT_OF_SCOPE_HINTS)


def _has_age_token(t: str) -> bool:
    t = (t or "")
    # 만 n세 / n세 / n학년 / 유아~ 등 범주만은 age token으로 보지 않음
    if re.search(r"(만\s*)?\d{1,2}\s*세", t):
        return True
    if re.search(r"\d\s*학년", t):
        return True
    return False

def _needs_date_question(user_text: str) -> bool:
    t = (user_text or "")
    date_dependent = any(k in t for k in [
        "몇시", "언제", "회차", "시간표", "상영", "운영", "열려", "열리", "가능", "예약", "신청", "접수", "마감", "남아", "잔여", "매진", "입장"
    ])
    return date_dependent and (not _has_date_token(t))

def _needs_age_question(user_text: str) -> bool:
    t = (user_text or "")
    age_sensitive = any(k in t for k in [
        "추천", "아이", "어린이", "유아", "유치원", "초등", "중등", "고등", "학생", "가족", "연령", "몇살", "나이", "7세", "8세"
    ])
    # 7세/8세 같은 고정표현은 이미 숫자가 들어가므로 _has_age_token에서 잡힐 수 있음. 그래도 안전하게 둠.
    return age_sensitive and (not _has_age_token(t))

def _needs_group_question(user_text: str) -> bool:
    t = (user_text or "")
    group_cue = any(k in t for k in [
        "단체", "학교", "기관", "학원", "견학", "수학여행", "인솔", "버스", "예약", "전화예약"
    ]) or bool(re.search(r"\d{2,4}\s*명", t))
    # 이미 개인/단체가 명시되어 있으면 질문하지 않음
    if any(k in t for k in ["개인", "단체"]):
        return False
    return group_cue

def _pre_questions_message(user_text: str) -> str:
    qs = []
    if _needs_group_question(user_text):
        qs.append("1) **개인 관람**인가요, **학교/기관 단체**인가요?")
    if _needs_age_question(user_text):
        qs.append("2) 관람 대상의 **정확한 나이(만 나이 또는 학년)** 를 알려주세요.")
    if _needs_date_question(user_text):
        qs.append("3) 방문 **날짜(또는 평일/주말)** 를 알려주시면 회차/예약 가능 여부를 정확히 확인해드릴게요.")

    if not qs:
        return ""

    return (
        "정확히 안내하려면 아래 정보가 필요해요. (해당되는 것만 답해주시면 돼요!)\n\n"
        + "\n".join(qs)
    )

def _scope_gate_response(user_text: str) -> str:
    return (
        "정확히 안내하려면 어떤 프로그램/공간/행사를 말씀하시는지 범위를 먼저 확인해야 해요.\n\n"
        "1) 어떤 주제인가요? (예: 전시관/교육·행사/예약·요금/관람안내/오시는 길)\n"
        "2) 가능하면 관련 공식 페이지(sciencecenter.go.kr/scipia) 링크가 있으면 함께 보내주세요.\n\n"
        "원하시면 제가 scipia에서 관련 페이지를 찾아 근거(출처)와 함께 정리해드릴게요."
    )

# ---------------------------------------------------------
# 7) Streamlit UI + 에이전트 실행
# ---------------------------------------------------------

def run_chat_assistant() -> None:
    """
    Streamlit 메인 챗봇 UI + 에이전트 실행
    app.py에서는 이 함수만 호출하면 됩니다.
    """
    _ensure_agent()
    agent = st.session_state.get(AGENT_KEY)
    if agent is None:
        return

    for msg in _get_messages():
        role = msg.get("role", "assistant")
        content = msg.get("content", "")
        if not content:
            continue
        if hasattr(st, "chat_message"):
            with st.chat_message(role):
                st.markdown(_escape_tildes(content))
        else:
            st.markdown(f"**{role}**: {_escape_tildes(content)}")

    user_input = st.chat_input("국립과천과학관 운영/프로그램/행사/공간에 대해 무엇이든 물어보세요 :)")
    if not user_input:
        return

    _get_messages().append({"role": "user", "content": user_input})

    # ✅ 관심 주제 메모리 업데이트(짧은 입력 '곤충' 등)
    topic = _resolve_interest_topic(user_input)
    if topic:
        _set_interest_topic(topic)

    # ✅ 대화 RAG 저장(사용자 발화)
    _rag_add("user", user_input)

    # ✅ 사용자가 제공한 전시관 위치 메모 저장
    saved_hall = _maybe_capture_hall_location_note(user_input)
    saved_prefix = f"알려주신 **{saved_hall}** 위치 정보를 메모해둘게요." if saved_hall else ""
    if hasattr(st, "chat_message"):
        with st.chat_message("user"):
            st.markdown(_escape_tildes(user_input))
    else:
        st.markdown(f"**user**: {_escape_tildes(user_input)}")

    # ✅ 스코프 점수 계산(어느 공간 이야기인지) + 세션에 저장(출처 버튼 기본 제공에 사용)
    scope_info = scope_match_score(user_input)
    best_area = scope_info.get("best_area")

    # ✅ best_area가 잡힐 때만 갱신 (후속 질문에서 스코프 유지)
    if best_area:
        st.session_state["last_scope_area"] = best_area

    # ✅ 인텐트(추천/확정 안내) 저장: 링크 버튼/가드 로직에 사용
    st.session_state["last_intent"] = "recommend" if _looks_like_recommendation_request(user_input) else "other"

    # ✅ 공지/연휴/휴관 등 전관(메인) 기준 질문은 스코프를 main_page로 리셋해 이전 전시관 버튼이 섞이지 않게
    if st.session_state.get("last_intent") != "recommend" and _looks_like_holiday_or_notice_request(user_input):
        st.session_state["last_scope_area"] = "main_page"

    # ✅ 운영/요금/예약/공지 등 '사실 확인' 질문인데 스코프가 명확하지 않으면 main_page로 리셋
    if (
        st.session_state.get("last_intent") != "recommend"
        and (not best_area)
        and _looks_like_fact_or_ops_request(user_input)
    ):
        st.session_state["last_scope_area"] = "main_page"

    # ✅ 추천 의도인데 특정 공간 키워드가 없으면, 국립과천과학관(상위 범주)로 기본 스코프를 둡니다.
    if (st.session_state["last_intent"] == "recommend") and (scope_info.get("best_area") is None):
        st.session_state["last_scope_area"] = "main_page"

    # -----------------------------------------------------
    # ✅ (UX) 추천/탐색 질문은 전시관명을 던지기보다
    # 1) 안전한 일반 안내(LLM 톤)
    # 2) 관심 주제 선택 질문(주제 리스트)
    # 로 먼저 범위를 좁힙니다.
    # -----------------------------------------------------
    known_interest = _get_interest_topic()
    if (st.session_state.get("last_intent") == "recommend") and (not known_interest):
        answer = _interest_topics_prompt_intro() + _interest_topics_prompt_list()
        sources_blob = ""
        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                display_answer = _clean_assistant_display_text(answer)
                st.markdown(_escape_tildes(display_answer))
                _render_source_buttons(display_answer)
                _render_inline_images(display_answer)
        else:
            display_answer = _clean_assistant_display_text(answer)
            st.markdown(f"**assistant**: {_escape_tildes(display_answer)}")
            _render_source_buttons(display_answer)
            _render_inline_images(display_answer)
        _get_messages().append({"role": "assistant", "content": display_answer})
        _rag_add("assistant", display_answer)
        return

    # -----------------------------------------------------
    # ✅ (NLP) 추상 주제 질문이면 관련 전시관을 먼저 '제안'
    # -----------------------------------------------------
    suggestion = _topic_suggestion_message(user_input)
    if suggestion and (not known_interest):
        answer = suggestion
        sources_blob = ""
        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                display_answer = _clean_assistant_display_text(answer)
                st.markdown(_escape_tildes(display_answer))
                _render_source_buttons(display_answer)
                _render_inline_images(display_answer)
        else:
            display_answer = _clean_assistant_display_text(answer)
            st.markdown(f"**assistant**: {_escape_tildes(display_answer)}")
            _render_source_buttons(display_answer)
            _render_inline_images(display_answer)
        _get_messages().append({"role": "assistant", "content": display_answer})
        _rag_add("assistant", display_answer)
        return

    if (
        _looks_like_holiday_request(user_input)
        and (not _looks_like_recent_notices_request(user_input))
        and (not _looks_like_notice_specific_inquiry(user_input))
        and _looks_like_fact_or_ops_request(user_input)
        and (_extract_holiday_keyword(user_input) != "운영")
    ):
        st.session_state["last_scope_area"] = "main_page"
        st.session_state["last_intent"] = "other"

        kw = _extract_holiday_keyword(user_input)

        raw_search = ""
        try:
            from gnsm import tools as _tools

            if getattr(_tools, "search_sciencecenter_notices", None):
                raw_search = _tools.search_sciencecenter_notices(query=kw, limit=6)
        except Exception:
            raw_search = ""

        items = _parse_sources_from_text(raw_search)
        notice_urls: list[str] = []
        for it in (items or []):
            u = str(it.get("url") or "").strip()
            if not u:
                continue
            if "/scipia/introduce/notice/" in u:
                notice_urls.append(u)
        notice_urls = notice_urls[:3]

        if not notice_urls:
            try:
                from gnsm import tools as _tools
                if getattr(_tools, "get_recent_sciencecenter_notices", None):
                    raw_recent = _tools.get_recent_sciencecenter_notices(limit=6)
                    items2 = _parse_sources_from_text(raw_recent)
                    for it in (items2 or []):
                        u = str(it.get("url") or "").strip()
                        if u and ("/scipia/introduce/notice/" in u):
                            notice_urls.append(u)
                    notice_urls = notice_urls[:3]
                    if raw_recent:
                        raw_search = (raw_search or "") + "\n\n" + raw_recent
                        items = _parse_sources_from_text(raw_search)
            except Exception:
                pass

        details_blob_parts: list[str] = []
        try:
            from gnsm import tools as _tools

            for u in notice_urls[:3]:
                if getattr(_tools, "get_sciencecenter_notice_page", None):
                    try:
                        details_blob_parts.append(_tools.get_sciencecenter_notice_page(u))
                    except Exception:
                        continue
        except Exception:
            pass

        context_blob = (raw_search or "")
        if details_blob_parts:
            context_blob = context_blob + "\n\n" + "\n\n---\n\n".join(details_blob_parts)

        answer = _build_notice_summary_answer(
            items=_parse_sources_from_text(raw_search),
            details_texts=details_blob_parts,
            title_prefix="공휴일/연휴 운영 관련 공지사항을 확인해 정리했습니다.",
        )

        display_answer = _clean_assistant_display_text(answer)
        merged = display_answer + "\n\n" + (context_blob or "")
        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                st.markdown(_escape_tildes(display_answer))
                _render_source_buttons(merged)
        else:
            st.markdown(f"**assistant**: {_escape_tildes(display_answer)}")
            _render_source_buttons(merged)

        _get_messages().append({
            "role": "assistant",
            "content": display_answer,
            "scope_area": "main_page",
            "intent": "other",
            "sources_blob": context_blob,
            "image_blob": "",
        })
        _rag_add("assistant", display_answer)
        return

    if _looks_like_notice_specific_inquiry(user_input) and (not _looks_like_recent_notices_request(user_input)):
        st.session_state["last_scope_area"] = "main_page"
        st.session_state["last_intent"] = "other"

        kw = _extract_notice_search_keyword(user_input)
        if _looks_like_holiday_or_notice_request(user_input):
            kw = _extract_holiday_keyword(user_input) or kw

        raw_search = ""
        try:
            from gnsm import tools as _tools

            if getattr(_tools, "search_sciencecenter_notices", None):
                raw_search = _tools.search_sciencecenter_notices(query=kw, limit=6)
        except Exception:
            raw_search = ""

        items = _parse_sources_from_text(raw_search)
        notice_urls: list[str] = []
        for it in (items or []):
            u = str(it.get("url") or "").strip()
            if not u:
                continue
            if "/scipia/introduce/notice/" in u:
                notice_urls.append(u)
        notice_urls = notice_urls[:3]

        # 검색 결과가 빈 경우: 최근 공지 목록으로 fallback
        if not notice_urls:
            try:
                from gnsm import tools as _tools
                if getattr(_tools, "get_recent_sciencecenter_notices", None):
                    raw_recent = _tools.get_recent_sciencecenter_notices(limit=6)
                    items2 = _parse_sources_from_text(raw_recent)
                    for it in (items2 or []):
                        u = str(it.get("url") or "").strip()
                        if u and ("/scipia/introduce/notice/" in u):
                            notice_urls.append(u)
                    notice_urls = notice_urls[:3]
                    if raw_recent:
                        raw_search = (raw_search or "") + "\n\n" + raw_recent
                        items = _parse_sources_from_text(raw_search)
            except Exception:
                pass

        details_blob_parts: list[str] = []
        try:
            from gnsm import tools as _tools

            for u in notice_urls[:3]:
                if getattr(_tools, "get_sciencecenter_notice_page", None):
                    try:
                        details_blob_parts.append(_tools.get_sciencecenter_notice_page(u))
                    except Exception:
                        continue
        except Exception:
            pass

        context_blob = (raw_search or "")
        if details_blob_parts:
            context_blob = context_blob + "\n\n" + "\n\n---\n\n".join(details_blob_parts)

        answer = _build_notice_summary_answer(
            items=items,
            details_texts=details_blob_parts,
            title_prefix="공지사항을 확인해 정리했습니다.",
        )

        display_answer = _clean_assistant_display_text(answer)
        merged = display_answer + "\n\n" + (context_blob or "")
        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                st.markdown(_escape_tildes(display_answer))
                _render_source_buttons(merged)
        else:
            st.markdown(f"**assistant**: {_escape_tildes(display_answer)}")
            _render_source_buttons(merged)

        _get_messages().append({
            "role": "assistant",
            "content": display_answer,
            "scope_area": "main_page",
            "intent": "other",
            "sources_blob": context_blob,
            "image_blob": "",
        })
        _rag_add("assistant", display_answer)
        return

    if _looks_like_recent_notices_request(user_input):
        st.session_state["last_scope_area"] = "main_page"
        st.session_state["last_intent"] = "other"
        try:
            from gnsm import tools as _tools

            if getattr(_tools, "get_recent_sciencecenter_notices", None):
                raw = _tools.get_recent_sciencecenter_notices(limit=6)
            else:
                raw = ""
        except Exception:
            raw = ""

        items = _parse_sources_from_text(raw)
        st.session_state["recent_notice_items"] = items

        # ✅ 최근 공지 목록 + 상단 공지 1~2개는 상세 페이지까지 열어 요약에 활용
        notice_urls: list[str] = []
        for it in items:
            u = str(it.get("url") or "").strip()
            if not u:
                continue
            if "/scipia/introduce/notice/" in u:
                notice_urls.append(u)
        notice_urls = notice_urls[:3]

        details_blob_parts: list[str] = []
        try:
            from gnsm import tools as _tools

            for u in notice_urls[:3]:
                if getattr(_tools, "get_sciencecenter_notice_page", None):
                    try:
                        details_blob_parts.append(_tools.get_sciencecenter_notice_page(u))
                    except Exception:
                        continue
        except Exception:
            pass

        context_blob = (raw or "")
        if details_blob_parts:
            context_blob = context_blob + "\n\n" + "\n\n---\n\n".join(details_blob_parts)

        answer = _build_notice_summary_answer(
            items=items,
            details_texts=details_blob_parts,
            title_prefix="최근 공지사항을 확인해 정리했습니다.",
        )

        display_answer = _clean_assistant_display_text(answer)
        merged = display_answer + "\n\n" + (context_blob or "")
        if hasattr(st, "chat_message"):
            with st.chat_message("assistant"):
                st.markdown(_escape_tildes(display_answer))
                _render_source_buttons(merged)
        else:
            st.markdown(f"**assistant**: {_escape_tildes(display_answer)}")
            _render_source_buttons(merged)

        _get_messages().append({
            "role": "assistant",
            "content": display_answer,
            "scope_area": "main_page",
            "intent": "other",
            "sources_blob": context_blob,
            "image_blob": "",
        })
        _rag_add("assistant", display_answer)
        return

    # -----------------------------------------------------
    # ✅ (UI) 동선 질문이면: 공식 동선 이미지 URL을 미리 추출해 함께 렌더링
    # -----------------------------------------------------
    image_blob = ""
    if _looks_like_route_request(user_input):
        try:
            from gnsm import tools as _tools

            url = ""
            # 1) 명시된 전시관명이 있으면 그 SSOT
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

    answer = ""
    sources_blob = ""
    if hasattr(st, "chat_message"):
        with st.chat_message("assistant"):
            with st.spinner("생각 중입니다..."):
                answer, sources_blob = _invoke_agent_safely(agent)
            if saved_prefix:
                answer = saved_prefix + "\n\n" + (answer or "")
            display_answer = _clean_assistant_display_text(answer)
            st.markdown(_escape_tildes(display_answer))
            merged = display_answer + "\n\n" + (sources_blob or "") + "\n\n" + (image_blob or "")
            _render_source_buttons(merged)
            _render_inline_images(merged)
    else:
        answer, sources_blob = _invoke_agent_safely(agent)
        if saved_prefix:
            answer = saved_prefix + "\n\n" + (answer or "")
        display_answer = _clean_assistant_display_text(answer)
        st.markdown(f"**assistant**: {_escape_tildes(display_answer)}")
        merged = display_answer + "\n\n" + (sources_blob or "") + "\n\n" + (image_blob or "")
        _render_source_buttons(merged)
        _render_inline_images(merged)

    final_display = display_answer if 'display_answer' in locals() else _clean_assistant_display_text(answer)
    _get_messages().append({
        "role": "assistant",
        "content": final_display,
        "scope_area": st.session_state.get("last_scope_area"),
        "intent": st.session_state.get("last_intent"),
        "sources_blob": sources_blob,
        "image_blob": image_blob,
    })
    _rag_add("assistant", final_display)


def _collect_sources_blob_from_result(result: Any) -> str:


    """agent.invoke 결과(messages 포함)에서 tool/assistant 메시지에 있는 [출처] 라인을 모아 반환합니다.
    UI에는 노출하지 않고, 버튼 렌더링에만 사용합니다.
    """
    try:
        msgs = result.get("messages", None) if isinstance(result, dict) else None
    except Exception:
        msgs = None
    if not msgs:
        return ""
    blobs: list[str] = []
    for m in msgs:
        try:
            content = ""
            if hasattr(m, "content"):
                content = str(m.content or "")
            elif isinstance(m, dict) and "content" in m:
                content = str(m.get("content") or "")
            else:
                content = str(m or "")
            if ("[출처" in content) or ("[이미지" in content):
                blobs.append(content)
        except Exception:
            continue
    return "\n\n".join(blobs)


def _looks_like_fact_or_ops_request(user_text: str) -> bool:
    """도구(공식 scipia) 근거를 강제해야 하는 질문인지 휴리스틱으로 판정합니다."""
    t = (user_text or "").lower()
    keywords = [
        # 운영/예약/요금/규정
        "요금", "가격", "무료", "유료", "할인",
        "예약", "예매", "신청", "접수", "취소", "환불",
        "운영", "운영시간", "시간", "회차", "시간표", "상영", "프로그램",
        "휴관", "개관", "열려", "닫혀", "가능", "마감",

        # 공지/행사/강연/공연(팩트성)
        "공지", "공지사항", "최근 공지", "안내문",
        "행사", "이벤트", "공연", "강연", "강좌", "세미나", "특별전", "기획전",
        "일정", "스케줄", "시간대", "언제", "몇 일", "며칠",

        # 위치/교통/주차 (스크린샷 케이스)
        "오시는 길", "오는 길", "가는 길", "교통", "지하철", "버스",
        "주차", "주차장", "위치", "주소", "길 안내", "동선",

        # 전시관/공간 관계(소속/포함/층/어느 건물)
        "안에", "안에 있", "소속", "포함", "몇 층", "층", "어느 층",
        "건물", "동", "바로 옆", "근처",
    ]
    return any(k in t for k in keywords)


def _looks_like_route_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    kws = ["동선", "방문 경로", "방문경로", "어떻게 가", "어떻게 가요", "가는 길", "오시는 길"]
    return any(k in t for k in kws)
def _invoke_agent_safely(agent: Any) -> tuple[str, str]:
    """
    agent.invoke 버전 차이/응답 형태 차이를 최대한 방어.
    """
    def _do_invoke(messages: list[dict[str, str]]) -> Any:
        try:
            payload = {"messages": messages}
            return agent.invoke(payload, config=_agent_config())
        except TypeError:
            return agent.invoke({"messages": messages}, _agent_config())

    try:
        msgs = _messages_for_agent()
        result = _do_invoke(msgs)
    except Exception as e:
        return _format_runtime_error(e), ""

    sources_blob = _collect_sources_blob_from_result(result)

    # ✅ 1회 재시도: 출처가 없고(=툴 미사용 가능성 높음) 운영/교통 등 팩트성 질문이면
    # 공식 scipia 도구 사용 + [출처] 포함을 강제합니다.
    user_text = ""
    try:
        user_text = str(st.session_state.get("messages", [])[-1].get("content", ""))
    except Exception:
        user_text = ""

    holiday_needs_notice = _looks_like_holiday_or_notice_request(user_text)
    recent_notices_request = _looks_like_recent_notices_request(user_text)
    has_notice_url = ("/scipia/introduce/notice/" in (sources_blob or ""))

    if (
        (st.session_state.get("last_intent") != "recommend")
        and (
            ((not sources_blob) and _looks_like_fact_or_ops_request(user_text))
            or (holiday_needs_notice and (not has_notice_url))
            or (recent_notices_request and (not has_notice_url))
        )
    ):
        holiday_kw = ""
        try:
            holiday_kw = _extract_holiday_keyword(user_text)
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
                    if _looks_like_holiday_or_notice_request(user_text)
                    else ""
                )
                + (
                    "최근/최신 공지사항 요청이면 get_recent_sciencecenter_notices(limit=6)로 공지 목록을 먼저 확인하고, "
                    "필요하면 중요한 공지 URL을 get_sciencecenter_notice_page로 열어 확인하세요. "
                    if _looks_like_recent_notices_request(user_text)
                    else ""
                )
                + "도구로 확인되지 않으면 추측하지 말고, 확인 질문 또는 확인 가능한 공식 URL 안내만 하세요."
            ),
        }

        try:
            forced_msgs = []
            inserted = False
            for m in msgs:
                forced_msgs.append(m)
                if (not inserted) and (m.get("role") == "system"):
                    forced_msgs.append(forced_system)
                    inserted = True
            if not inserted:
                forced_msgs.insert(0, forced_system)

            result = _do_invoke(forced_msgs)
            sources_blob = _collect_sources_blob_from_result(result)
        except Exception:
            # 재시도 실패는 조용히 무시하고 첫 결과로 진행
            pass

    try:
        msgs = result.get("messages", None) if isinstance(result, dict) else None
        if msgs:
            last = msgs[-1]
            if hasattr(last, "content"):
                return str(last.content), sources_blob
            if isinstance(last, dict) and "content" in last:
                return str(last["content"]), sources_blob
            return str(last), sources_blob
    except Exception:
        pass

    return str(result)


def _format_runtime_error(e: Exception) -> str:
    """
    사용자에게는 친절히, 개발자에게는 최소한의 힌트를 제공.
    """
    return (
        "죄송합니다. 일시적인 오류가 발생했습니다.\n\n"
        "아래 내용을 확인해 주세요:\n"
        "- OPENAI_API_KEY 설정 여부\n"
        "- langgraph/langchain_openai 버전 호환\n"
        "- tools.py 문법 오류 또는 누락된 툴 이름\n\n"
        f"오류: `{e}`"
    )


# ---------------------------------------------------------
# (호환) 분리된 모듈 버전으로 엔트리 연결
# ---------------------------------------------------------

try:
    from gnsm.ui_app import run_chat_assistant as run_chat_assistant  # type: ignore
except Exception:
    # gnsm 패키지가 없거나 import 에러가 나면 기존 구현을 사용합니다.
    pass
