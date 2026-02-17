from flask import Flask, render_template_string, request, jsonify, send_file
import requests
import os
import time
import threading
import re
import pandas as pd
import io

app = Flask(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

jobs = {}

HTML = """
<!doctype html>
<title>naverbookbot</title>
<h1>naverbookbot</h1>

<textarea id="keywords" rows="15" cols="60"
placeholder="한 줄에 하나씩 입력 (최대 1000개)"></textarea><br><br>

<button onclick="startSearch()">검색 시작</button>
<p id="count"></p>
<p id="progress"></p>

<div id="result"></div>

<script>
function startSearch(){
    let keywords = document.getElementById("keywords").value;
    let list = keywords.split("\\n").filter(k => k.trim() !== "");
    document.getElementById("count").innerText = "총 입력 건수: " + list.length;

    fetch("/start", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({keywords:list})
    }).then(res=>res.json())
    .then(data=>{
        checkStatus(data.job_id);
    });
}

function checkStatus(job_id){
    let interval = setInterval(()=>{
        fetch("/status?job_id="+job_id)
        .then(res=>res.json())
        .then(data=>{
            document.getElementById("progress").innerText =
            "진행률: "+data.done+"/"+data.total+
            " | 예상 남은시간: "+data.remaining+"초";

            if(data.finished){
                clearInterval(interval);
                loadResult(job_id);
            }
        });
    },1000);
}

function loadResult(job_id){
    fetch("/result?job_id="+job_id)
    .then(res=>res.text())
    .then(html=>{
        document.getElementById("result").innerHTML = html;
    });
}
</script>
"""

def get_search_volume(keyword):
    url = "https://api.naver.com/keywordstool"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {"hintKeywords": keyword, "showDetail": 1}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        data = r.json()
        if data["keywordList"]:
            pc = int(data["keywordList"][0]["monthlyPcQcCnt"])
            mobile = int(data["keywordList"][0]["monthlyMobileQcCnt"])
            return pc + mobile
    except:
        pass
    return 0

def has_seller(keyword):
    url = "https://search.naver.com/search.naver"
    params = {"query": keyword}
    try:
        r = requests.get(url, params=params, timeout=5)
        html = r.text
        if re.search(r"판매처\s*\d+", html):
            return True
    except:
        pass
    return False

def worker(job_id, keywords):
    results = []
    total = len(keywords)
    start_time = time.time()

    for idx, keyword in enumerate(keywords):
        volume = get_search_volume(keyword)
        seller = has_seller(keyword)

        grade = "B"
        if not seller:
            grade = "A"

        results.append({
            "keyword": keyword,
            "volume": volume,
            "grade": grade
        })

        jobs[job_id]["done"] = idx+1
        elapsed = time.time() - start_time
        avg = elapsed / (idx+1)
        remaining = round(avg * (total - (idx+1)),1)
        jobs[job_id]["remaining"] = remaining

        time.sleep(0.2)  # 과부하 방지

    jobs[job_id]["results"] = results
    jobs[job_id]["finished"] = True

@app.route("/")
def home():
    return HTML

@app.route("/start", methods=["POST"])
def start():
    data = request.json
    keywords = data["keywords"][:1000]

    job_id = str(time.time())
    jobs[job_id] = {
        "done":0,
        "total":len(keywords),
        "remaining":0,
        "finished":False,
        "results":[]
    }

    t = threading.Thread(target=worker, args=(job_id, keywords))
    t.start()

    return jsonify({"job_id":job_id})

@app.route("/status")
def status():
    job_id = request.args.get("job_id")
    job = jobs[job_id]
    return jsonify(job)

@app.route("/result")
def result():
    job_id = request.args.get("job_id")
    results = jobs[job_id]["results"]

    df = pd.DataFrame(results)
    df = df.sort_values(by=["grade","volume"], ascending=[True,False])

    html = df.to_html(index=False)
    return html

@app.route("/download")
def download():
    job_id = request.args.get("job_id")
    results = jobs[job_id]["results"]

    df = pd.DataFrame(results)

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(output,
        download_name="result.xlsx",
        as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
