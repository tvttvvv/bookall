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

# (참고: 화면 구조를 직접 크롤링하므로 NAVER_CLIENT_ID/SECRET 검색 API는 이제 사용하지 않아도 됩니다.)

# --- 광고 API 인증 헤더 생성 함수 ---
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

# --- 데이터 분석 로직 ---
def analyze_book(keyword):
    # 1. 총 검색량 조회 (광고 API - 가장 정확함)
    search_volume = 0
    try:
        uri = '/keywordstool'
        params = {'hintKeywords': keyword, 'showDetail': '1'}
        headers = get_ad_header('GET', uri)
        res = requests.get(f"https://api.naver.com{uri}", params=params, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()['keywordList'][0]
            search_volume = (data['monthlyPcQcCnt'] or 0) + (data['monthlyMobileQcCnt'] or 0)
            if isinstance(search_volume, str): search_volume = 10
    except Exception as e:
        print(f"광고 API 에러: {e}")
        search_volume = 0

    # 2. 화면 크롤링을 통한 A/B 분류 (요청하신 사진 기준)
    link = f"https://search.naver.com/search.naver?where=nexearch&query={urllib.parse.quote(keyword)}"
    grade = ""
    reason = ""
    seller_count = 0

    try:
        # 네이버 봇 차단 방지를 위한 헤더
        req_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        html_res = requests.get(link, headers=req_headers, timeout=5)
        soup = BeautifulSoup(html_res.text, "html.parser")

        # 네이버 도서 영역 찾기
        book_area = None
        # 보통 도서 정보는 cs_book 이라는 클래스를 가짐
        if soup.find(class_="cs_book"):
            book_area = soup.find(class_="cs_book")
        else:
            # 혹시 모르니 타이틀에 '도서'가 있는 영역도 교차 검증
            for sec in soup.find_all("div", class_="api_subject_bx"):
                title_tag = sec.find(class_="api_title")
                if title_tag and ("도서" in title_tag.text or "책정보" in title_tag.text):
                    book_area = sec
                    break

        # 기준 판단 로직
        if not book_area:
            # 기준 2: 검색했을 때 책 정보가 아예 안 나옴 (사진 2)
            grade = "B (일반)"
            reason = "도서 검색결과 없음"
        else:
            # 도서 영역이 있다면 텍스트 추출
            text_content = book_area.get_text()
            
            # 기준 1: 대표카드 및 판매처 숫자 확인 (사진 1)
            # 정규식으로 '판매처 00' 패턴을 찾음
            match = re.search(r'판매처\s*(\d+)', text_content)
            
            if match:
                seller_count = int(match.group(1))
                grade = "B (일반)"
                reason = f"대표카드 묶임 (판매처 {seller_count}개)"
            else:
                # 책 카드는 뜨는데 판매처가 묶이지 않은 경우
                grade = "A (황금 🏆)"
                reason = "대표카드 아님 (단독 노출)"

    except Exception as e:
        print(f"크롤링 에러: {e}")
        grade = "검색 실패"
        reason = "일시적 접속 오류"

    return {
        "keyword": keyword,
        "search_volume": search_volume,
        "seller_count": seller_count if seller_count > 0 else "-",
        "grade": grade,
        "reason": reason,
        "link": link
    }

# --- 웹 페이지 템플릿 ---
TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Book 분석기 Pro</title></head>
<body>
    <h1>📚 도서 키워드 통합 분석기</h1>
    <form method="POST">
        <textarea name="keywords" rows="10" cols="70" placeholder="책 제목들을 한 줄에 하나씩 입력하세요">{{keywords}}</textarea><br><br>
        <button type="submit" style="padding:10px 20px;">일괄 분석 시작</button>
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
        <tr>
            <td>{{r.keyword}}</td>
            <td>{{ "{:,}".format(r.search_volume) if r.search_volume > 0 else 0 }}</td>
            <td>{{ r.seller_count }}</td>
            <td><b>{{r.grade}}</b></td>
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
            time.sleep(0.3) # 네이버 크롤링 차단 방지를 위해 대기 시간을 조금 늘림

    return render_template_string(TEMPLATE, results=results, keywords=keywords_text)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
