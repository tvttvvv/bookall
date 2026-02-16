# main.py
import os
import time
import re
import io
import uuid
import threading
from urllib.parse import quote

import requests
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs = {}
lock = threading.Lock()

UA = {"User-Agent": "Mozilla/5.0"}

# -----------------------------
# 판매처 추출
# -----------------------------
def extract_store_count(html):
    try:
        matches = re.findall(
            r"(?:도서\s*)?판매처\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)",
            html
        )
        nums = []
        for m in matches:
            try:
                nums.append(int(m.replace(",", "")))
            except:
                pass
        if nums:
            return max(nums)
        return 0
    except:
        return 1

def get_store_count(keyword):
    try:
        url = f"https://search.naver.com/search.naver?where=book&query={quote(keyword)}"
        r = requests.get(url, headers=UA, timeout=10)
        return extract_store_count(r.text)
    except:
        return 1

# -----------------------------
# 작업 처리
# -----------------------------
def process(job_id, keywords):

    with lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["progress"] = 0
        jobs[job_id]["results"] = []

    results = []
    total = len(keywords)

    for i, kw in enumerate(keywords):

        try:
            store = get_store_count(kw)
            grade = "A" if store == 0 else "B"
            row = {
                "title": kw,
                "total": 0,
                "storeCount": store,
                "grade": grade,
                "link": f"https://search.naver.com/search.naver?where=book&query={quote(kw)}"
            }
        except:
            row = {
                "title": kw,
                "total": 0,
                "storeCount": 1,
                "grade": "B",
                "link": "#"
            }

        results.append(row)

        with lock:
            jobs[job_id]["progress"] = int(((i+1)/total)*100)
            jobs[job_id]["results"] = results

        time.sleep(0.3)

    with lock:
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
<title>BookVPro</title>
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

총 입력 권수: <b id="count">0</b><br><br>

<button onclick="start()">검색 시작</button>
<button onclick="download()">엑셀 다운로드</button>

<div id="progress"></div>

<table id="table">
<tr>
<th>책이름</th>
<th>판매처개수</th>
<th>분류</th>
<th>링크</th>
</tr>
</table>

<script>
let jobId=null;
let results=[];

document.getElementById("keywords").addEventListener("input", function(){
  let lines=this.value.split("\\n").filter(x=>x.trim()!="");
  document.getElementById("count").innerText=lines.length;
});

function start(){
  let lines=document.getElementById("keywords").value
    .split("\\n").filter(x=>x.trim()!="");

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
  let table=document.getElementById("table");
  table.innerHTML=
  "<tr><th>책이름</th><th>판매처개수</th><th>분류</th><th>링크</th></tr>";

  results.forEach(r=>{
    table.innerHTML+=
    "<tr>"+
    "<td>"+r.title+"</td>"+
    "<td>"+r.storeCount+"</td>"+
    "<td class='"+r.grade+"'>"+r.grade+"</td>"+
    "<td><a href='"+r.link+"' target='_blank'>열기</a></td>"+
    "</tr>";
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
    keywords=data.get("keywords",[])
    job_id=str(uuid.uuid4())

    with lock:
        jobs[job_id]={"status":"queued","progress":0,"results":[]}

    threading.Thread(target=process,args=(job_id,keywords),daemon=True).start()
    return {"job_id":job_id}

@app.get("/status/{job_id}")
def status(job_id:str):
    with lock:
        return jobs.get(job_id,{"error":"not found"})

@app.post("/download")
def download(data: dict = Body(...)):
    df=pd.DataFrame(data.get("results",[]))
    output=io.BytesIO()
    df.to_excel(output,index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":"attachment; filename=result.xlsx"}
    )
