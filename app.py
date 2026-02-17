from flask import Flask, request, render_template_string, send_file
import requests
import time
import os
import pandas as pd
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

MAX_WORKERS = 5
results_storage = []

# =========================
# 검색량 (광고 API 없으면 0)
# =========================
def get_search_volume(keyword):
    return 0  # 검색량은 일단 유지 (필요하면 다시 추가)

# =========================
# 판매처 개수 직접 추출 (모바일 검색 기준)
# =========================
def get_seller_count(keyword):
    try:
        url = "https://m.search.naver.com/search.naver"
        params = {"query": keyword}

        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)"
        }

        r = requests.get(url, params=params, headers=headers, timeout=10)
        html = r.text

        # "도서 판매처 198" 패턴 찾기
        match = re.search(r"도서 판매처\s*([0-9,]+)", html)

        if match:
            return int(match.group(1).replace(",", ""))

        return 0

    except:
        return 0

# =========================
# 분류 기준
# =========================
def classify(seller_count):
    if seller_count == 0:
        return "A"
    else:
        return "B"

# =========================
# 키워드 처리
# =========================
def process_keyword(keyword):
    seller = get_seller_count(keyword)
    grade = classify(seller)

    return {
        "keyword": keyword,
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
<th>판매처개수</th>
<th>분류</th>
<th>링크</th>
</tr>

{% for r in results %}
<tr>
<td>{{ r.keyword }}</td>
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
