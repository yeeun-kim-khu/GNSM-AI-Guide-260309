"""gnsm.text_parsing

이 파일은 LLM 답변 텍스트에서 출처/이미지 URL을 추출하고,
Streamlit UI에서 보여주기 좋은 형태로 정리하는 유틸을 모아둡니다.

- [출처] https://... / [출처-1-설명] ... 같은 포맷을 파싱
- [이미지-1] https://... / [이미지-1-설명] ... 같은 포맷을 파싱
- UI에는 URL을 그대로 노출하지 않고(버튼/이미지로만 표시),
  화면에 보여줄 텍스트는 URL/메타 라인을 제거한 버전을 사용합니다.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------
# 1) 출처/이미지 파서
# ---------------------------------------------------------

def parse_sources_from_text(text: str) -> list[dict[str, str]]:
    """답변 텍스트에서 출처 URL과(가능하면) 출처 설명을 추출합니다."""
    sources: list[dict[str, str]] = []
    if not text:
        return sources

    # 설명 라인: [출처-1-설명] ... 형태
    desc_pairs = re.findall(r"\[(출처-\d+)-설명\]\s*(.+)", text)
    desc_map = {k: v.strip() for k, v in desc_pairs}

    labeled_urls = re.findall(r"\[(출처(?:-\d+)?)\]\s*(https?://\S+)", text)
    seen = set()
    for label, url in labeled_urls:
        url = url.strip().rstrip(").,]}\"")
        if url in seen:
            continue
        seen.add(url)
        sources.append({
            "label": str(label),
            "url": str(url),
            "desc": str(desc_map.get(label, "")),
        })

    # fallback: labeled 패턴이 없고 [출처] URL 라인만 있을 때
    if not sources:
        url_lines = re.findall(r"\[출처(?:-\d+)?\]\s*(https?://\S+)", text)
        for url in url_lines:
            url = url.strip().rstrip(").,]}\"")
            if url in seen:
                continue
            seen.add(url)
            sources.append({"label": "출처", "url": url, "desc": ""})

    return sources


def parse_image_urls_from_text(text: str) -> list[dict[str, str]]:
    """답변 텍스트에서 [이미지-n] URL 및 설명을 추출합니다."""
    imgs: list[dict[str, str]] = []
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
            "label": str(label),
            "url": str(url),
            "desc": str(desc_map.get(label, "")),
        })

    return imgs


# ---------------------------------------------------------
# 2) UI 표시용 텍스트 정리
# ---------------------------------------------------------

def escape_tildes(text: str) -> str:
    """마크다운 취소선(~~) 방지를 위해 ~ 를 이스케이프합니다."""
    if not text:
        return text
    return text.replace("~", r"\~")


def strip_inline_meta_lines(text: str) -> str:
    """[출처-*], [이미지-*] 같은 메타 라인을 제거합니다."""
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


def strip_urls_from_text(text: str) -> str:
    """마크다운 링크/Raw URL을 제거해 '버튼만' 쓰는 UI에 맞춥니다."""
    t = text or ""
    if not t:
        return t

    try:
        # 1) Markdown 링크: [텍스트](URL)
        t = re.sub(r"\[[^\]]+\]\((https?://[^\s\)]+)\)", "", t)
        # 2) Raw URL
        t = re.sub(r"https?://[^\s\)\]\}>\"']+", "", t)
        # 2-1) URL 제거 후 남는 안내 문구 라인 제거
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


def clean_assistant_display_text(text: str) -> str:
    """UI에 표시할 assistant 텍스트(출처/이미지 라인/URL 제거)"""
    return strip_urls_from_text(strip_inline_meta_lines(text or ""))


# ---------------------------------------------------------
# 3) 에이전트 결과에서 출처/이미지 blob 수집
# ---------------------------------------------------------

def collect_sources_blob_from_result(result: Any) -> str:
    """agent.invoke 결과(messages 포함)에서 tool/assistant 메시지에 있는 [출처]/[이미지] 라인을 모읍니다."""
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
