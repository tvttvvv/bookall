from flask import Flask, request, render_template_string
import requests
import time
import hmac
import hashlib
import base64
import urllib.parse
import os # 환경 변수를 불러오기 위해 추가

app = Flask(__name__)

# --- API 설정 (Railway 환경 변수에서 불러오기) ---
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

AD_ACCESS_KEY = os.environ.get("ACCESS_KEY", "")
AD_SECRET_KEY = os.environ.get("SECRET_KEY", "")
AD_CUSTOMER_ID = os.environ.get("CUSTOMER_ID", "")

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
    # 1. 검색량 조회 (광고 API)
    search_volume = 0
    try:
        uri = '/keywordstool'
        params = {'hintKeywords': keyword, 'showDetail': '1'}
        headers = get_ad_header('GET', uri)
        res = requests.get(f"https://api.naver.com{uri}", params=params, headers=headers)
        if res.status_code == 200:
            data = res.json()['keywordList'][0]
            # PC + 모바일 검색량 합산
            search_volume = (data['monthlyPcQcCnt'] or 0) + (data['monthlyMobileQcCnt'] or 0)
            # 10 미만은 '10'으로 표기되는 특성 처리
            if isinstance(search_volume, str): search_volume = 10
    except Exception as e:
        print(f"광고 API 에러: {e}")
        search_volume = 0

    # 2. 상품수 및 링크 조회 (검색 API - 쇼핑)
    seller_count = 0
    link = f"https://search.naver.com/search.naver?query={urllib.parse.quote(keyword)}"
    try:
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
        }
        shop_url = f"https://openapi.naver.com/v1/search/shop.json?query={keyword}&display=1"
        res = requests.get(shop_url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            seller_count = data.get('total', 0)
    except Exception as e:
        print(f"검색 API 에러: {e}")
        pass

    # 3. 등급 분류 (A: 검색량 대비 상품수가 적음 / B: 경쟁 치열)
    # 검색량이 0보다 크고, 검색량 100당 상품이 50개 미만일 때 A (비율 0.5 미만)
    if search_volume > 0 and (seller_count / search_volume) < 0.5:
        grade = "A (황금)"
    else:
        grade = "B (일반)"

    return {
        "keyword": keyword,
        "search_volume": search_volume,
        "seller_count": seller_count,
        "grade": grade,
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
            <th>월간 총 검색량 (PC+MO)</th>
            <th>판매 상품 수</th>
            <th>등급</th>
            <th>링크</th>
        </tr>
        {% for r in results %}
        <tr>
            <td>{{r.keyword}}</td>
            <td>{{ "{:,}".format(r.search_volume) }}</td>
            <td>{{ "{:,}".format(r.seller_count) }}</td>
            <td><b>{{r.grade}}</b></td>
            <td><a href="{{r.link}}" target="_blank">네이버검색</a></td>
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
            time.sleep(0.15) # API 속도 제한(Rate Limit) 방지를 위한 약간의 대기 시간

    return render_template_string(TEMPLATE, results=results, keywords=keywords_text)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
