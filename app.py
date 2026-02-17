from flask import Flask, request, jsonify, render_template_string
import os
import time
import requests
import re
import hashlib
import hmac
import base64
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

app = Flask(__name__)

ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
CUSTOMER_ID = os.getenv("CUSTOMER_ID")

# =========================
# 광고 API
# =========================
def generate_signature(timestamp, method, uri):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(
        SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    )
    return base64.b64encode(hash.digest()).decode()

def get_search_volume(keyword):
    try:
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

        params = {"hintKeywords": keyword, "showDetail": 1}

        r = requests.get(
            "https://api.searchad.naver.com/keywordstool",
            headers=headers,
            params=params,
            timeout=10
        )

        if r.status_code != 200:
            return 0

        data = r.json()
        if not data.get("keywordList"):
            return 0

        item = data["keywordList"][0]

        def safe(v):
            if not v or "<" in str(v):
                return 0
            return int(v)

        return safe(item.get("monthlyPcQcCnt")) + safe(item.get("monthlyMobileQcCnt"))

    except:
        return 0

# =========================
# Selenium 판매처 추출
# =========================
def get_seller_count(keyword):
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=chrome_options)
        driver.get(f"https://m.search.naver.com/search.naver?query={keyword}")
        time.sleep(2)

        html = driver.page_source
        driver.quit()

        match = re.search(r"도서 판매처\s*([0-9,]+)", html)
        if match:
            return int(match.group(1).replace(",", ""))

        return 0

    except Exception as e:
        return 0

# =========================
# 대표카드 판별
# =========================
def has_represent_card(keyword):
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=chrome_options)
        driver.get(f"https://m.search.naver.com/search.naver?query={keyword}")
        time.sleep(2)

        html = driver.page_source
        driver.quit()

        return "api_subject_bx" in html and "book" in html

    except:
        return False

def classify(seller, card):
    if seller == 0 and not card:
        return "A"
    return "B"

# =========================
# UI
# =========================
HTML = """
<!doctype html>
<title>Book 통합 분석기</title>
<h2>Book 통합 분석기</h2>

<textarea id="keywords" rows="8" cols="60"></textarea><br><br>
<button onclick="startSearch()">일괄 분류 시작</button>

<div id="progress"></div>

<table border="1" cellpadding="5" id="resultTable">
<tr>
<th>키워드</th>
<th>총검색량</th>
<th>판매처개수</th>
<th>분류</th>
</tr>
</table>

<script>
async function startSearch() {
    const keywords = document.getElementById("keywords").value
        .split("\\n")
        .filter(k => k.trim() !== "");

    const table = document.getElementById("resultTable");
    table.innerHTML = "<tr><th>키워드</th><th>총검색량</th><th>판매처개수</th><th>분류</th></tr>";

    for (let i = 0; i < keywords.length; i++) {
        document.getElementById("progress").innerHTML =
            "진행중: " + (i+1) + " / " + keywords.length +
            " | 남은 개수: " + (keywords.length - i - 1);

        const res = await fetch("/analyze", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({keyword: keywords[i]})
        });

        const data = await res.json();

        table.innerHTML += `
            <tr>
            <td>${data.keyword}</td>
            <td>${data.volume}</td>
            <td>${data.seller}</td>
            <td>${data.grade}</td>
            </tr>
        `;
    }

    document.getElementById("progress").innerHTML = "완료!";
}
</script>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/analyze", methods=["POST"])
def analyze():
    keyword = request.json["keyword"]

    volume = get_search_volume(keyword)
    seller = get_seller_count(keyword)
    card = has_represent_card(keyword)
    grade = classify(seller, card)

    return jsonify({
        "keyword": keyword,
        "volume": volume,
        "seller": seller,
        "grade": grade
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
