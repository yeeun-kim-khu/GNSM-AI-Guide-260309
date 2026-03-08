# 국립과천과학관 AI 가이드 (Streamlit + LangGraph ReAct)

국립과천과학관(sciencecenter.go.kr/scipia) 공식 페이지를 근거로 운영/프로그램/행사/공간 정보를 안내하는 **Streamlit 기반 챗봇**입니다.

- **UI**: Streamlit 채팅 화면
- **Agent**: LangGraph ReAct + LangChain(OpenAI)
- **도구(@tool)**: scipia 페이지/공지사항/이미지 등을 가져오는 크롤링 도구
- **원칙**: 운영/요금/예약/공지/동선 등 **사실 확인이 필요한 답변은 도구(공식 페이지)를 우선 사용**

## 1) 빠른 실행 방법

### 1-1. 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1-2. 환경 변수 설정

이 앱은 OpenAI API Key가 필요합니다.

권장: 프로젝트 루트에 `.env` 파일을 만들고 아래처럼 넣어두면 `app.py` 실행 시 자동으로 로드됩니다.

```env
OPENAI_API_KEY=YOUR_KEY
```

macOS / Linux:

```bash
export OPENAI_API_KEY="YOUR_KEY"
```

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="YOUR_KEY"
```

### 1-3. 실행

```bash
streamlit run app.py
```

## 2) 프로젝트 구조(폴더/파일 설명)

최상위 폴더:

```text
예은/
  app.py
  requirements.txt
  README.md
  gnsm/
    ...
  tools.py        (DEPRECATED, 내용 없음/redirect 용)
  utils.py        (DEPRECATED, 내용 없음/redirect 용)
```

### 2-1. 엔트리 포인트

- `app.py`
  - Streamlit 앱 엔트리 파일입니다.
  - 내부에서 `gnsm.ui_app.run_chat_assistant()`를 호출합니다.

### 2-2. gnsm 패키지(실제 구현)

아래 파일들이 **실제 구현(핵심 로직)** 입니다.

- `gnsm/ui_app.py`
  - Streamlit 채팅 UI의 **메인 실행 파일**
  - 사용자 입력 수집, 세션 메시지 렌더링, UX 분기(추천/공지/동선), 에이전트 호출, 출처/이미지 렌더링까지 담당

- `gnsm/agent_runtime.py`
  - LangGraph ReAct 에이전트 생성/호출 담당
  - `gnsm.tools`의 @tool들을 안전하게 로드
  - 에이전트 실행 결과에서 최종 답변/출처 blob 분리
  - 필요 시 1회 재시도(도구 사용 강제) 로직 포함

- `gnsm/tools.py`
  - **도구(@tool) 모음**
  - scipia 페이지/공지/이미지 등을 가져오고 텍스트로 정리하는 함수들이 들어있습니다.
  - 에이전트는 이 도구들을 호출해 최신 근거를 확보합니다.

- `gnsm/prompt.py`
  - 시스템 프롬프트를 관리
  - 오늘 날짜(KST)를 프롬프트에 삽입하여 상대 날짜 해석(“이번 주”, “내일”)을 안정화

- `gnsm/messages.py`
  - 에이전트에게 전달할 메시지 배열을 구성
  - 시스템 프롬프트 + 상황별 가이드(동선/공지 등) + RAG 발췌 + 관심주제/사용자 메모 주입

- `gnsm/heuristics.py`
  - “추천/운영 사실확인/공지/동선” 등 **의도 판별**
  - 스코프(planetarium/observatory/space_analog/star_road 등) 점수화
  - 추가 확인 질문(날짜/나이/단체) 필요 여부 판단

- `gnsm/ui_render.py`
  - Streamlit 부가 렌더링
  - 출처 버튼(최소 1개 이상 제공) + 답변 내 [이미지-n] URL을 이미지로 표시

- `gnsm/text_parsing.py`
  - 답변 텍스트에서 `[출처]`, `[이미지]` 메타 정보를 파싱
  - UI에 표시할 텍스트 정리(메타 라인/URL 제거)

- `gnsm/state.py`
  - `st.session_state`에 저장되는 상태를 일관된 키로 관리
  - 메시지 히스토리, 관심 주제, 사용자 제공 위치 메모 등을 관리

- `gnsm/rag.py`
  - 세션 내부 “가벼운 RAG”
  - 대화 임베딩을 저장하고 유사한 과거 발화를 찾아 system 메시지로 주입

- `gnsm/hall_notes.py`
  - 사용자가 제공한 “전시관 위치 메모”를 추출/저장
  - 공식 근거가 아니라는 점을 전제로 보조 정보로만 사용

- `gnsm/notice_summary.py`
  - 공지 목록/상세 페이지 텍스트로부터 짧은 요약을 생성

- `gnsm/__init__.py`
  - 패키지 개요

- `gnsm/utils_legacy.py`
  - 과거 `utils.py` 코드 백업(현재 실행 경로에서 사용하지 않음)
  - 참고/비교용으로만 유지

## 3) 실행 흐름(설명/발표용)

### 3-1. 전체 흐름

1. 사용자가 `app.py` 실행 (`streamlit run app.py`)
2. `app.py`가 `gnsm.ui_app.run_chat_assistant()` 호출
3. `ui_app.py`에서 입력을 받으면
   - `heuristics.py`로 의도/스코프 판단
   - 필요 시 공지/최근 공지 등은 UI 레벨에서 빠르게 요약 처리
   - 동선 질문이면 이미지 URL을 먼저 추출
4. 에이전트 호출
   - `messages.py`가 system prompt + 컨텍스트를 포함한 메시지 배열 생성
   - `agent_runtime.py`가 LangGraph ReAct 에이전트 실행
   - 에이전트가 필요 시 `tools.py`의 도구를 호출하여 scipia 근거를 확보
5. 응답 출력
   - `text_parsing.py`로 UI 표시용 텍스트 정리
   - `ui_render.py`로 출처 버튼/이미지 렌더링
   - `rag.py`에 대화 요약(임베딩) 저장

## 4) 자주 발생하는 문제(FAQ)

### Q1) 화면에 “OPENAI_API_KEY가 설정되지 않았다”가 떠요

- `OPENAI_API_KEY` 환경 변수를 설정해야 합니다.
- 설정 후 터미널(또는 IDE)을 재시작한 다음 다시 실행해 주세요.

### Q2) tools 관련 에러가 나요

- `gnsm/tools.py`는 `requests`, `bs4(BeautifulSoup)` 등을 사용합니다.
- `pip install -r requirements.txt`가 정상적으로 완료되었는지 확인해 주세요.

### Q3) 공지/요금/예약 같은 질문에서 답이 부정확해요

- 이 앱은 원칙적으로 도구로 확인된 근거(Observation)에 기반해 답하도록 설계되었습니다.
- scipia 페이지 구조가 바뀌면 크롤링 파서가 실패할 수 있어요. 그 경우 `gnsm/tools.py`의 파싱 로직을 업데이트해야 합니다.

## 5) 개발 메모

- 모델: `gpt-4.1-mini` (temperature=0.2)
- 임베딩: `text-embedding-3-small`
- 외부 근거: <https://www.sciencecenter.go.kr/scipia/>

## 6) 최근 수정 사항(발표용 정리)

이 섹션은 “최근 공지사항” UX 개선을 중심으로, 발표를 위해 변경된 지점을 파일 단위로 정리한 내용입니다.

### 6-1. 사이드바 ‘최근 공지사항’ 클릭 → 질문 문구 자동 생성

- 변경 파일
  - `gnsm/ui_app.py`
- 변경 내용
  - 사이드바 ‘최근 공지사항’ 버튼 클릭 시, 사용자가 직접 입력하지 않아도 채팅 입력으로 자동 질의가 들어가도록 처리
  - 클릭한 공지의 상세 URL은 사용자에게 노출하지 않고, 세션 상태(`st.session_state`)에 힌트 값으로 저장해 내부 로직에서만 사용
  - 버튼 제목은 길이 제한(15자) + `...`로 한 줄 표시
  - 공지 질문 문구는 `"'{공지제목}' 공지사항에 대해 안내해줘"` 형태로 생성

### 6-2. 공지 상세 내용 표시 방식(아이콘 제거 / 줄바꿈 최소화)

- 변경 파일
  - `gnsm/notice_summary.py`
- 변경 내용
  - 공지 상세 텍스트에서 `Observation:` / `[출처]` 등 메타 라인을 제거하고 본문만 추출
  - 본문 포맷 함수 `_format_notice_content()`는
    - 이모지(📅/🏛️/👥 등) 자동 삽입을 하지 않도록 변경(= 아이콘 제거)
    - 줄바꿈을 공백으로 합쳐 과도한 줄바꿈을 줄임
  - `build_notice_summary_answer()`에서
    - 답변 첫 줄에 제목을 중복 출력하지 않도록(본문부터 시작하도록) 반환 형태 조정

### 6-3. ‘출처’ 하이퍼링크 버튼이 클릭한 공지 상세 URL로 이동하도록 수정

- 변경 파일
  - `gnsm/ui_render.py`
- 변경 내용
  - 답변 텍스트에 `/scipia/introduce/notice/<id>` 형태의 공지 상세 URL이 `[출처]`로 포함되어 있으면
    - 키워드 기반 판정(공지/안내/모집 등)과 무관하게 **해당 상세 URL을 우선 버튼으로 렌더링**
  - 언어 설정(`st.session_state['language']`)에 따라 버튼 텍스트가 한국어/영어로 표시되도록 조정
    - 한국어: `홈페이지 살펴보기`, `공지사항`, `전시관람 FAQ`
    - 영어: `Homepage`, `Announcements`, `Exhibition FAQ`

### 6-4. 사이드바 ‘채팅이력’ 숨김

- 변경 파일
  - `gnsm/ui_app.py`
- 변경 내용
  - 사이드바의 채팅 세션 목록/검색 UI를 비활성화하여 숨김 처리

### 6-5. 화면 글자 크기(타이포그래피) 한 단계 축소

- 변경 파일
  - `gnsm/ui_app.py`
- 변경 내용
  - 전역 CSS를 한 번 주입하여 채팅 메시지/마크다운(FAQ/공지 포함) 폰트 크기를 한 단계 낮춤

### 6-6. 테스트 방법(데모 시나리오)

1. 실행
   - `streamlit run app.py`
2. 사이드바 ‘최근 공지사항’에서 임의 공지 버튼 클릭
3. 확인 포인트
   - 공지 질문 문구가 자동으로 생성되는지
   - 본문이 아이콘 없이(이모지 자동 삽입 없이) 표시되는지
   - 답변 첫 줄에 제목이 중복으로 반복되지 않는지
   - 답변 아래 출처 버튼이 **클릭한 공지 상세 페이지**로 이동하는지
   - 언어가 한국어/영어일 때 출처 버튼명이 해당 언어로 나오는지
