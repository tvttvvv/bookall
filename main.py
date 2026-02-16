from flask import Flask, render_template_string, request, jsonify, send_file
import requests
import re
import csv
import io
from urllib.parse import quote

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

HTML = """
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

# 🔥 핵심 수정된 함수
def check_keyword(keyword):

    url = f"https://search.naver.com/search.naver?where=book&query={quote(keyword)}"

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        html = r.text

        # 판매처 숫자 완전 대응
        matches = re.findall(
            r"판매처\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)",
            html
        )

        if matches:
            numbers = []
            for m in matches:
                try:
                    numbers.append(int(m.replace(",", "")))
                except:
                    pass

            if numbers:
                return {
                    "keyword": keyword,
                    "count": max(numbers),
                    "grade": "B",
                    "link": url
                }

        return {
            "keyword": keyword,
            "count": 0,
            "grade": "A",
            "link": url
        }

    except:
        return {
            "keyword": keyword,
            "count": 0,
            "grade": "B",  # 안전 모드
            "link": url
        }

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/check", methods=["POST"])
def check():
    data = request.get_json()
    return jsonify(check_keyword(data["keyword"]))

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    results = data.get("results", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["키워드", "판매처개수", "분류", "링크"])

    for r in results:
        writer.writerow([r["keyword"], r["count"], r["grade"], r["link"]])

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="naverbookab_result.csv"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
