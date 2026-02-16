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

# Playwright는 환경에 따라 설치/런타임 이슈가 날 수 있어 전체를 방어함
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_OK = True
except Exception:
    sync_playwright = None
    PLAYWRIGHT_OK = False

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

# Job 저장소 + 락(스레드 안전)
jobs = {}
jobs_lock = threading.Lock()

HEADERS = {"User-Agent": "Mozilla/5.0"}

# -------------------------------------------------
# 광고 API 서명 (키 없으면 안전하게 빈 문자열)
# -------------------------------------------------
def generate_signature(timestamp: str, method: str, uri: str) -> str:
    try:
        if not SECRET_KEY:
            return ""
        message = f"{timestamp}.{method}.{uri}"
        dig = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
        return base64.b64encode(dig).decode()
    except Exception:
        return ""

# -------------------------------------------------
# 검색량 (총합) - 네이버 검색광고 API
# -------------------------------------------------
def get_search_volume(keyword: str) -> int:
    try:
        if not ACCESS_KEY or not SECRET_KEY or not CUSTOMER_ID:
            return 0

        timestamp = str(int(time.time() * 1000))
        uri = "/keywordstool"

        signature = generate_signature(timestamp, "GET", uri)
        if not signature:
            return 0

        headers = {
            "X-Timestamp": timestamp,
            "X-API-KEY": ACCESS_KEY,
            "X-Customer": CUSTOMER_ID,
            "X-Signature": signature,
        }

        params = {"hintKeywords": keyword, "showDetail": 1}

        r = requests.get(
            "https://api.searchad.naver.com" + uri,
            headers=headers,
            params=params,
            timeout=12
        )

        # 응답이 JSON이 아닐 가능성까지 방어
        try:
            data = r.json()
        except Exception:
            return 0

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

    except Exception:
        return 0

# -------------------------------------------------
# 판매처 숫자 추출 (HTML에서 최대값)
#   - "판매처 872" 같은 표기도 잡힘
# -------------------------------------------------
def extract_store_count_from_html(html: str) -> int:
    try:
        if not html:
            return 1  # 안전하게 B로
        if "판매처" not in html:
            return 0

        # 여러 케이스 대응: "판매처 12", "도서 판매처 1,234" 등
        patterns = [
            r"(?:도서\s*)?판매처\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)",
            r"판매처[^0-9]{0,30}([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)",
        ]

        nums = []
        for pat in patterns:
            matches = re.findall(pat, html)
            for m in matches:
                try:
                    nums.append(int(str(m).replace(",", "")))
                except Exception:
                    pass

        if nums:
            # “판매처 872” 같은 값이 있으면 여기서 872로 잡힘 → B 판정 확실
            return max(nums)

        # '판매처'는 있는데 숫자 파싱 실패면 안전하게 1(B)
        return 1
    except Exception:
        return 1

# -------------------------------------------------
# 판매처 집계 (Playwright 1회 실행/재사용)
#   - 실패하면 requests fallback (프로그램 크래시 방지)
# -------------------------------------------------
def get_store_counts_bulk(keywords: list[str]) -> dict[str, int]:
    results: dict[str, int] = {}

    # 1) Playwright 경로
    if PLAYWRIGHT_OK:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                for kw in keywords:
                    kw = (kw or "").strip()
                    if not kw:
                        continue

                    url = "https://search.naver.com/search.naver?where=book&query=" + quote(kw)
                    try:
                        page.goto(url, timeout=30000)
                        # JS 로딩 여유
                        page.wait_for_timeout(2500)
                        html = page.content()
                        results[kw] = extract_store_count_from_html(html)
                    except Exception:
                        # 에러 시 안전하게 B
                        results[kw] = 1

                    # 서버 보호
                    time.sleep(1)

                browser.close()

            # 빠진 키 있으면 fallback로 채움
            missing = [kw for kw in keywords if (kw or "").strip() and (kw.strip() not in results)]
            if not missing:
                return results

        except Exception:
            # Playwright 전체 실패 → fallback로 진행
            pass

    # 2) requests fallback (정확도는 Playwright보다 떨어질 수 있으나, 프로그램은 절대 안 죽게)
    for kw in keywords:
        kw = (kw or "").strip()
        if not kw:
            continue
        if kw in results:
            continue

        url = "https://search.naver.com/search.naver?where=book&query=" + quote(kw)
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            results[kw] = extract_store_count_from_html(r.text)
        except Exception:
            results[kw] = 1

        time.sleep(1)

    return results

# -------------------------------------------------
# row 생성
# -------------------------------------------------
def build_row(keyword: str, store_count: int | None = None) -> dict:
    kw = (keyword or "").strip()
    if not kw:
        return {
            "title": "",
            "total": 0,
            "storeCount": 1,
            "grade": "B",
            "link": ""
        }

    total = get_search_volume(kw)

    if store_count is None:
        # 혹시 단건 호출 시에도 안전하게
        store_count = get_store_counts_bulk([kw]).get(kw, 1)

    # A/B 분류 규칙
    grade = "A" if int(store_count) == 0 else "B"

    return {
        "title": kw,
        "total": int(total),
        "storeCount": int(store_count),
        "grade": grade,
        "link": "https://search.naver.com/search.naver?where=book&query=" + quote(kw)
    }

# -------------------------------------------------
# Job 처리
# -------------------------------------------------
def process_job(job_id: str, keywords: list[str]):
    try:
        clean = [(k or "").strip() for k in keywords]
        clean = [k for k in clean if k]

        total_count = max(len(clean), 1)

        with jobs_lock:
            jobs[job_id]["status"] = "running"
            jobs[job_id]["progress"] = 0
            jobs[job_id]["results"] = []

        # 판매처는 먼저 bulk로 정확 집계(Playwright 1회)
        store_map = get_store_counts_bulk(clean)

        results = []
        for i, kw in enumerate(clean):
            try:
                row = build_row(kw, store_map.get(kw, 1))
            except Exception:
                # 어떤 키워드에서든 절대 죽지 않게 안전 row
                row = {
                    "title": kw,
                    "total": 0,
                    "storeCount": 1,
                    "grade": "B",
                    "link": "https://search.naver.com/search.naver?where=book&query=" + quote(kw)
                }

            results.append(row)

            progress = int(((i + 1) / total_count) * 100)
            with jobs_lock:
                jobs[job_id]["progress"] = progress
                jobs[job_id]["results"] = results

            # 서버 보호(광고 API + 네이버 페이지)
            time.sleep(1)

        with jobs_lock:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["results"] = results

    except Exception:
        # 최악의 경우에도 job 객체는 completed로 끝내서 UI가 멈추지 않게
        with jobs_lock:
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
<title>BookVPro 통합 안정판</title>
<style>
body{font-family:Arial;padding:40px;}
textarea{width:720px;height:260px;}
table{border-collapse:collapse;margin-top:18px;min-width:980px;}
th,td{border:1px solid #ccc;padding:8px;text-align:center;}
th{background:#222;color:#fff;}
.A{color:green;font-weight:bold;}
.B{color:red;font-weight:bold;}
.controls{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:10px 0;}
.small{color:#555;font-size:14px;}
#progress{margin-top:12px;font-size:16px;}
button,select{padding:8px 10px;}
</style>
</head>
<body>

<h2>BookVPro 통합 검색 시스템</h2>

<div class="small">
- 줄바꿈으로 여러 권 입력 가능 / 복붙하면 자동으로 권수 카운트<br/>
- 검색량은 광고 API 총합(PC+모바일) / 판매처는 네이버 도서 검색페이지에서 숫자 집계
</div>

<br/>
<textarea id="keywords" placeholder="책 제목을 줄바꿈으로 입력하세요"></textarea>

<div class="controls">
  <div>총 입력 권수: <b id="count">0</b></div>

  <label>정렬:</label>
  <select id="sort" onchange="render()">
    <option value="original">원본</option>
    <option value="high">검색량 높은순</option>
    <option value="low">검색량 낮은순</option>
    <option value="A">A 우선</option>
  </select>

  <button id="btnStart" onclick="start()">검색 시작</button>
  <button id="btnDownload" onclick="download()" disabled>엑셀 다운로드</button>
</div>

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
let originalOrder=[];

const ta = document.getElementById("keywords");
ta.addEventListener("input", ()=>{
  const lines = ta.value.split("\\n").map(x=>x.trim()).filter(x=>x!=="");
  document.getElementById("count").innerText = lines.length;
});

function setRunningUI(isRunning){
  document.getElementById("btnStart").disabled = isRunning;
  document.getElementById("btnDownload").disabled = isRunning || results.length===0;
}

function start(){
  results=[];
  document.getElementById("btnDownload").disabled = true;

  const lines = document.getElementById("keywords").value
    .split("\\n").map(x=>x.trim()).filter(x=>x!=="");

  originalOrder=[...lines];

  if(lines.length===0){
    alert("책 제목을 입력하세요");
    return;
  }

  setRunningUI(true);
  document.getElementById("progress").innerText="작업 시작...";

  fetch("/start",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({keywords:lines})
  })
  .then(r=>r.json())
  .then(d=>{
    jobId=d.job_id;
    poll();
  })
  .catch(()=>{
    document.getElementById("progress").innerText="시작 실패(네트워크). 다시 시도";
    setRunningUI(false);
  });
}

function poll(){
  fetch("/status/"+jobId)
  .then(r=>r.json())
  .then(d=>{
    if(d.error){
      document.getElementById("progress").innerText="작업 정보를 찾을 수 없음";
      setRunningUI(false);
      return;
    }

    document.getElementById("progress").innerText="진행률: "+(d.progress??0)+"%";

    if(d.status!=="completed"){
      setTimeout(poll,2000);
    }else{
      results = Array.isArray(d.results) ? d.results : [];
      render();
      setRunningUI(false);
      document.getElementById("btnDownload").disabled = results.length===0;
    }
  })
  .catch(()=>{
    // 폴링 중 네트워크 흔들려도 UI가 멈추지 않게
    setTimeout(poll,2500);
  });
}

function getSorted(){
  const sort=document.getElementById("sort").value;
  const data=[...results];

  if(sort==="high"){
    data.sort((a,b)=>(b.total||0)-(a.total||0));
  }else if(sort==="low"){
    data.sort((a,b)=>(a.total||0)-(b.total||0));
  }else if(sort==="A"){
    data.sort((a,b)=>String(a.grade||"B").localeCompare(String(b.grade||"B")));
  }else{
    // 원본
    data.sort((a,b)=> originalOrder.indexOf(a.title) - originalOrder.indexOf(b.title));
  }
  return data;
}

function render(){
  const data = getSorted();

  const table=document.getElementById("table");
  table.innerHTML=`
  <tr>
    <th>책이름</th>
    <th>검색량</th>
    <th>판매처개수</th>
    <th>분류</th>
    <th>링크</th>
  </tr>`;

  data.forEach(r=>{
    const title = r.title ?? "";
    const total = (r.total ?? 0);
    const storeCount = (r.storeCount ?? 0);
    const grade = r.grade ?? "B";
    const link = r.link ?? "#";

    table.innerHTML += `
    <tr>
      <td>${escapeHtml(title)}</td>
      <td>${Number(total).toLocaleString()}</td>
      <td>${Number(storeCount).toLocaleString()}</td>
      <td class="${grade}">${grade}</td>
      <td><a href="${link}" target="_blank">열기</a></td>
    </tr>`;
  });
}

// XSS 방어(복붙 입력값 보호)
function escapeHtml(str){
  return String(str)
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#039;");
}

function download(){
  const data = getSorted(); // 현재 정렬 상태 그대로 다운로드

  fetch("/download",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({results:data})
  })
  .then(r=>r.blob())
  .then(blob=>{
    const url=window.URL.createObjectURL(blob);
    const a=document.createElement("a");
    a.href=url;
    a.download="result.xlsx";
    a.click();
  })
  .catch(()=>{
    alert("다운로드 실패(네트워크). 다시 시도");
  });
}
</script>

</body>
</html>
"""

# -------------------------------------------------
# API
# -------------------------------------------------
@app.post("/start")
def start(data: dict = Body(...)):
    try:
        keywords = data.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []

        job_id = str(uuid.uuid4())

        with jobs_lock:
            jobs[job_id] = {
                "status": "queued",
                "progress": 0,
                "results": []
            }

        t = threading.Thread(target=process_job, args=(job_id, keywords), daemon=True)
        t.start()

        return {"job_id": job_id}
    except Exception:
        # start가 실패해도 서버가 죽지 않게
        job_id = str(uuid.uuid4())
        with jobs_lock:
            jobs[job_id] = {"status": "completed", "progress": 100, "results": []}
        return {"job_id": job_id}

@app.get("/status/{job_id}")
def status(job_id: str):
    try:
        with jobs_lock:
            job = jobs.get(job_id)
        if not job:
            return {"error": "not found"}
        return job
    except Exception:
        return {"error": "not found"}

@app.post("/download")
def download(data: dict = Body(...)):
    try:
        rows = data.get("results", [])
        if not isinstance(rows, list):
            rows = []

        # 컬럼 순서 고정(요구한 형태)
        fixed_rows = []
        for r in rows:
            fixed_rows.append({
                "책이름": r.get("title", ""),
                "검색량": int(r.get("total", 0) or 0),
                "판매처개수": int(r.get("storeCount", 0) or 0),
                "분류": r.get("grade", "B"),
                "링크": r.get("link", "")
            })

        df = pd.DataFrame(fixed_rows, columns=["책이름", "검색량", "판매처개수", "분류", "링크"])

        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=result.xlsx"}
        )
    except Exception:
        # 다운로드도 실패해도 크래시 없이 빈 파일이라도 반환
        df = pd.DataFrame([], columns=["책이름", "검색량", "판매처개수", "분류", "링크"])
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=result.xlsx"}
        )
