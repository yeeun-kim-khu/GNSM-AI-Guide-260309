"""공지 상세 페이지 HTML 구조 분석 스크립트"""
import sys
sys.path.insert(0, r"c:\Users\yeeun\Documents\☆Space Research\code\gnsm_yeeun\예은")

from gnsm.tools import fetch_sciencecenter_page

# 최근 공지 URL
test_urls = [
    "https://www.sciencecenter.go.kr/scipia/introduce/notice/25782",
    "https://www.sciencecenter.go.kr/scipia/introduce/notice/25777",
    "https://www.sciencecenter.go.kr/scipia/introduce/notice/25772",
]

for url in test_urls:
    print(f"\n{'='*80}")
    print(f"Testing: {url}")
    print('='*80)
    
    try:
        text = fetch_sciencecenter_page(url)
        print(f"Length: {len(text)}")
        print(f"First 500 chars:\n{text[:500]}")
        print(f"\nLast 300 chars:\n{text[-300:]}")
        
        # 잡음 키워드 체크
        noise_keywords = ["과학관소식", "고객서비스", "안전관리", "정보나눔터", "전자민원", "분실물목록"]
        found_noise = [k for k in noise_keywords if k in text]
        if found_noise:
            print(f"\n⚠️ Noise keywords found: {found_noise}")
        
        # 실제 본문 키워드 체크
        content_keywords = ["안내", "개최", "신청", "모집", "운영", "관람", "무료", "기념"]
        found_content = [k for k in content_keywords if k in text]
        if found_content:
            print(f"✓ Content keywords found: {found_content}")
        else:
            print("❌ No content keywords found - likely failed to extract body")
            
    except Exception as e:
        print(f"Error: {e}")
    
    print()
