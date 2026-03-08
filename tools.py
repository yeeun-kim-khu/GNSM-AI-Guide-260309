"""tools.py (DEPRECATED)

이 파일은 더 이상 앱의 '실제 구현'을 담지 않습니다.

목표:
- 기존 코드베이스에서 실수로 `import tools`를 하더라도 동작은 하게(또는 명확히 실패하게) 만들기
- 실제 구현은 `gnsm.tools`로 완전히 이전되었습니다.

즉, 이 파일은 레거시 호환을 위한 '리다이렉트'만 제공합니다.
"""

from __future__ import annotations

from gnsm.tools import *  # noqa: F401,F403
