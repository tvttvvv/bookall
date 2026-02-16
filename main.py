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
from fastapi.responses import StreamingResponse

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

jobs = {}
jobs_lock = threading.Lock()

# -----------------------------
# 광고 API 서명
# -----------------------------
def generate_signature(timestamp, method, uri):
    message = f"{timestamp}.{method}.{uri}"
    hash_value = hmac.new(
        SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    return base64.b64encode(hash_value).decode()


# -----------------------------
# 검색량 총합
# -----------------------------
def get_search_volume(keyword):
    try:
        if not ACCESS_KEY:
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
            timeout=10
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


# -----------------------------
# 판매처 추출 (Railway 안전형)
# -----------------------------
def extract_store_count(keyword):

    url = f"https://search.naver.com/search.naver?where=book&query={quote(keyword)}"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        html = r.text

        matches = re.findall(
            r"판매처\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)",
            html
        )

        numbers = []
        for m in matches:
            try:
                numbers.append(int(m.replace(",", "")))
            except:
                pass

        if numbers:
            return max(numbers)

        return 0

    except:
        return 0


# -----------------------------
# Job 처리
# -----------------------------
def process_job(job_id, keywords):

    start_time = time.time()
    total_count = len(keywords)

    with jobs_lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["progress"] = 0
        jobs[job_id]["remaining"] = 0
        jobs[job_id]["results"] = []

    results = []

    for i, kw in enumerate(keywords):

        store_count = extract_store_count(kw)
        total = get_search_volume(kw)

        grade = "A" if store_count == 0 else "B"

        results.append({
            "title": kw,
            "total": total,
            "storeCount": store_count,
            "grade": grade,
            "link": f"https://search.naver.com/search.naver?where=book&query={quote(kw)}"
        })

        elapsed = time.time() - start_time
        avg_time = elapsed / (i + 1)
        remaining = int(avg_time * (total_count - (i + 1)))

        with jobs_lock:
            jobs[job_id]["progress"] = int(((i + 1) / total_count) * 100)
            jobs[job_id]["remaining"] = max(0, remaining)
            jobs[job_id]["results"] = results

        time.sleep(0.2)

    with jobs_lock:
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["remaining"] = 0


@app.post("/start")
def start(data: dict = Body(...)):
    keywords = data.get("keywords", [])
    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "remaining": 0,
        "results": []
    }

    threading.Thread(target=process_job, args=(job_id, keywords)).start()

    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str):
    return jobs.get(job_id, {"error":"not found"})


@app.post("/download")
def download(data: dict = Body(...)):
    df = pd.DataFrame(data.get("results", []))
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":"attachment; filename=result.xlsx"}
    )
