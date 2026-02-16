import os
import time
import hmac
import hashlib
import base64
import requests
import pandas as pd
import io
import re

from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
CUSTOMER_ID = os.getenv("CUSTOMER_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# -----------------------------
# 네이버 광고 API 서명 생성
# -----------------------------
def generate_signature(timestamp, method, uri):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(
        SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    )
    return base64.b64encode(hash.digest()).decode()


# -----------------------------
# 검색량 조회
# -----------------------------
def get_search_volume(keyword):

    timestamp = str(int(time.time() * 1000))
    method = "GET"
    uri = "/keywordstool"

    signature = generate_signature(timestamp, method, uri)

    headers = {
        "X-Timestamp": timestamp,
        "X-API-KEY": ACCESS_KEY,
        "X-Customer": CUSTOMER_ID,
        "X-Signature": signature,
    }

    params = {
        "hintKeywords": keyword,
        "showDetail": 1
    }

    url = "https://api.naver.com" + uri
    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        return 0

    data = response.json()

    if "keywordList" not in data or not data["keywordList"]:
        return 0

    first = data["keywordList"][0]

    pc = first.get("monthlyPcQcCnt", 0)
    mobile = first.get("monthlyMobileQcCnt", 0)

    if pc == "< 10":
        pc = 0
    if mobile == "< 10":
        mobile = 0

    return int(pc) + int(mobile)


# -----------------------------
# 판매처 개수 조회
# -----------------------------
def get_store_count(keyword):

    url = f"https://search.naver.com/search.naver?query={keyword}"

    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        html = r.text
        match = re.search(r"판매처\s*(\d+)", html)
        count = int(match.group(1)) if match else 0
        return count
    except:
        return 0


# -----------------------------
# 단일 검색
# -----------------------------
@app.get("/search")
def search(keyword: str = Query(...)):

    total = get_search_volume(keyword)
    count = get_store_count(keyword)
    grade = "A" if count == 0 else "B"

    return {
        "title": keyword,
        "total": total,
        "storeCount": count,
        "grade": grade,
        "link": f"https://search.naver.com/search.naver?query={keyword}"
    }


# -----------------------------
# 여러 줄 일괄 검색
# -----------------------------
@app.post("/bulk")
def bulk_search(data: dict = Body(...)):

    keywords = data.get("keywords", [])
    results = []

    for keyword in keywords:
        total = get_search_volume(keyword)
        count = get_store_count(keyword)
        grade = "A" if count == 0 else "B"

        results.append({
            "title": keyword,
            "total": total,
            "storeCount": count,
            "grade": grade,
            "link": f"https://search.naver.com/search.naver?query={keyword}"
        })

    return results


# -----------------------------
# 엑셀 다운로드
# -----------------------------
@app.post("/download")
def download(data: dict = Body(...)):

    results = data.get("results", [])

    df = pd.DataFrame(results)

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=result.xlsx"}
    )
