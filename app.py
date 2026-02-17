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
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
CUSTOMER_ID = os.getenv("CUSTOMER_ID")

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

MAX_WORKERS = 5
results_storage = []

# =========================
# 네이버 광고 API 서명 생성
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
# 검색량 가져오기
# =========================
def get_search_volume(keyword):
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
    r = requests.get(url, headers=headers, params=params)

    if r.status_code == 200:
        data = r.json()
        if data.get("keywordList"):
            item = data["keywordList"][0]
            pc = int(item.get("monthlyPcQcCnt") or 0)
            mobile = int(item.get("monthlyMobileQcCnt") or 0)
            return pc + mobile

    return 0

# =========================
# 판매처 개수 (네이버 쇼핑 total)
# =========================
def get_seller_count(keyword):
    url = "https://openapi.naver.com/v1/search/shop.json"

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    params = {
        "query": keyword,
        "display": 1
    }

    r = requests.get(url, headers=headers, params=params)

    if r.status_code == 200:
        return r.json().get("total", 0)

    return 0

# =========================
# A / B 분류 기준
# =========================
def classify(volume, seller):
    if volume >= 3000 and seller < 300:
        return "A"
    else:
        return "B"

# =========================
# 키워드 처리
# =========================
def process_keyword(keyword):
    volume = get_search_volume(keyword)
    seller = get_seller_count(keyword)
    grade = classify(volume, seller)

    return {
        "keyword": keyword,
        "total_search": volume,
        "seller_count": seller,
        "grade": grade,
        "link": f"https://search.shopping.naver.com/search/all?query={keyword}"
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
placeholder="책 제목을 한 줄에 하나씩 입력 (최대 1000개)"></textarea><br><br>
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

# =========================
# 메인
# =========================
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

        # A 먼저 → 검색량 많은 순
        results_storage.sort(
            key=lambda x: (x["grade"] != "A", -x["total_search"])
        )

        return render_template_string(HTML, results=results_storage)

    return render_template_string(HTML)

# =========================
# 엑셀 다운로드
# =========================
@app.route("/download")
def download():
    df = pd.DataFrame(results_storage)

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        download_name="book_analysis.xlsx",
        as_attachment=True
    )

# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
