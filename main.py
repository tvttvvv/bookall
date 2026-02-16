import re
import csv
import io
from urllib.parse import quote

import requests
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {"User-Agent": "Mozilla/5.0"}

HTML = r"""
<!doctype html>
<title>naverbookab</title>
<h1>naverbookab</h1>

<textarea id="keywords" rows="15" cols="60"
placeholder="책 제목을 한 줄에 하나씩 입력"></textarea><br><br>

<p>총 입력 건수: <span id="count">0</span></p>

<button onclick="startSearch()">일괄 분류 시작</button>
<button onclick="downloadExcel()">엑셀 다운로드</button>

<p id="progress"></p>

<select id="sort" onchange="renderTable()">
<option value="original">원본</option>
<option value="best">A 우선</option>
</select>

<table border="1" cellpadding="5" id="resultTable">
<tr>
<th>키워드</th>
<th>판매처개수</th>
<th>분류</th>
<th>링크</th>
</tr>
</table>

<script>
let results = [];
let originalOrder = [];

document.getElementById("keywords").addEventListener("input", function(){
    let lines = this.value.split("\\n").filter(x => x.trim() !== "");
    document.getElementById("count").innerText = lines.length;
});

function startSearch(){
    results = [];

    let lines = document.getElementById("keywords").value
        .split("\\n")
        .map(x => x.trim())
        .filter(x => x !== "");

    originalOrder = lines;

    processNext([...lines]);
}

function processNext(queue){
    if(queue.length === 0){
        return;
    }

    let keyword = queue.shift();

    fetch("/check", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({keyword: keyword})
    })
    .then(res => res.json())
    .then(data => {
        results.push(data);
        renderTable();
        processNext(queue);
    })
    .catch(() => {
        processNext(queue);
    });
}

function getSortedResults(){
    let sort = document.getElementById("sort").value;
    let data = [...results];

    if(sort === "best"){
        data.sort((a,b)=> a.grade.localeCompare(b.grade));
    } else {
        data.sort((a,b)=> originalOrder.indexOf(a.keyword) - originalOrder.indexOf(b.keyword));
    }

    return data;
}

function renderTable(){
    let table = document.getElementById("resultTable");

    table.innerHTML = `
    <tr>
    <th>키워드</th>
    <th>판매처개수</th>
    <th>분류</th>
    <th>링크</th>
    </tr>`;

    let data = getSortedResults();

    data.forEach(r=>{
        table.innerHTML += `
        <tr>
        <td>${r.keyword}</td>
        <td>${r.count}</td>
        <td>${r.grade}</td>
        <td><a href="${r.link}" target="_blank">열기</a></td>
        </tr>`;
    });
}

function downloadExcel(){
    fetch("/download", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({results: results})
    })
    .then(res => res.blob())
    .then(blob => {
        let url = window.URL.createObjectURL(blob);
        let a = document.createElement("a");
        a.href = url;
        a.download = "naverbookab_result.csv";
        a.click();
    });
}
</script>
"""

def check_keyword(keyword: str):

    url = "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        html = r.text

        matches = re.findall(r"판매처\s*([0-9]+(?:,[0-9]{3})*)", html)

        if matches:
            nums = [int(m.replace(",", "")) for m in matches]
            return {"keyword": keyword, "count": max(nums), "grade": "B", "link": url}

        return {"keyword": keyword, "count": 0, "grade": "A", "link": url}

    except:
        return {"keyword": keyword, "count": 0, "grade": "B", "link": url}


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


@app.post("/check")
def check(data: dict = Body(...)):
    keyword = (data.get("keyword") or "").strip()
    return check_keyword(keyword)


@app.post("/download")
def download(data: dict = Body(...)):
    results = data.get("results", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["키워드", "판매처개수", "분류", "링크"])

    for r in results:
        writer.writerow([r["keyword"], r["count"], r["grade"], r["link"]])

    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=naverbookab_result.csv"},
    )
