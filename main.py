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
from playwright.sync_api import sync_playwright

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


# ============================
# 검색량 API
# ============================
def generate_signature(timestamp, method, uri):
    message = f"{timestamp}.{method}.{uri}"
    hash_value = hmac.new(
        SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    return base64.b64encode(hash_value).decode()


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


# ============================
# 판매처 추출 (정확)
# ============================
def extract_store_count(html):

    if not html:
        return 0

    # 검색결과 없음 → A
    if "검색결과가 없습니다" in html:
        return 0

    # 판매처 숫자 모두 추출
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

    # 대표카드 강력 조건
    rep_markers = [
        "출판사 서평",
        "네이버는 상품판매의 당사자가 아닙니다",
        "도서 더보기"
    ]

    rep_count = sum(1 for m in rep_markers if m in html)
    if rep_count >= 2:
        return 1

    return 0


# ============================
# Job 처리 (진행률 + 남은시간 정확)
# ============================
def process_job(job_id, keywords):

    start_time = time.time()
    total_count = len(keywords)

    with jobs_lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["progress"] = 0
        jobs[job_id]["remaining"] = 0
        jobs[job_id]["current"] = ""
        jobs[job_id]["results"] = []

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for i, kw in enumerate(keywords):

            with jobs_lock:
                jobs[job_id]["current"] = kw

            url = f"https://search.naver.com/search.naver?where=book&query={quote(kw)}"

            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(1200)
                html = page.content()
                store_count = extract_store_count(html)
            except:
                store_count = 0

            total = get_search_volume(kw)

            grade = "A" if store_count == 0 else "B"

            results.append({
                "title": kw,
                "total": total,
                "storeCount": store_count,
                "grade": grade,
                "link": url
            })

            elapsed = time.time() - start_time
            avg_time = elapsed / (i + 1)
            remaining = int(avg_time * (total_count - (i + 1)))

            with jobs_lock:
                jobs[job_id]["progress"] = int(((i + 1) / total_count) * 100)
                jobs[job_id]["remaining"] = max(0, remaining)
                jobs[job_id]["results"] = results

        browser.close()

    with jobs_lock:
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["remaining"] = 0
        jobs[job_id]["current"] = ""


# ============================
# UI
# ============================
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>BookVPro 통합 검색 시스템</title>
<style>
body{font-family:Arial;padding:40px;}
textarea{width:700px;height:250px;}
table{border-collapse:collapse;margin-top:20px;}
th,td{border:1px solid #ccc;padding:8px;text-align:center;}
th{background:#222;color:#fff;}
.A{color:green;font-weight:bold;}
.B{color:red;font-weight:bold;}
</style>
</head>
<body>

<h2>BookVPro 통합 검색 시스템</h2>

<textarea id="keywords" placeholder="책 제목 줄바꿈 입력"></textarea><br><br>

<button onclick="start()">검색 시작</button>
<button onclick="download()">엑셀 다운로드</button>

<div id="progress"></div>
<div id="remaining"></div>
<div id="current"></div>

<table id="table">
<tr>
<th>책이름</th>
<th>검색량</th>
<th>판매처개수</th>
<th>분류</th>
<th>링크</th>
</tr>
</table>

<script>
let jobId=null;
let results=[];

function formatTime(sec){
  let m=Math.floor(sec/60);
  let s=sec%60;
  return m+"분 "+s+"초";
}

function start(){
  let lines=document.getElementById("keywords").value
    .split("\\n").filter(x=>x.trim()!=="");

  fetch("/start",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({keywords:lines})
  })
  .then(r=>r.json())
  .then(d=>{
    jobId=d.job_id;
    poll();
  });
}

function poll(){
  fetch("/status/"+jobId)
  .then(r=>r.json())
  .then(d=>{
    document.getElementById("progress").innerText="진행률: "+d.progress+"%";
    document.getElementById("remaining").innerText=
      d.remaining>0 ? "남은 예상 시간: "+formatTime(d.remaining) : "";
    document.getElementById("current").innerText=
      d.current ? "현재 처리중: "+d.current : "";

    if(d.status!=="completed"){
      setTimeout(poll,1500);
    }else{
      results=d.results;
      render();
    }
  });
}

function render(){
  let table=document.getElementById("table");
  table.innerHTML=`
  <tr>
  <th>책이름</th>
  <th>검색량</th>
  <th>판매처개수</th>
  <th>분류</th>
  <th>링크</th>
  </tr>`;

  results.forEach(r=>{
    table.innerHTML+=`
    <tr>
    <td>${r.title}</td>
    <td>${r.total.toLocaleString()}</td>
    <td>${r.storeCount}</td>
    <td class="${r.grade}">${r.grade}</td>
    <td><a href="${r.link}" target="_blank">열기</a></td>
    </tr>`;
  });
}

function download(){
  fetch("/download",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({results:results})
  })
  .then(r=>r.blob())
  .then(blob=>{
    let url=window.URL.createObjectURL(blob);
    let a=document.createElement("a");
    a.href=url;
    a.download="result.xlsx";
    a.click();
  });
}
</script>

</body>
</html>
"""


@app.post("/start")
def start(data: dict = Body(...)):
    keywords = data.get("keywords", [])
    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "remaining": 0,
        "current": "",
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
