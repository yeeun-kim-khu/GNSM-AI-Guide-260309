"""gnsm package

이 패키지는 '국립과천과학관 AI 가이드(Streamlit + LangGraph ReAct)' 앱의 핵심 로직을
기능 단위로 분리해둔 모듈 모음입니다.

- UI(Streamlit 렌더링)
- 에이전트(LangGraph) 초기화/호출
- 프롬프트
- 세션 상태/메모리
- 의도/스코프 휴리스틱
- 텍스트 파싱(출처/이미지)

app.py는 보통 gnsm.ui_app.run_chat_assistant()만 호출하면 동작합니다.
"""
