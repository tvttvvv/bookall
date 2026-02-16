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

# -------------------------------------------------
# 광고 API 서명
# -------------------------------------------------
def generate_signature(timestamp, method, uri):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(
        SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    return base64.b64encode(hash).decode()

# -------------------------------------------------
# 검색량 (총합)
# -------------------------------------------------
def get_search_volume(keyword):

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

    try:
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

# -------------------------------------------------
# 판매처 검사 (브라우저 1회 실행 최적화)
# -------------------------------------------------
def get_store_counts_bulk(keywords):

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for keyword in keywords:
            url = "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)

            try:
                page.goto(url, timeout=30000)
                page.wait_for_timeout(2500)

                html = page.content()

                if "판매처" not in html:
                    results[keyword] = 0
                    continue

                matches = re.findall(
                    r"(?:도서\s*)?판매처\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)",
                    html
                )

                if matches:
                    numbers = [int(m.replace(",", "")) for m in matches]
                    results[keyword] = max(numbers)
                else:
                    results[keyword] = 1

            except:
                results[keyword] = 1

            time.sleep(1)

        browser.close()

    return results

# -------------------------------------------------
# Job 처리
# -------------------------------------------------
def process_job(job_id, keywords):

    jobs[job_id]["status"] = "running"
    jobs[job_id]["progress"] = 0

    store_map = get_store_counts_bulk(keywords)

    results = []
    total_count = len(keywords)

    for i, kw in enumerate(keywords):

        total = get_search_volume(kw)
        store_count = store_map.get(kw, 1)
        grade = "B" if store_count > 0 else "A"

        results.append({
            "title": kw,
            "total": total,
            "storeCount": store_count,
            "grade": grade,
            "link": "https://search.naver.com/search.naver?where=book&query=" + quote(kw)
        })

        jobs[job_id]["progress"] = int(((i + 1) / total_count) * 100)
        time.sleep(1)

    jobs[job_id]["results"] = results
    jobs[job_id]["status"] = "completed"
    jobs[job_id]["progress"] = 100

# -------------------------------------------------
# UI
# -------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>BookAll 통합 시스템</title>
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

<h2>BookAll 통합 검색 시스템</h2>

<textarea id="keywords" placeholder="책 제목 줄바꿈 입력"></textarea><br><br>

<select id="sort" onchange="render()">
<option value="original">원본</option>
<option value="high">검색량 높은순</option>
<option value="low">검색량 낮은순</option>
<option value="A">A 우선</option>
</select>

<button onclick="start()">검색 시작</button>
<button onclick="download()">엑셀 다운로드</button>

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
let results=[];
let original=[];

function start(){
  let lines=document.getElementById("keywords").value
    .split("\\n").filter(x=>x.trim()!=="");

  original=[...lines];

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
      setTimeout(poll,2000);
    }else{
      results=d.results;
      render();
    }
  });
}

function render(){

  let sort=document.getElementById("sort").value;
  let data=[...results];

  if(sort==="high"){
    data.sort((a,b)=>b.total-a.total);
  }
  else if(sort==="low"){
    data.sort((a,b)=>a.total-b.total);
  }
  else if(sort==="A"){
    data.sort((a,b)=>a.grade.localeCompare(b.grade));
  }

  let table=document.getElementById("table");
  table.innerHTML=`
  <tr>
  <th>책이름</th>
  <th>검색량</th>
  <th>판매처개수</th>
  <th>분류</th>
  <th>링크</th>
  </tr>`;

  data.forEach(r=>{
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
