"""gnsm.heuristics

이 파일은 사용자의 입력 문장을 보고

- 어떤 의도인지(추천/공지/운영 사실 확인 등)
- 어떤 스코프(천체투영관/천문대/스페이스 아날로그/별에게로 가는 길 등)인지
- 답변 전에 추가 질문이 필요한지(날짜/나이/단체 여부)

를 판별하는 '가벼운 휴리스틱(규칙 기반)'을 모아둡니다.

주의:
- 이 모듈은 "사실을 확정"하지 않습니다.
- 여기서 하는 일은 "에이전트가 어떤 도구를 써야 하는지"와 "UX 흐름"을 돕는 것입니다.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------
# 1) 관심 주제(추천 질문 UX)
# ---------------------------------------------------------

def resolve_interest_topic(user_text: str) -> str:
    """사용자 입력에서 '관심 주제'를 추출합니다(전시관명 대신 주제)."""
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


# ---------------------------------------------------------
# 2) 스코프(어느 공간 이야기인지) 판별
# ---------------------------------------------------------

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
    # 상위 범주(과학관/전관) 식별용
    "main_page": ["국립과천과학관"],
}

SCOPE_KEYWORDS = sorted({k for ks in SCOPE_KEYWORDS_BY_AREA.values() for k in ks}, key=len, reverse=True)

_PROGRAM_KEYWORDS = [
    "프로그램", "체험", "교육", "강연", "행사", "이벤트",
    "예약", "신청", "접수", "시간표", "회차", "요금", "가격",
]


def scope_match_score(user_text: str) -> dict:
    """사용자 텍스트에서 스코프가 강한 영역을 점수화합니다."""
    t = (user_text or "").lower().strip()

    matched: dict = {}
    scores: dict = {}

    # - 키워드 포함 시 +1
    # - 2글자 이하 단축어는 오탐 가능성이 있어 +0.5로 취급 -> 정수화 위해 *2 방식 사용
    # - 긴 구문은 +2
    def _kw_weight(kw: str) -> int:
        kw = kw.strip()
        if len(kw) >= 6:
            return 4
        if len(kw) <= 2:
            return 1
        return 2

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

    candidate_areas = [a for a in scores.keys() if a not in ("main_page",)]
    sorted_areas = sorted(candidate_areas, key=lambda a: scores.get(a, 0), reverse=True)
    best_area = sorted_areas[0] if sorted_areas else None
    runner = sorted_areas[1] if len(sorted_areas) > 1 else None

    best_score2 = scores.get(best_area, 0) if best_area else 0
    runner_score2 = scores.get(runner, 0) if runner else 0

    return {
        "best_area": best_area if best_score2 > 0 else None,
        "best_score": best_score2 // 2,
        "runner_up_area": runner if runner_score2 > 0 else None,
        "runner_up_score": runner_score2 // 2,
        "matched": matched,
    }


def is_scope_clear(user_text: str, min_score: int = 2, min_gap: int = 1) -> bool:
    s = scope_match_score(user_text)
    if not s.get("best_area"):
        return False
    best = int(s.get("best_score") or 0)
    runner = int(s.get("runner_up_score") or 0)
    return (best >= min_score) and ((best - runner) >= min_gap)


def is_in_astronomy_hall_scope(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(k.lower() in t for k in SCOPE_KEYWORDS)


def looks_like_program_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(k.lower() in t for k in _PROGRAM_KEYWORDS)


# ---------------------------------------------------------
# 3) 공지/휴관/운영 정보 관련 휴리스틱
# ---------------------------------------------------------

def looks_like_holiday_or_notice_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    keywords = [
        "설", "설날", "추석", "명절", "연휴", "휴일", "공휴일",
        "신정", "삼일절", "어린이날", "부처님오신날", "석가탄신일", "석탄일",
        "현충일", "광복절", "개천절", "한글날", "성탄절", "크리스마스",
        "휴관", "임시휴관", "정기휴관", "대체공휴일", "대체휴일", "대체 휴일",
        "운영 안내", "운영안내", "공지", "공지사항",
    ]
    return any(k in t for k in keywords)


def looks_like_notice_specific_inquiry(user_text: str) -> bool:
    t = (user_text or "").lower()
    keywords = [
        "공지 있", "공지있", "공지 떴", "공지떴",
        "공지 확인", "공지확인", "안내 공지", "안내공지",
        "공지 내용", "공지내용",
        "세부내용", "세부 내용", "자세히", "상세히", "상세내용", "상세 내용",
        "더 알려", "더 자세히", "더 상세히",
    ]
    if any(k in t for k in keywords):
        return True
    if "공지" in t and ("공지사항" not in t):
        return True
    return False


def looks_like_recent_notices_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    keywords = [
        "최근 공지", "최신 공지", "최근공지", "최신공지",
        "최근 공지사항", "최신 공지사항",
        "최근 소식", "최신 소식",
        "최근안내", "최신안내", "최근 안내", "최신 안내",
        "공지사항 목록", "공지사항 리스트",
    ]
    if any(k in t for k in keywords):
        return True
    if ("공지사항" in t or "공지" in t) and any(k in t for k in ["안내", "요약", "정리", "알려", "보여", "목록", "리스트"]):
        return True
    if ("공지사항" in t or "공지" in t) and any(k in t for k in ["봐", "봐줘", "보여줘", "못봐", "못 봐", "확인해", "확인해줘"]):
        return True
    if t.strip() in ("공지", "공지사항", "공지 안내", "공지사항 안내", "공지사항좀", "공지좀"):
        return True
    if ("최근" in t or "최신" in t) and any(k in t for k in ["소식", "안내", "공지", "공지사항", "news"]):
        return True
    return False


def extract_notice_search_keyword(user_text: str) -> str:
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

    stop = {
        "공지", "공지사항", "안내", "운영", "관련", "여부", "확인",
        "있나", "있나요", "있어", "알려줘", "해줘", "해주세요", "주세요",
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


def extract_holiday_keyword(user_text: str) -> str:
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


# ---------------------------------------------------------
# 4) 추천 의도/사실확인 의도
# ---------------------------------------------------------

def looks_like_fact_or_ops_request(user_text: str) -> bool:
    """도구(공식 scipia) 근거를 강제해야 하는 질문인지 휴리스틱으로 판정합니다."""
    t = (user_text or "").lower()
    keywords = [
        "요금", "가격", "무료", "유료", "할인",
        "예약", "예매", "신청", "접수", "취소", "환불",
        "운영", "운영시간", "시간", "회차", "시간표", "상영", "프로그램",
        "휴관", "개관", "열려", "닫혀", "가능", "마감",
        "공지", "공지사항", "최근 공지", "안내문",
        "행사", "이벤트", "공연", "강연", "강좌", "세미나", "특별전", "기획전",
        "일정", "스케줄", "시간대", "언제", "몇 일", "며칠",
        "오시는 길", "오는 길", "가는 길", "교통", "지하철", "버스",
        "주차", "주차장", "위치", "주소", "길 안내", "동선",
        "안에", "소속", "포함", "몇 층", "층", "어느 층",
        "건물", "동", "바로 옆", "근처",
    ]
    return any(k in t for k in keywords)


def looks_like_route_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    kws = ["동선", "방문 경로", "방문경로", "어떻게 가", "어떻게 가요", "가는 길", "오시는 길"]
    return any(k in t for k in kws)


def looks_like_recommendation_request(user_text: str) -> bool:
    """'추천/뭐가 좋아/어떤 거'처럼 탐색형(비확정) 추천 의도인지 감지합니다."""
    t = (user_text or "").strip()
    if not t:
        return False

    if looks_like_fact_or_ops_request(t):
        return False

    keywords = [
        "추천", "추천해", "추천해줘", "뭐가 좋아", "뭐 보면", "뭐가 있", "어떤 프로그램",
        "프로그램 추천", "뭘 하면", "코스", "코스 추천", "처음 왔", "처음인데", "처음 방문",
        "가볼만", "가볼 만",
    ]
    return any(k in t for k in keywords)


# ---------------------------------------------------------
# 5) 추가 질문(날짜/나이/단체) 필요 판단
# ---------------------------------------------------------

def _has_date_token(t: str) -> bool:
    t = (t or "")
    if re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", t):
        return True
    if re.search(r"\d{1,2}\s*월\s*\d{1,2}\s*일", t):
        return True
    if any(w in t for w in [
        "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
        "평일", "주말", "오늘", "내일", "모레", "이번주", "다음주", "이번 달", "다음 달",
    ]):
        return True
    return False


def _has_age_token(t: str) -> bool:
    t = (t or "")
    if re.search(r"(만\s*)?\d{1,2}\s*세", t):
        return True
    if re.search(r"\d\s*학년", t):
        return True
    return False


def needs_date_question(user_text: str) -> bool:
    t = (user_text or "")
    date_dependent = any(k in t for k in [
        "몇시", "언제", "회차", "시간표", "상영", "운영", "열려", "가능",
        "예약", "신청", "접수", "마감", "잔여", "매진", "입장",
    ])
    return date_dependent and (not _has_date_token(t))


def needs_age_question(user_text: str) -> bool:
    t = (user_text or "")
    age_sensitive = any(k in t for k in [
        "추천", "아이", "어린이", "유아", "유치원", "초등", "중등", "고등",
        "학생", "가족", "연령", "몇살", "나이", "7세", "8세",
    ])
    return age_sensitive and (not _has_age_token(t))


def needs_group_question(user_text: str) -> bool:
    t = (user_text or "")
    group_cue = any(k in t for k in [
        "단체", "학교", "기관", "학원", "견학", "수학여행", "인솔", "버스", "전화예약",
    ]) or bool(re.search(r"\d{2,4}\s*명", t))

    if any(k in t for k in ["개인", "단체"]):
        return False

    return group_cue


def pre_questions_message(user_text: str) -> str:
    qs = []
    if needs_group_question(user_text):
        qs.append("1) **개인 관람**인가요, **학교/기관 단체**인가요?")
    if needs_age_question(user_text):
        qs.append("2) 관람 대상의 **정확한 나이(만 나이 또는 학년)** 를 알려주세요.")
    if needs_date_question(user_text):
        qs.append("3) 방문 **날짜(또는 평일/주말)** 를 알려주시면 회차/예약 가능 여부를 정확히 확인해드릴게요.")

    if not qs:
        return ""

    return "정확히 안내하려면 아래 정보가 필요해요. (해당되는 것만 답해주시면 돼요!)\n\n" + "\n".join(qs)


# ---------------------------------------------------------
# 6) 추천 질문용 안내 문구
# ---------------------------------------------------------

def interest_topics_prompt_intro() -> str:
    return (
        "국립과천과학관은 우리가 만날 수 있는 다양한 주제에 대해서 "
        "직접 보고·듣고·체험하면서 과학을 이해할 수 있게 구성된 공간이에요. "
        "실내 상설전시(기초과학/첨단기술), 천문·우주, 야외 생태·공원 전시, "
        "시기별 특별 프로그램/행사 등이 함께 운영돼요.\n\n"
        "관심있는 주제를 알려주시면 더 정확한 안내를 도와드릴게요! 어떤 주제에 관심 있으세요?\n\n"
    )


def interest_topics_prompt_list(core_topics: Optional[list[str]] = None) -> str:
    defaults = [
        "첨단기술", "미래과학", "천문우주", "동물/자연", "공룡",
        "곤충/생태", "유아/어린이", "전시해설", "행사/공연",
    ]

    merged: list[str] = []
    seen = set()
    for x in (core_topics or []) + defaults:
        if x in seen:
            continue
        seen.add(x)
        merged.append(x)

    return "\n".join([f"- {x}" for x in merged[:9]])
