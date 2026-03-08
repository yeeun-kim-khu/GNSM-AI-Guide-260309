# session_manager.py
"""채팅 세션 저장 및 관리 모듈"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class SessionManager:
    """채팅 세션을 저장하고 불러오는 클래스"""
    
    def __init__(self, sessions_dir: str = "chat_sessions"):
        """
        Args:
            sessions_dir: 세션 파일을 저장할 디렉토리 경로
        """
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(exist_ok=True)
    
    def generate_session_id(self) -> str:
        """새로운 세션 ID 생성 (타임스탬프 기반)"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def generate_title(self, messages: list) -> str:
        """
        채팅 메시지에서 세션 제목 생성
        
        Args:
            messages: 채팅 메시지 리스트
            
        Returns:
            세션 제목 (첫 번째 사용자 질문 또는 기본 제목)
        """
        if not messages:
            return "새 대화"
        
        # 첫 번째 사용자 메시지 찾기
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                # (chat~~~숫자) 패턴 제거
                import re
                content = re.sub(r'\(chat[^\)]*\)', '', content).strip()
                
                # 너무 긴 제목은 자르기
                if len(content) > 30:
                    return content[:30] + "..."
                return content
        
        return "새 대화"
    
    def save_session(self, session_id: str, messages: list, metadata: Optional[dict] = None) -> bool:
        """
        채팅 세션 저장
        
        Args:
            session_id: 세션 ID
            messages: 채팅 메시지 리스트
            metadata: 추가 메타데이터 (선택)
            
        Returns:
            저장 성공 여부
        """
        try:
            session_data = {
                "id": session_id,
                "title": self.generate_title(messages),
                "messages": messages,
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata or {}
            }
            
            session_file = self.sessions_dir / f"{session_id}.json"
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"세션 저장 오류: {e}")
            return False
    
    def load_session(self, session_id: str) -> Optional[dict]:
        """
        채팅 세션 불러오기
        
        Args:
            session_id: 세션 ID
            
        Returns:
            세션 데이터 또는 None
        """
        try:
            session_file = self.sessions_dir / f"{session_id}.json"
            if not session_file.exists():
                return None
            
            with open(session_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"세션 불러오기 오류: {e}")
            return None
    
    def list_sessions(self, limit: int = 20) -> list[dict]:
        """
        저장된 세션 목록 조회 (최신순)
        
        Args:
            limit: 최대 조회 개수
            
        Returns:
            세션 정보 리스트 (id, title, timestamp)
        """
        try:
            sessions = []
            for session_file in self.sessions_dir.glob("*.json"):
                try:
                    with open(session_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        sessions.append({
                            "id": data.get("id"),
                            "title": data.get("title", "제목 없음"),
                            "timestamp": data.get("timestamp"),
                            "message_count": len(data.get("messages", []))
                        })
                except Exception:
                    continue
            
            # 타임스탬프 기준 최신순 정렬
            sessions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            
            return sessions[:limit]
        except Exception as e:
            print(f"세션 목록 조회 오류: {e}")
            return []
    
    def delete_session(self, session_id: str) -> bool:
        """
        세션 삭제
        
        Args:
            session_id: 세션 ID
            
        Returns:
            삭제 성공 여부
        """
        try:
            session_file = self.sessions_dir / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()
                return True
            return False
        except Exception as e:
            print(f"세션 삭제 오류: {e}")
            return False
    
    def update_session_title(self, session_id: str, new_title: str) -> bool:
        """
        세션 제목 수정
        
        Args:
            session_id: 세션 ID
            new_title: 새 제목
            
        Returns:
            수정 성공 여부
        """
        try:
            session_data = self.load_session(session_id)
            if not session_data:
                return False
            
            session_data["title"] = new_title
            
            session_file = self.sessions_dir / f"{session_id}.json"
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"세션 제목 수정 오류: {e}")
            return False
