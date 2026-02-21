from flask import Flask, request, render_template_string
import requests
from bs4 import BeautifulSoup
import time
import hmac
import hashlib
import base64
import urllib.parse
import os
import re

app = Flask(__name__)

# --- 광고 API 설정 (Railway 환경 변수) ---
AD_ACCESS_KEY = os.environ.get("ACCESS_KEY", "")
AD_SECRET_KEY = os.environ.get("SECRET_KEY", "")
AD_CUSTOMER_ID = os.environ.get("CUSTOMER_ID", "")

def get_ad_header(method, uri):
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(AD_SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    signature = base64.b64encode(hash).decode()
    
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Timestamp": timestamp,
        "X-API-KEY": AD_ACCESS_KEY,
        "X-Customer": str(AD_CUSTOMER_ID),
        "X-Signature": signature
    }

def analyze_book(keyword):
    # 1. 총 검색량 조회 (광고 API 정확도 개선)
    search_volume = 0
    try:
        uri = '/keywordstool'
        # 띄어쓰기 문제 해결을 위해 공백 제거
        clean_keyword = keyword.replace(" ", "")
        params = {'hintKeywords': clean_keyword, 'showDetail': '1'}
        headers = get_ad_header('GET', uri)
        res = requests.get(f"https://api.naver.com{uri}", params=params, headers=headers, timeout=5)
        
        if res.status_code == 200:
            data_list = res.json().get('keywordList', [])
            found = False
            # API가 반환한 목록 중 가장 유사한 키워드의 검색량 추출
            for item in data_list:
                api_kw = item.get('relKeyword', '').replace(" ", "")
                if api_kw.lower() == clean_keyword.lower():
                    pc = item.get('monthlyPcQcCnt', 0)
                    mo = item.get('monthlyMobileQcCnt', 0)
                    # '< 10' 문자열 처리
                    if isinstance(pc, str): pc = 10
                    if isinstance(mo, str): mo = 10
                    search_volume = pc + mo
                    found = True
                    break
            
            # 정확히 일치하지 않아도 검색결과가 있다면 첫 번째 데이터 사용
            if not found and len(data_list) > 0:
                item = data_list[0]
                pc = item.get('monthlyPcQcCnt', 0)
                mo = item.get('monthlyMobileQcCnt', 0)
                if isinstance(pc, str): pc = 10
                if isinstance(mo, str): mo = 10
                search_volume = pc + mo
    except Exception as e:
        print(f"광고 API 에러: {e}")
        search_volume = 0

    # 2. 화면 크롤링 (네이버 차단 우회 및 구조 파악 개선)
    link = f"https://search.naver.com/search.naver?where=nexearch&query={urllib.parse.quote(keyword)}"
    grade = ""
    reason = ""
    seller_count = 0

    try:
        # 네이버가 봇을 차단하지 않도록 진짜 브라우저처럼 위장
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://www.naver.com/"
        }
        html_res = requests.get(link, headers=req_headers, timeout=5)
        soup = BeautifulSoup(html_res.text, "html.parser")

        # 네이버 도서 영역을 광범위하게 찾기
        book_area = None
        
        # 방식 A: 클래스명으로 찾기 (최신 네이버 구조 반영)
        book_area = soup.find(class_=re.compile(r'cs_book|sp_book'))
        
        # 방식 B: 클래스가 바뀌었을 경우를 대비해 '도서' 타이틀을 가진 섹션 직접 찾기
        if not book_area:
            for bx in soup.find_all("div", class_="api_subject_bx"):
                title_tag = bx.find(class_=re.compile(r'api_title|title'))
                if title_tag and ('도서' in title_tag.get_text() or '책정보' in title_tag.get_text()):
                    book_area = bx
                    break

        if book_area:
            # 도서 영역 텍스트 전체에서 '판매처 [숫자]' 추출
            book_text = book_area.get_text(separator=" ", strip=True)
            match = re.search(r'(?:도서\s*)?판매처\s*([\d,]+)', book_text)
            
            if match:
                seller_count = int(match.group(1).replace(',', ''))
                grade = "B (일반)"
                reason = f"대표카드 묶임 (판매처 {seller_count}개)"
            else:
                grade = "A (황금 🏆)"
                reason = "대표카드 아님 (단독 노출)"
        else:
            # 도서 영역을 못 찾았지만 혹시 화면 어딘가에 책 판매처가 뜬다면 (최후의 보루)
            page_text = soup.get_text(separator=" ", strip=True)
            match_fallback = re.search(r'도서\s*판매처\s*([\d,]+)', page_text)
            if match_fallback:
                seller_count = int(match_fallback.group(1).replace(',', ''))
                grade = "B (일반)"
                reason = f"대표카드 묶임 (판매처 {seller_count}개)"
            else:
                grade = "B (일반)"
                reason = "도서 검색결과 없음"

    except Exception as e:
        print(f"크롤링 에러: {e}")
        grade = "오류"
        reason = "일시적 스크래핑 실패"

    return {
        "keyword": keyword,
        "search_volume": search_volume,
        "seller_count": seller_count if seller_count > 0 else "-",
        "grade": grade,
        "reason": reason,
        "link": link
    }

# --- 웹 페이지 템플릿 (UI 약간 다듬음) ---
TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Book 분석기 Pro</title></head>
<body>
    <h1>📚 도서 키워드 통합 분석기</h1>
    <form method="POST">
        <textarea name="keywords" rows="10" cols="70" placeholder="책 제목들을 한 줄에 하나씩 입력하세요">{{keywords}}</textarea><br><br>
        <button type="submit" style="padding:10px 20px; font-weight:bold; cursor:pointer;">일괄 분석 시작</button>
    </form>

    {% if results %}
    <hr>
    <table border="1" style="width:100%; border-collapse: collapse; text-align:center;">
        <tr style="background-color: #f2f2f2;">
            <th>키워드</th>
            <th>월간 총 검색량</th>
            <th>판매처 수</th>
            <th>분류 등급</th>
            <th>분류 이유 (참고용)</th>
            <th>링크</th>
        </tr>
        {% for r in results %}
        <tr style="background-color: {{ '#e6f7ff' if 'A' in r.grade else 'white' }};">
            <td style="padding: 5px;">{{r.keyword}}</td>
            <td>{{ "{:,}".format(r.search_volume) if r.search_volume > 0 else 0 }}</td>
            <td><b style="color:#d9534f;">{{ r.seller_count }}</b></td>
            <td><span style="color: {{ 'blue' if 'A' in r.grade else 'black' }}; font-weight:bold;">{{r.grade}}</span></td>
            <td style="color: gray; font-size: 0.9em;">{{r.reason}}</td>
            <td><a href="{{r.link}}" target="_blank">확인하기</a></td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    results = []
    keywords_text = ""
    if request.method == "POST":
        keywords_text = request.form.get("keywords", "")
        keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
        
        for keyword in keywords:
            results.append(analyze_book(keyword))
            time.sleep(0.5) # 서버 차단 방지용 딜레이 (조금 늘림)

    return render_template_string(TEMPLATE, results=results, keywords=keywords_text)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
