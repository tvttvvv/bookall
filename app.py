from flask import Flask, request, render_template_string, jsonify
import requests
from bs4 import BeautifulSoup
import time
import hmac
import hashlib
import base64
import urllib.parse
import os
import re

app = Flask(__name__)

# --- 광고 API 설정 ---
AD_ACCESS_KEY = os.environ.get("ACCESS_KEY", "")
AD_SECRET_KEY = os.environ.get("SECRET_KEY", "")
AD_CUSTOMER_ID = os.environ.get("CUSTOMER_ID", "")

def get_ad_header(method, uri):
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(AD_SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    signature = base64.b64encode(hash).decode()
    
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Timestamp": timestamp,
        "X-API-KEY": AD_ACCESS_KEY,
        "X-Customer": str(AD_CUSTOMER_ID),
        "X-Signature": signature
    }

def analyze_book(keyword):
    search_volume = 0
    try:
        uri = '/keywordstool'
        clean_keyword = keyword.replace(" ", "")
        params = {'hintKeywords': clean_keyword, 'showDetail': '1'}
        headers = get_ad_header('GET', uri)
        res = requests.get(f"https://api.naver.com{uri}", params=params, headers=headers, timeout=5)
        
        if res.status_code == 200:
            data_list = res.json().get('keywordList', [])
            found = False
            for item in data_list:
                api_kw = item.get('relKeyword', '').replace(" ", "")
                if api_kw.lower() == clean_keyword.lower():
                    pc = item.get('monthlyPcQcCnt', 0)
                    mo = item.get('monthlyMobileQcCnt', 0)
                    if isinstance(pc, str): pc = 10
                    if isinstance(mo, str): mo = 10
                    search_volume = pc + mo
                    found = True
                    break
            
            if not found and len(data_list) > 0:
                item = data_list[0]
                pc = item.get('monthlyPcQcCnt', 0)
                mo = item.get('monthlyMobileQcCnt', 0)
                if isinstance(pc, str): pc = 10
                if isinstance(mo, str): mo = 10
                search_volume = pc + mo
    except Exception as e:
        print(f"광고 API 에러: {e}")
        search_volume = 0

    pc_link = f"https://search.naver.com/search.naver?where=nexearch&query={urllib.parse.quote(keyword)}"
    grade = ""
    reason = ""
    seller_count = 0

    try:
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://www.naver.com/"
        }
        html_res = requests.get(pc_link, headers=req_headers, timeout=5)
        soup = BeautifulSoup(html_res.text, "html.parser")
        
        main_pack = soup.find(id="main_pack")
        
        if not main_pack:
            if "captcha" in html_res.text.lower() or "비정상적인" in html_res.text:
                grade = "오류"
                reason = "네이버 봇 차단 (일시적 접근 제한)"
            else:
                grade = "C (검색불가)"
                reason = "검색결과 없음"
        else:
            main_text = main_pack.get_text(separator=" ", strip=True)
            
            match = re.search(r'(판매처|판매자|판매몰|쇼핑몰)\s*([\d,]+)', main_text)
            
            if match:
                seller_word = match.group(1)
                seller_count = int(match.group(2).replace(',', ''))
                grade = "B (일반)"
                reason = f"대표카드 묶임 ({seller_word} {seller_count}개)"
            else:
                is_book_card_exist = False
                
                for bx in main_pack.find_all("div", class_=re.compile(r'api_subject_bx|sc_new|cs_book')):
                    bx_text = bx.get_text(separator=" ", strip=True)
                    title_tag = bx.find(class_=re.compile(r'title|api_title'))
                    title_text = title_tag.get_text() if title_tag else ""
                    
                    if ('도서' in title_text or '책정보' in title_text) or ('저자' in bx_text and '발행' in bx_text):
                        is_book_card_exist = True
                        break
                
                if is_book_card_exist:
                    grade = "A (황금 🏆)"
                    reason = "대표카드 아님 (단독 노출)"
                else:
                    grade = "C (검색불가)"
                    reason = "도서 검색결과 없음"

    except Exception as e:
        print(f"크롤링 에러: {e}")
        grade = "오류"
        reason = "일시적 스크래핑 실패"

    return {
        "keyword": keyword,
        "search_volume": search_volume,
        "seller_count": seller_count if seller_count > 0 else "-",
        "grade": grade,
        "reason": reason,
        "link": pc_link
    }

# --- 웹 페이지 템플릿 ---
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Book 분석기 Pro</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; padding: 20px; }
        .input-area { margin-bottom: 20px; }
        .stats { font-weight: bold; color: #333; margin-bottom: 10px; }
        .btn { padding: 10px 20px; font-weight: bold; cursor: pointer; margin-right: 10px; transition: background-color 0.3s; }
        .btn:disabled { background-color: #cccccc; cursor: not-allowed; }
        .btn-excel { background-color: #28a745; color: white; border: none; border-radius: 5px; }
        .btn-submit { background-color: #007bff; color: white; border: none; border-radius: 5px; }
        select { padding: 9px; font-size: 15px; border-radius: 5px; margin-right: 10px; }
        .progress-container { margin-top: 15px; padding: 15px; background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 5px; display: none; }
        .progress-text { font-weight: bold; margin-bottom: 8px; font-size: 16px; color: #333; }
        .progress-bar-bg { width: 100%; background-color: #e9ecef; border-radius: 5px; height: 20px; overflow: hidden; }
        .progress-bar-fill { width: 0%; height: 100%; background-color: #007bff; transition: width 0.4s ease; }
        table { width: 100%; border-collapse: collapse; text-align: center; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 8px; }
        th { background-color: #f2f2f2; position: sticky; top: 0; }
        
        /* 등급별 배경색 추가 */
        .grade-a { background-color: #e6f7ff; }
        .grade-c { background-color: #fcfcfc; color: #777; }
        
        .table-container { max-height: 600px; overflow-y: auto; margin-top: 10px; border-bottom: 1px solid #ddd; display: none; }
    </style>
</head>
<body>
    <h1>📚 도서 키워드 통합 분석기 (A-C-B 정렬)</h1>
    
    <div class="input-area">
        <textarea id="keywordInput" rows="10" cols="70" placeholder="책 제목들을 한 줄에 하나씩 입력하세요"></textarea>
        <div class="stats">입력된 키워드: 총 <span id="countDisplay" style="color: blue;">0</span> 건</div>
        
        <div style="display: flex; align-items: center; margin-top: 10px;">
            <select id="sortOption">
                <option value="original">입력 순서대로 표시 (원본)</option>
                <option value="grade">A등급 우선 정렬 (A → C → B)</option>
            </select>
            <button id="submitBtn" class="btn btn-submit" onclick="startAnalysis()">일괄 분석 시작</button>
        </div>
    </div>

    <div id="progressContainer" class="progress-container">
        <div id="progressText" class="progress-text">대기 중...</div>
        <div class="progress-bar-bg">
            <div id="progressBar" class="progress-bar-fill"></div>
        </div>
    </div>

    <div id="resultHeader" style="display: flex; justify-content: space-between; align-items: center; display: none; margin-top: 20px;">
        <h3 style="margin: 0;">분석 결과</h3>
        <button onclick="downloadExcel()" class="btn btn-excel">📥 엑셀로 다운로드</button>
    </div>
    
    <div id="tableContainer" class="table-container">
        <table id="resultTable">
            <thead>
                <tr>
                    <th>키워드</th>
                    <th>월간 총 검색량</th>
                    <th>판매처 수</th>
                    <th>분류 등급</th>
                    <th>분류 이유 (참고용)</th>
                    <th>링크</th>
                </tr>
            </thead>
            <tbody id="resultBody">
            </tbody>
        </table>
    </div>

    <script>
        const textarea = document.getElementById('keywordInput');
        const countDisplay = document.getElementById('countDisplay');
        const sortOptionSelect = document.getElementById('sortOption');

        function updateCount() {
            const lines = textarea.value.split('\\n').filter(line => line.trim() !== '');
            countDisplay.textContent = lines.length;
        }
        textarea.addEventListener('input', updateCount);

        sortOptionSelect.addEventListener('change', function() {
            applyCurrentSort();
        });

        // 🔥 A -> C -> B 순서로 정렬하는 핵심 로직
        function applyCurrentSort() {
            const tbody = document.getElementById('resultBody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const sortOption = document.getElementById('sortOption').value;

            if (sortOption === 'grade') {
                rows.sort((a, b) => {
                    const textA = a.querySelector('td:nth-child(4) span').innerText;
                    const textB = b.querySelector('td:nth-child(4) span').innerText;
                    
                    // A는 1점, C는 2점, B는 3점, 오류는 4점
                    let scoreA = 4;
                    if (textA.includes('A')) scoreA = 1;
                    else if (textA.includes('C')) scoreA = 2;
                    else if (textA.includes('B')) scoreA = 3;

                    let scoreB = 4;
                    if (textB.includes('A')) scoreB = 1;
                    else if (textB.includes('C')) scoreB = 2;
                    else if (textB.includes('B')) scoreB = 3;
                    
                    if (scoreA === scoreB) {
                        return parseInt(a.getAttribute('data-index')) - parseInt(b.getAttribute('data-index'));
                    }
                    return scoreA - scoreB;
                });
                
                tbody.innerHTML = '';
                rows.forEach(row => tbody.appendChild(row));
                document.getElementById('tableContainer').scrollTop = 0;
            } else {
                rows.sort((a, b) => {
                    return parseInt(a.getAttribute('data-index')) - parseInt(b.getAttribute('data-index'));
                });
                
                tbody.innerHTML = '';
                rows.forEach(row => tbody.appendChild(row));
                
                const container = document.getElementById('tableContainer');
                container.scrollTop = container.scrollHeight;
            }
        }

        async function startAnalysis() {
            const btn = document.getElementById('submitBtn');
            const keywordsText = textarea.value;
            const keywords = keywordsText.split('\\n').map(k => k.trim()).filter(k => k !== '');
            const total = keywords.length;

            if (total === 0) {
                alert('키워드를 입력해주세요!');
                return;
            }

            btn.disabled = true;
            btn.innerText = "분석 진행 중...";
            document.getElementById('progressContainer').style.display = 'block';
            document.getElementById('resultHeader').style.display = 'flex';
            document.getElementById('tableContainer').style.display = 'block';
            
            const tbody = document.getElementById('resultBody');
            tbody.innerHTML = ''; 
            document.getElementById('progressBar').style.width = '0%';

            for (let i = 0; i < total; i++) {
                const kw = keywords[i];
                document.getElementById('progressText').innerText = `[${i + 1} / ${total}] "${kw}" 분석 중...`;
                
                let rowData = null;
                try {
                    const response = await fetch('/api/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ keyword: kw })
                    });
                    rowData = await response.json();
                } catch (error) {
                    rowData = {
                        keyword: kw, search_volume: 0, seller_count: "-",
                        grade: "오류", reason: "네트워크 통신 실패", link: "#"
                    };
                }

                rowData.original_index = i;
                appendRow(rowData);

                const percent = Math.round(((i + 1) / total) * 100);
                document.getElementById('progressBar').style.width = percent + '%';
                
                await new Promise(r => setTimeout(r, 600));
            }

            document.getElementById('progressText').innerText = `✅ 분석 완료! (총 ${total}건)`;
            btn.disabled = false;
            btn.innerText = "일괄 분석 시작";
        }

        function appendRow(r) {
            const tbody = document.getElementById('resultBody');
            const tr = document.createElement('tr');
            
            tr.setAttribute('data-index', r.original_index);
            
            const isGradeA = r.grade.includes('A');
            const isGradeC = r.grade.includes('C');
            
            if (isGradeA) tr.className = 'grade-a';
            else if (isGradeC) tr.className = 'grade-c';

            const svFormat = r.search_volume > 0 ? r.search_volume.toLocaleString() : '0';
            
            let gradeColor = 'black';
            if (isGradeA) gradeColor = 'blue';
            else if (isGradeC) gradeColor = '#f0ad4e'; // C등급은 약간의 주황/황토색으로 포인트
            else if (r.grade.includes('오류')) gradeColor = 'red';

            tr.innerHTML = `
                <td>${r.keyword}</td>
                <td>${svFormat}</td>
                <td><b style="color:#d9534f;">${r.seller_count}</b></td>
                <td><span style="color: ${gradeColor}; font-weight:bold;">${r.grade}</span></td>
                <td style="color: gray; font-size: 0.9em;">${r.reason}</td>
                <td><a href="${r.link}" target="_blank">확인하기</a></td>
            `;
            tbody.appendChild(tr);
            
            applyCurrentSort();
        }

        function downloadExcel() {
            let csv = '\\uFEFF'; 
            let rows = document.querySelectorAll("#resultTable tr");
            
            for (let i = 0; i < rows.length; i++) {
                let row = [], cols = rows[i].querySelectorAll("td, th");
                for (let j = 0; j < cols.length; j++) {
                    let data = "";
                    if (cols[j].querySelector("a")) {
                        data = cols[j].querySelector("a").href;
                    } else {
                        data = cols[j].innerText.replace(/"/g, '""'); 
                    }
                    row.push('"' + data + '"');
                }
                csv += row.join(",") + "\\n";
            }
            
            let blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            let link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = "도서_분석결과.csv";
            link.style.display = "none";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        }
    </script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def home():
    return render_template_string(TEMPLATE)

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json()
    keyword = data.get("keyword", "")
    result = analyze_book(keyword)
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
