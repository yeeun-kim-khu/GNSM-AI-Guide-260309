"""gnsm.notice_summary

공지사항(또는 공지 상세 페이지)을 여러 개 가져온 뒤,
사용자에게 보여줄 '짧은 요약 문장'을 만드는 헬퍼.

핵심 개선:
- items 키가 url/desc로 고정되어 있지 않아도 동작
- details_texts가 str이 아니어도 문자열로 정규화
- [출처] 포맷이 달라도 본문에서 첫 URL로 매칭 시도
- 과한 필터링(특히 '국립과천과학관' 금지) 완화
"""

from __future__ import annotations

import re
from typing import Any


def _get_first(it: dict, keys: list[str]) -> str:
    for k in keys:
        v = it.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _as_text(x: Any) -> str:
    """details_texts 요소가 dict/object여도 안전하게 문자열화."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        # 가능한 필드 후보들
        for k in ("text", "detail", "content", "body", "html", "raw"):
            v = x.get(k)
            if v:
                return str(v)
        return ""
    return str(x)


def _first_url(text: str) -> str:
    """본문에서 첫 URL을 뽑아온다. (출처 포맷이 달라도 대응)"""
    if not text:
        return ""
    m = re.search(r"(https?://[^\s\)\]\}\"\']+)", text)
    return m.group(1).strip() if m else ""


def _pick_notice_snippet(detail_text: str, max_lines: int = 999) -> str:
    t = detail_text or ""
    if not t:
        return ""

    lines = [ln.strip() for ln in t.splitlines()]
    picked: list[str] = []

    banned = (
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
        "출처",
        "출처]",
        "국가상징",
        "메뉴",
        "시작",
        "마이페이지",
        "알아보기",
        "회원가입",
        "사이트맵",
        # ⚠️ "국립과천과학관"은 제거 (정상 문장까지 날리는 원인)
        "전시해설",
        "전체일정",
        "000년",
        "특별기획전",
        "PRINT",
        "일정",
        "팝업",
        "자세히보기",
        "과학관소식",
        "고객서비스",
        "안전관리",
        "정보나눔터",
        "전자민원",
        "분실물목록",
        "공지/공고",
        "카드뉴스",
        "보도자료",
        "현장스케치",
        "채용공고",
        "이용약관",
        "관련사이트",
        "대표전화",
        "02-3677-1500",
    )

    date_noise_re = re.compile(
        r"^\d{4}\.\d{2}\.\d{2}.*~\s*\d{4}\.\d{2}\.\d{2}.*(공지/공고\s*상세)?$"
    )

    other_museum_re = re.compile(r"국립(?!과천)[가-힣A-Za-z0-9]{1,20}과학관")
    addr_noise_re = re.compile(r"(경기도\s*과천시|상하벌로|\b0\d{1,2}-\d{3,4}-\d{4}\b)")
    ui_noise_re = re.compile(r"(세부\s*정보\s*보기|요금\s*안내)")
    source_stub_re = re.compile(r"^\[?\s*출처[^\]]*\]?\s*$")

    def _ok_line(ln: str) -> bool:
        if not ln:
            return False
        if ln.startswith("Observation"):
            return False
        if ln.startswith("[출처"):
            return False
        if "sciencecenter.go.kr" in ln:
            # URL만 있는 라인 잡음 처리
            if len(ln) < 80:
                return False
        if source_stub_re.match(ln.strip()):
            return False
        if addr_noise_re.search(ln):
            return False
        if ui_noise_re.search(ln):
            return False
        if date_noise_re.search(ln):
            return False
        if ("국립과천과학관" not in ln) and other_museum_re.search(ln):
            return False
        if any(x in ln for x in banned):
            return False
        if ln in ("공지사항", "공지", "국립과천과학관"):
            return False
        if len(ln) < 2:
            return False
        return True

    # 1차: 라인 기준으로 상단 1~2개 뽑기
    for ln in lines:
        if _ok_line(ln):
            picked.append(ln)
            if len(picked) >= max(1, int(max_lines)):
                break
    
    print(f"[_pick_notice_snippet] total lines: {len(lines)}, picked: {len(picked)}, max_lines: {max_lines}")
    if picked:
        print(f"[_pick_notice_snippet] result: {' '.join(picked)[:200]}")

    if picked:
        return "\n".join(picked).strip()

    # 2차 폴백: 공백정리한 상단 1~2개라도 확보
    cleaned: list[str] = []
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("Observation"):
            continue
        if ln.startswith("[출처"):
            continue
        if source_stub_re.match(ln.strip()):
            continue
        if addr_noise_re.search(ln) or ui_noise_re.search(ln):
            continue
        if date_noise_re.search(ln):
            continue
        if ("국립과천과학관" not in ln) and other_museum_re.search(ln):
            continue
        if any(x in ln for x in banned):
            continue

        ss = " ".join((ln or "").split()).strip()
        if len(ss) >= 10:
            cleaned.append(ss)
        if len(cleaned) >= max(1, int(max_lines)):
            break
    if cleaned:
        return "\n".join(cleaned).strip()

    # 3차 폴백: 문장 단위 추출
    plain = " ".join(lines)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return ""

    sents = re.findall(r"[가-힣0-9][^.!?\n]{10,240}?(?:다\.|니다\.|요\.|함\.|습니다\.|\.)", plain)
    sent_picked: list[str] = []
    for s in sents:
        ss = " ".join((s or "").split()).strip()
        if not ss:
            continue
        if source_stub_re.match(ss):
            continue
        if addr_noise_re.search(ss):
            continue
        if ui_noise_re.search(ss):
            continue
        if date_noise_re.search(ss):
            continue
        if ("국립과천과학관" not in ss) and other_museum_re.search(ss):
            continue
        if any(x in ss for x in banned):
            continue
        if ss.startswith("[출처"):
            continue
        if len(ss) < 12:
            continue

        sent_picked.append(ss)
        if len(sent_picked) >= max(1, int(max_lines)):
            break

    return "\n".join(sent_picked).strip()


def _format_notice_content(content: str) -> str:
    """공지사항 내용을 가독성 좋게 포맷팅 (이모지 제거, 줄바꿈 최소화)"""
    lines = content.split("\n")
    formatted_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        formatted_lines.append(line)
    
    # 줄바꿈을 공백으로 변경하여 한 줄로 이어지도록 함
    return " ".join(formatted_lines)


def build_notice_summary_answer(items: list[dict], details_texts: list[Any], title_prefix: str) -> str:
    """공지 목록(items) + 공지 상세(details_texts)를 이용해 요약 답변을 생성합니다."""

    url_to_title: dict[str, str] = {}
    titles_only: list[str] = []

    # items 구조 유연화
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        u = _get_first(it, ["url", "link", "href", "detail_url"])
        d = _get_first(it, ["desc", "title", "subject", "name", "text"])
        if u and d and u not in url_to_title:
            url_to_title[u] = d
        if d:
            titles_only.append(d)

    # 크롤링한 상세 내용을 그대로 반환
    summaries: list[str] = []
    for dt0 in (details_texts or [])[:6]:
        dt = _as_text(dt0)
        if not dt:
            continue

        # Observation: 부분 제거하고 본문만 추출
        content = dt
        if "Observation:" in content:
            content = content.split("Observation:", 1)[1].strip()
        if "[출처]" in content:
            # [출처] URL 다음부터가 본문
            parts = content.split("\n", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        
        if content and len(content) > 50:  # 최소 50자 이상이면 본문으로 판단
            # 가독성 개선: 섹션 구분, 이모지 추가
            formatted_content = _format_notice_content(content)
            summaries.append(formatted_content)

    if summaries:
        # 제목 중복 방지 - 본문만 반환
        return "\n\n".join(summaries)

    if titles_only:
        uniq: list[str] = []
        seen = set()
        for t in titles_only:
            tt = " ".join((t or "").split())
            if not tt or tt in seen:
                continue
            seen.add(tt)
            uniq.append(tt)
        uniq = uniq[:6]
        return (title_prefix or "공지사항 요약") + "\n\n" + "\n".join([f"- {t}" for t in uniq])

    # 마지막 폴백: 최소 UX 유지
    if items:
        n = min(6, len(items))
        return (title_prefix or "공지사항 요약") + "\n\n" + "\n".join([f"- 공지사항 {i}" for i in range(1, n + 1)])

    return (title_prefix or "공지사항 요약") + "\n\n" + "공지사항을 불러왔지만 요약할 핵심 문장을 추출하지 못했습니다. 버튼에서 확인해 주세요."


_sidebar_notices_cache = None

def get_recent_notices_for_sidebar(limit: int = 5) -> list[dict]:
    """
    사이드바에 표시할 최근 공지사항 목록 가져오기 (캐싱 적용)
    
    Args:
        limit: 가져올 공지사항 개수
        
    Returns:
        공지사항 리스트 [{"title": "...", "url": "..."}, ...]
    """
    global _sidebar_notices_cache
    
    # 캐시가 있으면 즉시 반환
    if _sidebar_notices_cache is not None:
        return _sidebar_notices_cache[:limit]
    
    try:
        from gnsm import tools as _tools
        
        # 최근 공지사항 가져오기 (tool 함수는 .invoke()로 호출)
        print("[DEBUG] 공지사항 가져오기 시작...")
        result = _tools.get_recent_sciencecenter_notices.invoke({"limit": 10})
        print(f"[DEBUG] 공지사항 결과 길이: {len(result) if result else 0}")
        
        if not result:
            print("[DEBUG] 공지사항 결과가 비어있음")
            _sidebar_notices_cache = []
            return []
        
        # 결과 파싱 - [출처-n] URL과 [출처-n-설명] 제목 추출
        notices = []
        lines = result.split("\n")
        print(f"[DEBUG] 파싱할 라인 수: {len(lines)}")
        
        current_url = ""
        for line in lines:
            line = line.strip()
            
            # [출처-n] URL 파싱
            if line.startswith("[출처-") and "] http" in line:
                parts = line.split("] ", 1)
                if len(parts) == 2:
                    current_url = parts[1].strip()
                    print(f"[DEBUG] URL 발견: {current_url}")
            
            # [출처-n-설명] 제목 파싱
            elif "[출처-" in line and "-설명]" in line:
                parts = line.split("-설명]", 1)
                if len(parts) == 2:
                    title = parts[1].strip()
                    if title:
                        print(f"[DEBUG] 공지사항 발견: {title}, URL: {current_url}")
                        notices.append({
                            "title": title,
                            "url": current_url
                        })
                        current_url = ""  # 다음 공지를 위해 초기화
            
            if len(notices) >= 10:  # 최대 10개까지 캐싱
                break
        
        print(f"[DEBUG] 총 {len(notices)}개 공지사항 파싱 완료")
        # 캐시 저장
        _sidebar_notices_cache = notices
        return notices[:limit]
    except Exception as e:
        import traceback
        print(f"[DEBUG] 사이드바 공지사항 로드 오류: {e}")
        print(f"[DEBUG] 상세 에러:\n{traceback.format_exc()}")
        _sidebar_notices_cache = []
        return []
