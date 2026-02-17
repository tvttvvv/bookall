from flask import Flask, request, render_template_string
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
import time
import random

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9"
}

TEMPLATE = """
<h1>Book 통합 분석기</h1>

<form method="POST">
<textarea name="keywords" rows="10" cols="70">{{keywords}}</textarea><br><br>
<button type="submit">일괄 분류 시작</button>
</form>

{% if progress %}
<p><b>진행중:</b> {{progress}} / {{total}} | 남은 개수: {{remaining}}</p>
{% endif %}

{% if results %}
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
<td>{{r.keyword}}</td>
<td>{{r.search_volume}}</td>
<td>{{r.seller_count}}</td>
<td>{{r.grade}}</td>
<td><a href="{{r.link}}" target="_blank">열기</a></td>
</tr>
{% endfor %}
</table>
{% endif %}
"""

def extract_search_volume(html):
    match = re.search(r'([\d,]+)\s*건', html)
    if match:
        return int(match.group(1).replace(",", ""))
    return 0

def extract_seller_count(soup):
    seller_count = 0
    has_card = False

    # 네이버 도서 대표 카드 영역
    card = soup.select_one("div.api_subject_bx")
    if card:
        has_card = True
        text = card.get_text(" ", strip=True)

        # 판매처 숫자 추출
        match = re.search(r'판매처\s*(\d+)', text)
        if match:
            seller_count = int(match.group(1))

    return seller_count, has_card

def analyze_keyword(keyword):
    encoded = urllib.parse.quote(keyword)
    url = f"https://search.naver.com/search.naver?where=nexearch&query={encoded}"

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        html = res.text
        soup = BeautifulSoup(html, "html.parser")

        search_volume = extract_search_volume(html)
        seller_count, has_card = extract_seller_count(soup)

        # 분류 기준
        if seller_count == 0 and not has_card:
            grade = "A"
        else:
            grade = "B"

        return {
            "keyword": keyword,
            "search_volume": search_volume,
            "seller_count": seller_count,
            "grade": grade,
            "link": url
        }

    except Exception:
        return {
            "keyword": keyword,
            "search_volume": 0,
            "seller_count": 0,
            "grade": "A",
            "link": url
        }

@app.route("/", methods=["GET", "POST"])
def home():
    results = []
    keywords_text = ""
    progress = None
    total = 0
    remaining = 0

    if request.method == "POST":
        keywords_text = request.form.get("keywords", "")
        keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
        total = len(keywords)

        for i, keyword in enumerate(keywords):
            result = analyze_keyword(keyword)
            results.append(result)

            progress = i + 1
            remaining = total - progress

            # 차단 방지 딜레이
            time.sleep(random.uniform(1.0, 2.0))

    return render_template_string(
        TEMPLATE,
        results=results,
        keywords=keywords_text,
        progress=progress,
        total=total,
        remaining=remaining
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
