# app.py
import os
import streamlit as st
from gnsm.ui_app import run_chat_assistant


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        # python-dotenv 미설치 또는 .env 미존재 환경에서도 앱이 죽지 않게 합니다.
        pass

def _check_api_key():
    if not os.getenv("OPENAI_API_KEY"):
        st.warning(
            "⚠️ OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.",
            icon="⚠️",
        )

def main():
    _load_env()

    # 브라우저 탭 아이콘을 싸돌이로 설정
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    favicon_path = os.path.join(current_dir, "assets", "ssadori_face_remove.png")
    
    st.set_page_config(
        page_title="국립과천과학관 AI 가이드",
        page_icon=favicon_path,
        layout="centered",
    )

    _check_api_key()
    
    # 언어 설정에 따른 제목
    language = st.session_state.get("language", "한국어")
    
    # 싸돌이 이미지와 제목 함께 표시
    col_icon, col_title = st.columns([1, 9])
    with col_icon:
        import os
        try:
            # 절대 경로 사용
            current_dir = os.path.dirname(os.path.abspath(__file__))
            image_path = os.path.join(current_dir, "assets", "ssadori_face_remove.png")
            st.image(image_path, width=72)
        except Exception as e:
            # 폴백: 이모지 표시
            st.write("🤖")
    with col_title:
        if language == "English":
            st.markdown("# Gwacheon National Science Museum AI Guide!")
        else:
            st.markdown("# 국립과천과학관 AI 가이드!")
    
    # 기본 스타일링
    st.markdown("""
    <style>
        /* 사용자 메시지 스타일 - 과학관 테마색 (보라/파랑 계열) */
        .stChatMessage[data-testid="user-message"] {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
            border-radius: 15px !important;
            padding: 15px !important;
        }
        
        .stChatMessage[data-testid="user-message"] p {
            color: white !important;
            font-weight: 500 !important;
        }
        
        /* AI 답변 내 중요 텍스트 (### 헤더) 크기 조정 */
        .stChatMessage[data-testid="assistant-message"] h3 {
            font-size: 1.2rem !important;
            margin-top: 1rem !important;
            margin-bottom: 0.5rem !important;
        }
        
    </style>
    """, unsafe_allow_html=True)
    
    # 웰컴 메시지 - 첫 방문자 가이드
    if "messages" not in st.session_state or len(st.session_state.messages) == 0:
        if language == "English":
            st.info("""
👋 **Welcome to the Gwacheon National Science Museum AI Guide!**

I'm an AI guide that provides real-time information about the Gwacheon National Science Museum.

**💡 I can help you with:**
- 🕐 **Operating hours** and closure days
- 🎫 **Admission fees** and discount information
- 🚗 **Directions** and parking information
- 🎪 **Exhibition halls** and hands-on programs
- 📢 **Latest announcements** and events
- ❓ **Frequently Asked Questions** (FAQ)

Click the buttons below or feel free to ask anything! ✨
            """)
            
            # 퀵 액션 버튼
            st.markdown("### 🎯 Quick Questions")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("🕐 Hours", use_container_width=True, help="Check operating hours"):
                    st.session_state["faq_query"] = "과학관 운영시간"
                    st.rerun()
            
            with col2:
                if st.button("🎫 Admission", use_container_width=True, help="Check admission fees"):
                    st.session_state["faq_query"] = "과학관 관람료"
                    st.rerun()
            
            with col3:
                if st.button("🚗 Directions", use_container_width=True, help="Get directions and parking info"):
                    st.session_state["faq_query"] = "과학관으로 오시는 길"
                    st.rerun()
            
            with col4:
                if st.button("❓ FAQ", use_container_width=True, help="View frequently asked questions"):
                    st.session_state["faq_query"] = "과학관 자주 묻는 질문(FAQ)"
                    st.rerun()
        else:
            st.info("""
👋 **국립과천과학관 AI 가이드에 오신 것을 환영합니다!**

저는 국립과천과학관에 대한 모든 정보를 실시간으로 안내해드리는 AI 가이드예요.

**💡 이런 질문에 답변할 수 있어요:**
- 🕐 **운영시간** 및 휴관일 안내
- 🎫 **관람료** 및 할인 정보
- 🚗 **교통편** 및 주차 안내
- 🎪 **전시관** 및 체험 프로그램 소개
- 📢 **최신 공지사항** 및 행사 정보
- ❓ **자주 묻는 질문**(FAQ)

아래 버튼을 클릭하거나 궁금한 것을 자유롭게 물어보세요! ✨
            """)
            
            # 퀵 액션 버튼
            st.markdown("### 🎯 빠른 질문")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("🕐 운영시간", use_container_width=True, help="과학관 운영시간을 알려드려요"):
                    st.session_state["faq_query"] = "과학관 운영시간"
                    st.rerun()
            
            with col2:
                if st.button("🎫 관람료", use_container_width=True, help="관람료 및 할인 정보를 안내해드려요"):
                    st.session_state["faq_query"] = "과학관 관람료"
                    st.rerun()
            
            with col3:
                if st.button("🚗 오시는 길", use_container_width=True, help="교통편 및 주차 정보를 알려드려요"):
                    st.session_state["faq_query"] = "과학관으로 오시는 길"
                    st.rerun()
            
            with col4:
                if st.button("❓ FAQ", use_container_width=True, help="자주 묻는 질문을 확인하세요"):
                    st.session_state["faq_query"] = "과학관 자주 묻는 질문(FAQ)"
                    st.rerun()
        
        st.markdown("---")
    else:
        if language == "English":
            st.write("Feel free to ask anything! 😉")
        else:
            st.write("무엇이든 물어보세요.😉")

    run_chat_assistant()

if __name__ == "__main__":
    main()
