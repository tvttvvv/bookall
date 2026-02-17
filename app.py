from flask import Flask, request, render_template_string, send_file
import requests
import time
import os
import pandas as pd
import io
import hashlib
import hmac
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# =========================
# 환경변수
# =========================
ACCESS_KEY = os.getenv("ACCESS_KEY") or ""
SECRET_KEY = os.getenv("SECRET_KEY") or ""
CUSTOMER_ID = os.getenv("CUSTOMER_ID") or ""

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID") or ""
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET") or ""

MAX_WORKERS = 5
results_storage = []

# =========================
# 광고 API 서명
# =========================
def generate_signature(timestamp, method, uri):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(
        SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    )
    return base64.b64encode(hash.digest()).decode()

# =========================
# 검색량
# =========================
def get_search_volume(keyword):
    try:
        if not ACCESS_KEY:
            return 0

        uri = "/keywordstool"
        method = "GET"
        timestamp = str(int(time.time() * 1000))
        signature = generate_signature(timestamp, method, uri)

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Timestamp": timestamp,
            "X-API-KEY": ACCESS_KEY,
            "X-Customer": CUSTOMER_ID,
            "X-Signature": signature,
        }

        params = {
            "hintKeywords": keyword,
            "showDetail": 1
        }

        url = "https://api.searchad.naver.com/keywordstool"
        r = requests.get(url, headers=headers, params=params, timeout=10)

        if r.status_code != 200:
            return 0

        data = r.json()
        if not data.get("keywordList"):
            return 0

        item = data["keywordList"][0]

        def safe(v):
            if not v:
                return 0
            if isinstance(v, str) and "<" in v:
                return 0
            return int(v)

        return safe(item.get("monthlyPcQcCnt")) + safe(item.get("monthlyMobileQcCnt"))

    except:
        return 0

# =========================
# 판매처 개수 (도서 API 사용)
# =========================
def get_seller_count(keyword):
    try:
        if not NAVER_CLIENT_ID:
            return 0

        url = "https://openapi.naver.com/v1/search/book.json"

        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
        }

        params = {
            "query": keyword,
            "display": 1
        }

        r = requests.get(url, headers=headers, params=params, timeout=10)

        if r.status_code != 200:
            return 0

        return r.json().get("total", 0)

    except:
        return 0

# =========================
# 대표카드 판별 (내부용)
# =========================
def has_represent_card(keyword):
    try:
        url = "https://m.search.naver.com/search.naver"
        params = {"query": keyword}

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        r = requests.get(url, params=params, headers=headers, timeout=10)
        html = r.text

        return "api_subject_bx" in html and "book" in html

    except:
        return False

# =========================
# 분류
# =========================
def classify(seller_count, has_card):
    if seller_count == 0 and not has_card:
        return "A"
    else:
        return "B"

# =========================
# 키워드 처리
# =========================
def process_keyword(keyword):
    volume = get_search_volume(keyword)
    seller = get_seller_count(keyword)
    card = has_represent_card(keyword)
    grade = classify(seller, card)

    return {
        "keyword": keyword,
        "total_search": volume,
        "seller_count": seller,
        "grade": grade,
        "link": f"https://search.naver.com/search.naver?query={keyword}"
    }

# =========================
# HTML
# =========================
HTML = """
<!doctype html>
<title>Book 통합 분석기</title>
<h1>Book 통합 분석기</h1>

<form method="POST">
<textarea name="keywords" rows="10" cols="60"
placeholder="책 제목을 한 줄에 하나씩 입력"></textarea><br><br>
<button type="submit">일괄 분류 시작</button>
</form>

{% if results %}
<hr>
총 입력 건수: {{ results|length }}<br><br>

<table border="1" cellpadding="5">
<tr>
<th>키워드</th>
<th>총검색량</th>
<th>판매처개수</th>
<th>분류</th>
<th>링크</th>
</tr>

{% for r in results %}
<tr>
<td>{{ r.keyword }}</td>
<td>{{ "{:,}".format(r.total_search) }}</td>
<td>{{ "{:,}".format(r.seller_count) }}</td>
<td>{{ r.grade }}</td>
<td><a href="{{ r.link }}" target="_blank">열기</a></td>
</tr>
{% endfor %}
</table>

<br><br>
<a href="/download">엑셀 다운로드</a>
{% endif %}
"""

@app.route("/", methods=["GET", "POST"])
def home():
    global results_storage
    results_storage = []

    if request.method == "POST":
        keywords = request.form.get("keywords", "").splitlines()
        keywords = [k.strip() for k in keywords if k.strip()]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_keyword, k) for k in keywords]
            for future in as_completed(futures):
                results_storage.append(future.result())

        return render_template_string(HTML, results=results_storage)

    return render_template_string(HTML)

@app.route("/download")
def download():
    df = pd.DataFrame(results_storage)
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    return send_file(output, download_name="book_analysis.xlsx", as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
