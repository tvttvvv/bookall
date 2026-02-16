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
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# 환경 변수
# -----------------------------
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
CUSTOMER_ID = os.getenv("CUSTOMER_ID")

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://www.naver.com"
}

jobs = {}
store_cache = {}

# -----------------------------
# 광고 API 서명
# -----------------------------
def generate_signature(timestamp, method, uri):
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY 없음")

    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(
        SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()

    return base64.b64encode(hash).decode()

# -----------------------------
# 검색량 (총합만)
# -----------------------------
def get_search_volume(keyword):

    if not ACCESS_KEY or not CUSTOMER_ID or not SECRET_KEY:
        return 0

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

    url = "https://api.searchad.naver.com" + uri

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()

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

    except:
        return 0

# -----------------------------
# 판매처 개수 (도서 전용 페이지 기반)
# -----------------------------
def get_store_count(keyword):

    if keyword in store_cache:
        return store_cache[keyword]

    url = "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)

    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=10)
        html = r.text

        # 판매처 숫자 전부 찾기
        matches = re.findall(r"판매처\s*([0-9,]+)", html)

        if not matches:
            store_cache[keyword] = 0
            return 0

        numbers = []
        for m in matches:
            try:
                numbers.append(int(m.replace(",", "")))
            except:
                pass

        if numbers:
            max_value = max(numbers)
            store_cache[keyword] = max_value
            return max_value

        store_cache[keyword] = 0
        return 0

    except:
        store_cache[keyword] = 0
        return 0

# -----------------------------
# 1건 처리
# -----------------------------
def build_row(keyword):

    total = get_search_volume(keyword)
    store_count = get_store_count(keyword)

    grade = "B" if store_count > 0 else "A"

    return {
        "title": keyword,
        "total": total,
        "storeCount": store_count,
        "grade": grade,
        "link": "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)
    }

# -----------------------------
# Job 처리
# -----------------------------
def process_job(job_id, keywords):

    results = []
    total_count = len(keywords)

    jobs[job_id]["status"] = "running"
    jobs[job_id]["progress"] = 0

    for i, kw in enumerate(keywords):

        kw = kw.strip()
        if not kw:
            continue

        row = build_row(kw)
        results.append(row)

        jobs[job_id]["progress"] = int(((i + 1) / total_count) * 100)

        time.sleep(0.15)  # 과도한 요청 방지

    jobs[job_id]["results"] = results
    jobs[job_id]["status"] = "completed"
    jobs[job_id]["progress"] = 100

# -----------------------------
# UI
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>BookVPro 통합</title>
<style>
body{font-family:Arial;padding:40px;}
textarea{width:700px;height:250px;}
button,select{padding:8px;}
table{border-collapse:collapse;margin-top:20px;min-width:1000px;}
th,td{border:1px solid #ccc;padding:8px;text-align:center;}
th{background:#222;color:#fff;}
.A{color:green;font-weight:bold;}
.B{color:red;font-weight:bold;}
</style>
</head>
<body>

<h2>BookVPro 통합 검색 시스템</h2>

<textarea id="keywords" placeholder="책 제목을 줄바꿈으로 입력"></textarea><br><br>

<button onclick="start()">검색 시작</button>
<button onclick="download()">엑셀 다운로드</button>

<select id="sort" onchange="render()">
<option value="original">원본</option>
<option value="totalDesc">검색량 높은순</option>
<option value="totalAsc">검색량 낮은순</option>
<option value="Afirst">A 우선</option>
</select>

<div id="progress"></div>

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
let originalOrder=[];
let results=[];

function start(){
  let lines=document.getElementById("keywords").value
    .split("\\n").filter(x=>x.trim()!=="");

  originalOrder=lines;

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

    if(d.status!=="completed"){
      setTimeout(poll,1000);
    }else{
      results=d.results;
      render();
    }
  });
}

function getSorted(){
  let s=document.getElementById("sort").value;
  let data=[...results];

  if(s==="totalDesc"){
    data.sort((a,b)=>b.total-a.total);
  }
  else if(s==="totalAsc"){
    data.sort((a,b)=>a.total-b.total);
  }
  else if(s==="Afirst"){
    data.sort((a,b)=>a.grade.localeCompare(b.grade));
  }
  else{
    data.sort((a,b)=>originalOrder.indexOf(a.title)-originalOrder.indexOf(b.title));
  }

  return data;
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

  getSorted().forEach(r=>{
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
    body:JSON.stringify({results:getSorted()})
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

# -----------------------------
# API
# -----------------------------
@app.post("/start")
def start(data: dict = Body(...)):
    keywords = data.get("keywords", [])
    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "results": []
    }

    threading.Thread(target=process_job, args=(job_id, keywords)).start()

    return {"job_id": job_id}

@app.get("/status/{job_id}")
def status(job_id: str):
    if job_id not in jobs:
        return JSONResponse({"error":"job not found"}, status_code=404)
    return jobs[job_id]

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
