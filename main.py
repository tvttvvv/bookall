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

# Playwright는 환경에 따라 실패할 수 있어 안전하게 import
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    sync_playwright = None
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

# 1이면 playwright 우선, 0이면 requests만 사용(서버에서 playwright가 불안하면 0 추천)
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "1").strip() != "0"

UA_HEADERS = {"User-Agent": "Mozilla/5.0"}

jobs = {}
jobs_lock = threading.Lock()


# -----------------------------
# 광고 API 서명
# -----------------------------
def generate_signature(timestamp: str, method: str, uri: str) -> str:
    try:
        if not SECRET_KEY:
            return ""
        msg = f"{timestamp}.{method}.{uri}"
        dig = hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()
        return base64.b64encode(dig).decode()
    except Exception:
        return ""


# -----------------------------
# 검색량 총합 (정확값)
# -----------------------------
def get_search_volume(keyword: str) -> int:
    try:
        if not ACCESS_KEY or not SECRET_KEY or not CUSTOMER_ID:
            return 0

        timestamp = str(int(time.time() * 1000))
        uri = "/keywordstool"
        sig = generate_signature(timestamp, "GET", uri)
        if not sig:
            return 0

        headers = {
            "X-Timestamp": timestamp,
            "X-API-KEY": ACCESS_KEY,
            "X-Customer": CUSTOMER_ID,
            "X-Signature": sig,
        }

        params = {"hintKeywords": keyword, "showDetail": 1}

        r = requests.get(
            "https://api.searchad.naver.com" + uri,
            headers=headers,
            params=params,
            timeout=12,
        )

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
    except Exception:
        return 0


# -----------------------------
# 대표카드 감지 (두 번째 이미지 규칙)
# -----------------------------
def has_representative_card(html: str) -> bool:
    if not html:
        return False

    markers = [
        "도서 더보기",
        "네이버는 상품판매의 당사자가 아닙니다",
        "출판사 서평",
        "발행",
        "리뷰",
        "랭킹",
        "네이버페이포인트",
        "네이버 도서",
    ]

    hit = 0
    for m in markers:
        if m in html:
            hit += 1

    # 너무 느슨하면 오탐이라 2개 이상이면 대표카드로 판단
    return hit >= 2


# -----------------------------
# 판매처 숫자 추출 (첫 번째 이미지 규칙)
# -----------------------------
def extract_store_count(html: str) -> int:
    """
    규칙:
    - '판매처 872' 같은 숫자 하나라도 있으면 -> 그 최대값 반환 (=> 무조건 B)
    - 숫자 없더라도 대표카드면 -> 1 반환 (=> 무조건 B)
    - 둘 다 없으면 -> 0 (=> A)
    - 불확실/에러는 프로그램 안정 위해 1(B)
    """
    try:
        if not html:
            return 1

        patterns = [
            r"(?:도서\s*)?판매처\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)",
            r"판매처[^0-9]{0,30}([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)",
        ]

        nums = []
        for pat in patterns:
            for m in re.findall(pat, html):
                try:
                    nums.append(int(str(m).replace(",", "")))
                except Exception:
                    pass

        if nums:
            return max(nums)  # ✅ 판매처 숫자 있으면 무조건 B

        if has_representative_card(html):
            return 1  # ✅ 대표카드면 무조건 B

        if "판매처" in html:
            return 1  # 판매처 문구만 있어도 B로

        return 0  # ✅ 아무것도 없으면 A
    except Exception:
        return 1


def build_naver_book_url(keyword: str) -> str:
    return "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)


# -----------------------------
# 판매처 bulk: playwright 우선 + 실패 시 requests fallback
# -----------------------------
def get_store_counts_bulk(keywords: list[str]) -> dict[str, int]:
    # 원본 순서 유지한 채 공백 제거 + 중복 제거(부하 감소)
    clean = []
    seen = set()
    for k in keywords:
        k = (k or "").strip()
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        clean.append(k)

    results: dict[str, int] = {}

    # 1) Playwright 경로
    if USE_PLAYWRIGHT and PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                for kw in clean:
                    url = build_naver_book_url(kw)
                    try:
                        page.goto(url, timeout=30000, wait_until="networkidle")
                        page.wait_for_timeout(1200)
                        html = page.content()
                        results[kw] = extract_store_count(html)
                    except Exception:
                        results[kw] = 1
                    time.sleep(0.6)

                browser.close()

            # playwright로 못 채운 키 있으면 fallback에서 채움
        except Exception:
            # playwright 전체 실패 → fallback로 통째로 처리
            results = {}

    # 2) requests fallback (playwright가 실패/비활성일 때)
    for kw in clean:
        if kw in results:
            continue
        url = build_naver_book_url(kw)
        try:
            r = requests.get(url, headers=UA_HEADERS, timeout=12)
            results[kw] = extract_store_count(r.text)
        except Exception:
            results[kw] = 1
        time.sleep(0.4)

    return results


# -----------------------------
# 1건 row
# -----------------------------
def build_row(keyword: str, store_count: int) -> dict:
    total = get_search_volume(keyword)
    grade = "A" if int(store_count) == 0 else "B"
    return {
        "title": keyword,
        "total": int(total),
        "storeCount": int(store_count),
        "grade": grade,
        "link": build_naver_book_url(keyword)
    }


# -----------------------------
# Job 처리: 어떤 예외가 나도 results는 비지 않게
# -----------------------------
def process_job(job_id: str, keywords: list[str]):
    # 기본 상태 세팅
    with jobs_lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["progress"] = 0
        jobs[job_id]["results"] = []
        jobs[job_id]["error"] = ""

    clean = [(k or "").strip() for k in keywords]
    clean = [k for k in clean if k]
    total_count = max(len(clean), 1)

    # 판매처 먼저 bulk
    try:
        store_map = get_store_counts_bulk(clean)
    except Exception as e:
        store_map = {}
        with jobs_lock:
            jobs[job_id]["error"] = f"store_count_failed: {type(e).__name__}"

    results = []
    for i, kw in enumerate(clean):
        try:
            store_count = store_map.get(kw, 1)  # 못잡으면 B로 안전
            row = build_row(kw, store_count)
        except Exception as e:
            row = {
                "title": kw,
                "total": 0,
                "storeCount": 1,
                "grade": "B",
                "link": build_naver_book_url(kw)
            }
            with jobs_lock:
                # 에러가 있어도 작업은 계속 진행
                if not jobs[job_id].get("error"):
                    jobs[job_id]["error"] = f"row_failed: {type(e).__name__}"

        results.append(row)

        progress = int(((i + 1) / total_count) * 100)
        with jobs_lock:
            jobs[job_id]["progress"] = progress
            jobs[job_id]["results"] = results

        time.sleep(0.3)

    with jobs_lock:
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["results"] = results


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
<title>BookVPro 통합 검색 시스템</title>
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
#error{margin-top:8px;color:#b00020;font-size:14px;}
button,select{padding:8px 10px;}
</style>
</head>
<body>

<h2>BookVPro 통합 검색 시스템</h2>

<div class="small">
- 줄바꿈 복붙 시 자동 권수 카운트<br/>
- B 규칙: (1) 판매처 숫자(예: 판매처 872)가 하나라도 있으면 무조건 B (2) 대표카드(상세 카드)면 무조건 B
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
<div id="error"></div>

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
  document.getElementById("error").innerText = "";

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
    if(d.error){
      document.getElementById("error").innerText = "주의: " + d.error;
    }

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

function escapeHtml(str){
  return String(str)
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#039;");
}

function download(){
  const data = getSorted();

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


@app.post("/start")
def start(data: dict = Body(...)):
    keywords = data.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {"status": "queued", "progress": 0, "results": [], "error": ""}

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
    rows = data.get("results", [])
    if not isinstance(rows, list):
        rows = []

    fixed_rows = []
    for r in rows:
        fixed_rows.append({
            "책이름": r.get("title", ""),
            "검색량": int(r.get("total", 0) or 0),
            "판매처개수": int(r.get("storeCount", 0) or 0),
            "분류": r.get("grade", "B"),
            "링크": r.get("link", ""),
        })

    df = pd.DataFrame(fixed_rows, columns=["책이름", "검색량", "판매처개수", "분류", "링크"])
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=result.xlsx"},
    )
