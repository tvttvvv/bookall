import os
import time
import hmac
import hashlib
import base64
import requests
import pandas as pd
import io

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from dotenv import load_dotenv

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

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# -----------------------------
# 광고 API 서명
# -----------------------------
def generate_signature(timestamp, method, uri):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(
        SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    )
    return base64.b64encode(hash.digest()).decode()

# -----------------------------
# 검색량 조회 (광고 API)
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

    url = "https://api.searchad.naver.com" + uri

    try:
        r = requests.get(url, headers=headers, params=params)
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
# 판매처 개수 (도서 Open API 기반)
# -----------------------------
def get_store_count(keyword):

    url = "https://openapi.naver.com/v1/search/book.json"

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    params = {
        "query": keyword,
        "display": 1
    }

    try:
        r = requests.get(url, headers=headers, params=params)
        data = r.json()

        if "items" not in data or not data["items"]:
            return 0

        item = data["items"][0]

        # 네이버 도서 API에는 직접 판매처 수는 없지만
        # 링크 존재 여부로 판단 (도서 존재 여부 기반 경쟁 판단)
        link = item.get("link")

        if link:
            return 1  # 도서 존재 = 경쟁 있음
        else:
            return 0

    except:
        return 0

# -----------------------------
# UI
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
    <head>
    <title>BookVPro 통합 시스템</title>
    <style>
    body {font-family:Arial;padding:40px;}
    textarea {width:600px;height:250px;}
    table {border-collapse:collapse;margin-top:20px;}
    th,td {border:1px solid #ccc;padding:8px;text-align:center;}
    th {background:#222;color:#fff;}
    select,button {padding:6px;}
    </style>
    </head>
    <body>

    <h2>BookVPro 통합 검색 시스템</h2>

    <textarea id="keywords" placeholder="책 제목을 줄바꿈으로 입력하세요"></textarea><br><br>
    <button onclick="startSearch()">검색 시작</button>
    <button onclick="downloadExcel()">엑셀 다운로드</button>

    <br><br>
    정렬:
    <select id="sort" onchange="renderTable()">
        <option value="original">원본</option>
        <option value="totalDesc">검색량 높은순</option>
        <option value="totalAsc">검색량 낮은순</option>
        <option value="Afirst">A 우선</option>
    </select>

    <table id="resultTable">
    <tr>
        <th>책이름</th>
        <th>검색량</th>
        <th>판매처개수</th>
        <th>등급</th>
        <th>링크</th>
    </tr>
    </table>

    <script>
    let results = [];
    let originalOrder = [];

    function startSearch(){
        let lines = document.getElementById("keywords").value
                    .split("\\n")
                    .filter(x=>x.trim()!=="");

        originalOrder = lines;

        Promise.all(
            lines.map(k =>
                fetch("/searchOne",{
                    method:"POST",
                    headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({keyword:k})
                }).then(res=>res.json())
            )
        ).then(data=>{
            results = data;
            renderTable();
        });
    }

    function getSorted(){
        let sort = document.getElementById("sort").value;
        let data = [...results];

        if(sort==="totalDesc"){
            data.sort((a,b)=> b.total - a.total);
        }
        else if(sort==="totalAsc"){
            data.sort((a,b)=> a.total - b.total);
        }
        else if(sort==="Afirst"){
            data.sort((a,b)=> a.grade.localeCompare(b.grade));
        }
        else{
            data.sort((a,b)=> originalOrder.indexOf(a.title) - originalOrder.indexOf(b.title));
        }

        return data;
    }

    function renderTable(){
        let table = document.getElementById("resultTable");
        table.innerHTML = `
        <tr>
        <th>책이름</th>
        <th>검색량</th>
        <th>판매처개수</th>
        <th>등급</th>
        <th>링크</th>
        </tr>`;

        getSorted().forEach(r=>{
            table.innerHTML += `
            <tr>
            <td>${r.title}</td>
            <td>${r.total}</td>
            <td>${r.storeCount}</td>
            <td>${r.grade}</td>
            <td><a href="${r.link}" target="_blank">열기</a></td>
            </tr>`;
        });
    }

    function downloadExcel(){
        fetch("/download",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({results:getSorted()})
        })
        .then(res=>res.blob())
        .then(blob=>{
            let url = window.URL.createObjectURL(blob);
            let a = document.createElement("a");
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
# 단일 검색
# -----------------------------
@app.post("/searchOne")
def search_one(data: dict = Body(...)):
    keyword = data["keyword"]
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
# 엑셀 다운로드
# -----------------------------
@app.post("/download")
def download(data: dict = Body(...)):
    df = pd.DataFrame(data["results"])
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=result.xlsx"}
    )
