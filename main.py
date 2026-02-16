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
# ENV (네이버 검색광고 API)
# -----------------------------
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
CUSTOMER_ID = os.getenv("CUSTOMER_ID")

# -----------------------------
# HTTP
# -----------------------------
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.naver.com"
}

# -----------------------------
# Job Store
# -----------------------------
jobs = {}  # job_id -> {"status","progress","results","error"}
store_cache = {}  # keyword -> storeCount (간단 캐시)

# -----------------------------
# 네이버 광고 API 서명
# -----------------------------
def generate_signature(timestamp: str, method: str, uri: str) -> str:
    # 보호: 키가 없으면 바로 예외로 원인 드러나게
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY 환경변수가 없습니다.")
    message = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(
        SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")

# -----------------------------
# 검색량 (PC+모바일 총합만)
# -----------------------------
def get_search_volume_total(keyword: str) -> int:
    # 보호: 환경변수 미설정이면 0으로 두지 말고 에러로 알려주는 게 디버깅에 좋음
    if not ACCESS_KEY or not CUSTOMER_ID or not SECRET_KEY:
        raise RuntimeError("검색광고 API 환경변수(ACCESS_KEY/SECRET_KEY/CUSTOMER_ID) 중 누락이 있습니다.")

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

    params = {"hintKeywords": keyword, "showDetail": 1}
    url = "https://api.searchad.naver.com" + uri

    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return 0

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

    try:
        return int(pc) + int(mobile)
    except:
        return 0

# -----------------------------
# 판매처 개수 (도서 전용 검색 페이지 HTML에서 "판매처 숫자" 존재 여부)
# 기준:
#   - "판매처 숫자"가 1개라도 있으면 B
#   - 완전히 없으면 A
# -----------------------------
def get_store_count_from_book_search(keyword: str) -> int:
    if keyword in store_cache:
        return store_cache[keyword]

    url = "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)

    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=10)
        html = r.text

        # 판매처 35 / 판매처 3 / 판매처 1,234 등 대응
        m = re.search(r"판매처\s*([0-9,]+)", html)
        if m:
            num = int(m.group(1).replace(",", ""))
            store_cache[keyword] = num
            return num

        # 못 찾으면 0
        store_cache[keyword] = 0
        return 0

    except:
        store_cache[keyword] = 0
        return 0

# -----------------------------
# 통합 1건 처리
# -----------------------------
def build_row(keyword: str) -> dict:
    total = get_search_volume_total(keyword)
    store_count = get_store_count_from_book_search(keyword)
    grade = "B" if store_count > 0 else "A"

    return {
        "title": keyword,
        "total": total,                 # PC/모바일 제외, 총합만
        "storeCount": store_count,
        "grade": grade,
        "link": "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)
    }

# -----------------------------
# 백그라운드 Job (대량 처리 안정화: 순차 처리)
# -----------------------------
def process_job(job_id: str, keywords: list[str]):
    try:
        results = []
        total = len(keywords)
        jobs[job_id]["status"] = "running"
        jobs[job_id]["progress"] = 0

        for i, kw in enumerate(keywords):
            kw = kw.strip()
            if not kw:
                continue
            row = build_row(kw)
            results.append(row)
            jobs[job_id]["progress"] = int(((i + 1) / total) * 100)

            # 네이버쪽/서버쪽 부담 줄이기(초당 폭주 방지)
            time.sleep(0.15)

        jobs[job_id]["results"] = results
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)

# -----------------------------
# UI
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<title>BookVPro 통합</title>
<style>
body{font-family:Arial;padding:40px;}
textarea{width:720px;height:260px;}
button,select{padding:8px 10px;margin-right:6px;}
table{border-collapse:collapse;margin-top:18px;min-width:1100px;}
th,td{border:1px solid #ccc;padding:8px;text-align:center;}
th{background:#222;color:#fff;}
#wrap{display:flex;gap:18px;align-items:center;margin:14px 0;}
#tablebox{overflow-x:auto;}
.badgeA{font-weight:700;color:#1b7f2a;}
.badgeB{font-weight:700;color:#b00020;}
</style>
</head>
<body>
<h2>BookVPro 통합 검색 시스템</h2>

<textarea id="keywords" placeholder="책 제목을 줄바꿈으로 입력하세요"></textarea><br><br>

<div id="wrap">
  <button onclick="start()">검색 시작</button>
  <button onclick="download()">엑셀 다운로드</button>

  <label>정렬:</label>
  <select id="sort" onchange="render()">
    <option value="original">원본</option>
    <option value="totalDesc">검색량 높은순</option>
    <option value="totalAsc">검색량 낮은순</option>
    <option value="Afirst">A 우선</option>
  </select>
</div>

<div id="progress" style="font-size:16px;margin-top:10px;"></div>

<div id="tablebox">
<table id="table">
  <tr>
    <th>책이름</th>
    <th>검색량</th>
    <th>판매처개수</th>
    <th>분류</th>
    <th>링크</th>
  </tr>
</table>
</div>

<script>
let jobId = null;
let originalOrder = [];
let originalResults = [];

function start(){
  const lines = document.getElementById("keywords").value
    .split("\\n").map(x=>x.trim()).filter(Boolean);

  if(lines.length === 0){
    alert("키워드를 입력해줘");
    return;
  }

  originalOrder = lines;
  originalResults = [];
  jobId = null;

  document.getElementById("progress").innerText = "검색 시작...";
  document.getElementById("table").innerHTML = `
    <tr>
      <th>책이름</th><th>검색량</th><th>판매처개수</th><th>분류</th><th>링크</th>
    </tr>`;

  fetch("/start", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({keywords: lines})
  })
  .then(r=>r.json())
  .then(d=>{
    jobId = d.job_id;
    poll();
  })
  .catch(e=>{
    document.getElementById("progress").innerText = "에러: " + e;
  });
}

function poll(){
  fetch("/status/" + jobId)
    .then(r=>r.json())
    .then(d=>{
      if(d.status === "error"){
        document.getElementById("progress").innerText = "오류: " + (d.error || "unknown");
        return;
      }

      document.getElementById("progress").innerText =
        "진행률: " + d.progress + "%";

      if(d.status !== "completed"){
        setTimeout(poll, 1200);
      }else{
        originalResults = d.results || [];
        render();
        document.getElementById("progress").innerText += " (완료)";
      }
    });
}

function sorted(){
  const s = document.getElementById("sort").value;
  let data = [...originalResults];

  if(s === "totalDesc"){
    data.sort((a,b)=> (b.total||0) - (a.total||0));
  }else if(s === "totalAsc"){
    data.sort((a,b)=> (a.total||0) - (b.total||0));
  }else if(s === "Afirst"){
    data.sort((a,b)=> (a.grade||"Z").localeCompare(b.grade||"Z"));
  }else{
    data.sort((a,b)=> originalOrder.indexOf(a.title) - originalOrder.indexOf(b.title));
  }

  return data;
}

function render(){
  const t = document.getElementById("table");
  t.innerHTML = `
    <tr>
      <th>책이름</th><th>검색량</th><th>판매처개수</th><th>분류</th><th>링크</th>
    </tr>`;

  sorted().forEach(r=>{
    const badge = (r.grade === "A") ? "badgeA" : "badgeB";
    t.innerHTML += `
      <tr>
        <td>${r.title}</td>
        <td>${Number(r.total||0).toLocaleString()}</td>
        <td>${r.storeCount ?? 0}</td>
        <td class="${badge}">${r.grade}</td>
        <td><a href="${r.link}" target="_blank">열기</a></td>
      </tr>`;
  });
}

function download(){
  if(!originalResults || originalResults.length === 0){
    alert("먼저 검색을 실행해줘");
    return;
  }

  fetch("/download", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({results: sorted()})
  })
  .then(r=>r.blob())
  .then(blob=>{
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "result.xlsx";
    a.click();
  });
}
</script>
</body>
</html>
"""

# -----------------------------
# Job 시작/상태
# -----------------------------
@app.post("/start")
def start(data: dict = Body(...)):
    keywords = data.get("keywords", [])
    keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": 0, "results": [], "error": None}

    t = threading.Thread(target=process_job, args=(job_id, keywords), daemon=True)
    t.start()

    return {"job_id": job_id}

@app.get("/status/{job_id}")
def status(job_id: str):
    if job_id not in jobs:
        return JSONResponse({"status": "error", "progress": 0, "error": "job not found"}, status_code=404)
    return jobs[job_id]

# -----------------------------
# 엑셀 다운로드
# -----------------------------
@app.post("/download")
def download(data: dict = Body(...)):
    results = data.get("results", [])
    df = pd.DataFrame(results)

    # 최종 컬럼 순서 고정
    cols = ["title", "total", "storeCount", "grade", "link"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[cols]
    df.columns = ["책이름", "검색량", "판매처개수", "분류", "링크"]

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=result.xlsx"}
    )
