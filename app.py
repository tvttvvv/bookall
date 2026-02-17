from flask import Flask, render_template_string, request, jsonify, send_file
import requests
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import io

app = Flask(__name__)

MAX_WORKERS = 10
results_storage = []
progress_data = {"done": 0, "total": 0, "start": 0}

HTML = """
<!doctype html>
<title>Book 통합 분석기</title>
<h1>Book 통합 분석기</h1>

<form method="post">
<textarea name="keywords" id="keywords" rows="15" cols="60"
placeholder="책 제목을 한 줄에 하나씩 입력 (최대 1000개)"></textarea><br><br>

총 입력 건수: <span id="count">0</span><br><br>

<button type="submit">일괄 분류 시작</button>
</form>

<br>
정렬:
<select id="sortSelect" onchange="sortTable()">
  <option value="original">원본</option>
  <option value="aFirst">A 우선</option>
</select>

{% if results %}
<br><br>
<b>총 소요시간:</b> {{ total_time }}초
<br>
<button onclick="downloadExcel()">엑셀 다운로드</button>
<br><br>

<table border="1" id="resultTable">
<tr>
<th>키워드</th>
<th>검색결과수</th>
<th>분류</th>
<th>링크</th>
</tr>

{% for r in results %}
<tr>
<td>{{ r.keyword }}</td>
<td>{{ r.count }}</td>
<td>{{ r.grade }}</td>
<td><a href="{{ r.link }}" target="_blank">열기</a></td>
</tr>
{% endfor %}
</table>
{% endif %}

<script>
const textarea = document.getElementById("keywords");
if(textarea){
textarea.addEventListener("input", function(){
  let lines = textarea.value.split("\\n").filter(l => l.trim() !== "");
  document.getElementById("count").innerText = lines.length;
});
}

function sortTable(){
  let table = document.getElementById("resultTable");
  let rows = Array.from(table.rows).slice(1);
  let mode = document.getElementById("sortSelect").value;

  rows.sort((a,b)=>{
    if(mode === "aFirst"){
      return a.cells[2].innerText.localeCompare(b.cells[2].innerText);
    }else{
      return 0;
    }
  });

  rows.forEach(r => table.appendChild(r));
}

function downloadExcel(){
  let sortMode = document.getElementById("sortSelect").value;
  window.location.href = "/download?sort=" + sortMode;
}
</script>
"""

def check_keyword(keyword):
    url = f"https://search.naver.com/search.naver?query={keyword}"

    try:
        res = requests.get(url, timeout=10)
        html = res.text
    except:
        return {"keyword": keyword, "count": 0, "grade": "B", "link": url}

    # 판매처 숫자 찾기
    match = re.search(r"판매처\s*(\d+)", html)
    count = int(match.group(1)) if match else 0

    grade = "B" if count > 0 else "A"

    return {
        "keyword": keyword,
        "count": count,
        "grade": grade,
        "link": url
    }

@app.route("/", methods=["GET", "POST"])
def home():
    global results_storage
    results_storage = []
    total_time = 0

    if request.method == "POST":
        start = time.time()

        keywords = request.form.get("keywords","").splitlines()
        keywords = [k.strip() for k in keywords if k.strip()][:1000]

        progress_data["done"] = 0
        progress_data["total"] = len(keywords)
        progress_data["start"] = time.time()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(check_keyword, k) for k in keywords]

            for future in as_completed(futures):
                result = future.result()
                results_storage.append(result)
                progress_data["done"] += 1

        total_time = round(time.time() - start,2)

    return render_template_string(HTML, results=results_storage, total_time=total_time)

@app.route("/progress")
def progress():
    done = progress_data["done"]
    total = progress_data["total"]
    elapsed = time.time() - progress_data["start"] if progress_data["start"] else 0

    if done > 0:
        avg = elapsed / done
        remain = round((total-done)*avg)
    else:
        remain = 0

    return jsonify({
        "done": done,
        "total": total,
        "remaining": remain
    })

@app.route("/download")
def download():
    sort_mode = request.args.get("sort","original")
    data = results_storage.copy()

    if sort_mode == "aFirst":
        data.sort(key=lambda x: x["grade"])

    df = pd.DataFrame(data)
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        download_name="book_result.xlsx",
        as_attachment=True
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
