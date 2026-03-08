# tools.py
# 국립과천과학관 천문우주관(천체투영관/천문대/스페이스 아날로그) 전용 도구 모음
#
# ✅ 선배님 스타일(권장)
# - docstring: 길고 상세하게 (도구 선택 기준/범위/금지영역/주의사항을 명확히)
# - return: 짧게 (1~3문장 자연어 문단), bullet/facts/카드 포맷 강제하지 않음
# - “정보를 많이 담아야 할 것 같으면” → 도구를 더 쪼개서 해결
#
# 주의
# - 시간표/회차/운영일 등 변동 가능성이 큰 정보는 이 파일에서 “확정”하지 않습니다.
# - 요금/환불/예약 규정처럼 민감한 정보는 ‘핵심 규칙’만 간단히 안내하고, 최신 안내 확인을 덧붙입니다.

from __future__ import annotations
try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

import math
import os
import time
from typing import Any, Optional

import streamlit as st

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

from datetime import datetime, timedelta, timezone

try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover
    from langchain.tools import tool

import requests
import re

from urllib.parse import urlparse, urljoin


MUSEUM_BASE_URL = "https://www.sciencecenter.go.kr"

_FAQ_ENTRIES_KEY = "gnsm_faq_entries"
_FAQ_ENTRIES_TS_KEY = "gnsm_faq_entries_ts"
_FAQ_CACHE_TTL_SECONDS = 6 * 60 * 60


def _strip_html_tags_to_text(html: str) -> str:
    s = html or ""
    if not s:
        return ""
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?>.*?</\1>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p\s*>", "\n", s)
    s = re.sub(r"(?is)</div\s*>", "\n", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _faq_cache_get() -> list[dict[str, Any]]:
    items = st.session_state.get(_FAQ_ENTRIES_KEY)
    if not isinstance(items, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        q = str(it.get("q") or "").strip()
        a = str(it.get("a") or "").strip()
        if q and a:
            cleaned.append({"q": q, "a": a, "emb": it.get("emb")})
    return cleaned


def _faq_cache_is_fresh() -> bool:
    ts = st.session_state.get(_FAQ_ENTRIES_TS_KEY)
    try:
        ts2 = float(ts)
    except Exception:
        return False
    return (time.time() - ts2) < float(_FAQ_CACHE_TTL_SECONDS)


def _clean_faq_text(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    t = re.sub(r"^[\s\-–•·]+", "", t)
    t = re.sub(r"^(Q|A)\s*[\.:：\)]\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(질문|답변)\s*[\.:：\)]\s*", "", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def _parse_faq_entries_from_text(text: str) -> list[dict[str, Any]]:
    t = (text or "").strip()
    if not t:
        return []

    norm = re.sub(r"\n{3,}", "\n\n", t)
    parts = re.split(r"(?im)^\s*(?:Q|질문)\s*[\.:：\)]\s*", norm)
    entries: list[dict[str, Any]] = []
    seen = set()
    for p in parts[1:]:
        lines = [ln.strip() for ln in (p or "").splitlines() if ln.strip()]
        if not lines:
            continue
        q = lines[0]
        rest = "\n".join(lines[1:]).strip()
        if not rest:
            continue

        m = re.search(r"(?im)^\s*(?:A|답변)\s*[\.:：\)]\s*", rest)
        a = rest[m.end():].strip() if m else rest

        qq = _clean_faq_text(q)
        aa = _clean_faq_text(a)
        if not qq or not aa:
            continue
        key = qq.lower()
        if key in seen:
            continue
        seen.add(key)
        entries.append({"q": qq, "a": aa})

    return entries


def _parse_faq_entries_from_html(html_text: str) -> list[dict[str, Any]]:
    ht = html_text or ""
    if not ht:
        return []

    if BeautifulSoup is None:
        return _parse_faq_entries_from_text(_strip_html_tags_to_text(ht))

    soup = BeautifulSoup(ht, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        try:
            tag.decompose()
        except Exception:
            pass

    def _t(node) -> str:
        if node is None:
            return ""
        try:
            txt = node.get_text(separator="\n", strip=True)
        except Exception:
            txt = ""
        txt = "\n".join([ln for ln in (txt or "").splitlines() if ln.strip()])
        return txt.strip()

    entries: list[dict[str, Any]] = []
    seen = set()

    def _add(q: str, a: str) -> None:
        qq = _clean_faq_text(q)
        aa = _clean_faq_text(a)
        if not qq or not aa:
            return
        key = qq.lower()
        if key in seen:
            return
        seen.add(key)
        entries.append({"q": qq, "a": aa})

    try:
        for dl in soup.find_all("dl"):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            if not dts or not dds:
                continue
            if len(dts) == len(dds):
                for dt, dd in zip(dts, dds):
                    _add(_t(dt), _t(dd))
    except Exception:
        pass

    if entries:
        return entries

    try:
        q_selectors = [".question", ".faq_q", ".q", "[class*='question']", "[class*='faq_q']"]
        a_selectors = [".answer", ".faq_a", ".a", "[class*='answer']", "[class*='faq_a']"]

        q_nodes = []
        for sel in q_selectors:
            q_nodes.extend(soup.select(sel) or [])

        for qn in q_nodes:
            parent = qn.parent
            an = None
            if parent is not None:
                for sel in a_selectors:
                    an = parent.select_one(sel)
                    if an is not None:
                        break
            if an is None:
                sib = qn.find_next_sibling()
                if sib is not None:
                    for sel in a_selectors:
                        an = sib.select_one(sel) if hasattr(sib, "select_one") else None
                        if an is not None:
                            break
            if an is None and sib is not None:
                an = sib

            qtxt = _t(qn)
            atxt = _t(an) if an is not None else ""
            if qtxt and atxt and (len(atxt) >= 5):
                _add(qtxt, atxt)
    except Exception:
        pass

    if entries:
        return entries

    return _parse_faq_entries_from_text(_t(soup))


def _embed_text_openai(text: str) -> Optional[list[float]]:
    if OpenAI is None:
        return None
    if not os.getenv("OPENAI_API_KEY"):
        return None
    t = (text or "").strip()
    if not t:
        return None
    try:
        client = OpenAI()
        resp = client.embeddings.create(model="text-embedding-3-small", input=t[:4000])
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


def _regex_extract_notice_links_with_titles(html_text: str) -> list[dict]:
    ht = html_text or ""
    if not ht:
        return []

    links: list[dict] = []
    seen = set()

    # 0) BeautifulSoup 기반: 페이지 구조가 바뀌어도 a[href]를 전수 조사해 notice 링크를 모은다
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(ht, "html.parser")
            for a in soup.select("a[href]"):
                href = str(a.get("href") or "").strip()
                if not href:
                    continue

                m = re.search(r"/scipia/introduce/notice/(?P<id>\d{4,})", href)
                if not m:
                    continue

                nid = (m.group("id") or "").strip()
                u = f"{MUSEUM_BASE_URL}/scipia/introduce/notice/{nid}"
                if u in seen:
                    continue
                seen.add(u)

                title = ""
                try:
                    title = a.get_text(" ", strip=True)
                except Exception:
                    title = ""
                title = " ".join((title or "").split())

                # [관람가이드] 같은 접두사는 a 텍스트에 포함되지 않는 경우가 있어, 행(tr)에서 복원
                try:
                    if not re.match(r"^\[[^\]]+\]", title or ""):
                        tr = a.find_parent("tr")
                        if tr is not None:
                            row_text = " ".join((tr.get_text(" ", strip=True) or "").split())
                            m2 = re.search(r"\[[^\]]+\]", row_text)
                            if m2:
                                prefix = (m2.group(0) or "").strip()
                                if prefix and title:
                                    title = f"{prefix} {title}"
                except Exception:
                    pass
                if not title:
                    title = f"공지 {nid}"

                links.append({"title": title, "url": u})
        except Exception:
            pass

    if links:
        return links

    # 1) anchor 기반: <a ... href=".../notice/123">TITLE</a>
    for m in re.finditer(
        r"(?is)<a\b[^>]*href=['\"](?P<href>[^'\"]*/scipia/introduce/notice/(?P<id>\d{4,})[^'\"]*)['\"][^>]*>(?P<title>.*?)</a>",
        ht,
    ):
        nid = (m.group("id") or "").strip()
        u = f"{MUSEUM_BASE_URL}/scipia/introduce/notice/{nid}"
        if u in seen:
            continue
        seen.add(u)
        title_html = (m.group("title") or "").strip()
        title = _strip_html_tags_to_text(title_html)
        title = " ".join((title or "").split())
        if not title:
            title = f"공지 {nid}"
        links.append({"title": title, "url": u})
        if len(links) >= 30:
            break

    if links:
        return links

    # 2) URL 패턴만 있는 경우
    found = re.findall(r"/scipia/introduce/notice/(\d{4,})", ht)
    for nid in found[:30]:
        u = f"{MUSEUM_BASE_URL}/scipia/introduce/notice/{nid}"
        if u in seen:
            continue
        seen.add(u)
        links.append({"title": f"공지 {nid}", "url": u})
    return links


def comp_scipia_ssot_urls() -> dict[str, str]:
    return {
        "홈페이지": f"{MUSEUM_BASE_URL}/",
        "Homepage": f"{MUSEUM_BASE_URL}/",
        "공지사항": f"{MUSEUM_BASE_URL}/scipia/introduce/notice",
        "Announcements": f"{MUSEUM_BASE_URL}/scipia/introduce/notice",
        "자주묻는질문": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqTotal",
        "FAQ": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqTotal",
        "전시관람 FAQ": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqDisplay",
        "Exhibition FAQ": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqDisplay",
        "시설이용 FAQ": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqFacilities",
        "Facilities FAQ": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqFacilities",
        "이용안내": f"{MUSEUM_BASE_URL}/scipia/guide/totalGuide",
        "Visitor Guide": f"{MUSEUM_BASE_URL}/scipia/guide/totalGuide",
        "주차안내": f"{MUSEUM_BASE_URL}/scipia/introduce/parking",
        "주차 안내": f"{MUSEUM_BASE_URL}/scipia/introduce/parking",
        "연간회원": f"{MUSEUM_BASE_URL}/scipia/guide/paidMember",
        "연간 회원": f"{MUSEUM_BASE_URL}/scipia/guide/paidMember",
        "단체관람": f"{MUSEUM_BASE_URL}/scipia/guide/groupTours",
        "단체 관람": f"{MUSEUM_BASE_URL}/scipia/guide/groupTours",
        "추천관람코스": f"{MUSEUM_BASE_URL}/scipia/guide/recommendCourse",
        "추천 관람코스": f"{MUSEUM_BASE_URL}/scipia/guide/recommendCourse",
        "관람객대피": f"{MUSEUM_BASE_URL}/scipia/communication/safety",
        "안전사고수칙": f"{MUSEUM_BASE_URL}/scipia/communication/safetyRule",
        "편의시설": f"{MUSEUM_BASE_URL}/scipia/guide/convenience",
        "식음시설": f"{MUSEUM_BASE_URL}/scipia/guide/food",
        "교통안내": f"{MUSEUM_BASE_URL}/scipia/introduce/location",
        "행사": f"{MUSEUM_BASE_URL}/scipia/events/list/culture",
        "공연": f"{MUSEUM_BASE_URL}/scipia/events/list/play",
        "천체투영관 소개": f"{MUSEUM_BASE_URL}/scipia/display/planetarium",
        "천체투영관 운영": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/24281",
        "천체투영관 프로그램": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/24281",
        "천체투영관 예약": f"{MUSEUM_BASE_URL}/scipia/schedules?ACADEMY_CD=ACD007&CLASS_CD=CL7001",
        "천체투영관 단체": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/23441",
        "천문대 소개": f"{MUSEUM_BASE_URL}/scipia/display/planetarium/observation",
        "천문대 운영": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/25098",
        "천문대 프로그램": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/25098",
        "천문대 예약": f"{MUSEUM_BASE_URL}/scipia/schedules?ACADEMY_CD=ACD007&CLASS_CD=CL7003",
        "천문대 단체": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/25100",
        "스페이스 아날로그 소개": f"{MUSEUM_BASE_URL}/scipia/display/planetarium/spaceAnalog",
        "스페이스 아날로그 예약": f"{MUSEUM_BASE_URL}/scipia/schedules?ACADEMY_CD=ACD007&CLASS_CD=CL7002",
        "스페이스 아날로그 단체": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/24400",
        "자연사관": f"{MUSEUM_BASE_URL}/scipia/display/mainBuilding/naturalHistory",
        "첨단기술관": f"{MUSEUM_BASE_URL}/scipia/display/mainBuilding/advancedTechnology2",
        "과학탐구관": f"{MUSEUM_BASE_URL}/scipia/display/mainBuilding/basicScience",
        "한국문명관": f"{MUSEUM_BASE_URL}/scipia/display/mainBuilding/traditionalSciences",
        "미래상상SF관": f"{MUSEUM_BASE_URL}/scipia/display/mainBuilding/sfSpecial",
        "유아체험관": f"{MUSEUM_BASE_URL}/scipia/display/mainBuilding/kidsPlayground",
        "명예의전당": f"{MUSEUM_BASE_URL}/scipia/display/frontier/hallOfFame",
        "특별기획전": f"{MUSEUM_BASE_URL}/scipia/events/list/exhibition#n",
        "체험전시물 예약": f"{MUSEUM_BASE_URL}/scipia/display/displayExperience",
        "상설전시관 체험 프로그램": f"{MUSEUM_BASE_URL}/scipia/display/displayExperience",
        "전시장 프로그램 안내": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/25399",
        "2026 겨울 전시장 프로그램": f"{MUSEUM_BASE_URL}/scipia/introduce/notice/25617",
        "전시해설": f"{MUSEUM_BASE_URL}/scipia/display/displayExplanation",
        "전시해설 프로그램": f"{MUSEUM_BASE_URL}/scipia/display/displayExplanation",
        "곤충생태관": f"{MUSEUM_BASE_URL}/scipia/display/outdoorEcological/insectarium",
        "생태공원": f"{MUSEUM_BASE_URL}/scipia/display/outdoorEcological/ecoPark",
        "공룡공원": f"{MUSEUM_BASE_URL}/scipia/display/outdoorEcological/dinosaurAndHistory",
        "옥외전시장": f"{MUSEUM_BASE_URL}/scipia/display/outdoorEcological/outdoor",
        "인사말": f"{MUSEUM_BASE_URL}/scipia/introduce/chief",
        "연혁": f"{MUSEUM_BASE_URL}/scipia/introduce/history",
        "조직 및 연혁": f"{MUSEUM_BASE_URL}/scipia/introduce/organization",
        "주변시설": f"{MUSEUM_BASE_URL}/scipia/introduce/surround",
        "유관기관": f"{MUSEUM_BASE_URL}/scipia/introduce/familySites",
        "수도권과학관": f"{MUSEUM_BASE_URL}/scipia/introduce/capitalScience",
        "보도자료": f"{MUSEUM_BASE_URL}/scipia/introduce/report",
        "현장스케치": f"{MUSEUM_BASE_URL}/scipia/introduce/sketch",
        "채용공고": f"{MUSEUM_BASE_URL}/scipia/introduce/recruit",
        "일반자료실": f"{MUSEUM_BASE_URL}/scipia/communication/normalLibrary",
        "규정자료실": f"{MUSEUM_BASE_URL}/scipia/communication/roleLibrary",
        "자주묻는질문": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqTotal",
        "의견수렴": f"{MUSEUM_BASE_URL}/scipia/communication/opinions",
        "과학자료실": f"{MUSEUM_BASE_URL}/scipia/references",
        "자원봉사": f"{MUSEUM_BASE_URL}/scipia/schedules/voluntary",
    }


def comp_scipia_ssot_url(label: str) -> str:
    return comp_scipia_ssot_urls().get(label, "")


def comp_scipia_domains() -> list[str]:
    return [
        "운영/예약",
        "관람안내",
        "주차/교통",
        "행사/공연",
        "전시(상설/야외)",
        "천문우주관",
        "자료/소통",
        "채용/기관소개",
    ]


def comp_keywords_core_ops() -> list[str]:
    return ["운영", "예약", "신청", "접수", "결제", "취소", "환불", "요금", "가격", "시간", "운영시간", "휴관"]


def comp_keywords_visit_guide() -> list[str]:
    return ["이용안내", "관람안내", "단체", "연간회원", "편의시설", "식음", "추천코스", "안전", "대피"]


def comp_keywords_transport_parking() -> list[str]:
    return ["주차", "주차안내", "교통", "오시는 길", "위치", "버스", "지하철"]


def comp_keywords_events() -> list[str]:
    return ["행사", "공연", "이벤트", "문화", "전시", "특별", "기획전", "강연", "세미나"]


def comp_keywords_exhibitions() -> list[str]:
    return [
        "자연사관",
        "첨단기술관",
        "과학탐구관",
        "한국문명관",
        "미래상상sf관",
        "유아체험관",
        "명예의전당",
        "곤충생태관",
        "생태공원",
        "공룡공원",
        "옥외전시장",
        "전시해설",
        "체험전시물",
    ]


def comp_halls_astronomy() -> list[str]:
    return [
        "천체투영관 소개",
        "천문대 소개",
        "스페이스 아날로그 소개",
    ]


def comp_halls_main_building() -> list[str]:
    return [
        "자연사관",
        "첨단기술관",
        "과학탐구관",
        "한국문명관",
        "미래상상SF관",
        "유아체험관",
        "명예의전당",
    ]


def comp_halls_outdoor() -> list[str]:
    return [
        "곤충생태관",
        "생태공원",
        "공룡공원",
        "옥외전시장",
    ]


def comp_halls_exhibition_related() -> list[str]:
    return [
        "전시해설",
        "전시장 프로그램 안내",
        "체험전시물 예약",
        "특별기획전",
    ]


def comp_domains_core_ops_labels() -> list[str]:
    return [
        "공지사항",
        "이용안내",
        "주차안내",
        "연간회원",
        "단체관람",
        "추천관람코스",
        "관람객대피",
        "안전사고수칙",
        "편의시설",
        "식음시설",
        "교통안내",
    ]


def comp_domains_events_labels() -> list[str]:
    return [
        "행사",
        "공연",
    ]


def comp_domains_communication_labels() -> list[str]:
    return [
        "일반자료실",
        "규정자료실",
        "자주묻는질문",
        "의견수렴",
        "과학자료실",
    ]


def comp_domains_org_labels() -> list[str]:
    return [
        "인사말",
        "연혁",
        "조직 및 연혁",
        "주변시설",
        "유관기관",
        "수도권과학관",
        "보도자료",
        "현장스케치",
        "채용공고",
        "자원봉사",
    ]


def comp_hall_aliases() -> dict[str, list[str]]:
    return {
        "미래상상SF관": ["미래상상SF관", "SF관", "sf관", "미래상상sf관"],
        "자연사관": ["자연사관"],
        "첨단기술관": ["첨단기술관"],
        "과학탐구관": ["과학탐구관"],
        "한국문명관": ["한국문명관"],
        "유아체험관": ["유아체험관"],
        "명예의전당": ["명예의전당"],
        "곤충생태관": ["곤충생태관"],
        "생태공원": ["생태공원"],
        "공룡공원": ["공룡공원"],
        "옥외전시장": ["옥외전시장"],
        "천체투영관 소개": ["천체투영관", "천체투영관 소개", "planetarium"],
        "천문대 소개": ["천문대", "천문대 소개", "observatory"],
        "스페이스 아날로그 소개": ["스페이스 아날로그", "스페이스아날로그", "스아", "space analog"],
        "전시해설": ["전시해설"],
        "체험전시물 예약": ["체험전시물", "체험전시물 예약"],
        "전시장 프로그램 안내": ["전시장 프로그램", "전시장 프로그램 안내"],
        "특별기획전": ["특별기획전", "특별전", "기획전"],
        "행사": ["행사", "이벤트"],
        "공연": ["공연"],
        "이용안내": ["이용안내", "관람안내"],
        "공지사항": ["공지", "공지사항", "안내"],
        "주차안내": ["주차", "주차안내"],
        "교통안내": ["교통", "오시는 길", "위치"],
        "단체관람": ["단체", "단체관람"],
        "연간회원": ["연간회원", "회원"],
        "편의시설": ["편의시설"],
        "식음시설": ["식음", "식음시설", "식당", "카페"],
        "추천관람코스": ["추천코스", "추천관람코스"],
        "관람객대피": ["대피", "관람객대피"],
        "안전사고수칙": ["안전", "안전사고수칙"],
        "자주묻는질문": ["FAQ", "자주묻는질문"],
        "채용공고": ["채용", "채용공고"],
        "과학자료실": ["과학자료", "과학자료실"],
        "자원봉사": ["자원봉사", "봉사"],
    }


def comp_hall_profile(label: str) -> dict:
    url = comp_scipia_ssot_url(label)
    aliases = comp_hall_aliases().get(label, [label])
    keywords = list({a.lower() for a in aliases if a})
    return {
        "label": label,
        "url": url,
        "aliases": aliases,
        "keywords": keywords,
    }


def comp_all_hall_labels() -> list[str]:
    return [
        *comp_halls_astronomy(),
        *comp_halls_main_building(),
        *comp_halls_outdoor(),
        *comp_halls_exhibition_related(),
    ]


def resolve_hall_label(user_text: str) -> str:
    t = (user_text or "").strip().lower()
    if not t:
        return ""
    aliases_map = comp_hall_aliases()
    best_label = ""
    best_len = 0
    for label, aliases in aliases_map.items():
        for a in aliases:
            a2 = (a or "").strip().lower()
            if not a2:
                continue
            if a2 in t and len(a2) > best_len:
                best_label = label
                best_len = len(a2)
    if best_label:
        return best_label
    for label in comp_all_hall_labels():
        if (label or "").strip().lower() in t:
            return label
    return ""


def comp_hall_slugs() -> dict[str, str]:
    return {
        "자연사관": "natural_history",
        "첨단기술관": "advanced_technology",
        "과학탐구관": "basic_science",
        "한국문명관": "traditional_sciences",
        "미래상상SF관": "sf_special",
        "유아체험관": "kids_playground",
        "명예의전당": "hall_of_fame",
        "곤충생태관": "insectarium",
        "생태공원": "eco_park",
        "공룡공원": "dinosaur_and_history",
        "옥외전시장": "outdoor",
        "천체투영관 소개": "planetarium",
        "천문대 소개": "observatory",
        "스페이스 아날로그 소개": "space_analog",
        "전시해설": "display_explanation",
        "전시장 프로그램 안내": "display_program_notice",
        "체험전시물 예약": "display_experience",
        "특별기획전": "special_exhibition",
    }


def comp_hall_intro_ssot_url(label: str) -> str:
    """관(공간) 소개/기준 페이지 SSOT URL을 반환합니다."""
    return comp_scipia_ssot_url(label)


def comp_hall_operation_policy_sentence(label: str) -> str:
    """관별 운영 안내 정책 문장(변동 정보는 Tool/공식 페이지 확인)."""
    return (
        f"{label} 운영 여부·운영시간·입장/이용 규정은 상황에 따라 변동될 수 있어요. "
        f"정확한 안내를 위해 공식 scipia 페이지를 확인한 뒤 안내합니다."
    )


def comp_hall_reservation_policy_sentence(label: str) -> str:
    """관별 예약/신청 정책 문장(확정 수치/규정은 Tool 근거)."""
    return (
        f"{label} 관련 예약/신청/결제/취소 규정은 변동될 수 있어요. "
        f"필요하면 공식 scipia 안내(예약/신청 페이지 또는 공지)를 확인해 정확히 안내합니다."
    )


def comp_hall_caution_policy_sentence(label: str) -> str:
    """관별 유의사항 정책 문장(현장 운영에 따라 달라질 수 있음)."""
    return (
        f"{label} 이용 시 유의사항(안전/동선/제한사항)은 현장 상황에 따라 달라질 수 있어요. "
        f"방문 전 공식 안내 및 현장 안내를 함께 확인해 주세요."
    )


def comp_hall_keyword_seeds(label: str) -> list[str]:
    """관별 링크 탐색/검색에 쓸 키워드 시드를 반환합니다."""
    aliases = comp_hall_aliases().get(label, [label])
    base = [a for a in aliases if a]
    # 전관 공통 도메인 키워드도 함께 포함
    return list({*base, *comp_keywords_core_ops(), *comp_keywords_visit_guide()})


# =========================================================
#  전시관(관별) 세부 컴포넌트: 라벨별 고정 함수(얇은 래퍼)
#  - 내용 자체(팩트)는 넣지 않고, SSOT URL + 정책 문장만 제공
# =========================================================

def url_natural_history_intro() -> str:
    return comp_scipia_ssot_url("자연사관")


def comp_natural_history_overview_sentence() -> str:
    return "자연사관 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_natural_history_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("자연사관")


def comp_natural_history_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("자연사관")


def comp_natural_history_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("자연사관")


def url_advanced_technology_intro() -> str:
    return comp_scipia_ssot_url("첨단기술관")


def comp_advanced_technology_overview_sentence() -> str:
    return "첨단기술관 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_advanced_technology_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("첨단기술관")


def comp_advanced_technology_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("첨단기술관")


def comp_advanced_technology_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("첨단기술관")


def url_basic_science_intro() -> str:
    return comp_scipia_ssot_url("과학탐구관")


def comp_basic_science_overview_sentence() -> str:
    return "과학탐구관 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_basic_science_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("과학탐구관")


def comp_basic_science_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("과학탐구관")


def comp_basic_science_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("과학탐구관")


def url_traditional_sciences_intro() -> str:
    return comp_scipia_ssot_url("한국문명관")


def comp_traditional_sciences_overview_sentence() -> str:
    return "한국문명관 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_traditional_sciences_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("한국문명관")


def comp_traditional_sciences_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("한국문명관")


def comp_traditional_sciences_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("한국문명관")


def url_sf_special_intro() -> str:
    return comp_scipia_ssot_url("미래상상SF관")


def comp_sf_special_overview_sentence() -> str:
    return "미래상상SF관 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_sf_special_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("미래상상SF관")


def comp_sf_special_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("미래상상SF관")


def comp_sf_special_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("미래상상SF관")


def url_kids_playground_intro() -> str:
    return comp_scipia_ssot_url("유아체험관")


def comp_kids_playground_overview_sentence() -> str:
    return "유아체험관 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_kids_playground_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("유아체험관")


def comp_kids_playground_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("유아체험관")


def comp_kids_playground_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("유아체험관")


def url_hall_of_fame_intro() -> str:
    return comp_scipia_ssot_url("명예의전당")


def comp_hall_of_fame_overview_sentence() -> str:
    return "명예의전당 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_hall_of_fame_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("명예의전당")


def comp_hall_of_fame_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("명예의전당")


def comp_hall_of_fame_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("명예의전당")


def url_insectarium_intro() -> str:
    return comp_scipia_ssot_url("곤충생태관")


def comp_insectarium_overview_sentence() -> str:
    return "곤충생태관 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_insectarium_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("곤충생태관")


def comp_insectarium_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("곤충생태관")


def comp_insectarium_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("곤충생태관")


def url_eco_park_intro() -> str:
    return comp_scipia_ssot_url("생태공원")


def comp_eco_park_overview_sentence() -> str:
    return "생태공원 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_eco_park_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("생태공원")


def comp_eco_park_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("생태공원")


def comp_eco_park_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("생태공원")


def url_dinosaur_and_history_intro() -> str:
    return comp_scipia_ssot_url("공룡공원")


def comp_dinosaur_and_history_overview_sentence() -> str:
    return "공룡공원 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_dinosaur_and_history_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("공룡공원")


def comp_dinosaur_and_history_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("공룡공원")


def comp_dinosaur_and_history_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("공룡공원")


def url_outdoor_intro() -> str:
    return comp_scipia_ssot_url("옥외전시장")


def comp_outdoor_overview_sentence() -> str:
    return "옥외전시장 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_outdoor_operation_policy_sentence() -> str:
    return comp_hall_operation_policy_sentence("옥외전시장")


def comp_outdoor_reservation_policy_sentence() -> str:
    return comp_hall_reservation_policy_sentence("옥외전시장")


def comp_outdoor_caution_policy_sentence() -> str:
    return comp_hall_caution_policy_sentence("옥외전시장")


def url_planetarium_intro_ssot() -> str:
    return comp_scipia_ssot_url("천체투영관 소개")


def comp_planetarium_overview_sentence_general() -> str:
    return "천체투영관 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_planetarium_operation_policy_sentence_general() -> str:
    return comp_hall_operation_policy_sentence("천체투영관")


def comp_planetarium_reservation_policy_sentence_general() -> str:
    return comp_hall_reservation_policy_sentence("천체투영관")


def comp_planetarium_caution_policy_sentence_general() -> str:
    return comp_hall_caution_policy_sentence("천체투영관")


def url_observatory_intro_ssot() -> str:
    return comp_scipia_ssot_url("천문대 소개")


def comp_observatory_overview_sentence_general() -> str:
    return "천문대 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_observatory_operation_policy_sentence_general() -> str:
    return comp_hall_operation_policy_sentence("천문대")


def comp_observatory_reservation_policy_sentence_general() -> str:
    return comp_hall_reservation_policy_sentence("천문대")


def comp_observatory_caution_policy_sentence_general() -> str:
    return comp_hall_caution_policy_sentence("천문대")


def url_space_analog_intro_ssot() -> str:
    return comp_scipia_ssot_url("스페이스 아날로그 소개")


def comp_space_analog_overview_sentence_general() -> str:
    return "스페이스 아날로그 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def comp_space_analog_operation_policy_sentence_general() -> str:
    return comp_hall_operation_policy_sentence("스페이스 아날로그")


def comp_space_analog_reservation_policy_sentence_general() -> str:
    return comp_hall_reservation_policy_sentence("스페이스 아날로그")


def comp_space_analog_caution_policy_sentence_general() -> str:
    return comp_hall_caution_policy_sentence("스페이스 아날로그")


def url_display_explanation_intro() -> str:
    return comp_scipia_ssot_url("전시해설")


def comp_display_explanation_overview_sentence() -> str:
    return "전시해설 관련 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def url_display_program_notice_intro() -> str:
    return comp_scipia_ssot_url("전시장 프로그램 안내")


def comp_display_program_notice_overview_sentence() -> str:
    return "전시장 프로그램 안내는 공식 공지 내용을 기준으로 확인해드릴게요."


def url_display_experience_intro() -> str:
    return comp_scipia_ssot_url("체험전시물 예약")


def comp_display_experience_overview_sentence() -> str:
    return "체험전시물 예약 안내는 공식 scipia 페이지를 기준으로 확인해드릴게요."


def url_special_exhibition_intro() -> str:
    return comp_scipia_ssot_url("특별기획전")


def comp_special_exhibition_overview_sentence() -> str:
    return "특별기획전은 기간/일정이 변동될 수 있어 공식 scipia 페이지를 기준으로 확인해드릴게요."


@tool
def get_hall_bundle_pages(user_text_or_label: str) -> str:
    """
    사용자가 말한 관/공간을 식별한 뒤, 해당 관의 소개 SSOT + 전관 공통 운영 안내(이용안내/공지사항)를 함께 확인합니다.

    - 목적: 전관에서 특정 전시관/공간 질문이 들어왔을 때 근거(출처)를 빠르게 확보
    - 입력:
      - user_text_or_label: 사용자 질문 또는 라벨(예: "자연사관", "SF관")
    - 출력:
      - Observation + (여러 출처 URL) + 각 페이지 텍스트
    """
    label = resolve_hall_label(user_text_or_label) or (user_text_or_label or "").strip()
    if not label:
        return "Observation:\n\n관(공간)을 특정할 수 없습니다. 예: 자연사관/첨단기술관/유아체험관 처럼 알려주세요."

    intro_url = comp_scipia_ssot_url(label)
    urls: list[str] = []
    if intro_url:
        urls.append(intro_url)

    # 전관 공통 운영 안내/공지(변동 가능성이 높아 항상 함께 확인)
    for core in ["이용안내", "공지사항"]:
        u = comp_scipia_ssot_url(core)
        if u and u not in urls:
            urls.append(u)

    texts = []
    for u in urls:
        try:
            t = fetch_sciencecenter_page(u)
        except Exception as e:
            t = f"[크롤링 실패] {e}"
        texts.append(f"[출처] {u}\n{t}")
    return "Observation:\n\n" + "\n\n---\n\n".join(texts)


def get_today_kst_str() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")


# =========================================================
#  0. 크롤링 컴포넌트 ( LLM이 직접 호출하지 않음)
# =========================================================

def url_planetarium_intro() -> str:
    """
    [출처 참조 컴포넌트] `url_planetarium_intro` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천체투영관 "소개" 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “천체투영관 소개”, “천체투영관이 뭐야?”, “천체투영관 시설”처럼
      천체투영관의 기본 소개/공간 성격을 물었을 때, 정확한 정보를 전달하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 천체투영관 소개 페이지

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/display/planetarium"


def url_planetarium_program_notice() -> str:
    """
    [출처 참조 컴포넌트] `url_planetarium_program_notice` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천체투영관의 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “천체투영관”, "천체투영관 예약", "천체투영관 프로그램"처럼 천체투영관에 대한정보를 물었을 때,
      정확한 정보를 전달하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 천체투영관 운영 안내사항(공지/안내/예약 등)

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/introduce/notice/24281"


def url_planetarium_group_notice() -> str:
    """
    [출처 참조 컴포넌트] `url_planetarium_group_notice` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천체투영관 단체 운영에 대한 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “천체투영관 단체” 와 같은 정보를 물었을 때,
      정확한 정보를 전달하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 천체투영관 단체 이용안내

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/introduce/notice/23441"


def url_star_road_exhibition() -> str:
    """
    [출처 참조 컴포넌트] `url_star_road_exhibition` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천체투영관 1층 상설 전시 '별에게로 가는 길'에 대한 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “천체투영관 전시”, "천체투영관 상설전시"와 같은 정보를 물었을 때,
      정확한 정보를 전달하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 천체투영관 전시해설 안내

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/schedules/CS110062250020000001"


def url_space_analog_page() -> str:
    """
    [출처 참조 컴포넌트] `url_space_analog_page` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 스페이스 아날로그의 전시관, 프로그램 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “스페이스 아날로그”에 대한 정보를 물었을 때,
      정확한 정보를 확인하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 스페이스 아날로그 운영 안내

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/display/planetarium/spaceAnalog"


def url_space_analog_group_notice() -> str:
    """
    [출처 참조 컴포넌트] `url_space_analog_group_notice` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 스페이스 아날로그 단체 운영에 대한 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “스페이스 아날로그 단체”, "우주인 체험 단체"와 같은 스페이스 아날로그에서 단체 체험에 관련된 정보를 물었을 때,
      정확한 정보를 전달하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 스페이스 아날로그 단체 이용안내

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/introduce/notice/24400"


def url_observatory_page() -> str:
    """
    [출처 참조 컴포넌트] `url_observatory_page` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천문대에 대한 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “천문대 시설”, "천문대 망원경", "천문대 뭐하는 곳?" 등에 대한 정보를 물었을 때,
      정확한 정보를 전달하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 관련 페이지(공지/안내/예약 등)

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/display/planetarium/observation"


def url_observatory_notice() -> str:
    """
    [출처 참조 컴포넌트] `url_observatory_notice` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천문대 이번주 운영에 대한 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “천문대 운영”, "관측 할 수 있어?", "천체관측"와 같은 천체 관측에 관련된 정보를 물었을 때,
      정확하고 최신의 정보를 전달하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 천문대 단체 이용안내

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/introduce/notice/25098"


def url_observatory_group_notice() -> str:
    """
    [출처 참조 컴포넌트] `url_observatory_group_notice` 는(은) 공식 기준 페이지(SSOT URL)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천문대 단체 운영에 대한 정보를 확인해야 할 때 참조할 URL(공식 기준 페이지)을 제공합니다.
    - 실제 페이지 내용 수집(크롤링)은 `fetch_sciencecenter_page()`를 사용한 Tool에서 수행합니다.

    [언제 호출하는 컴포넌트인가]
    - 사용자가 “천문대 단체”, "관측 단체", "단체 관측", "천체관측 단체"와 같은 천문대에서 단체 체험에 관련된 정보를 물었을 때,
      정확한 정보를 전달하기 위해 이 URL을 사용합니다.

    [데이터 출처/근거]
    - (출처 참조) 국립과천과학관 공식 홈페이지의 천문대 단체 이용안내

    [주의/전제]
    - 이 함수는 URL만 반환합니다. 페이지 내용은 수시로 바뀔 수 있으므로, Tool이 최신 페이지를 다시 가져와야 합니다.
    - URL 구조가 변경될 수 있으므로, 크롤링 실패 시 “최신 공지 확인”을 안내합니다.

    [출력 형식]
    - str: URL 문자열
    """
    return "https://www.sciencecenter.go.kr/scipia/introduce/notice/25100"


@tool
def get_planetarium_program_notice() -> str:
    """
    천체투영관 정규 상영 프로그램 공지 페이지를 확인합니다.
    """
    url = url_planetarium_program_notice()
    text = fetch_sciencecenter_page(url, timeout=15)
    if isinstance(text, str) and text.startswith("[크롤링 실패]"):
        try:
            text2 = fetch_sciencecenter_page(url, timeout=25)
            if isinstance(text2, str) and (not text2.startswith("[크롤링 실패]")):
                text = text2
        except Exception:
            pass
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


def _extract_notice_item_links(html_text: str, base_url: str) -> list[dict]:
    """공지사항 목록 페이지 HTML에서 개별 공지 링크를 추출합니다."""
    if BeautifulSoup is None:
        return _regex_extract_notice_links_with_titles(html_text)

    soup = BeautifulSoup(html_text, "html.parser")
    links: list[dict] = []
    seen = set()

    def _make_notice_url_from_id(nid: str) -> str:
        nid2 = (nid or "").strip()
        if not nid2.isdigit():
            return ""
        return f"{MUSEUM_BASE_URL}/scipia/introduce/notice/{nid2}"

    def _extract_notice_id_from_text(s: str) -> str:
        if not s:
            return ""
        m = re.search(r"/scipia/introduce/notice/(\d+)", s)
        if m:
            return m.group(1)
        m = re.search(r"(?:notice|Noti|NOTICE)[^0-9]*(\d{4,})", s)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d{5,})\b", s)
        if m:
            return m.group(1)
        return ""

    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        onclick = (a.get("onclick") or "").strip()

        candidate_urls: list[str] = []

        if href and (href.lower().startswith("http") or href.startswith("/")):
            candidate_urls.append(urljoin(base_url, href).split("#")[0])

        if (not candidate_urls) and href:
            nid = _extract_notice_id_from_text(href)
            u = _make_notice_url_from_id(nid)
            if u:
                candidate_urls.append(u)

        if (not candidate_urls) and onclick:
            nid = _extract_notice_id_from_text(onclick)
            u = _make_notice_url_from_id(nid)
            if u:
                candidate_urls.append(u)

        if not candidate_urls:
            for k, v in (a.attrs or {}).items():
                if k in ("href", "onclick"):
                    continue
                vv = " ".join(v) if isinstance(v, (list, tuple)) else str(v)
                nid = _extract_notice_id_from_text(vv)
                u = _make_notice_url_from_id(nid)
                if u:
                    candidate_urls.append(u)
                    break

        if not candidate_urls:
            continue

        abs_url = candidate_urls[0]

        try:
            p = urlparse(abs_url)
        except Exception:
            continue

        if p.scheme not in ("http", "https"):
            continue
        if p.netloc != "www.sciencecenter.go.kr":
            continue
        if not p.path.startswith("/scipia/introduce/notice/"):
            continue

        tail = p.path.rsplit("/", 1)[-1]
        if not tail.isdigit():
            continue

        if abs_url in seen:
            continue
        seen.add(abs_url)

        title = a.get_text(" ", strip=True)
        title = " ".join((title or "").split())
        if not title:
            title = " ".join(((a.get("title") or "") or (a.get("aria-label") or "")).split())

        # [관람가이드] 같은 접두사가 링크 텍스트에서 빠지는 경우가 있어 tr 텍스트에서 복원
        try:
            if title and (not re.match(r"^\[[^\]]+\]", title)):
                tr = a.find_parent("tr")
                if tr is not None:
                    row_text = " ".join((tr.get_text(" ", strip=True) or "").split())
                    m2 = re.search(r"\[[^\]]+\]", row_text)
                    if m2:
                        prefix = (m2.group(0) or "").strip()
                        if prefix:
                            title = f"{prefix} {title}"
        except Exception:
            pass
        if not title:
            try:
                tr = a.find_parent("tr")
                if tr is not None:
                    title = " ".join((tr.get_text(" ", strip=True) or "").split())
            except Exception:
                title = ""
        if not title:
            title = f"공지 {tail}"
        links.append({"title": title, "url": abs_url})

    # 목록이 <a href>가 아니라 onclick 기반(tr/li/div 등)인 경우 대응
    if not links:
        for el in soup.select("[onclick]"):
            try:
                onclick = (el.get("onclick") or "").strip()
            except Exception:
                onclick = ""
            if not onclick:
                continue
            nid = _extract_notice_id_from_text(onclick)
            u = _make_notice_url_from_id(nid)
            if not u:
                continue
            if u in seen:
                continue
            seen.add(u)

            title = ""
            try:
                title = " ".join((el.get_text(" ", strip=True) or "").split())
            except Exception:
                title = ""
            if not title:
                try:
                    tr = el.find_parent("tr")
                    if tr is not None:
                        title = " ".join((tr.get_text(" ", strip=True) or "").split())
                except Exception:
                    title = ""
            if not title:
                title = f"공지 {nid}"
            links.append({"title": title, "url": u})

    if not links:
        # fallback: HTML 전체에서 notice URL 패턴 직접 추출
        found = re.findall(r"/scipia/introduce/notice/(\d{4,})", html_text or "")
        for nid in found[:20]:
            u = _make_notice_url_from_id(nid)
            if not u:
                continue
            if u in seen:
                continue
            seen.add(u)
            links.append({"title": f"공지 {nid}", "url": u})

    if not links:
        # 마지막 fallback: '공지/notice' 문맥과 함께 나오는 숫자(공지 ID) 복원
        ctx_ids = re.findall(r"(?:공지|notice)[^0-9]{0,30}(\d{4,})", html_text or "", flags=re.IGNORECASE)
        for nid in ctx_ids[:20]:
            u = _make_notice_url_from_id(nid)
            if not u:
                continue
            if u in seen:
                continue
            seen.add(u)
            links.append({"title": f"공지 {nid}", "url": u})

    return links


@tool
def search_sciencecenter_notices(query: str, limit: int = 6) -> str:
    """국립과천과학관 공지사항 목록에서 키워드로 공지를 찾아 URL을 제공합니다.

    - 언제 쓰나:
      - 설/추석/연휴/휴관/운영 안내 등 최신 공지 확인이 필요할 때
    - 입력:
      - query: 찾을 키워드 (예: "설", "연휴", "휴관")
      - limit: 최대 결과 개수
    - 출력:
      - Observation + 공지사항 목록 출처
      - 매칭된 공지별로 [출처-n] URL + [출처-n-설명] 공지 제목

    주의: 목록에서 찾은 뒤, 상세 내용 확인은 get_sciencecenter_notice_page로 URL을 넣어 확인하세요.
    """
    q = " ".join((query or "").strip().split())
    if not q:
        return "Observation:\n\n검색 키워드(query)가 비어 있습니다."

    url = comp_scipia_ssot_url("공지사항") or f"{MUSEUM_BASE_URL}/scipia/introduce/notice"

    headers = {
        "User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{MUSEUM_BASE_URL}/scipia/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        # page 파라미터 변형으로 1회 재시도
        try:
            url2 = url if "page=" in url else (url + "?&page=1")
            response = requests.get(url2, headers=headers, timeout=15)
            response.raise_for_status()
            url = url2
        except Exception:
            return (
                "Observation:\n\n"
                + f"[출처] {url}\n\n"
                + f"공지사항 목록 요청에 실패했습니다: {e}"
            )

    items = _extract_notice_item_links(response.text, url)
    if not items:
        items = _regex_extract_notice_links_with_titles(response.text)
    if not items:
        items = _regex_extract_notice_links_with_titles(response.text)
    ql = q.lower()
    matched = [it for it in items if ql in str(it.get("title") or "").lower()]

    lines: list[str] = []
    lines.append("Observation:\n\n")
    lines.append(f"[출처] {url}\n")

    if not matched:
        lines.append(f"\n'{q}' 키워드로 매칭되는 공지를 목록에서 찾지 못했습니다.\n")
        lines.append("다른 키워드(예: '설', '연휴', '휴관', '운영')로 다시 검색해 보세요.")
        return "".join(lines).strip()

    max_n = max(1, int(limit))
    for i, it in enumerate(matched[:max_n], start=1):
        u = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        if not u:
            continue
        lines.append(f"\n[출처-{i}] {u}\n")
        if title:
            lines.append(f"[출처-{i}-설명] {title}\n")

    return "".join(lines).strip()


@tool
def get_recent_sciencecenter_notices(limit: int = 6) -> str:
    """국립과천과학관 공지사항 '최근/상단' 항목을 목록에서 직접 확인해 URL과 제목을 제공합니다.

    - 언제 쓰나:
      - 사용자가 "최근 공지", "최신 공지", "공지사항 뭐 있어?"처럼 최근 공지 요약을 요청할 때
    - 입력:
      - limit: 최대 결과 개수
    - 출력:
      - Observation + 공지사항 목록 출처
      - 최근(또는 상단) 공지별로 [출처-n] URL + [출처-n-설명] 공지 제목

    주의: 상세 내용 확인이 필요하면 get_sciencecenter_notice_page로 해당 공지 URL을 열어 확인하세요.
    """
    url = comp_scipia_ssot_url("공지사항") or f"{MUSEUM_BASE_URL}/scipia/introduce/notice"

    headers = {
        "User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": f"{MUSEUM_BASE_URL}/scipia/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        try:
            url2 = url if "page=" in url else (url + "?&page=1")
            response = requests.get(url2, headers=headers, timeout=15)
            response.raise_for_status()
            url = url2
        except Exception:
            return (
                "Observation:\n\n"
                + f"[출처] {url}\n\n"
                + f"공지사항 목록 요청에 실패했습니다: {e}"
            )

    items = _extract_notice_item_links(response.text, url)
    if not items:
        items = _regex_extract_notice_links_with_titles(response.text)

    lines: list[str] = []
    lines.append("Observation:\n\n")
    lines.append(f"[출처] {url}\n")

    if not items:
        lines.append("\n공지사항 목록에서 공지 링크를 추출하지 못했습니다.")
        return "".join(lines).strip()

    max_n = max(1, int(limit))
    for i, it in enumerate(items[:max_n], start=1):
        u = str(it.get("url") or "").strip()
        title = str(it.get("title") or "").strip()
        if not u:
            continue
        lines.append(f"\n[출처-{i}] {u}\n")
        if title:
            lines.append(f"[출처-{i}-설명] {title}\n")

    return "".join(lines).strip()


@tool
def get_parking_guide_page() -> str:
    """주차 안내(공식 scipia) 페이지를 가져옵니다."""
    url = comp_scipia_ssot_url("주차안내")
    return get_scipia_page(url)


@tool
def get_paid_member_page() -> str:
    """연간회원(공식 scipia) 페이지를 가져옵니다."""
    url = comp_scipia_ssot_url("연간회원")
    return get_scipia_page(url)


@tool
def get_group_tours_page() -> str:
    """단체 관람(공식 scipia) 페이지를 가져옵니다."""
    url = comp_scipia_ssot_url("단체관람")
    return get_scipia_page(url)


@tool
def get_recommend_course_page() -> str:
    """추천 관람코스(공식 scipia) 페이지를 가져옵니다."""
    url = comp_scipia_ssot_url("추천관람코스")
    return get_scipia_page(url)


@tool
def get_sciencecenter_faq_entries(force_refresh: bool = False, max_items: int = 250) -> str:
    """국립과천과학관 '자주묻는질문(FAQ)' 페이지를 크롤링해 Q/A 항목을 추출하고 세션 캐시에 저장합니다.

    - 언제 쓰나:
      - FAQ 기반으로 답변하기 전에, 최신 FAQ 원문을 세션에 적재해야 할 때
    - 입력:
      - force_refresh: True면 캐시를 무시하고 다시 크롤링
      - max_items: 최대 추출 항목 수(기본 250)
    - 출력:
      - Observation + [출처] + FAQ 항목 수(캐시 여부 포함)
    """
    url = comp_scipia_ssot_url("자주묻는질문") or f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqTotal"

    if (not force_refresh) and _faq_cache_is_fresh():
        cached = _faq_cache_get()
        if cached:
            st.session_state[_FAQ_ENTRIES_KEY] = cached
            return (
                "Observation:\n\n"
                + f"[출처] {url}\n\n"
                + f"FAQ 항목 수: {len(cached)} (캐시)"
            )

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("허용되지 않는 URL 스킴입니다.")
        if parsed.netloc and parsed.netloc != "www.sciencecenter.go.kr":
            raise ValueError("허용되지 않는 도메인입니다. (sciencecenter.go.kr만 허용)")
        if not parsed.path.startswith("/scipia"):
            raise ValueError("허용되지 않는 경로입니다. (/scipia 이하만 허용)")

        headers = {
            "User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        html = resp.text or ""
    except Exception as e:
        return "Observation:\n\n" + f"[출처] {url}\n\n" + f"[크롤링 실패] {e}"

    entries = _parse_faq_entries_from_html(html)
    entries = entries[: max(1, int(max_items))]
    st.session_state[_FAQ_ENTRIES_KEY] = entries
    st.session_state[_FAQ_ENTRIES_TS_KEY] = float(time.time())
    return "Observation:\n\n" + f"[출처] {url}\n\n" + f"FAQ 항목 수: {len(entries)}"


@tool
def search_sciencecenter_faq(query: str, k: int = 5, use_embedding: bool = True) -> str:
    """FAQ 항목에서 질문(query)과 관련된 Q/A를 찾아 요약이 아닌 '원문 답변'을 반환합니다.

    - 언제 쓰나:
      - 사용자의 질문이 과학관 운영/이용/예약 등 FAQ에 있을 가능성이 높을 때
    - 입력:
      - query: 사용자의 질문
      - k: 반환할 후보 개수
      - use_embedding: True면(가능 시) 임베딩 유사도로 재정렬
    - 출력:
      - Observation + [출처] + 상위 FAQ Q/A
    """
    q = (query or "").strip()
    url = comp_scipia_ssot_url("자주묻는질문") or f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqTotal"
    if not q:
        return "Observation:\n\n" + f"[출처] {url}\n\n" + "검색어가 비어 있습니다."

    if (not _faq_cache_is_fresh()) or (not _faq_cache_get()):
        _ = get_sciencecenter_faq_entries(force_refresh=False)

    entries = _faq_cache_get()
    if not entries:
        return "Observation:\n\n" + f"[출처] {url}\n\n" + "FAQ 항목을 추출하지 못했습니다."

    toks = re.findall(r"[가-힣A-Za-z0-9]{2,}", q.lower())
    toks = list(dict.fromkeys([t for t in toks if t]))

    def _lex_score(it: dict[str, Any]) -> float:
        text = f"{str(it.get('q') or '')}\\n{str(it.get('a') or '')}".lower()
        if not text:
            return 0.0
        s = 0.0
        for t in toks:
            if t in text:
                s += 1.0
        if q.lower() in text:
            s += 2.0
        return s

    scored = [(float(_lex_score(it)), it) for it in entries]
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = [it for _, it in scored[: max(25, max(int(k), 5))]]

    qemb = _embed_text_openai(q) if use_embedding else None
    reranked: list[tuple[float, dict[str, Any]]] = []
    if qemb is not None:
        for it in candidates:
            base = float(_lex_score(it))
            emb = it.get("emb")
            if not isinstance(emb, list) or not emb:
                emb = _embed_text_openai((str(it.get("q") or "") + "\n" + str(it.get("a") or ""))[:3000])
                if emb is not None:
                    it["emb"] = emb
            sim = _cosine_similarity(qemb, emb or []) if isinstance(emb, list) else -1.0
            reranked.append((base + max(0.0, sim) * 3.0, it))
        reranked.sort(key=lambda x: x[0], reverse=True)
    else:
        reranked = [(float(_lex_score(it)), it) for it in candidates]
        reranked.sort(key=lambda x: x[0], reverse=True)

    top = [it for _, it in reranked[: max(1, int(k))]]
    lines: list[str] = []
    for i, it in enumerate(top, start=1):
        qq = str(it.get("q") or "").strip()
        aa = str(it.get("a") or "").strip()
        if not qq or not aa:
            continue
        if len(aa) > 900:
            aa = aa[:900] + "…"
        lines.append(f"[FAQ-{i}] 질문: {qq}\n답변: {aa}")

    if not lines:
        lines = ["- 일치하는 FAQ 항목을 찾지 못했습니다."]

    st.session_state[_FAQ_ENTRIES_KEY] = entries
    return "Observation:\n\n" + f"[출처] {url}\n\n" + "\n\n".join(lines)


@tool
def get_display_experience_page() -> str:
    """상설전시관 체험 프로그램/체험전시물 예약(공식 scipia) 페이지를 가져옵니다."""
    url = comp_scipia_ssot_url("체험전시물 예약")
    return get_scipia_page(url)


@tool
def get_winter_exhibition_program_2026_page() -> str:
    """2026 겨울 전시장 프로그램(공식 scipia 공지/안내) 페이지를 가져옵니다."""
    url = comp_scipia_ssot_url("2026 겨울 전시장 프로그램")
    return get_scipia_page(url)


@tool
def get_display_explanation_page() -> str:
    """전시해설 프로그램(공식 scipia) 페이지를 가져옵니다."""
    url = comp_scipia_ssot_url("전시해설")
    return get_scipia_page(url)


@tool
def get_planetarium_intro_page() -> str:
    """
    천체투영관 소개 페이지를 확인합니다.
    - 목적: 천체투영관의 기본 소개/공간 성격/시설 안내를 공식 페이지 텍스트로 확보
    - 입력: 없음
    - 출력: Observation + 출처 URL + 페이지 텍스트
    """
    url = url_planetarium_intro()
    text = fetch_sciencecenter_page(url)
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


@tool
def get_planetarium_group_bundle_pages() -> str:
    """
    천체투영관 '단체 문의/예약' 답변을 위해 필요한 공식 페이지(소개 + 운영 안내 + 단체 예약 안내)를 한 번에 확인합니다.
    - 목적: 단체 예약/요금/절차가 운영 안내와 연결되어 있을 수 있으므로, 관련 페이지를 함께 확인하여 환각을 줄임
    - 입력: 없음
    - 출력: Observation + (여러 출처 URL) + 각 페이지 텍스트
    """
    urls = [
        url_planetarium_intro(),
        url_planetarium_program_notice(),
        url_planetarium_group_notice(),
    ]
    texts = []
    for u in urls:
        try:
            t = fetch_sciencecenter_page(u)
        except Exception as e:
            t = f"[크롤링 실패] {e}"
        texts.append(f"[출처] {u}\n{t}")
    return "Observation:\n\n" + "\n\n---\n\n".join(texts)


@tool
def get_star_road_exhibition_page() -> str:
    """
    천체투영관 1층 상설 전시(별에게로 가는 길) 해설/이용 안내 페이지를 확인합니다.
    - 목적: 전시 해설 운영 방식/동선/유의사항 등 변동 가능 정보를 공식 페이지 텍스트로 확보
    - 입력: 없음
    - 출력: Observation + 출처 URL + 페이지 텍스트
    """
    url = url_star_road_exhibition()
    text = fetch_sciencecenter_page(url)
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


@tool
def get_space_analog_group_bundle_pages() -> str:
    """
    스페이스 아날로그 '단체 문의/예약' 답변을 위해 필요한 공식 페이지(소개 + 단체 예약 안내)를 한 번에 확인합니다.
    - 목적: 단체 운영/예약 절차가 소개 페이지의 운영 안내와 연결되어 있을 수 있으므로 함께 확인
    - 입력: 없음
    - 출력: Observation + (여러 출처 URL) + 각 페이지 텍스트
    """
    urls = [
        url_space_analog_page(),
        url_space_analog_group_notice(),
    ]
    texts = []
    for u in urls:
        try:
            t = fetch_sciencecenter_page(u)
        except Exception as e:
            t = f"[크롤링 실패] {e}"
        texts.append(f"[출처] {u}\n{t}")
    return "Observation:\n\n" + "\n\n---\n\n".join(texts)


@tool
def get_observatory_notice_page() -> str:
    """
    천문대 운영 안내(이번주 운영/이용 안내 등) 공지 페이지를 확인합니다.
    """
    url = url_observatory_notice()
    text = fetch_sciencecenter_page(url)
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


@tool
def get_observatory_group_bundle_pages() -> str:
    """
    천문대 '단체 문의/예약' 답변을 위해 필요한 공식 페이지(소개 + 운영 안내 + 단체 예약 안내)를 한 번에 확인합니다.
    - 목적: 단체 예약/요금/절차가 운영 안내와 연결되어 있을 수 있으므로, 관련 페이지를 함께 확인하여 환각을 줄임
    - 입력: 없음
    - 출력: Observation + (여러 출처 URL) + 각 페이지 텍스트
    """
    urls = [
        url_observatory_page(),
        url_observatory_notice(),
        url_observatory_group_notice(),
    ]
    texts = []
    for u in urls:
        try:
            t = fetch_sciencecenter_page(u)
        except Exception as e:
            t = f"[크롤링 실패] {e}"
        texts.append(f"[출처] {u}\n{t}")
    return "Observation:\n\n" + "\n\n---\n\n".join(texts)



@tool
def get_observatory_official_page() -> str:
    """
    천문대 공식 안내 페이지를 확인합니다.
    """
    url = url_observatory_page()
    text = fetch_sciencecenter_page(url)
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


@tool
def get_space_analog_official_page() -> str:
    """
    스페이스 아날로그 공식 안내 페이지를 확인합니다.
    - 목적: 변동 가능성이 있는 운영/프로그램/이용 안내를 공식 페이지 텍스트로 확보
    - 입력: 없음
    - 출력: Observation + 출처 URL + 페이지 텍스트
    """
    url = url_space_analog_page()
    text = fetch_sciencecenter_page(url)
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


@tool
def get_sciencecenter_notice_page(url: str) -> str:
    """
    국립과천과학관 '공지/안내' 페이지를 URL로 받아 내용을 확인합니다. (범용 크롤링)
    - 언제 쓰나:
      - 운영/모집/예약/환불 등 '변동 가능' 정보가 질문에 포함될 때
      - 도구에 없는 최신 공지 내용을 확인해야 할 때
    - 입력:
      - url: https://www.sciencecenter.go.kr/scipia/introduce/notice/.... 형태 권장
    - 출력: Observation + 출처 URL + 페이지 텍스트
    """
    text = fetch_sciencecenter_page(url)
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


@tool
def get_sciencecenter_faq(category: str = "total") -> str:
    """
    국립과천과학관 '자주묻는질문(FAQ)' 페이지를 카테고리별로 확인합니다.
    - 언제 쓰나:
      - 사용자가 자주 묻는 질문에 대한 답변을 요청할 때
      - 전시관람, 시설이용 등에 대한 일반적인 질문에 답변할 때
    - 입력:
      - category: "total" (전체), "display" (전시관람), "facilities" (시설이용)
    - 출력: Observation + 출처 URL + FAQ 내용
    """
    print(f"[DEBUG] ===== get_sciencecenter_faq 호출됨! category={category} =====")
    
    category_urls = {
        "total": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqTotal",
        "display": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqDisplay",
        "facilities": f"{MUSEUM_BASE_URL}/scipia/communication/faq/faqFacilities",
    }
    
    url = category_urls.get(category.lower(), category_urls["total"])
    print(f"[DEBUG] FAQ URL: {url}")
    
    # FAQ 페이지는 JavaScript로 동적 렌더링되므로 Selenium 사용
    text = _fetch_faq_with_selenium(url)
    
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


def _fetch_faq_with_selenium(url: str) -> str:
    """
    FAQ 페이지를 Selenium으로 크롤링하여 질문 목록을 추출합니다.
    공지사항 크롤링과 동일한 방식 사용.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import time
    
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(options=options)
    try:
        print(f"[DEBUG] FAQ 페이지 로드 시작: {url}")
        driver.get(url)
        
        # JavaScript 렌더링 대기 (공지사항과 동일)
        time.sleep(3)
        
        # 페이지 소스 가져오기
        html = driver.page_source
        print(f"[DEBUG] 페이지 HTML 길이: {len(html)}")
        
        # BeautifulSoup으로 파싱
        soup = BeautifulSoup(html, "html.parser")
        
        # 스크립트/스타일 제거
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        
        # 헤더/메뉴/푸터 제거 (공지사항과 동일)
        for sel in ["header", "footer", "nav", ".gnb", ".lnb", ".breadcrumb", ".location", 
                    ".quick", ".util", ".skip", ".skipNavi", ".skip_navi", ".btnArea", 
                    ".btn_area", ".share", ".sns", "#header", "#footer", "#gnb", "#lnb",
                    ".header", ".footer", ".nav", ".navigation", ".menu", ".sidebar",
                    ".top_menu", ".topMenu", ".sub_menu", ".subMenu", ".left_menu", ".leftMenu"]:
            for elem in soup.select(sel):
                elem.decompose()
        
        # FAQ 테이블 찾기 (달력 제외)
        faq_table = None
        
        # 방법 1: board-list 클래스 (게시판 테이블)
        faq_table = soup.select_one("table.board-list")
        if faq_table:
            print(f"[DEBUG] FAQ 테이블 발견 (선택자: table.board-list)")
        
        # 방법 2: 모든 테이블 중에서 FAQ 관련 테이블 찾기
        if not faq_table:
            all_tables = soup.select("table")
            print(f"[DEBUG] 페이지 내 전체 테이블 개수: {len(all_tables)}")
            for idx, table in enumerate(all_tables):
                # 테이블 내용 확인
                first_row = table.select_one("tbody tr")
                if first_row:
                    cells = first_row.select("td")
                    if len(cells) > 0:
                        first_cell_text = cells[0].get_text(strip=True)
                        print(f"[DEBUG] 테이블 {idx+1} 첫 셀: '{first_cell_text}'")
                        
                        # 날짜 패턴만 있는 테이블 제외 (달력)
                        if re.match(r'^\d{1,5}2026-\d{2}-\d{2}$', first_cell_text):
                            print(f"[DEBUG] 테이블 {idx+1}: 달력으로 판단, 건너뜀")
                            continue
                        
                        # FAQ 게시판 테이블 선택
                        # - 번호(숫자)로 시작
                        # - "제목", "상단공지" 등의 키워드 포함
                        if (first_cell_text.isdigit() or 
                            "제목" in first_cell_text or 
                            "상단공지" in first_cell_text or
                            "공지" in first_cell_text):
                            faq_table = table
                            print(f"[DEBUG] FAQ 테이블 발견 (테이블 {idx+1}, 첫 셀: '{first_cell_text}')")
                            break
        
        if not faq_table:
            print(f"[DEBUG] FAQ 테이블을 찾을 수 없음. 전체 텍스트 추출 시도")
            text = soup.get_text(separator="\n", strip=True)
            # 메뉴 라인 제거
            lines = []
            banned = ["로그인", "회원가입", "사이트맵", "마이페이지", "ENG", "검색",
                     "전시해설", "안내", "행사", "전체일정", "특별기획전", "공연", "휴관일",
                     "대표전화", "Fax", "주소", "경기도 과천시"]
            for line in text.splitlines():
                s = line.strip()
                if not s or any(k in s for k in banned):
                    continue
                lines.append(s)
            return "\n".join(lines[:20])  # 상위 20줄만
        
        # 테이블에서 행 추출 (질문과 답변 모두)
        rows = faq_table.select("tbody tr")
        print(f"[DEBUG] FAQ 행 개수: {len(rows)}")
        
        faq_items = []
        for idx, row in enumerate(rows[:15]):  # 상위 15개 확인
            cells = row.select("td")
            if len(cells) < 2:
                continue
            
            # 디버깅: 모든 셀의 내용 출력
            print(f"[DEBUG] 행 {idx+1} - 셀 개수: {len(cells)}")
            for cell_idx, cell in enumerate(cells[:5]):  # 처음 5개 셀만
                cell_text = cell.get_text(strip=True)
                print(f"[DEBUG]   셀 {cell_idx}: '{cell_text}' (길이: {len(cell_text)})")
            
            # 번호 (첫 번째 셀)
            num_text = cells[0].get_text(strip=True)
            
            # 제목 찾기
            title_text = ""
            
            # 방법 1: title 클래스가 있는 셀
            title_cell = row.select_one("td.title")
            if title_cell:
                title_text = title_cell.get_text(strip=True)
                print(f"[DEBUG] title 클래스 셀 발견: {title_text}")
            
            # 방법 2: 모든 셀을 순회하며 가장 긴 유효한 텍스트 찾기
            if not title_text:
                max_len = 0
                for cell_idx, cell in enumerate(cells):
                    text = cell.get_text(strip=True)
                    
                    # 날짜 패턴 제외
                    if re.search(r'\d{4,5}-\d{2}-\d{2}', text):
                        continue
                    
                    # 숫자만 있는 경우 제외
                    if text.isdigit():
                        continue
                    
                    # 헤더 제외
                    if text in ["번호", "제목", "작성자", "조회수", "등록일"]:
                        continue
                    
                    # 너무 짧은 텍스트 제외
                    if len(text) < 5:
                        continue
                    
                    # 가장 긴 텍스트 선택
                    if len(text) > max_len:
                        max_len = len(text)
                        title_text = text
                        print(f"[DEBUG] 제목 후보 발견 (셀 {cell_idx}): {title_text}")
            
            if not title_text:
                print(f"[DEBUG] 행 {idx+1}: 제목을 찾을 수 없음")
                continue
            
            if title_text:
                # FAQ 상세 페이지 URL 추출
                faq_url = ""
                title_link = row.select_one("td.title a, a")
                if title_link and title_link.get("href"):
                    href = title_link.get("href")
                    if href.startswith("/"):
                        faq_url = f"https://www.sciencecenter.go.kr{href}"
                    elif href.startswith("http"):
                        faq_url = href
                
                print(f"[DEBUG] FAQ 항목 {idx+1}: {num_text} - {title_text}")
                if faq_url:
                    print(f"[DEBUG] FAQ URL: {faq_url}")
                
                faq_items.append({
                    "number": num_text,
                    "title": title_text,
                    "url": faq_url
                })
        
        # FAQ 상세 페이지로 이동하여 답변 추출
        if faq_items:
            print(f"[DEBUG] FAQ 항목 {len(faq_items)}개 발견, 답변 크롤링 시작")
            
            # 각 FAQ 상세 페이지 크롤링
            for idx, item in enumerate(faq_items[:5]):  # 상위 5개만
                if not item.get('url'):
                    print(f"[DEBUG] FAQ {idx+1}: URL이 없음, 건너뜀")
                    item['answer'] = ""
                    continue
                
                try:
                    print(f"[DEBUG] FAQ {idx+1} 상세 페이지 크롤링: {item['url']}")
                    
                    # 상세 페이지로 이동
                    driver.get(item['url'])
                    time.sleep(1)  # 페이지 로드 대기 (속도 개선)
                    
                    # 페이지 HTML 파싱
                    detail_soup = BeautifulSoup(driver.page_source, "html.parser")
                    
                    # 답변 내용 찾기 (여러 선택자 시도)
                    answer_text = ""
                    answer_selectors = [
                        ".board-view .content",
                        ".board-view",
                        ".view-content",
                        ".faq-answer",
                        ".answer",
                        "div.content"
                    ]
                    
                    for selector in answer_selectors:
                        answer_elem = detail_soup.select_one(selector)
                        if answer_elem:
                            answer_text = answer_elem.get_text(separator="\n", strip=True)
                            if len(answer_text) > 20:
                                print(f"[DEBUG] FAQ {idx+1} 답변 발견 (선택자: {selector}, 길이: {len(answer_text)})")
                                break
                    
                    # 메뉴/헤더/푸터 텍스트 제거
                    if answer_text:
                        lines = answer_text.splitlines()
                        clean_lines = []
                        banned_keywords = ["로그인", "회원가입", "사이트맵", "마이페이지", "검색", 
                                          "전시해설", "안내", "대표전화", "Fax", "주소"]
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            # 메뉴 라인 제외
                            if any(kw in line for kw in banned_keywords):
                                continue
                            clean_lines.append(line)
                        
                        answer_text = "\n".join(clean_lines)
                    
                    item['answer'] = answer_text if answer_text else ""
                    
                    # 목록 페이지로 돌아가기
                    driver.back()
                    time.sleep(0.5)  # 속도 개선
                    
                except Exception as e:
                    print(f"[DEBUG] FAQ {idx+1} 크롤링 오류: {e}")
                    item['answer'] = ""
                    # 오류 발생 시 목록 페이지로 돌아가기
                    try:
                        driver.get(url)
                        time.sleep(1)
                    except:
                        pass
            
            # 결과 포맷팅 (메인 페이지 URL만 포함)
            result_lines = ["전시관람 자주 묻는 질문 (상위 5개):\n"]
            for idx, item in enumerate(faq_items[:5], 1):
                result_lines.append(f"{idx}. **{item['title']}**")
                if item.get('answer') and len(item['answer']) > 20:
                    # 답변 미리보기 (처음 150자)
                    answer_preview = item['answer'][:150] + "..." if len(item['answer']) > 150 else item['answer']
                    result_lines.append(f"   💡 {answer_preview}")
            
            # 메인 페이지 URL만 출처로 추가
            result_lines.append(f"\n🔗 {url}")
            
            return "\n\n".join(result_lines)
        else:
            print(f"[DEBUG] FAQ 항목을 찾을 수 없음")
            return "FAQ 목록을 찾을 수 없습니다."
            
    except Exception as e:
        print(f"[DEBUG] FAQ 크롤링 오류: {e}")
        import traceback
        traceback.print_exc()
        return f"FAQ 페이지 크롤링 중 오류 발생: {str(e)}"
    finally:
        driver.quit()


def fetch_sciencecenter_page(url: str, timeout: int = 10) -> str:
    """
    국립과천과학관 홈페이지 페이지를 requests 기반으로 가져옵니다.
    FAQ 페이지는 Selenium을 사용합니다.
    성공 시 페이지의 텍스트 전체를 반환합니다.
    """

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("허용되지 않는 URL 스킴입니다.")
    if parsed.netloc and parsed.netloc != "www.sciencecenter.go.kr":
        raise ValueError("허용되지 않는 도메인입니다. (sciencecenter.go.kr만 허용)")
    if not parsed.path.startswith("/scipia"):
        raise ValueError("허용되지 않는 경로입니다. (/scipia 이하만 허용)")
    
    # FAQ 페이지는 JavaScript 렌더링이 필요하므로 Selenium 사용
    if "/communication/faq/" in url:
        print(f"[DEBUG] FAQ 페이지 감지, Selenium 사용: {url}")
        return _fetch_faq_with_selenium(url)

    headers = {
        "User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        "Referer": f"{MUSEUM_BASE_URL}/scipia/",
    }
    fallback_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        "Referer": f"{MUSEUM_BASE_URL}/scipia/",
        "Connection": "keep-alive",
    }

    def _do_get(h: dict[str, str]) -> str:
        try:
            response = requests.get(url, headers=h, timeout=timeout)
            response.raise_for_status()
            return response.text
        except Exception as e:
            return f"[크롤링 실패] {e}"

    html = _do_get(headers)
    if isinstance(html, str) and html.startswith("[크롤링 실패]"):
        return html

    if BeautifulSoup is None:
        return _strip_html_tags_to_text(html)

    def _strip_menu_lines(txt: str) -> str:
        """메뉴 라인 제거 (안전망)"""
        banned = [
            "로그인","회원가입","사이트맵","마이페이지","ENG","검색",
            "전시해설","안내","행사","전체일정","특별기획전","공연","휴관일",
            "PRINT","PDF","닫기","실행","중지","이동",
            "과학관소식","고객서비스","안전관리","정보나눔터","전자민원","분실물목록",
            "공지/공고","카드뉴스","보도자료","현장스케치","채용공고",
            "이용약관","관련사이트","대표전화","Fax","주소"
        ]
        out = []
        for ln in (txt or "").splitlines():
            s = " ".join(ln.split()).strip()
            if not s:
                continue
            if any(k == s for k in banned):
                continue
            # 한 줄에 금지어가 너무 많으면 메뉴로 판단
            hit = sum(k in s for k in banned)
            if hit >= 3:
                continue
            out.append(s)
        return "\n".join(out)
    
    def _post_clean_text(text: str) -> str:
        text2 = re.sub(r"\n{3,}", "\n\n", text or "").strip()
        if not text2:
            return ""
        banned_substrings = (
            "바로가기",
            "건너띄기",
            "주메뉴",
            "본문 바로가기",
            "Skip",
            "skip",
            "대한민국 공식 전자정부",
            "전자정부 누리집",
            "애국가 듣기",
            "행사 전체일정",
            "행사 전체 일정",
            "미래과학자 그림대회",
            "공지/공고 상세",
            "그런사람:",
            "그런사람",
            "ResponsiveVoice",
            "Non-Commercial License",
            "creativecommons.org",
            "used under",
            "used under 개인정보",
            "used under 개인정보 처리방침",
            "개인정보 처리방침",
            "이메일주소 무단수집거부",
            "이메일주소",
            "무단수집거부",
            "미래를 상상하며 행복을 주는",
            "과학기술정보통신부",
            "국립중앙과학관",
            "국립부산과학관",
            "한국과학관협회",
            "한국과학창의재단",
            "국민재난안전포털",
            "아시아태평양과학관협회",
            "국가상징",
            "국가상징 알아보기",
            "알아보기 열린",
            "알아보기열린",
            "열린군데",
        )
        date_noise_re = re.compile(
            r"^\s*\d{4}\.\d{2}\.\d{2}.*~\s*\d{4}\.\d{2}\.\d{2}.*(공지/공고\s*상세)?\s*$"
        )
        other_museum_re = re.compile(r"국립(?!과천)[가-힣A-Za-z0-9]{1,20}과학관")
        cleaned_lines: list[str] = []
        seen_lines: set[str] = set()
        for ln in (text2 or "").splitlines():
            s = (ln or "").strip()
            if not s:
                continue
            if date_noise_re.search(s):
                continue
            if ("국립과천과학관" not in s) and other_museum_re.search(s):
                continue
            if any(x in s for x in banned_substrings):
                continue
            if s in seen_lines:
                continue
            seen_lines.add(s)
            cleaned_lines.append(s)
        out = "\n".join(cleaned_lines)
        out = re.sub(r"\n{3,}", "\n\n", out or "").strip()
        return out

    soup = BeautifulSoup(html, "html.parser")

    # 스크립트/스타일 제거
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # 공통 헤더/푸터/내비게이션 계열 제거(본문 추출 품질 향상)
    try:
        for sel in [
            "header",
            "footer",
            "nav",
            "aside",
            ".gnb",
            ".lnb",
            ".breadcrumb",
            ".location",
            ".quick",
            ".util",
            ".skip",
            ".skipNavi",
            ".skip_navi",
            ".btnArea",
            ".btn_area",
            ".share",
            ".sns",
        ]:
            for n in soup.select(sel):
                try:
                    n.decompose()
                except Exception:
                    continue
    except Exception:
        pass

    def _text_of(node) -> str:
        if node is None:
            return ""
        try:
            t = node.get_text(separator="\n", strip=True)
        except Exception:
            t = ""
        return "\n".join([ln for ln in (t or "").splitlines() if ln.strip()])

    # 공지 상세(/introduce/notice/<id>)는 본문 영역이 따로 있는 경우가 많아,
    # 가능한 한 '본문 컨테이너'를 우선 선택(큰 컨테이너(#contents 등)는 후순위)
    candidates = []
    matched_selector = None
    try:
        if parsed.path.startswith("/scipia/introduce/notice/"):
            selectors = [
                "#voiceContents",               # ✅ 본문만 (최우선)
                ".board-body #voiceContents",   # ✅ 본문만
                ".view_cont",                   # ✅ 본문 컨테이너
                ".viewCont",
                ".board_view .view_cont",
                ".board_view .viewCont",
                ".board_view .content",
                ".board_view .cont",
                ".board_view .board_cont",
                ".boardView",
                ".bbs_view .view_cont",
                ".bbs_view",
                ".notice_view",
                ".view",
                "article .view_cont",
                "article",
                ".board-body",                  # ⚠️ 다시 추가 (fallback용, 후처리로 메뉴 제거)
                "main",
                "#contents .view_cont",
                "#contents .board_view",
                "#contents",
                ".contents",
                ".subContents",
                ".content",
                ".cont",
            ]
            for sel in selectors:
                el = soup.select_one(sel)
                if el is not None:
                    candidates.append(el)
                    if matched_selector is None:
                        matched_selector = sel
    except Exception:
        candidates = []
    
    # DEBUG: selector 매칭 확인
    if parsed.path.startswith("/scipia/introduce/notice/"):
        print(f"[DEBUG fetch_sciencecenter_page] URL: {url}")
        print(f"  Matched selector: {matched_selector}")
        print(f"  Candidates count: {len(candidates)}")

    if candidates:
        def _noise_score(t: str) -> int:
            tt = (t or "").lower()
            noise = 0
            for w in [
                "행사 전체일정",
                "공지/공고 상세",
                "카드뉴스",
                "보도자료",
                "현장스케치",
                "채용공고",
                "이용약관",
                "개인정보",
                "이메일주소",
            ]:
                if w in tt:
                    noise += 3
            return noise

        # 길이(정보량)와 잡음(메뉴/푸터) 적음을 함께 고려
        scored = []
        for n in candidates:
            tx = _text_of(n)
            scored.append((max(0, len(tx)) - _noise_score(tx) * 50, tx))
        scored.sort(key=lambda x: x[0], reverse=True)
        text = scored[0][1] if scored else _text_of(candidates[0])
    else:
        body = soup.body if getattr(soup, "body", None) is not None else soup
        text = _text_of(body)

    text = _post_clean_text(text)
    
    # 메뉴 라인 제거 (안전망)
    text = _strip_menu_lines(text)

    if parsed.path.startswith("/scipia/introduce/notice/"):
        # 공지 페이지는 JavaScript로 렌더링되므로 무조건 Selenium 사용
        print(f"  Notice page detected - using Selenium (JavaScript rendering)")
        try:
            sel_txt = fetch_sciencecenter_page_selenium(url)
            sel_txt2 = _post_clean_text(sel_txt)
            sel_txt2 = _strip_menu_lines(sel_txt2)
            print(f"  [Selenium] Extracted {len(sel_txt2)} chars")
            if sel_txt2 and len(sel_txt2) >= 50:
                print("  [Selenium] SUCCESS")
                return sel_txt2
            else:
                print(f"  [Selenium] Too short ({len(sel_txt2)} chars)")
        except Exception as e:
            print(f"  [Selenium] FAILED: {e}")
        
        return text if text else "[크롤링 실패] 페이지 내용을 가져올 수 없습니다."

    return text


def fetch_sciencecenter_page_selenium(url: str) -> str:
    """
    requests로 페이지 내용을 가져오지 못했을 경우 사용하는 fallback.
    (실제 사용 시 webdriver 설정 필요)
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        html = driver.page_source
    finally:
        driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    
    # 스크립트/스타일 제거
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    
    # 헤더/메뉴/푸터 제거
    for sel in ["header", "footer", "nav", ".gnb", ".lnb", ".breadcrumb", ".location", 
                ".quick", ".util", ".skip", ".skipNavi", ".skip_navi", ".btnArea", 
                ".btn_area", ".share", ".sns", "#header", "#footer", "#gnb", "#lnb",
                ".header", ".footer", ".nav", ".navigation", ".menu", ".sidebar",
                ".top_menu", ".topMenu", ".sub_menu", ".subMenu", ".left_menu", ".leftMenu"]:
        for elem in soup.select(sel):
            elem.decompose()
    
    # 메뉴 텍스트가 포함된 요소 제거
    menu_keywords = ["검색", "마이페이지", "전시해설", "안내", "행사", "전체일정", 
                     "특별기획전", "공연", "휴관일", "자세히보기", "과학관소식",
                     "로그인", "회원가입", "사이트맵", "ENG"]
    for elem in soup.find_all(text=True):
        if elem.parent and any(kw in str(elem) for kw in menu_keywords):
            # 부모 요소가 nav, ul, li 등 메뉴 구조면 제거
            parent = elem.parent
            if parent.name in ["nav", "ul", "li", "a", "button"]:
                parent.decompose()
    
    # 본문만 추출 시도 (구체적인 selector부터)
    content = None
    for sel in ["#voiceContents",
                ".board-body #voiceContents",
                ".view_cont", ".viewCont", 
                ".board_view .view_cont", ".board_view .viewCont",
                ".bbs_view .view_cont", ".bbs_view",
                ".notice_view", ".boardView",
                "article .view_cont", "article",
                "#contents .view_cont", "#contents .board_view",
                "#contents", ".contents", ".subContents", ".content"]:
        content = soup.select_one(sel)
        if content:
            # 너무 짧으면 (메뉴만 있을 가능성) 다음 selector 시도
            text_preview = content.get_text(strip=True)
            if len(text_preview) > 50:
                break
            content = None
    
    # 본문이 있으면 본문만, 없으면 전체
    target = content if content else soup.body if soup.body else soup
    
    text = target.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    return text


@tool
def get_scipia_homepage() -> str:
    """
    국립과천과학관 scipia 홈페이지(전관 안내의 기준 진입점) 텍스트를 확인합니다.
    - 목적: 전관 안내에서 가장 먼저 참조할 수 있는 공식 페이지 텍스트를 확보
    - 입력: 없음
    - 출력: Observation + 출처 URL + 페이지 텍스트
    """
    url = "https://www.sciencecenter.go.kr/scipia/"
    text = fetch_sciencecenter_page(url)
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


def _extract_scipia_links(html_text: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    links: list[dict] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        try:
            p = urlparse(abs_url)
        except Exception:
            continue
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc != "www.sciencecenter.go.kr":
            continue
        if not p.path.startswith("/scipia"):
            continue
        abs_url = abs_url.split("#")[0]
        if abs_url in seen:
            continue
        seen.add(abs_url)
        text = a.get_text(" ", strip=True)
        links.append({"text": text, "url": abs_url})
    return links


def _extract_scipia_image_urls(html_text: str, base_url: str, limit: int = 8) -> list[dict]:
    """scipia HTML에서 이미지 URL을 추출합니다.

    - 반환: [{"url": <absolute_url>, "alt": <alt_text>}, ...]
    - 목적: '동선/방문 경로' 같은 안내 이미지가 페이지에 포함된 경우 UI에서 그대로 보여주기.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    imgs: list[dict] = []
    seen = set()
    exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")

    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        abs_url = urljoin(base_url, src)
        abs_url = abs_url.split("#")[0]
        abs_url = abs_url.split("?")[0] + ("?" + abs_url.split("?", 1)[1] if "?" in abs_url else "")
        try:
            p = urlparse(abs_url)
        except Exception:
            continue
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc != "www.sciencecenter.go.kr":
            continue
        # scipia 페이지 내 이미지는 /scipia 또는 업로드 경로로 올 수 있어 path prefix를 강제하지 않음
        if not p.path.lower().endswith(exts):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        alt = (img.get("alt") or "").strip()
        imgs.append({"url": abs_url, "alt": alt})
        if len(imgs) >= max(1, int(limit)):
            break
    return imgs


def _is_route_like_image(url: str, alt: str) -> bool:
    u = (url or "").lower()
    a = (alt or "").lower()
    keywords = [
        "동선", "경로", "방문", "방문경로", "방문 경로", "안내", "route", "path", "way",
        "location", "map", "guide",
    ]
    return any(k in u or k in a for k in keywords)


@tool
def get_scipia_image_urls(url: str, limit: int = 6) -> str:
    """scipia 내부 페이지의 이미지(URL) 목록을 추출합니다.

    - 목적: 방문 경로/동선 안내 이미지가 페이지에 올라와 있을 때, LLM이 텍스트로 '추측'하지 않고
      공식 이미지를 그대로 보여주기 위함.
    - 입력:
      - url: https://www.sciencecenter.go.kr/scipia/... 형태
      - limit: 최대 이미지 개수(기본 6)
    - 출력: Observation + [출처] + [이미지-n] URL + (가능하면) [이미지-n-설명] alt
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("허용되지 않는 URL 스킴입니다.")
    if parsed.netloc and parsed.netloc != "www.sciencecenter.go.kr":
        raise ValueError("허용되지 않는 도메인입니다. (sciencecenter.go.kr만 허용)")
    if not parsed.path.startswith("/scipia"):
        raise ValueError("허용되지 않는 경로입니다. (/scipia 이하만 허용)")

    headers = {"User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    imgs = _extract_scipia_image_urls(response.text, url, limit=int(limit))
    lines: list[str] = []
    for i, it in enumerate(imgs, start=1):
        u = (it.get("url") or "").strip()
        if not u:
            continue
        lines.append(f"[이미지-{i}] {u}")
        alt = (it.get("alt") or "").strip()
        if alt:
            lines.append(f"[이미지-{i}-설명] {alt}")

    if not lines:
        lines = ["(이미지를 찾지 못했습니다. 해당 페이지에 이미지가 없거나 로딩 방식이 다를 수 있어요.)"]

    return "Observation:\n\n" + f"[출처] {url}\n\n" + "\n".join(lines)


@tool
def get_scipia_route_images(url: str, limit: int = 4) -> str:
    """scipia 내부 페이지에서 '동선/방문경로/안내 지도'로 보이는 이미지 URL만 추출합니다.

    - 목적: 모델이 임의 동선을 만들지 않고, 공식 페이지에 명시된 이미지 근거가 있을 때만
      UI에 이미지를 함께 표시하도록 지원합니다.
    - 입력:
      - url: https://www.sciencecenter.go.kr/scipia/... 형태
      - limit: 최대 이미지 개수(기본 4)
    - 출력: Observation + [출처] + [이미지-n] URL + (가능하면) [이미지-n-설명]
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("허용되지 않는 URL 스킴입니다.")
    if parsed.netloc and parsed.netloc != "www.sciencecenter.go.kr":
        raise ValueError("허용되지 않는 도메인입니다. (sciencecenter.go.kr만 허용)")
    if not parsed.path.startswith("/scipia"):
        raise ValueError("허용되지 않는 경로입니다. (/scipia 이하만 허용)")

    headers = {"User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    imgs = _extract_scipia_image_urls(response.text, url, limit=12)
    route_imgs = [it for it in imgs if _is_route_like_image(it.get("url", ""), it.get("alt", ""))]
    route_imgs = route_imgs[: max(1, int(limit))]

    lines: list[str] = []
    for i, it in enumerate(route_imgs, start=1):
        u = (it.get("url") or "").strip()
        if not u:
            continue
        lines.append(f"[이미지-{i}] {u}")
        alt = (it.get("alt") or "").strip()
        if alt:
            lines.append(f"[이미지-{i}-설명] {alt}")

    if not lines:
        lines = ["(해당 페이지에서 '동선/방문경로'로 보이는 이미지를 찾지 못했습니다.)"]

    return "Observation:\n\n" + f"[출처] {url}\n\n" + "\n".join(lines)


@tool
def get_scipia_navigation_links(limit: int = 30) -> str:
    """
    scipia 홈페이지에서 전관 안내에 유용한 링크(내부 /scipia 링크)를 추출합니다.
    - 목적: 사용자가 특정 공간/프로그램/행사를 물었을 때 관련 공식 페이지로 빠르게 안내하기 위한 링크 후보 확보
    - 입력:
      - limit: 반환할 최대 링크 수(기본 30)
    - 출력: Observation + 출처 URL + 링크 목록
    """
    url = "https://www.sciencecenter.go.kr/scipia/"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)"}, timeout=10)
    response.raise_for_status()
    links = _extract_scipia_links(response.text, url)
    links = links[: max(1, int(limit))]
    lines = []
    for i, it in enumerate(links, start=1):
        txt = (it.get("text") or "").strip()
        u = (it.get("url") or "").strip()
        if txt:
            lines.append(f"- [{i}] {txt}: {u}")
        else:
            lines.append(f"- [{i}] {u}")
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + "\n".join(lines)
    )


@tool
def search_scipia_links(keyword: str, limit: int = 20) -> str:
    """
    scipia 홈페이지의 링크 텍스트/URL에서 키워드를 포함하는 내부 링크를 찾아 반환합니다.
    - 목적: 전관(운영/프로그램/행사/공간) 질문에 대해 관련 공식 페이지 후보를 빠르게 찾기
    - 입력:
      - keyword: 찾고 싶은 키워드(예: "예약", "교육", "행사", "전시", "오시는 길")
      - limit: 반환할 최대 결과 수(기본 20)
    - 출력: Observation + 출처 URL + 매칭 링크 목록
    """
    kw = (keyword or "").strip().lower()
    if not kw:
        return "Observation:\n\n키워드가 비어 있어 검색할 수 없습니다."
    url = "https://www.sciencecenter.go.kr/scipia/"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (GNSM-AI-Guide)"}, timeout=10)
    response.raise_for_status()
    links = _extract_scipia_links(response.text, url)
    matches: list[dict] = []
    for it in links:
        txt = (it.get("text") or "").lower()
        u = (it.get("url") or "").lower()
        if kw in txt or kw in u:
            matches.append(it)
    matches = matches[: max(1, int(limit))]
    lines = []
    for i, it in enumerate(matches, start=1):
        txt = (it.get("text") or "").strip()
        u = (it.get("url") or "").strip()
        if txt:
            lines.append(f"- [{i}] {txt}: {u}")
        else:
            lines.append(f"- [{i}] {u}")
    if not lines:
        lines = ["- 일치하는 링크를 찾지 못했습니다. 키워드를 바꿔서 다시 시도해 주세요."]
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + "\n".join(lines)
    )


@tool
def get_scipia_page(url: str) -> str:
    """
    scipia 내부 페이지 URL을 받아 페이지 텍스트를 확인합니다. (전관 범용 크롤링)
    - 목적: 특정 공간/운영/프로그램/행사/규정 등 사실 확인이 필요할 때 공식 페이지 텍스트를 확보
    - 입력:
      - url: https://www.sciencecenter.go.kr/scipia/... 형태의 URL
    - 출력: Observation + 출처 URL + 페이지 텍스트
    """
    text = fetch_sciencecenter_page(url)
    return (
        "Observation:\n\n"
        f"[출처] {url}\n\n"
        + text
    )


# =========================================================
#  A. 공통/천문우주관 컴포넌트 (원천 텍스트/데이터 조각)
#     (컴포넌트는 세세하게 쪼개도 OK)
# =========================================================

def comp_astronomy_hall_facilities() -> list[str]:
    """
    천문우주관을 구성하는 핵심 시설/공간 목록을 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천문우주관이 어떤 하위 공간으로 구성되어 있는지(천체투영관/천문대/스페이스 아날로그) 목록 형태로 제공합니다.
    - 다른 안내 문장(개요/추천/동선 안내 등)을 구성할 때 기초 데이터로 사용합니다.

    [언제 사용해야 하는가]
    - ‘천문우주관 구성’이 필요한 소개/정리 문장을 만들 때
    - 선택지(“어느 공간이 궁금하세요?”)를 제시할 때

    [주의/전제]
    - 시설 구성은 장기적으로는 변경될 수 있으나, 본 컴포넌트는 ‘현재 기준 목록’의 역할만 합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return ["천체투영관", "천문대", "스페이스 아날로그"]


def comp_astronomy_hall_overview_sentence() -> str:
    """
    천문우주관을 한 문장으로 요약한 ‘개요 문장’을 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 사용자가 천문우주관이 무엇인지 빠르게 이해할 수 있도록, 구성과 성격을 1문장으로 소개합니다.

    [언제 사용해야 하는가]
    - 전체 소개(overview) 도구에서 첫 문장으로 사용
    - 상세 설명을 덧붙이기 전 ‘큰 그림’을 제시할 때

    [주의/전제]
    - 운영 시간/회차/요금 등 변동 가능 정보는 포함하지 않습니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "천문우주관은 천체투영관, 천문대, 스페이스 아날로그로 구성된 우주·천문 체험 공간입니다."


def comp_astronomy_hall_overview_detail_sentence() -> str:
    """
    천문우주관 각 공간의 역할을 덧붙이는 ‘상세 개요 문장’을 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 천체투영관/천문대/스페이스 아날로그가 각각 어떤 체험을 제공하는지 한 문단으로 설명합니다.

    [언제 사용해야 하는가]
    - 천문우주관 소개 도구(overview)에서, 기본 소개 다음에 이어지는 ‘설명 문장’으로 사용
    - 방문객이 “각 공간 뭐가 달라요?”를 물을 때

    [주의/전제]
    - 프로그램의 세부 회차/요금/예약 방식 등은 포함하지 않습니다(변동 가능성이 큼).

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "천체투영관은 360˚ 돔 스크린(풀돔) 영상 관람과 천체 시뮬레이션 라이브 해설을, "
        "천문대는 망원경·전파망원경 관측 프로그램을, "
        "스페이스 아날로그는 우주인 훈련·화성거주 훈련을 체험할 수 있습니다."
    )


def comp_astronomy_hall_outdoor_layout_guide() -> str:
    """
    천문우주관 야외전시장 동선 및 주요 시설 배치 안내 문장을 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - ‘상설전시관(중앙홀) 후문’ 기준으로 야외전시장 내 주요 시설의 상대 위치(정면/좌측/뒤편)를 안내합니다.
    - 유아차/휠체어 이동 가능 여부(계단·엘리베이터·오르막길 포함)를 반드시 함께 안내합니다.

    [언제 사용해야 하는가]
    - “천문우주관 어디 있어요?”, “천체투영관/스페이스 아날로그/천문대는 어디 방향이에요?”처럼
      위치·동선·상대 배치를 묻는 질문
    - “유모차/휠체어로 이동 가능해요?”처럼 접근성 문의가 포함된 질문

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "천문우주관은 상설전시관(중앙홀) 후문으로 나오시면 야외전시장에 위치해 있습니다. "
        "상설전시관 후문을 등지고 정면에는 둥근 구 모양의 건물인 천체투영관이 있습니다. "
        "상설전시관 후문을 등지고 좌측 방향에 별난공간(놀이터)가 있고, 별난공간을 지나 직진하면 회색 육각기둥 모양의 건물 스페이스 아날로그가 있습니다. "
        "천체투영관 뒤편에는 천문대가 있습니다. "
        "천문우주관으로 오시는 길은 계단과 엘리베이터, 오르막길로 이어져 있어 유아차와 휠체어 이용도 가능합니다."
    )


# (하위 호환) 예전 이름을 호출하던 코드가 있을 수 있어 alias를 남겨둡니다.
def comp_astronomy_hall_floor_guide_sentence() -> str:
    """
    [호환용 alias]
    - 기존 코드에서 사용하던 comp_astronomy_hall_floor_guide_sentence()를 유지하기 위한 별칭 함수입니다.
    - 실제 내용은 ‘층별 안내’가 아니라 ‘야외전시장 동선/배치 안내’이므로,
      신규 코드에서는 comp_astronomy_hall_outdoor_layout_guide() 사용을 권장합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return comp_astronomy_hall_outdoor_layout_guide()


# =========================================================
#  B. 천체투영관 컴포넌트
# =========================================================

def comp_planetarium_seat_count() -> int:
    """
    천체투영관 상영관 좌석 수(규모)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 좌석 규모를 설명하는 문장을 만들 때 사용하는 ‘기초 수치’입니다.

    [주의/전제]
    - 좌석 수는 시설 운영/개선에 따라 변경될 수 있으므로, 실제 운영 기준과 다를 수 있습니다.
      (민감 정보로 취급되면 별도 최신 확인 흐름과 함께 사용하세요.)

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return 250


def comp_planetarium_program_catalog() -> list[dict]:
    """
    천체투영관 정규 프로그램 카탈로그(예시)를 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - ‘프로그램 이름/대상/주제’ 수준의 목록을 제공합니다.
    - 시간표(회차/시각) 확정용 데이터가 아니라, 라인업 소개/추천 방향을 위한 데이터입니다.

    [주의/전제]
    - 실제 운영 라인업/작품 구성은 변동될 수 있습니다.
    - 반드시 ‘예시/목록’ 안내로 사용하고, 회차/시간은 최신 공지 확인을 유도하세요.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return [
        {"title": "3-2-1 발사", "target": "유아-초등 저학년", "type": "발사체/우주여행 애니메이션"},
        {"title": "일식과 월식", "target": "초등-성인", "type": "천문 현상"},
        {"title": "보이저", "target": "초등-성인", "type": "우주탐사"},
        {"title": "우주 끝으로", "target": "초등-성인", "type": "태양계에서 우주 끝까지 가상여행"},
        {"title": "오로라", "target": "초등-성인", "type": "지구/대기/자기장"},
        {"title": "별빛이 그린 이야기", "target": "초등-성인", "type": "광학식투영기 해설"},
    ]


def comp_planetarium_operation_rules_sentence() -> str:
    """
    천체투영관 관람 수칙(핵심)을 요약한 문장을 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 음식물/촬영/대화 등 상영 중 기본 제한과, 상영 시작 후 입장 제한 가능성을 안내합니다.

    [주의/전제]
    - 세부 운영은 현장 상황에 따라 달라질 수 있으므로, 원칙 중심으로만 사용합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "상영 중에는 음식물 반입, 플래시 촬영, 큰 소리 대화가 제한될 수 있으며, "
        "상영 시작 후에는 입장이 제한되거나 중간 입장이 어려울 수 있습니다."
    )


def comp_planetarium_opening_hours_policy_sentence() -> str:
    """
    천체투영관 상영 시간표가 변동될 수 있음을 안내하는 정책 문장을 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 평일/주말·공휴일에 따라 상영표가 다를 수 있으니, 방문 전 안내를 확인하도록 유도합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "천체투영관 상영 시간표는 평일과 주말·공휴일에 따라 다르며, 방문 전 상세 프로그램 안내를 꼭 참고해주세요!"


def comp_planetarium_reservation_rules_sentence() -> str:
    """
    천체투영관 예약/결제의 핵심 원칙을 짧게 안내하는 문장을 반환합니다.

    [주의/전제]
    - 예약/결제/취소 정책은 변동 가능성이 있으므로, 최종 기준 확인을 함께 안내하는 흐름이 안전합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "프로그램은 홈페이지에서 온라인 예약·결제할 수 있고, 예약일 기준 당일 미결제 시 자동 취소될 수 있습니다."


def comp_planetarium_refund_rules_sentence() -> str:
    """
    천체투영관 환불 원칙(핵심)을 안내하는 문장을 반환합니다.

    [주의/전제]
    - 민감한 규정이므로 예외를 단정하지 말고, 최종 안내 확인을 병행하는 것이 안전합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "환불은 프로그램 시작 전까지 가능하며, 시작 이후에는 환불이 불가능합니다."


def comp_planetarium_child_policy_sentence() -> str:
    """
    천체투영관 유아 동반/발권 관련 핵심 문장을 반환합니다.

    [주의/전제]
    - 연령 기준은 정책 변경 가능성이 있으므로 최종 안내 확인 문구와 함께 사용하는 것을 권장합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "36개월~7세 이하 유아는 성인 보호자 티켓과 함께 발권하고 동반 입장해야 합니다."


def comp_planetarium_seat_tip_sentence() -> str:
    """
    좌석 선택에 대한 ‘권장(팁)’ 문장을 반환합니다.

    [주의/전제]
    - 개인차(멀미/선호)에 따라 다를 수 있으므로 단정적 표현을 피합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "돔 화면 특성상 중앙에 가까운 좌석이 관람이 편할 수 있으나, 개인차가 있을 수 있습니다."


def comp_star_road_exhibition_basic_sentence() -> str:
    """
    천체투영관 상설전시 ‘별에게로 가는 길(The way to stars)’ 기본 소개 문장을 반환합니다.

    [주의/전제]
    - 영문 표기는 사용자가 안내문/번역을 요청할 때도 동일하게 유지합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "천체투영관 상설전시 「별에게로 가는 길(The way to stars)」은 "
        "천체투영관의 역사, 빛공해, 별자리에 숨겨진 비밀에 대해 소개합니다."
    )


def comp_star_road_exhibition_visit_sentence() -> str:
    """
    ‘별에게로 가는 길(The way to stars)’ 관람 방식(자유 관람) 안내 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "천체투영관 1층 복도 전시로 상영 전후에 자유 관람 형태로 즐길 수 있습니다."


def comp_star_road_guided_tour_sentence() -> str:
    """
    ‘별에게로 가는 길’ 전시해설(해설 프로그램) 성격 안내 문장을 반환합니다.

    [주의/전제]
    - 운영 요일/시간/정원/요금은 변동 가능성이 크므로 홈페이지 안내 기준임을 명확히 합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "전시해설은 해설자와 함께 전시 공간을 돌며 설명을 듣는 프로그램이며, "
        "운영 요일·시간·정원·요금은 홈페이지 안내 기준입니다."
    )


def comp_planetarium_group_price_sentence() -> str:
    """
    천체투영관 단체 요금/할인 관련 핵심 안내 문장을 반환합니다.

    [주의/전제]
    - 요금은 민감 정보이며 변경될 수 있으므로, 최종 확인 문구를 병행하는 것이 안전합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "단체 관람 요금은 유아 1,000원, 청소년 및 성인 2,000원이며, "
        "별도의 단체 할인이나 인솔자 할인은 제공되지 않습니다."
    )


def comp_planetarium_group_reservation_sentence() -> str:
    """
    천체투영관 단체 관람의 ‘운영 방식(개요)’을 안내하는 문장을 반환합니다.

    [주의/전제]
    - 실제 배정/절차는 운영 상황에 따라 달라질 수 있습니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "단체 관람은 1학기(3~7월), 2학기(9~12월) 평일 프로그램을 대상으로 하며, 온라인 예매로 운영됩니다."


def comp_planetarium_floor_sentence() -> str:
    """
    천체투영관 층 구성과 좌석 규모를 한 문장으로 안내하는 문장을 반환합니다.

    [주의/전제]
    - 좌석 수는 comp_planetarium_seat_count()에 의존합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    seat = comp_planetarium_seat_count()
    return f"천체투영관은 1층(로비·상설전시 등)과 2층(돔 상영관, 약 {seat}석)으로 구성됩니다."


def comp_planetarium_program_list_sentence() -> str:
    """
    천체투영관 정규 프로그램 예시 목록을 한 문장으로 구성해 반환합니다.

    [주의/전제]
    - ‘예시 목록’이며 세부 회차/시간은 상영표 공지 기준임을 함께 포함합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    titles = [p["title"] for p in comp_planetarium_program_catalog()]
    return "정규 프로그램 예: " + ", ".join([f"「{t}」" for t in titles]) + " (세부 회차/시간은 상영표 공지 기준)"


def comp_planetarium_daytype_by_date(date_str: str) -> str:
    """
    입력 날짜(YYYY-MM-DD)를 평일/주말 유형으로 구분합니다.

    [무엇을 하는 컴포넌트인가]
    - 토/일 여부만 확실하게 판별합니다.
    - 법정 공휴일 여부는 포함하지 않습니다.

    [주의/전제]
    - 입력 형식이 맞지 않으면 예외가 발생할 수 있습니다(상위 도구에서 try/except 처리 권장).

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = dt.weekday()  # 월=0 ... 일=6
    return "주말/공휴일" if weekday >= 5 else "평일"


def comp_planetarium_age_reco_short(age: int) -> str:
    """
    연령 기반 천체투영관 추천 방향(짧은 문장)을 반환합니다.

    [무엇을 하는 컴포넌트인가]
    - 나이에 따라 ‘부담이 적은 콘텐츠 방향’과 ‘추천 프로그램 예시’를 제안합니다.
    - 회차/시각/상영 여부는 확정하지 않습니다.

    [주의/전제]
    - 개인차(어두운 환경, 음향, 멀미 등)가 있으므로 단정 표현을 피합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    if age <= 3:
        return (
            "만 3세 이하의 경우 어두운 환경과 큰 음향, 상영 시간 특성상 관람이 어려울 수 있어 "
            "관람 가능 연령 및 규정을 먼저 확인한 뒤, 가능하면 조금 더 자란 이후 관람을 권장드립니다."
        )
    if age <= 7:
        return "유아·초등 저학년에게는 「3-2-1 발사」처럼 재미있는 애니메이션 프로그램을 우선 추천합니다."
    return "초등 고학년 이상·성인에게는 「일식과 월식」, 「보이저」, 「우주 끝으로」, 「오로라」 등 심화 주제 프로그램을 추천합니다."


# =========================================================
#  C. 천문대 컴포넌트
# =========================================================

def comp_observatory_location_sentence() -> str:
    """
    천문대 위치를 간단히 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "천문대는 국립과천과학관 야외전시장에 있으며, 천체투영관 뒤편 언덕 위에 위치해 있습니다."


def comp_observatory_program_catalog() -> list[dict]:
    """
    천문대 프로그램 '이름/구성' 카탈로그(고정).
    - 주간: 태양 관측 및 수업 / 주간 공개관측 / 망원경실습 <스타파인더>
    - 야간: 야간 천체관측 <별바라기> / 달과별 관측회
    - 주의: '이번주 운영 여부/날짜별 운영일/예약 오픈 여부'는 매주 공지로 바뀌므로 여기서 확정 금지.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return [
        {"name": "태양 관측 및 수업", "type": "주간"},
        {"name": "주간 공개관측", "type": "주간"},
        {"name": "망원경실습 <스타파인더>", "type": "주간"},
        {"name": "야간 천체관측 <별바라기>", "type": "야간"},
        {"name": "달과별 관측회", "type": "야간"},
    ]


def comp_observatory_day_program_sentence() -> str:
    """
    주간(낮) 천문대 프로그램 성격을 간단히 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "낮에는 태양관측 등 주간 관측 프로그램이 운영될 수 있습니다."


def comp_observatory_night_program_sentence() -> str:
    """
    야간 천문대 프로그램 성격을 간단히 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "밤에는 달·행성·계절별 별 등을 대상으로 한 야간 관측 프로그램이 운영될 수 있습니다."


def comp_observatory_radio_program_sentence() -> str:
    """
    전파 프로그램(전파망원경 활용) 성격을 간단히 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "전파망원경을 활용한 전파 프로그램(예: ‘전파로 본 우주’)이 운영될 수 있습니다."


def comp_observatory_weather_policy_sentence() -> str:
    """
    기상에 따른 취소/대체 가능성을 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "구름·비·황사 등 기상 상황에 따라 관측이 취소되거나 대체 프로그램으로 진행될 수 있습니다."


def comp_observatory_accessibility_sentence() -> str:
    """
    천문대 접근성(이동 난이도) 관련 기본 안내 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "천문대는 언덕 이동 구간이 포함될 수 있어 경사로나 계단 구간이 있을 수 있습니다."


def comp_observatory_accessibility_reco_sentence() -> str:
    """
    접근성 이슈가 있는 관람객에게 ‘사전 문의 권장’ 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "이동이 어려운 관람객은 방문 전 동선과 참여 가능 여부를 사전 문의하는 것을 권장드립니다."


def comp_observatory_safety_sentence() -> str:
    """
    천문대 안전 수칙(핵심)을 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "관측실/옥상 등에서는 안내자의 지시에 따라 이동하고, 장비를 임의로 만지지 않으며 계단·문턱에 주의해야 합니다."


def comp_observatory_reservation_policy_sentence() -> str:
    """
    천문대 예약 방식 변동 가능성을 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "프로그램 종류에 따라 예약 방식이 달라질 수 있어, 최신 운영 방식은 홈페이지 공지 또는 현장 안내를 확인하는 것이 좋습니다."


def comp_observatory_telescopes_sentence() -> str:
    """
    천문대에서 활용 가능한 대표 관측 장비를 소개하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "천문대에는 주망원경(1m급 반사망원경 등)과 보조 관측 장비, 태양 관측 장비가 활용될 수 있습니다."


def comp_observatory_radio_facility_sentence() -> str:
    """
    전파망원경 설비(가능) 안내 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "전파망원경 설비가 있으며, 전파 프로그램에서 활용될 수 있습니다."


def comp_observatory_group_sentence() -> str:
    """
    천문대 단체 운영 가능성을 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "학교/단체 프로그램은 별도 일정과 내용으로 운영될 수 있으며, 단체 예약을 통해 조정될 수 있습니다."


# =========================================================

def comp_observatory_group_reservation_sentence() -> str:
    """
    천문대 단체 예약/운영 방식(키워드: 단체/예약/절차) 안내 문장을 반환합니다.

    [주의/전제]
    - 단체 운영은 시즌/프로그램/기상/시설 상황에 따라 달라질 수 있어 확정 표현을 피합니다.
    - 최신 기준은 ‘천문대 단체 이용안내’ 및 주간 운영 공지에서 확인하도록 유도합니다.
    """
    return (
        "천문대 단체 관람/체험은 프로그램·일정에 따라 운영 방식과 예약 절차가 달라질 수 있습니다. "
        "방문 날짜(평일/주말)와 인원·연령을 확인한 뒤, 홈페이지 단체 안내/운영 공지 기준으로 예약을 진행해주세요."
    )


def comp_observatory_group_price_sentence() -> str:
    """
    천문대 단체 요금/할인 관련 안내 문장을 반환합니다.

    [주의/전제]
    - 요금은 민감 정보이며 변경될 수 있으므로, 구체 금액 단정 대신 ‘공식 안내 확인’을 포함합니다.
    """
    return "단체 요금과 할인 적용 여부는 프로그램별·시기별로 달라질 수 있으니, 홈페이지 단체 이용안내의 최신 기준을 확인해주세요."


def comp_observatory_group_policy_sentence() -> str:
    """
    천문대 단체 운영 시 유의사항(키워드: 인솔자/안전/집합/지각/기상) 안내 문장을 반환합니다.
    """
    return (
        "단체 참여 시에는 인솔자 동반, 집합 시간 준수, 안전 수칙 안내(장비·이동 동선)를 따라야 합니다. "
        "또한 기상 상황에 따라 관측이 취소되거나 대체 프로그램으로 변경될 수 있습니다."
    )

#  D. 스페이스 아날로그 컴포넌트
# =========================================================

def comp_space_analog_overview_sentence() -> str:
    """
    스페이스 아날로그의 성격을 한 문장으로 소개합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "스페이스 아날로그는 심우주 탐사의 시작점이 될 화성 탐사를 위한 우주인 훈련과 화성에서의 미션 수행을 단계별로 체험해 볼 수 있는 체험형 전시공간입니다."


def comp_space_analog_program_catalog() -> list[dict]:
    """
    스페이스 아날로그 프로그램 카탈로그(고정).
    - 주의: '잔여석/당일 운영 여부'는 공지/예약 시스템 기준. 여기서 확정 금지.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return [
        {
            "name": "화성거주 체험 (A)",
            "desc": "연료전지 조립",
            "fee": 2000,
            "age": "초3 이상",
            "capacity": 18,
        },
        {
            "name": "화성거주 체험 (B)",
            "desc": "태양전지 조립",
            "fee": 2000,
            "age": "초3 이상",
            "capacity": 18,
        },
        {
            "name": "심화 체험",
            "desc": "아날로그 및 화성거주 체험",
            "fee": 10000,
            "age": "초5 이상",
            "capacity": 18,
        },
        {
            "name": "기본 해설",
            "desc": "아날로그 및 화성거주 해설",
            "fee": 2000,
            "age": "초3 이상",
            "capacity": 24,
        },
    ]


def comp_space_analog_timeslot_catalog() -> dict:
    """
    스페이스 아날로그 시간표 카탈로그(고정 '틀').
    - 주의: 실제 운영/변동은 홈페이지 안내 기준.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return {
        "weekday": [
            {"time": "10:00~10:40", "program": "화성거주 체험 (A)"},
            {"time": "11:00~11:40", "program": "화성거주 체험 (B)"},
            {"time": "13:30~14:10", "program": "화성거주 체험 (A)"},
            {"time": "14:30~15:10", "program": "화성거주 체험 (B)"},
            {"time": "16:00~16:40", "program": "아날로그 및 화성거주 해설"},
        ],
        "weekend_holiday": [
            {"time": "10:00~10:40", "program": "화성거주 체험 (A)"},
            {"time": "11:00~11:40", "program": "화성거주 체험 (B)"},
            {"time": "13:30~15:30", "program": "심화 체험"},
            {"time": "16:00~16:40", "program": "아날로그 및 화성거주 해설"},
        ],
    }


def comp_space_analog_program_list_sentence() -> str:
    """스페이스 아날로그 프로그램을 '정식 명칭' 기준으로 한 줄로 정리."""
    return (
        "화성거주 체험 (A)(연료전지 조립), 화성거주 체험 (B)(태양전지 조립), "
        "심화 체험(아날로그 및 화성거주 체험), 기본 해설(아날로그 및 화성거주 해설)"
    )


def comp_space_analog_zone_sentence() -> str:
    """
    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    
    스페이스 아날로그 존 구성 예시를 안내하는 문장을 반환합니다.
    """
    return "존 구성 예: 임무 브리핑 존, 우주비행사 준비 존, 화성 기지 존, 임무 정리/디브리핑 존."


def comp_space_analog_course_sentence() -> str:
    """
    스페이스 아날로그 기본/심화 과정의 성격 차이를 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "기본 과정은 초등 3학년 이상 입문자 친화 구성, "
        "심화 과정은 초등 5학년 이상 또는 청소년·성인 대상의 임무/팀워크 요소를 강화한 구성입니다."
    )

def comp_space_analog_timeslot_catalog() -> dict:
    """
    스페이스 아날로그 시간표 카탈로그(고정 '틀').
    - 주의: 실제 운영/변동은 홈페이지 안내 기준.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return {
        "weekday": [
            {"time": "10:00~10:40", "program": "화성거주 체험 (A)"},
            {"time": "11:00~11:40", "program": "화성거주 체험 (B)"},
            {"time": "13:30~14:10", "program": "화성거주 체험 (A)"},
            {"time": "14:30~15:10", "program": "화성거주 체험 (B)"},
            {"time": "16:00~16:40", "program": "아날로그 및 화성거주 해설"},
        ],
        "weekend_holiday": [
            {"time": "10:00~10:40", "program": "화성거주 체험 (A)"},
            {"time": "11:00~11:40", "program": "화성거주 체험 (B)"},
            {"time": "13:30~", "program": "[심화 2시간] 아날로그 훈련 / 화성거주 체험 (A, B)"},
            {"time": "14:30~15:10", "program": "화성거주 체험 (B)"},
            {"time": "16:00~16:40", "program": "아날로그 및 화성거주 해설"},
        ],
    }

def comp_space_analog_safety_sentence() -> str:
    """
    스페이스 아날로그 안전/유의사항(핵심)을 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "체험 특성상 계단·좁은 통로 이동이 포함될 수 있고, 권장 조건(신장·체중 등)이 적용될 수 있어 "
        "운영직원의 안내를 꼭 따라주세요."
    )

def comp_space_analog_reservation_sentence() -> str:
    """
    스페이스 아날로그 예약/규정이 프로그램별로 달라질 수 있음을 안내하는 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return (
        "스페이스 아날로그는 예약제로 운영됩니다."
        "프로그램별 연령·정원·집합 시간·취소/환불·지각 규정은 각 안내를 확인하는 것이 좋습니다."
    )


def comp_space_analog_visit_tip_sentence() -> str:
    """
    스페이스 아날로그 방문 팁(복장/도착) 안내 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "움직이기 편한 복장과 미끄럽지 않은 신발을 권장하며, 시작 시간보다 여유 있게 도착하는 것이 좋습니다."


def comp_space_analog_group_sentence() -> str:
    """
    스페이스 아날로그 단체 운영 가능성 안내 문장을 반환합니다.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return "학교/단체용 프로그램은 단체 커리큘럼과 시간표로 운영될 수 있으며, 사전 협의로 구성/인원 조정이 가능할 수 있습니다."


def comp_space_analog_group_reservation_sentence() -> str:
    """
    스페이스 아날로그 단체 예약/운영 방식(키워드: 단체/예약/절차) 안내 문장을 반환합니다.

    [주의/전제]
    - 단체 운영은 커리큘럼/회차/정원/운영 일정에 따라 달라질 수 있으므로 확정 표현을 피합니다.
    - 최신 기준은 ‘스페이스 아날로그 단체 이용안내’의 공지 기준으로 안내합니다.
    """
    return (
        "스페이스 아날로그 단체 체험은 단체 전용 커리큘럼/시간표로 운영될 수 있어, "
        "방문 날짜(평일/주말), 인원, 참여자 연령을 기준으로 홈페이지 단체 안내에 따라 사전 예약/협의를 진행해주세요."
    )


def comp_space_analog_group_price_sentence() -> str:
    """
    스페이스 아날로그 단체 요금/할인 관련 안내 문장을 반환합니다.

    [주의/전제]
    - 요금은 변동 가능성이 있으므로 구체 금액 단정 대신 ‘공식 안내 확인’을 포함합니다.
    """
    return "단체 요금과 할인 적용 여부는 프로그램·코스에 따라 달라질 수 있으니, 홈페이지 단체 이용안내의 최신 기준을 확인해주세요."


def comp_space_analog_group_policy_sentence() -> str:
    """
    스페이스 아날로그 단체 운영 유의사항(키워드: 집합/지각/안전/보호자/복장) 안내 문장을 반환합니다.
    """
    return (
        "단체 참여 시에는 집합 시간·안전 수칙(체험 장비/공간 이동)을 준수해야 하며, "
        "프로그램에 따라 복장/신발/보호자 동반 등 조건이 있을 수 있어 사전 안내를 확인하는 것이 좋습니다."
    )


def comp_space_analog_age_reco_short(age: int) -> str:
    """
    연령 기반 스페이스 아날로그 추천 방향(짧은 문장)을 반환합니다.

    [주의/전제]
    - 실제 운영 코스/규정은 변동 가능성이 있으므로, 최종 안내 확인 흐름과 함께 사용하세요.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    if age < 10:
        return "초등 저학년은 부담이 적은 기본 과정이나 전시해설 성격의 참여를 우선 권장하며, 컨디션에 따라 선택하는 것이 좋습니다."
    if age < 13:
        return "초등 고학년은 기본·심화 모두 도전할 수 있으며, 팀워크/임무 수행 요소가 있는 체험에 적합합니다."
    return "청소년·성인은 심화 과정과 전시해설을 조합해 우주탐사 맥락을 더 깊게 이해하는 구성이 잘 맞을 수 있습니다."


# =========================================================
#  E. @tool — 선배님 스타일: return은 짧게, docstring은 길게
# =========================================================

# ---------------- 공통/천문우주관 ----------------

@tool
def get_astronomy_hall_overview() -> str:
    """
    천문우주관 개요 안내 도구.

    [무엇을 하는 도구인가]
    - 사용자가 “천문우주관이 뭐예요?”, “여기에서 뭐 할 수 있어요?”처럼 전반적인 소개를 요청할 때,
      천문우주관의 구성(천체투영관/천문대/스페이스 아날로그)과 각 공간의 역할을 간단히 설명합니다.
    - 방문객이 ‘무엇을 기대하면 되는지’ 큰 그림을 잡게 하는 것이 목적입니다.

    [언제 호출해야 하는가]
    - 사용자가 천문우주관 전체를 한 번에 이해하고 싶어 하는 질문을 할 때 사용합니다.
      예) “천문우주관에서 뭐해요?”, “아이랑 가면 뭐가 좋아요?”, “세 공간이 뭐가 달라요?”
    - 특정 공간(천체투영관/천문대/스페이스 아날로그)으로 질문이 한정되지 않은 경우에 적합합니다.

    [언제 호출하면 안 되는가]
    - 사용자가 이미 특정 공간을 지정해 질문하는 경우에는 해당 전용 도구를 사용합니다.
    - 시간표/회차/요금/예약 등 ‘운영 정보 확정’이 핵심이면 해당 규정/운영 도구로 분리합니다.

    [주의/전제]
    - 운영 시간표와 세부 회차는 변동 가능성이 크므로 본 도구에서 확정하지 않습니다.
    """
    return f"{comp_astronomy_hall_overview_sentence()} {comp_astronomy_hall_overview_detail_sentence()}"


@tool
def get_astronomy_hall_outdoor_layout_guide() -> str:
    """
    천문우주관 야외전시장 ‘위치/동선/배치’ 안내 도구.

    [무엇을 하는 도구인가]
    - 상설전시관(중앙홀) 후문 기준으로 야외전시장 내 주요 시설의 상대 위치를 안내합니다.
      (정면=천체투영관 / 좌측=별난공간 지나 스페이스 아날로그 / 뒤편=천문대)
    - 유아차/휠체어 이동 가능 여부(계단/엘리베이터/오르막길 포함)를 함께 안내합니다.

    [언제 호출해야 하는가]
    - “천문우주관 어디 있어요?”, “천체투영관/스페이스 아날로그/천문대가 어디 방향이에요?”
    - “유모차/휠체어로 이동 가능해요?”처럼 접근성 문의

    [언제 호출하면 안 되는가]
    - 특정 시설(천문대) 내부 안전/예약/기상 정책처럼 ‘주제 전용’ 문의에는 해당 전용 도구를 사용합니다.
    - 운영 시간표/회차/요금 확정은 별도 도구 또는 공지 확인으로 분리합니다.

    [주의/전제]
    - 행사/통제 등으로 체감 동선이 달라질 수 있습니다.
    """
    return comp_astronomy_hall_outdoor_layout_guide()


# (하위 호환) 기존 도구명을 유지하고 싶으면 wrapper로 남겨둡니다.
@tool
def get_astronomy_hall_floor_guide() -> str:
    """
    [호환용 wrapper]
    - 기존 코드에서 사용하던 get_astronomy_hall_floor_guide()를 유지하기 위한 래퍼 도구입니다.
    - 실제 내용은 ‘층별 안내’가 아니라 ‘야외전시장 동선/배치 안내’이므로,
      신규 코드에서는 get_astronomy_hall_outdoor_layout_guide() 사용을 권장합니다.
    """
    return get_astronomy_hall_outdoor_layout_guide()


# ---------------- 천체투영관 ----------------
# (이하 @tool 블록은 원문 유지 — 이미 docstring+return 구조가 잘 갖춰져 있습니다.)

@tool
def get_planetarium_route_guide() -> str:
    """
    천체투영관 ‘동선(어떻게 가요?)’ 전용 안내 도구.
    - ‘상설전시관(중앙홀) 후문’ 기준 야외전시장 배치 안내 문구를 그대로 제공합니다.
    - 마지막에 문의 전화번호를 포함합니다.
    """
    return f"{comp_astronomy_hall_outdoor_layout_guide()}\n\n문의: 02-3677-1561"


@tool
def get_planetarium_overview() -> str:
    """
    천체투영관 개요(무엇을 하는 곳인지) 안내 도구.

    [무엇을 하는 도구인가]
    - 천체투영관이 어떤 공간인지(돔 상영 + 천체 시뮬레이션 해설)를 큰 틀에서 소개합니다.
    - 세부 회차/시간표/당일 운영은 변동 가능성이 높으므로, ‘시간표/몇 시’ 질문에는
      공지/시간표 도구(크롤링)를 우선 사용하도록 유도합니다.

    [언제 호출해야 하는가]
    - “천체투영관이 뭐예요?”, “돔에서 뭐 해요?”, “어떤 프로그램이 있어요?”처럼 개요 소개가 필요할 때.

    [언제 호출하면 안 되는가]
    - “오늘 몇 시?”, “주말 시간표”, “예약 가능?”처럼 날짜 의존/확정 정보가 핵심인 질문(시간표 도구 사용).

    [주의/전제]
    - 상영작/편성/회차는 시즌·행사에 따라 바뀔 수 있습니다.
    """
    return (
        "천체투영관은 돔(screen) 안에서 우주·천문 주제의 영상(풀돔/돔영화)을 관람하고, "
        "필요에 따라 천체 시뮬레이션 해설도 함께 듣는 공간입니다. "
        "상영작과 회차(몇 시)는 변동될 수 있으니, 특정 날짜의 시간표가 필요하면 ‘오늘/주말 시간표’로 물어봐 주세요."
    )

@tool
def get_planetarium_operation_info() -> str:
    """
    천체투영관 관람 수칙(핵심) 안내 도구.

    [무엇을 하는 도구인가]
    - 상영관 관람 중 대표적인 제한(음식물/촬영/대화 등)과 입장 유의사항을 짧게 안내합니다.
    - 방문객이 ‘상영 중 행동’과 ‘입장 타이밍’을 이해하도록 돕는 것이 목적입니다.

    [언제 호출해야 하는가]
    - 관람 규정 관련 질문에서 사용합니다.
      예) “사진 찍어도 돼요?”, “상영 중에 들어가도 돼요?”, “아이랑 들어가도 되나요?”

    [언제 호출하면 안 되는가]
    - 예약/환불/요금/유아 동반 규정처럼 더 민감하고 구체적인 운영 규정은 전용 도구를 사용합니다.
    - 특정 회차/시각을 확정하는 답변을 만들기 위해 사용하지 않습니다.

    [주의/전제]
    - 세부 운영은 현장 안내/공지에 따라 달라질 수 있으나, 안전·질서 관련 원칙은 안내가 필요합니다.
    """
    return comp_planetarium_operation_rules_sentence()


@tool
def get_planetarium_opening_hours() -> str:
    """
    천체투영관 상영 시간 운영 원칙 안내 도구.

    [무엇을 하는 도구인가]
    - 상영 시간표가 ‘평일/주말·공휴일’에 따라 달라질 수 있다는 원칙과,
      최신 공지를 확인해야 한다는 안내를 제공합니다.
    - 특정 날짜의 ‘정확한 회차/시각’을 확정하는 도구가 아닙니다.

    [언제 호출해야 하는가]
    - 시간표가 바뀔 수 있음을 설명해야 할 때 사용합니다.
      예) “주말이랑 평일 시간표 달라요?”, “오늘 몇 시에 해요?”(단, 확정 요구가 아닐 때)

    [언제 호출하면 안 되는가]
    - 사용자가 특정 날짜/회차의 정확한 시각을 ‘확정’해달라고 요청하는 경우:
      본 도구는 확정 답변 대신 공지 확인을 안내하는 용도입니다.

    [주의/전제]
    - 최신 상영표는 홈페이지 공지사항을 기준으로 합니다.
    """
    return comp_planetarium_opening_hours_policy_sentence()


@tool
def get_planetarium_program_list() -> str:
    """
    천체투영관 정규 프로그램 ‘예시 목록’ 안내 도구.

    [무엇을 하는 도구인가]
    - “무슨 프로그램이 있어요?” 질문에 대해 작품명 수준의 예시 목록을 제공합니다.
    - 시간표(회차/시각)는 변동 가능성이 크므로 본 도구에서 확정하지 않습니다.

    [언제 호출해야 하는가]
    - 프로그램 라인업을 빠르게 훑고 싶어 하는 질문에 사용합니다.
      예) “뭐 볼 수 있어요?”, “아이랑 볼 만한 거 있어요?”

    [언제 호출하면 안 되는가]
    - 특정 날짜/회차를 확정해야 한다면 상영표 공지 확인 안내(또는 별도 도구)로 분리합니다.

    [주의/전제]
    - 목록은 ‘정규 프로그램 예시’이며 운영 회차는 공지된 상영표가 기준입니다.
    """
    return comp_planetarium_program_list_sentence()


@tool
def get_planetarium_programs_by_date(date: str) -> str:
    """
    입력 날짜 기준으로 ‘평일/주말·공휴일’ 시간표 유형을 판단하는 도구.

    [무엇을 하는 도구인가]
    - 사용자가 날짜를 주었을 때 그 날짜가 평일인지, 주말(토/일)인지 판단해
      “어떤 유형의 상영표를 참고해야 하는지”만 안내합니다.
    - 실제 회차/시각은 공지 상영표가 기준이며 본 도구가 확정하지 않습니다.

    [언제 호출해야 하는가]
    - 사용자가 날짜를 명시했고, 평일/주말 여부에 따라 시간표가 달라지는지 궁금해할 때 사용합니다.
      예) “2025-12-20에는 평일 시간표예요?” “이 날은 주말 상영표 봐야 해요?”

    [언제 호출하면 안 되는가]
    - 사용자가 날짜 형식을 주지 않았거나, 날짜가 불명확하면 먼저 날짜를 확인해야 합니다.
    - 공휴일(법정 공휴일) 여부까지 확정해달라는 질문에는 본 도구만으로 단정하지 않습니다.
      (이 도구는 토/일 기준의 ‘주말’ 판정만 확실히 할 수 있습니다.)

    [주의/전제]
    - 입력 형식은 YYYY-MM-DD 입니다.
    """
    try:
        kind = comp_planetarium_daytype_by_date(date)
        return f"{date}은(는) {kind}에 해당하므로, 보통 {kind} 상영표를 우선 확인하시면 됩니다(세부 회차/시간은 최신 상영표 공지 기준)."
    except Exception:
        return "날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식(예: 2025-12-15)으로 입력해 주세요."


@tool
def recommend_planetarium_programs_by_age(age: int) -> str:
    """
    연령 기반 천체투영관 프로그램 추천(방향) 도구.

    [무엇을 하는 도구인가]
    - “아이 몇 살인데 뭐가 좋아요?” 같은 질문에 대해, 연령대별로 무리 없는 관람 방향을 짧게 제안합니다.
    - 개별 프로그램의 회차/시각/상영 여부는 상영표 공지를 확인해야 합니다.

    [언제 호출해야 하는가]
    - 사용자가 나이를 명확히 제공했을 때, 어떤 유형의 콘텐츠가 적합한지 제안이 필요할 때 사용합니다.

    [언제 호출하면 안 되는가]
    - 나이가 불명확하면 먼저 나이를 확인하는 것이 우선입니다.
    - 의료/감각 민감도 등 개인 특성에 대해 단정적 결론을 내리기 위해 사용하지 않습니다.

    [주의/전제]
    - 추천은 ‘방향’이며, 실제 선택은 관람객의 선호/컨디션에 따라 달라질 수 있습니다.
    """
    return comp_planetarium_age_reco_short(age)


@tool
def get_planetarium_exhibition_info() -> str:
    """
    상설전시 ‘별에게로 가는 길(The way to stars)’ 기본 소개 도구.

    [무엇을 하는 도구인가]
    - “별에게로 가는 길이 뭐예요?”처럼 전시 성격을 궁금해하는 질문에,
      전시 주제(별/은하/우주탐사 등)와 관람 방식(상설/자유 관람)을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - 상설전시 소개 또는 무료/자유 관람 여부를 맥락상 확인해야 하는 질문에서 사용합니다.

    [언제 호출하면 안 되는가]
    - 전시해설(도슨트/해설 프로그램) 운영 요일·시간·정원·요금처럼 세부 운영을 확정해야 할 때는 전시해설 도구를 사용합니다.

    [주의/전제]
    - 현장 동선/운영은 행사나 통제에 따라 달라질 수 있습니다.
    """
    return f"{comp_star_road_exhibition_basic_sentence()} {comp_star_road_exhibition_visit_sentence()}"


@tool
def get_star_road_exhibition_info() -> str:
    """
    상설전시 ‘별에게로 가는 길’ 전시해설(해설 프로그램) 안내 도구.

    [무엇을 하는 도구인가]
    - 해설자와 함께 전시를 돌며 설명을 듣는 ‘전시해설 프로그램’의 성격을 안내하고,
      운영 세부(요일/시간/정원/요금)는 홈페이지 안내 기준임을 명확히 합니다.

    [언제 호출해야 하는가]
    - “전시 해설도 있나요?”, “해설 예약은 어디서 해요?”처럼 전시해설 프로그램 자체를 묻는 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 사용자가 “오늘 몇 시예요?”처럼 세부 운영을 확정해달라고 요청하면,
      본 도구는 확정보다는 ‘홈페이지 확인’ 안내를 제공하는 용도임을 분명히 해야 합니다.

    [주의/전제]
    - 운영 정보는 변동 가능성이 있으므로 최신 안내를 확인하는 것이 안전합니다.
    """
    return comp_star_road_guided_tour_sentence()


@tool
def get_planetarium_group_program_info() -> str:
    """
    천체투영관 단체 이용(요금/할인/사전 예약) 안내 도구.

    [무엇을 하는 도구인가]
    - 학교/단체 방문자가 가장 자주 묻는 핵심(단체 요금, 할인 여부, 사전 예약 필요)을 간단히 안내합니다.

    [언제 호출해야 하는가]
    - “단체 요금 얼마예요?”, “인솔자 할인 있어요?”, “단체 할인 되나요?”, “단체 예약해야 해요?”에 사용합니다.

    [언제 호출하면 안 되는가]
    - 특정 날짜의 단체 배정 가능 여부/세부 절차를 확정해야 하면, 관련 안내(공지/예약 시스템) 확인을 유도합니다.

    [주의/전제]
    - 단체 운영 방식은 시즌/운영 상황에 따라 세부 절차가 달라질 수 있습니다.
    """
    return f"{comp_planetarium_group_price_sentence()} {comp_planetarium_group_reservation_sentence()}"


@tool
def get_planetarium_facility_info() -> str:
    """
    천체투영관 시설/동선(층 구성·좌석 규모) 요약 도구.

    [무엇을 하는 도구인가]
    - “상영관 몇 층이에요?”, “좌석 몇 석이에요?”처럼 시설 규모·층 구성을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - 시설 규모/층 구성/기본 동선이 핵심인 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 구체 회차/시간표, 예약/환불/요금 규정 질문에는 전용 도구를 사용합니다.

    [주의/전제]
    - 행사·통제에 따라 관람 동선이 일부 달라질 수 있습니다.
    """
    return comp_planetarium_floor_sentence()


@tool
def get_planetarium_floor_guide() -> str:
    """
    천체투영관 층별 구성 안내 도구.

    [무엇을 하는 도구인가]
    - 사용자가 ‘천체투영관’으로 범위를 한정해 층별 구성을 물을 때,
      1층/2층 구성과 이동 방법을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - “천체투영관 2층은 어떻게 가요?”, “로비는 1층이에요?” 등에 사용합니다.

    [언제 호출하면 안 되는가]
    - 천문우주관 전체 층 안내가 필요하면 천문우주관 동선/배치 안내 도구를 사용합니다.

    [주의/전제]
    - 현장 운영 상황에 따라 세부 동선은 달라질 수 있습니다.
    """
    return comp_planetarium_floor_sentence()


@tool
def get_planetarium_seat_info() -> str:
    """
    천체투영관 좌석/관람 환경 안내 도구.

    [무엇을 하는 도구인가]
    - 좌석 수(규모)와 좌석 선택에 대한 ‘방향’(중앙이 편할 수 있음)을 짧게 안내합니다.
    - 개인차(멀미/선호)로 인해 단정적 추천을 피합니다.

    [언제 호출해야 하는가]
    - “좌석 몇 개예요?”, “어디 앉는 게 좋아요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 예약 좌석 배정 같은 확정 정보를 요구하는 경우에는 본 도구로 단정하지 않습니다.

    [주의/전제]
    - 좌석 추천은 개인차가 있을 수 있습니다.
    """
    seat = comp_planetarium_seat_count()
    return f"천체투영관은 약 {seat}석 규모이며, 돔 화면 특성상 중앙에 가까운 좌석이 편할 수 있지만 개인차가 있을 수 있습니다."


@tool
def get_planetarium_reservation_info() -> str:
    """
    천체투영관 예약/결제/환불/유아 동반 규정 안내 도구(핵심만).

    [무엇을 하는 도구인가]
    - 예약/결제, 환불 가능 시점, 유아 동반 입장 규정을 ‘핵심 문장’으로 짧게 안내합니다.
    - 운영 규정은 민감하므로, 과도한 해석을 붙이지 않고 핵심만 전달합니다.

    [언제 호출해야 하는가]
    - “결제 안 하면 어떻게 돼요?”, “환불 돼요?”, “유아만 들어가도 돼요?” 등에 사용합니다.

    [언제 호출하면 안 되는가]
    - 예외 규정(특수 케이스)을 확정해달라는 요구에는 본 도구만으로 단정하지 말고,
      최신 안내/현장 문의를 함께 권장합니다.

    [주의/전제]
    - 정책은 변경될 수 있으므로, 최종 기준은 홈페이지/현장 안내를 확인하는 것이 안전합니다.
    """
    return (
        f"{comp_planetarium_reservation_rules_sentence()} "
        f"{comp_planetarium_refund_rules_sentence()} "
        f"{comp_planetarium_child_policy_sentence()}"
    )


@tool
def get_planetarium_visit_tips() -> str:
    """
    천체투영관 관람 팁(규정 아님) 안내 도구.

    [무엇을 하는 도구인가]
    - 관람을 편하게 하는 팁(스마트폰 화면, 좌석 선택 방향 등)을 짧게 안내합니다.
    - 규정이 아니라 ‘권장’이므로 단정적 표현을 피합니다.

    [언제 호출해야 하는가]
    - “편하게 보려면?”, “준비할 거 있어요?” 같은 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 규정/금지사항은 관람 수칙 도구를 사용합니다.

    [주의/전제]
    - 개인차가 있을 수 있습니다.
    """
    return f"상영 중에는 스마트폰 화면 밝기를 낮추거나 전원을 꺼 주시면 좋고, {comp_planetarium_seat_tip_sentence()}"


@tool
def _planetarium_rules_viewing_text() -> str:
    """
    [내부 헬퍼] 천체투영관 관람 규정/유의사항 '팩트 카드' 원문.
    - PDF 원문을 최대한 그대로 붙여넣는 것을 권장
    """
    return (
        "천체투영관 관람 안내(규정)\n"
        "- 관람 가능/권장 연령 규정: 예) 7세 미만 권장하지 않음, 36개월~7세 미만 보호자 동반 등\n"
        "- 입장 시간 규정: 예) 시작 10분 전부터 입장, 시작 2분 전까지 착석, 정시 시작 후 입장 불가\n"
        "- 관람 유의사항: 예) 음식물 반입, 사진/영상 촬영, 안전/소음, 어지럼증 주의 등\n"
        "\n"
        "※ 위 항목은 '천체투영관 운영 안내.pdf'의 문구를 그대로 반영해 주세요."
    )


@tool
def _planetarium_booking_refund_text() -> str:
    """
    [내부 헬퍼] 예매/취소/환불 규정 '팩트 카드' 원문.
    """
    return (
        "천체투영관 예매/취소/환불 안내\n"
        "- 온라인 예매 오픈 시점: 예) 방문 예정일 기준 14일 전 오전 10시부터\n"
        "- 예매 방법/경로: 홈페이지/모바일 등\n"
        "- 취소/환불 규정: 환불 가능 기한, 수수료 여부, 부분 취소 가능 여부 등\n"
        "- 현장 구매/현장 접수 안내: 가능 여부, 위치, 유의사항\n"
        "\n"
        "※ 위 항목은 '천체투영관 운영 안내.pdf'의 문구를 그대로 반영해 주세요."
    )


@tool
def _planetarium_fee_text() -> str:
    """
    [내부 헬퍼] 요금/우대/증빙 등 '팩트 카드' 원문.
    """
    return (
        "천체투영관 요금/우대 안내\n"
        "- 기본 요금: 성인/청소년/어린이 등\n"
        "- 우대/할인 대상 및 조건: 증빙 필요 여부 포함\n"
        "- 단체 요금/단체 예약 규정(있다면)\n"
        "\n"
        "※ 위 항목은 '천체투영관 운영 안내 세부사항.pdf'의 표/문구를 그대로 반영해 주세요."
    )

@tool
def get_planetarium_program_catalog() -> str:
    """
    [천체투영관] 현재 운영 중인 정규 프로그램(예시) 목록을 제공합니다.

    - 프로그램 이름, 권장 대상, 주제를 함께 안내합니다.
    - 시간표/회차 확정이 아닌 '라인업 소개용' 정보입니다.
    - 사용자가 '프로그램 알려줘 / 뭐 상영해요 / 상영작 목록' 등을 물으면
      반드시 이 툴을 사용해 프로그램명을 먼저 제시하세요.
    """
    items = comp_planetarium_program_catalog()

    lines = ["천체투영관 정규 프로그램(예시)"]
    for item in items:
        lines.append(
            f"- {item['title']} "
            f"(대상: {item['target']} / 주제: {item['type']})"
        )

    lines.append(
        "※ 실제 상영 프로그램과 회차는 날짜별로 변동될 수 있으므로 "
        "방문 전 최신 공지 또는 현장 안내를 확인해 주세요."
    )
    return "\n".join(lines)


@tool
def _planetarium_program_catalog_text() -> str:
    """
    [내부 헬퍼] 프로그램명(정식 명칭) 목록. (필요시 시즌별/분기별로 교체)
    """
    return (
        "천체투영관 프로그램(정식 명칭)\n"
        "- 프로그램명 1\n"
        "- 프로그램명 2\n"
        "- 프로그램명 3\n"
        "\n"
        "※ 프로그램명은 '천체투영관 운영 안내 세부사항.pdf'의 편성표/목록을 그대로 옮겨 적어 주세요."
    )


@tool
def _planetarium_daily_schedule_text() -> str:
    """
    [내부 헬퍼] 일일/주말 운영시간표(있다면).
    - 프로그램명이 자주 바뀌면 catalog와 schedule을 분리하는 게 안정적
    """
    return (
        "천체투영관 운영 시간표\n"
        "- 평일 시간표: 11:00 / 13:00 / ... 형태\n"
        "- 주말/공휴일 시간표\n"
        "\n"
        "※ 시간표는 '천체투영관 운영 안내 세부사항.pdf' 기준으로 작성해 주세요."
    )


@tool
def get_planetarium_viewing_rules() -> str:
    """
    [천체투영관] 관람 규정/유의사항을 '공식 안내문' 형태로 반환합니다.
    - 연령/보호자 동반 기준, 입장 가능 시간, 시작 후 입장 여부 등은 반드시 정확히 안내하세요.
    - 문구는 가능한 한 공식 문서 원문 표현을 유지하세요.
    """
    return _planetarium_rules_viewing_text()


@tool
def get_planetarium_booking_and_refund_rules() -> str:
    """
    [천체투영관] 예매/취소/환불 규정을 공식 안내문 형태로 반환합니다.
    - 예매 오픈 시점(며칠 전, 몇 시), 취소 가능 기한 등 변동이 큰 핵심 규정을 정확히 안내하세요.
    """
    return _planetarium_booking_refund_text()


@tool
def get_planetarium_fee_info() -> str:
    """
    [천체투영관] 요금/우대/할인 정보를 공식 안내문 형태로 반환합니다.
    - 요금표/우대 조건은 오해가 없도록 정확한 문구로 안내하세요.
    """
    return _planetarium_fee_text()


@tool
def get_planetarium_program_catalog() -> str:
    """
    [천체투영관] 정식 프로그램명(작품명)을 정확히 나열합니다.
    - 사용자가 '뭐 상영해요?'라고 물으면, 가능한 한 이 툴을 우선 사용해 프로그램명을 먼저 제시하세요.
    """
    return _planetarium_program_catalog_text()


@tool
def get_planetarium_daily_schedule() -> str:
    """
    [천체투영관] 운영 시간표(회차)를 제공합니다.
    - 시간표는 변동될 수 있으므로, 최신 공지 확인 안내를 함께 포함하는 것을 권장합니다.
    """
    return _planetarium_daily_schedule_text()


def comp_planetarium_schedule() -> dict:
    """
    천체투영관 상영 시간표(예시/기준표)를 반환합니다.

    - '평일/주말'로 구분한 대표 시간표입니다.
    - 실제 상영작/회차는 변동될 수 있으므로, 날짜가 특정되면 최신 공지 확인 문구를 반드시 포함하세요.

    [언제 호출하는 컴포넌트인가]
    - 관련 안내/규칙/설명에 대한 근거 정보를 제공해야 할 때 사용합니다.
    - 단, 회차/시간표/운영일처럼 변동 가능성이 큰 정보는 ‘공식 기준 페이지’를 우선 확인하도록 Tool에서 유도합니다.
    """
    return {
        "weekday": [
            {"time": "11:00", "title": "3-2-1 발사"},
            {"time": "13:00", "title": "우주 끝으로"},
            {"time": "14:00", "title": "일식과 월식"},
            {"time": "15:00", "title": "보이저"},
            {"time": "16:00", "title": "별빛이 그린 이야기"},
        ],
        "weekend": [
            {"time": "11:00", "title": "생명의 빛, 오로라"},
            {"time": "13:00", "title": "우주 끝으로"},
            {"time": "14:00", "title": "3-2-1 발사"},
            {"time": "15:00", "title": "보이저"},
            {"time": "16:00", "title": "별빛이 그린 이야기"},
        ],
        "note": "※ 시간표/상영작은 변동될 수 있으니 방문 전 최신 공지 또는 현장 안내를 확인해 주세요."
    }


@tool
def get_planetarium_schedule(day_type: str) -> str:
    """
    [천체투영관] 상영 시간표를 줄 단위로 정리해 제공합니다.
    day_type: '평일' 또는 '주말'
    """
    data = comp_planetarium_schedule()

    key = "weekday" if day_type.strip() == "평일" else "weekend"
    rows = data.get(key, [])

    lines = [f"천체투영관 {day_type} 상영 시간표 (예시)", ""]

    for r in rows:
        # ✅ 핵심: 줄 단위 출력
        lines.append(f"{r['time']}  {r['title']}")

    lines.append("")
    lines.append(
        "※ 상영 시간과 프로그램은 변동될 수 있으므로 "
        "방문 전 최신 공지 및 현장 안내를 확인해 주세요."
    )

    return "\n".join(lines)


@tool
def get_planetarium_program_and_schedule() -> str:
    """
    [천체투영관] 프로그램(작품) 목록 + 상영 시간표를 함께 제공합니다.
    - 사용자가 '프로그램 알려줘', '몇 시에 뭐 해요'를 물으면 우선 사용을 권장합니다.
    """
    # 1) 프로그램 목록(예시)
    items = comp_planetarium_program_catalog()
    program_lines = ["천체투영관 정규 프로그램(예시)"]
    for it in items:
        program_lines.append(f"- {it['title']} (대상: {it['target']} / 주제: {it['type']})")

    # 2) 시간표(평일/주말)
    sch = comp_planetarium_schedule()
    wd_lines = ["", "상영 시간표(평일 기준)"]
    for r in sch.get("weekday", []):
        wd_lines.append(f"- {r['time']}  {r['title']}")

    we_lines = ["", "상영 시간표(주말 기준)"]
    for r in sch.get("weekend", []):
        we_lines.append(f"- {r['time']}  {r['title']}")

    note = ["", sch.get("note", "")]

    return "\n".join(program_lines + wd_lines + we_lines + note)


# ---------------- 천문대 ----------------
# (이하 블록도 원문 유지 — 이미 docstring+return 구조가 잘 갖춰져 있습니다.)
@tool
def get_observatory_route_guide() -> str:
    """
    천문대 ‘동선(어떻게 가요?)’ 전용 안내 도구.
    - ‘상설전시관(중앙홀) 후문’ 기준 야외전시장 배치 안내 문구를 그대로 제공합니다.
    - 마지막에 문의 전화번호를 포함합니다.
    """
    return f"{comp_astronomy_hall_outdoor_layout_guide()}\n\n문의: 02-3677-1565"


@tool
def get_observatory_overview() -> str:
    """
    천문대 개요(무엇을 하는 곳인지) 안내 도구.

    [무엇을 하는 도구인가]
    - 천문대에서 할 수 있는 관측 활동(낮/밤/전파)을 ‘큰 틀’로 소개합니다.
    - 세부 회차/요금/예약 방식은 변동 가능성이 있어 본 도구에서 확정하지 않습니다.

    [언제 호출해야 하는가]
    - “천문대에서는 뭐 해요?”, “낮이랑 밤이랑 뭐가 달라요?”처럼 개요가 필요한 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 위치/접근성/안전/예약/기상 정책처럼 특정 주제가 핵심이면 해당 전용 도구를 사용합니다.

    [주의/전제]
    - 관측 대상은 계절·기상에 따라 달라질 수 있습니다.
    """
    return f"{comp_observatory_day_program_sentence()} {comp_observatory_night_program_sentence()} {comp_observatory_radio_program_sentence()}"


@tool
def get_observatory_location_info() -> str:
    """
    천문대 위치 안내 도구.

    [무엇을 하는 도구인가]
    - 천문대가 과학관 내 어디에 있는지(야외전시장/언덕 위)를 위치 중심으로 안내합니다.

    [언제 호출해야 하는가]
    - “천문대 어디 있어요?”, “어떻게 가요?”처럼 위치/방향이 핵심인 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 이동 난이도(경사/계단)가 핵심이면 접근성 도구를 사용합니다.

    [주의/전제]
    - 상세 동선은 현장 운영 상황에 따라 달라질 수 있습니다.
    """
    return comp_observatory_location_sentence()


@tool
def get_observatory_program_list() -> str:
    """
    천문대 프로그램 '정식 명칭'을 사용자에게 먼저 보여주는 도구.

    [목적]
    - 사용자가 '천문대에서 뭐 해요?', '어떤 프로그램 있어요?'라고 물을 때
      가능한 프로그램 선택지를 먼저 제시해 대화를 사용자 친화적으로 만든다.

    [반드시 포함]
    - 주간/야간 프로그램명을 정확한 명칭으로 나열:
      태양 관측 및 수업 / 주간 공개관측 / 망원경실습 <스타파인더> /
      야간 천체관측 <별바라기> / 달과별 관측회

    [금지]
    - 운영 요일/날짜를 여기서 확정하지 말 것(매주 공지로 변동).
    - 참가비/정원 등 숫자도 '이번주 확정값'처럼 단정하지 말 것.

    [후속 질문 유도]
    - 사용자가 '예약/시간/이번주 운영'을 원하면
      '방문 날짜(또는 평일/주말)'를 먼저 물어보도록 유도한다.
    """
    items = comp_observatory_program_catalog()
    day = [x["name"] for x in items if x["type"] == "주간"]
    night = [x["name"] for x in items if x["type"] == "야간"]
    return (
        f"천문대 프로그램은 주간({', '.join(day)})과 야간({', '.join(night)})으로 운영됩니다. "
        "방문 날짜(또는 평일/주말)를 알려주시면, 해당 주 공지 기준으로 운영 여부를 확인해 안내해드릴게요."
    )


@tool
def get_observatory_facility_info() -> str:
    """
    천문대 시설/장비(대표) 안내 도구.

    [무엇을 하는 도구인가]
    - 천문대에서 활용되는 대표 장비(광학 망원경, 태양 관측 장비, 전파망원경 설비 가능)를 짧게 소개합니다.
    - 장비의 세부 스펙/상태/가동 여부를 확정하는 용도가 아닙니다.

    [언제 호출해야 하는가]
    - “망원경 뭐 써요?”, “전파망원경 있어요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 특정 장비가 ‘오늘 운영되는지’를 확정해달라는 질문에는 단정하지 않고,
      최신 안내/현장 문의를 유도합니다.

    [주의/전제]
    - 장비 운용은 점검/기상/운영상 이유로 변동될 수 있습니다.
    """
    return f"{comp_observatory_telescopes_sentence()} {comp_observatory_radio_facility_sentence()}"


@tool
def get_observatory_program_info() -> str:
    """천문대 프로그램을 간단히 소개하고, 방문 날짜 확인을 유도."""
    catalog = comp_observatory_program_catalog()
    day = [x["name"] for x in catalog if x["type"] == "주간"]
    night = [x["name"] for x in catalog if x["type"] == "야간"]
    return (
        f"천문대는 주간({', '.join(day)})과 야간({', '.join(night)}) 프로그램으로 운영됩니다. "
        "운영은 주간 공지에 따라 변동될 수 있어요. 방문 날짜(또는 평일/주말)를 알려주시면, 해당 주 공지 기준으로 안내해드릴게요."
    )


from langchain.tools import tool

@tool
def get_observatory_program_catalog() -> str:
    """
    [천문대] 정식 프로그램명을 정확히 나열합니다.
    - 프로그램명을 반드시 '정식 명칭' 그대로 안내합니다.
    - 회차/운영 여부는 주간 공지에 따라 변동될 수 있으므로 단정하지 않습니다.
    """
    return (
        "천문대 프로그램(정식 명칭)\n"
        "- 야간: 달과별 관측회, 야간 천체관측 <별바라기>\n"
        "- 주간: 태양 관측 프로그램, 망원경실습 <스타파인더> \n"
        "- 전파: 전파망원경 프로그램\n"
        "※ 운영 회차/예약 가능 여부는 최신 공지 또는 현장 안내를 확인해 주세요."
    )


@tool
def get_observatory_daytime_program_info() -> str:
    """
    천문대 낮(주간) 관측 안내 도구.

    [무엇을 하는 도구인가]
    - 낮에 참여할 수 있는 관측(태양관측 등) 성격을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - “낮에 가면 뭐 봐요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 구체 운영 회차/시간을 확정해야 하는 경우에는 공지 확인 안내가 필요합니다.

    [주의/전제]
    - 태양 관측은 전용 장비/필터와 안내자 지시가 필요할 수 있습니다.
    """
    return "낮에는 태양관측 등 주간 관측 프로그램이 운영될 수 있으며, 태양 관측은 전용 장비를 사용하므로 안내자 지시에 따라 참여하는 것이 좋습니다."


@tool
def get_observatory_nighttime_program_info() -> str:
    """
    천문대 야간 관측 안내 도구.

    [무엇을 하는 도구인가]
    - 야간에 관측할 수 있는 대상(달/행성/계절별 별 등)과 ‘기상 영향’이 큰 특성을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - “밤에 뭐 보여요?”, “야간 관측은 어떤 느낌이에요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 오늘 특정 대상을 ‘확정’해달라는 질문에는 단정하지 않습니다(계절/기상에 따라 변경 가능).

    [주의/전제]
    - 관측 대상은 계절·기상에 따라 달라질 수 있습니다.
    """
    return "야간에는 달·행성·계절별 별 등을 관측할 수 있으며, 관측 대상은 계절과 기상에 따라 달라질 수 있습니다."


@tool
def get_observatory_radio_program_info() -> str:
    """
    천문대 전파 프로그램 안내 도구.

    [무엇을 하는 도구인가]
    - 전파망원경을 활용한 프로그램이 무엇인지(전파 영역에서 우주를 관측하는 개요)를 짧게 소개합니다.

    [언제 호출해야 하는가]
    - “전파망원경으로 뭐 해요?”, “전파 프로그램이 뭐예요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 구체 회차/예약 가능 여부 확정에는 예약/운영 도구와 공지 확인 안내가 필요합니다.

    [주의/전제]
    - 운영 방식은 변동될 수 있습니다.
    """
    return "전파 프로그램은 전파망원경을 활용해 전파 영역에서 우주를 관측하는 방법(신호 측정/해석의 개요)을 소개하는 형태로 운영될 수 있습니다."


@tool
def recommend_observatory_programs_by_age(age: int) -> str:
    """
    연령 기반 천문대 프로그램 추천(방향) 도구.

    [무엇을 하는 도구인가]
    - 나이를 기준으로 ‘부담이 적은 선택지’와 ‘도전 가능한 선택지’를 짧게 제안합니다.
    - 개인차가 크므로 단정적 결론 대신 방향만 제공합니다.

    [언제 호출해야 하는가]
    - “아이 몇 살인데 어떤 게 좋아요?” 질문에서 나이가 명확할 때 사용합니다.

    [언제 호출하면 안 되는가]
    - 나이가 불명확하면 먼저 확인하는 것이 우선입니다.

    [주의/전제]
    - 야간/전파 프로그램은 대기 시간과 설명 난이도가 있을 수 있어 컨디션을 고려하는 것이 좋습니다.
    """
    if age <= 7:
        return "초등 저학년 이하라면 비교적 부담이 적은 주간(태양관측 등) 프로그램을 우선 권장하며, 야간·전파 프로그램은 컨디션을 고려해 선택하는 것이 좋습니다."
    if age <= 13:
        return "초등 고학년~중학생은 주간과 야간 관측 모두 추천 가능하며, 관심이 크다면 전파 프로그램도 설명 난이도와 집중도를 고려해 선택해볼 수 있습니다."
    return "청소년·성인은 야간 관측과 전파 프로그램처럼 심화 요소가 있는 선택지가 잘 맞을 수 있으며, 관심 주제(행성/별/전파)를 미리 정하면 만족도가 높아질 수 있습니다."


@tool
def get_observatory_reservation_info() -> str:
    """
    천문대 예약/운영 변동 안내 도구.

    [무엇을 하는 도구인가]
    - 천문대 프로그램은 종류에 따라 예약 방식이 달라질 수 있음을 알리고,
      최신 운영 방식은 공지/현장 안내 확인이 필요하다는 점을 강조합니다.

    [언제 호출해야 하는가]
    - “예약해야 해요?”, “운영이 바뀔 수 있어요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 특정 프로그램의 특정 날짜 예약 가능 여부를 확정해야 하면,
      시스템/공지 확인이 필요하며 본 도구만으로 단정하지 않습니다.

    [주의/전제]
    - 기상 요인으로 취소/대체가 있을 수 있습니다.
    """
    return f"{comp_observatory_reservation_policy_sentence()} {comp_observatory_weather_policy_sentence()}"


@tool
def get_observatory_program_detail_info() -> str:
    """천문대 주간/야간 프로그램 운영시간·대상·예약 방식 요약. (홈페이지 안내 기준, 변동 가능)"""
    return (
        "천문대 주간 프로그램(기준: 2025년 안내)은 "
        "‘태양 관측&수업(10:00~10:40, 11:00~11:40 / 40분 / 7세 이상 / 20명 / 온라인 예약+잔여석 당일 현장 예약 / 무료)’, "
        "‘주간 공개관측(13:00~15:30 / 10~20분 / 모든 연령 / 예약 없이 현장 참여 / 무료)’, "
        "‘망원경실습 <스타파인더>(16:00~16:40 / 40분 / 7세 이상 / 15명 / 온라인 예약+잔여석 당일 현장 예약 / 무료)’로 안내되어 있습니다. "
        "야간 프로그램은 ‘야간 천체관측 <별바라기>(금·토 / 4-9월 20:00-21:30, 10-3월 19:30-21:00 / 7세 이상 / 40명 / 온라인 예약 / 당일 현장 예약 불가 / 10,000원/1인)’, "
        "‘달과별 관측회(운영일자 별도 공지 / 7세 이상 / 250명 / 온라인 예약 / 당일 현장 예약 불가 / 5,000원/1인)’로 안내되어 있습니다."
    )


@tool
def get_observatory_booking_rules() -> str:
    """천문대 예약 규칙(오픈 시점/결제/연령 제한 등) 요약. (홈페이지 안내 기준, 변동 가능)"""
    return (
        "주간/야간 프로그램 예약 접수는 프로그램 참가 예정일로부터 7일 전 9시부터 시작되는 것으로 안내되어 있습니다. "
        "1인(아이 1명)당 5명까지 예약 가능하며, 유료(야간) 프로그램은 예약 당일 내로 결제해야 하고 "
        "미결제 시 당일 24시(밤 12시)에 자동 취소됩니다. "
        "7세 미만 어린이가 참여할 수 있는 천문대 프로그램은 ‘주간 공개관측’만 안내되어 있으며, "
        "그 외 프로그램은 7세 이상부터 참여 가능합니다. "
        "금요일 야간천체관측은 2주 전까지 단체 예약을 받으며, 단체 접수된 금요일에는 일반 예약을 받지 않는 것으로 안내되어 있습니다."
    )


@tool
def get_observatory_weather_policy() -> str:
    """
    천문대 기상 정책(취소/대체 가능) 안내 도구.

    [무엇을 하는 도구인가]
    - 관측 프로그램이 기상 영향을 크게 받는다는 점과,
      취소 또는 대체 프로그램으로 전환될 수 있다는 점을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - “비 오면 어떻게 돼요?”, “구름 많으면 취소돼요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 오늘 취소 여부를 ‘확정’하려는 질문에는 단정하지 말고 공지/현장 안내 확인을 유도합니다.

    [주의/전제]
    - 야간 관측은 특히 날씨 영향이 큽니다.
    """
    return comp_observatory_weather_policy_sentence()


@tool
def get_observatory_safety_info() -> str:
    """
    천문대 안전 수칙 안내 도구.

    [무엇을 하는 도구인가]
    - 관측실/옥상 등에서의 기본 안전 수칙(이동, 장비 취급, 계단/문턱 주의)을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - “아이 데려가도 안전해요?”, “장비 만져도 돼요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 응급상황 대응/의료적 판단 등은 본 도구 범위 밖입니다.

    [주의/전제]
    - 어두운 환경에서 이동할 수 있으므로 안내자 지시를 따르는 것이 중요합니다.
    """
    return comp_observatory_safety_sentence()


@tool
def get_observatory_accessibility_info() -> str:
    """
    천문대 접근성(이동 난이도) 안내 도구.

    [무엇을 하는 도구인가]
    - 천문대까지의 이동 동선이 언덕/경사/계단을 포함할 수 있음을 안내합니다.
    - 이용 가능 여부를 단정하지 않고, 필요 시 사전 문의를 권장합니다.

    [언제 호출해야 하는가]
    - “유모차/휠체어 가능해요?”, “걷기 힘든데 갈 수 있어요?”처럼 접근성 자체가 핵심인 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - “천문대 어디 있어요?”처럼 위치가 핵심이면 위치 도구를 사용합니다.
    - 운영/예약/요금 확정은 해당 전용 도구로 분리합니다.

    [주의/전제]
    - 현장 통제/기상/운영에 따라 체감 난이도는 달라질 수 있습니다.
    """
    return f"{comp_observatory_accessibility_sentence()} {comp_observatory_accessibility_reco_sentence()}"


@tool
def get_observatory_group_visit_info() -> str:
    """
    천문대 단체 이용 안내 도구.

    [무엇을 하는 도구인가]
    - 학교/단체 방문 시 프로그램이 별도 일정/내용으로 운영될 수 있음을 안내하고,
      사전 예약/협의가 필요할 수 있음을 짧게 전달합니다.

    [언제 호출해야 하는가]
    - “단체 프로그램 가능해요?”, “단체로 가면 어떻게 해요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 특정 날짜/인원에 대한 확정 배정 여부는 단정하지 말고 예약/문의 안내를 유도합니다.

    [주의/전제]
    - 단체 운영은 시즌/현장 여건에 따라 달라질 수 있습니다.
    """
    return comp_observatory_group_sentence()

@tool
def get_observatory_group_program_info() -> str:
    """천문대 단체 프로그램(예약 방식/대상/인원/유의사항) 요약. (홈페이지 안내 기준, 변동 가능)"""
    return (
        "천문대 단체 프로그램은 전화 예약으로 진행됩니다. "
        "주간관측(단체)은 화-금요일 10:00-10:40 / 11:00-11:40 / 13:00-13:40(40분)으로 안내되며, "
        "대상은 5세(2020년생) 이상이고 7세 미만 아동은 보호자 동반 참여가 필수입니다(20-80명). "
        "야간천체관측 <별바라기>(단체)는 금요일(4-9월 20:00-21:30, 10-3월 19:30-21:00)로 안내되며, "
        "7세(2018년생) 이상, 15-60명, 참가비 10,000원/1인이고 참가신청서 이메일 접수가 필수입니다. "
        "단체 프로그램 예약/문의: 02-3677-1565 (화-일 09:30-17:30 / 점심 11:50-12:50 제외). "
        "단체 프로그램 이용 시 과학관 입장권(전시관 관람권) 구매가 필요하다는 안내가 포함되어 있습니다."
    )

# ---------------- 스페이스 아날로그 ----------------

@tool
def get_space_analog_route_guide() -> str:
    """
    스페이스 아날로그 ‘동선(어떻게 가요?)’ 전용 안내 도구.
    - ‘상설전시관(중앙홀) 후문’ 기준 야외전시장 배치 안내 문구를 그대로 제공합니다.
    - 마지막에 문의 전화번호를 포함합니다.
    """
    return f"{comp_astronomy_hall_outdoor_layout_guide()}\n\n문의: 02-3677-1402"



@tool
def get_space_analog_overview() -> str:
    """
    스페이스 아날로그 개요(무엇을 하는 곳인지) 안내 도구.

    [무엇을 하는 도구인가]
    - 스페이스 아날로그의 목적/체험 성격을 큰 틀에서 소개합니다.
    - 세부 코스(회차/시간/예약 가능 여부)는 운영 상황에 따라 달라질 수 있으므로
      ‘예약/시간표’가 핵심인 질문에는 공식 안내/예약 도구를 함께 안내합니다.

    [언제 호출해야 하는가]
    - “스페이스 아날로그가 뭐예요?”, “어떤 체험이에요?”처럼 공간 소개가 필요할 때.

    [주의/전제]
    - 대상 연령/요금/회차는 변경될 수 있으니 최신 안내 확인을 유도하세요.
    """
    return (
        f"{comp_space_analog_overview_sentence()} "
        "체험 코스는 운영일/회차에 따라 달라질 수 있어요. "
        "방문 예정 날짜가 있으면 말씀해 주시면 예약·운영 안내를 더 정확히 도와드릴게요."
    )

@tool
def get_space_analog_info() -> str:
    """
    스페이스 아날로그 개요 안내 도구.

    [무엇을 하는 도구인가]
    - 스페이스 아날로그가 어떤 공간인지(우주인 훈련과 화성 거주 체험 체험)를 한 문단으로 소개합니다.

    [언제 호출해야 하는가]
    - “스페이스 아날로그가 뭐예요?”처럼 개요 소개가 필요한 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 예약/요금/회차/지각 규정 확정은 전용 도구 또는 최신 안내 확인이 필요합니다.

    [주의/전제]
    - 세부 구성과 운영 방식은 프로그램 안내에 따라 달라질 수 있습니다.
    """
    return comp_space_analog_overview_sentence()


@tool
def get_space_analog_program_catalog() -> str:
    """
    스페이스 아날로그 프로그램(콘텐츠/요금/대상)의 '고정 카탈로그' 안내 도구.

    [반드시 맞춰야 하는 명칭/내용]
    - 화성거주 체험 (A): 연료전지 조립
    - 화성거주 체험 (B): 태양전지 조립
    - 심화 체험: 아날로그 및 화성거주 체험
    - 기본 해설: 아날로그 및 화성거주 해설
    - 요금/대상/인원은 리플릿/홈페이지 안내 기준 설명 가능(단, 변동 가능성 문구 포함)

    [금지]
    - '새로운 프로그램명/스토리' 창작 금지.
    - '오늘 운영 확정' 금지(운영은 홈페이지 안내 기준).
    """
    return (
        "스페이스 아날로그는 ‘화성거주 체험 (A)(연료전지 조립)’, ‘화성거주 체험 (B)(태양전지 조립)’, "
        "‘심화 체험(아날로그 및 화성거주 체험)’, ‘기본 해설(아날로그 및 화성거주 해설)’로 구성됩니다. "
        "방문 날짜가 정해졌다면 평일/주말 여부에 따라 시간표 안내도 도와드릴게요."
    )


@tool
def get_space_analog_program_info() -> str:
    """스페이스 아날로그 프로그램을 간단히 소개하고, 방문 날짜 확인을 유도."""
    return (
        f"스페이스 아날로그 프로그램은 {comp_space_analog_program_list_sentence()} 로 구성됩니다. "
        "시간표와 예약 가능 여부는 방문 날짜(평일/주말)에 따라 달라질 수 있어요. 방문 날짜를 알려주시면 안내해드릴게요."
    )


@tool
def get_space_analog_fee_and_age_info() -> str:
    """스페이스 아날로그 관람료/대상(최소 연령) 요약. (홈페이지 안내 기준, 변동 가능)"""
    return (
        "스페이스 아날로그는 예약제로 운영되며, 기본 해설/기본 체험 프로그램은 40분 진행(초3 이상 참여)입니다. "
        "심화 체험은 2시간 진행(초5 이상 참여)이며, 프로그램 시작 10분 전까지 도착을 권장합니다. "
        "관람료는 기본 체험(A/B)·기본 해설 2,000원(우대 1,000원), 심화 체험 10,000원(우대 5,000원)으로 안내되어 있습니다. "
        "우대 기준(예: 연간회원, 65세 이상 등)은 홈페이지 안내를 참고해 주세요."
    )


@tool
def get_space_analog_booking_info() -> str:
    """스페이스 아날로그 온라인 예약/취소 안내 요약. (홈페이지 안내 기준, 변동 가능)"""
    return (
        "온라인 예약은 최대 6매까지 가능하며(결제는 카드 결제만 가능, 계좌이체 불가), "
        "기본 프로그램은 참여일 15일 전 새벽 0시부터 당일 3분 전까지, "
        "심화 프로그램은 참여일 15일 전 새벽 0시부터 당일 30분 전까지 예약할 수 있습니다. "
        "예약 변경이 필요한 경우 기존 예약을 취소 후 신규 예약을 진행해 주세요. "
        "예약 취소는 마이페이지 > 예약내역 > 스페이스아날로그에서 프로그램 시작 30분 전까지 가능하며, "
        "프로그램 시작 후에는 취소 및 환불이 불가합니다. "
        "문의: 02-3677-1402 (화-일 09:30-17:30 / 점심 11:50-12:50 / 휴관일 제외)"
    )


@tool
def get_space_analog_program_catalog() -> str:
    """
    스페이스 아날로그 프로그램(콘텐츠/요금/대상)의 '고정 카탈로그' 안내 도구.

    [반드시 맞춰야 하는 명칭/내용]
    - 화성거주 체험 (A): 연료전지 조립
    - 화성거주 체험 (B): 태양전지 조립
    - 심화 체험: 아날로그 및 화성거주 체험
    - 기본 해설: 아날로그 및 화성거주 해설
    - 요금/대상/인원은 리플릿 기준 설명 가능(단, 변동 가능성 문구 포함)

    [금지]
    - '새로운 프로그램명/스토리' 창작 금지.
    - '오늘 운영 확정' 금지(운영은 홈페이지 안내 기준).
    """
    return (
        "스페이스 아날로그는 ‘화성거주 체험 (A)(연료전지 조립)’, ‘화성거주 체험 (B)(태양전지 조립)’, "
        "‘심화 체험(아날로그 및 화성거주 체험)’, ‘기본 해설(아날로그 및 화성거주 해설)’로 구성됩니다. "
        "요금/대상/인원 등은 리플릿 및 홈페이지 안내 기준으로 변동될 수 있습니다. "
        "방문 날짜가 정해졌다면 평일/주말 여부에 따라 시간표 안내도 도와드릴게요."
    )


@tool
def get_space_analog_zone_info() -> str:
    """
    스페이스 아날로그 존(구성 예시) 안내 도구.

    [무엇을 하는 도구인가]
    - “안에 뭐가 있어요?” 질문에 대해 존 구성 예시를 짧게 안내합니다.
    - 존의 세부 역할/구성은 프로그램 안내에 따라 달라질 수 있습니다.

    [언제 호출해야 하는가]
    - 공간 구성(존)을 궁금해하는 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 특정 존이 반드시 포함되는지, 오늘 운영되는지 확정해야 하는 질문에는 단정하지 않습니다.

    [주의/전제]
    - 구성 예시는 이해를 돕기 위한 예시입니다.
    """
    return comp_space_analog_zone_sentence()


@tool
def get_space_analog_program_info() -> str:
    """
    스페이스 아날로그 코스(기본/심화) 차이 안내 도구.

    [무엇을 하는 도구인가]
    - 기본 과정과 심화 과정이 어떤 방향으로 다른지(입문/임무·팀워크 강화)를 짧게 설명합니다.

    [언제 호출해야 하는가]
    - “기본이랑 심화 차이 뭐예요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 오늘 어떤 코스가 열리는지 확정하려면 최신 안내 확인이 필요합니다.

    [주의/전제]
    - 권장 연령/세부 규정은 프로그램 안내를 확인하는 것이 안전합니다.
    """
    return comp_space_analog_course_sentence()


@tool
def get_space_analog_course_list() -> str:
    """
    스페이스 아날로그 코스(권장 연령) 요약 안내 도구.

    [무엇을 하는 도구인가]
    - “몇 학년부터 돼요?” 같은 질문에서 코스별 권장 연령의 큰 기준을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - 연령/학년 기준이 핵심인 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 예외/세부 조건(신장·체중 등)을 확정하려면 최신 안내 확인이 필요합니다.

    [주의/전제]
    - 프로그램별 세부 조건은 변동될 수 있습니다.
    """
    return "기본 과정은 초등 3학년 이상, 심화 과정은 초등 5학년 이상 또는 청소년·성인 대상이며, 전시해설 성격의 프로그램도 운영될 수 있습니다(세부 조건은 안내 기준)."


@tool
def recommend_space_analog_programs_by_age(age: int) -> str:
    """
    연령 기반 스페이스 아날로그 추천(방향) 도구.

    [무엇을 하는 도구인가]
    - 나이에 따라 무리 없는 코스 선택 방향을 짧게 제안합니다.

    [언제 호출해야 하는가]
    - “아이/학생/어른은 뭐가 좋아요?”처럼 연령 기반 추천이 필요한 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 나이가 불명확하면 먼저 확인하는 것이 우선입니다.

    [주의/전제]
    - 체험 난이도/집중도는 개인차가 있을 수 있습니다.
    """
    return comp_space_analog_age_reco_short(age)


@tool
def get_space_analog_safety_info() -> str:
    """
    스페이스 아날로그 안전/유의사항 안내 도구.

    [무엇을 하는 도구인가]
    - 체험형 공간 특성(계단/좁은 통로, 권장 조건 적용 가능 등)과 안전 수칙을 짧게 안내합니다.

    [언제 호출해야 하는가]
    - “안전해요?”, “무서운 구간 있어요?”, “주의할 게 있어요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 개인의 건강 상태에 대한 단정(가능/불가능)은 본 도구 범위 밖입니다.

    [주의/전제]
    - 체험 중에는 안내자 지시를 따르는 것이 가장 중요합니다.
    """
    return comp_space_analog_safety_sentence()


@tool
def get_space_analog_reservation_info() -> str:
    """
    스페이스 아날로그 예약/취소(원칙) 안내 도구.

    [무엇을 하는 도구인가]
    - 예약제 운영 가능성과, 프로그램별 세부 규정(연령/정원/집합/환불/지각)이 안내 기준임을 짧게 설명합니다.

    [언제 호출해야 하는가]
    - “예약해야 해요?”, “지각하면 어떻게 돼요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 특정 날짜의 잔여석/확정 규정 확인은 시스템/공지 확인이 필요합니다.

    [주의/전제]
    - 세부 규정은 프로그램별로 다를 수 있습니다.
    """
    return comp_space_analog_reservation_sentence()


@tool
def get_space_analog_group_program_info() -> str:
    """
    스페이스 아날로그 단체 이용 안내 도구.

    [무엇을 하는 도구인가]
    - 단체 프로그램이 별도 커리큘럼/시간표로 운영될 수 있고, 사전 협의로 조정될 수 있음을 안내합니다.

    [언제 호출해야 하는가]
    - “단체로 갈 수 있어요?”, “단체 프로그램 구성 바꿀 수 있어요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 특정 날짜·인원에 대한 확정 배정 여부는 단정하지 말고 예약/문의 안내를 유도합니다.

    [주의/전제]
    - 운영 여건에 따라 조정 가능 범위는 달라질 수 있습니다.
    """
    return comp_space_analog_group_sentence()


@tool
def get_space_analog_visit_tips() -> str:
    """
    스페이스 아날로그 방문 팁(복장/준비) 안내 도구.

    [무엇을 하는 도구인가]
    - 복장과 준비 관련 팁을 짧게 안내합니다(규정이 아니라 권장 사항).

    [언제 호출해야 하는가]
    - “뭐 입고 가요?”, “준비물 있어요?” 질문에 사용합니다.

    [언제 호출하면 안 되는가]
    - 규정/금지/환불 같은 운영 규정 확정은 전용 도구 또는 최신 안내 확인이 필요합니다.

    [주의/전제]
    - 개인차가 있을 수 있습니다.
    """
    return comp_space_analog_visit_tip_sentence()