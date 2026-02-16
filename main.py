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
let total = 0;
let completed = 0;
let startTime;

document.getElementById("keywords").addEventListener("input", function(){
    let lines = this.value.split("\\n").filter(x => x.trim() !== "");
    document.getElementById("count").innerText = lines.length;
});

function startSearch(){
    results = [];
    completed = 0;
    startTime = Date.now();
    let lines = document.getElementById("keywords").value
                .split("\\n")
                .filter(x => x.trim() !== "");
    originalOrder = lines;
    total = lines.length;

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
        completed++;

        let elapsed = (Date.now() - startTime)/1000;
        let avg = elapsed / completed;
        let remain = Math.round(avg * (total - completed));

        document.getElementById("progress").innerText =
            "진행: " + completed + "/" + total +
            " | 남은 예상시간: " + remain + "초";

        renderTable();
        processNext(queue);
    })
    .catch(err => {
        // 네트워크/서버 오류 시에도 다음 진행
        results.push({keyword, count: 0, grade: "B", link: "https://search.naver.com/search.naver?where=book&query="+encodeURIComponent(keyword)});
        completed++;
        renderTable();
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
    let sortedData = getSortedResults();

    fetch("/download", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({results: sortedData})
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

# ✅ 판매처 판정: "판매처 숫자"가 한 번이라도 있으면 무조건 B (절대 A 금지)
def check_keyword(keyword: str) -> dict:
    # 반드시 도서 전용 검색
    url = "https://search.naver.com/search.naver?where=book&query=" + quote(keyword)

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        html = r.text

        # 콤마/큰 숫자 전부 대응: 3, 157, 1,234, 12,345, 103,582 ...
        matches = re.findall(r"판매처\s*([0-9]+(?:,[0-9]{3})*)", html)

        if matches:
            nums = []
            for m in matches:
                try:
                    nums.append(int(m.replace(",", "")))
                except:
                    pass

            if nums:
                # 하나라도 있으면 무조건 B
                return {"keyword": keyword, "count": max(nums), "grade": "B", "link": url}

        # 판매처 숫자 완전 없음 → A
        return {"keyword": keyword, "count": 0, "grade": "A", "link": url}

    except:
        # 예외/차단/타임아웃이면 안전하게 B
        return {"keyword": keyword, "count": 0, "grade": "B", "link": url}


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


@app.post("/check")
def check(data: dict = Body(...)):
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        return JSONResponse({"keyword": "", "count": 0, "grade": "A", "link": ""})
    return check_keyword(keyword)


@app.post("/download")
def download(data: dict = Body(...)):
    results = data.get("results", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["키워드", "판매처개수", "분류", "링크"])

    for r in results:
        writer.writerow([
            r.get("keyword", ""),
            r.get("count", 0),
            r.get("grade", ""),
            r.get("link", "")
        ])

    output.seek(0)

    bytes_io = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    return StreamingResponse(
        bytes_io,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=naverbookab_result.csv"},
    )
