import os
import time
import re
import io
import uuid
import hmac
import hashlib
import base64
import threading
from urllib.parse import quote

import requests
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

# playwright 안전 import
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
CUSTOMER_ID = os.getenv("CUSTOMER_ID")

USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "0") == "1"

UA_HEADERS = {"User-Agent": "Mozilla/5.0"}

jobs = {}
jobs_lock = threading.Lock()


# ============================
# 광고 API 서명
# ============================
def generate_signature(timestamp, method, uri):
    try:
        msg = f"{timestamp}.{method}.{uri}"
        digest = hmac.new(
            SECRET_KEY.encode(),
            msg.encode(),
            hashlib.sha256
        ).digest()
        return base64.b64encode(digest).decode()
    except:
        return ""


# ============================
# 검색량 정확값
# ============================
def get_search_volume(keyword):
    try:
        if not ACCESS_KEY or not SECRET_KEY or not CUSTOMER_ID:
            return 0

        timestamp = str(int(time.time() * 1000))
        uri = "/keywordstool"

        headers = {
            "X-Timestamp": timestamp,
            "X-API-KEY": ACCESS_KEY,
            "X-Customer": CUSTOMER_ID,
            "X-Signature": generate_signature(timestamp, "GET", uri),
        }

        params = {"hintKeywords": keyword, "showDetail": 1}

        r = requests.get(
            "https://api.searchad.naver.com" + uri,
            headers=headers,
            params=params,
            timeout=12
        )

        data = r.json()

        if "keywordList" not in data or not data["keywordList"]:
            return 0

        first = data["keywordList"][0]
        pc = first.get("monthlyPcQcCnt", 0)
        mobile = first.get("monthlyMobileQcCnt", 0)

        if pc == "< 10": pc = 0
        if mobile == "< 10": mobile = 0

        return int(pc) + int(mobile)

    except:
        return 0


# ============================
# 대표카드 감지
# ============================
def has_representative_card(html):
    markers = [
        "도서 더보기",
        "네이버는 상품판매의 당사자가 아닙니다",
        "출판사 서평",
        "발행",
        "리뷰",
        "랭킹",
        "네이버 도서"
    ]
    count = 0
    for m in markers:
        if m in html:
            count += 1
    return count >= 2


# ============================
# 판매처 추출
# ============================
def extract_store_count(html):
    try:
        patterns = [
            r"(?:도서\s*)?판매처\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)"
        ]

        numbers = []

        for pat in patterns:
            for m in re.findall(pat, html):
                try:
                    numbers.append(int(str(m).replace(",", "")))
                except:
                    pass

        if numbers:
            return max(numbers)

        if has_representative_card(html):
            return 1

        return 0

    except:
        return 1


def build_url(keyword):
    return "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)


# ============================
# 판매처 bulk 처리
# ============================
def get_store_counts_bulk(keywords):
    results = {}

    if USE_PLAYWRIGHT and PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                for kw in keywords:
                    try:
                        page.goto(build_url(kw), timeout=30000)
                        page.wait_for_timeout(1500)
                        html = page.content()
                        results[kw] = extract_store_count(html)
                    except:
                        results[kw] = 1
                    time.sleep(0.5)

                browser.close()

            return results
        except:
            pass

    # fallback requests
    for kw in keywords:
        try:
            r = requests.get(build_url(kw), headers=UA_HEADERS, timeout=12)
            results[kw] = extract_store_count(r.text)
        except:
            results[kw] = 1
        time.sleep(0.4)

    return results


# ============================
# 작업 처리
# ============================
def process_job(job_id, keywords):

    with jobs_lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["progress"] = 0
        jobs[job_id]["results"] = []

    clean = [k.strip() for k in keywords if k.strip()]
    total_count = max(len(clean), 1)

    store_map = get_store_counts_bulk(clean)

    results = []

    for i, kw in enumerate(clean):

        try:
            store_count = store_map.get(kw, 1)
            total = get_search_volume(kw)
            grade = "A" if store_count == 0 else "B"

            row = {
                "title": kw,
                "total": total,
                "storeCount": store_count,
                "grade": grade,
                "link": build_url(kw)
            }
        except:
            row = {
                "title": kw,
                "total": 0,
                "storeCount": 1,
                "grade": "B",
                "link": build_url(kw)
            }

        results.append(row)

        with jobs_lock:
            jobs[job_id]["progress"] = int(((i + 1) / total_count) * 100)
            jobs[job_id]["results"] = results

        time.sleep(0.2)

    with jobs_lock:
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100


# ============================
# UI 루트
# ============================
@app.get("/", response_class=HTMLResponse)
def home():
    return "<h2>BookVPro 서버 정상 작동중</h2><p>/docs 로 테스트 가능</p>"


@app.post("/start")
def start(data: dict = Body(...)):
    keywords = data.get("keywords", [])
    job_id = str(uuid.uuid4())

    with jobs_lock:
        jobs[job_id] = {"status": "queued", "progress": 0, "results": []}

    t = threading.Thread(target=process_job, args=(job_id, keywords), daemon=True)
    t.start()

    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    return job if job else {"error": "not found"}


@app.post("/download")
def download(data: dict = Body(...)):
    df = pd.DataFrame(data.get("results", []))
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=result.xlsx"}
    )
