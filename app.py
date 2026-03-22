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
import random

app = Flask(__name__)

AD_ACCESS_KEY = os.environ.get("ACCESS_KEY", "")
AD_SECRET_KEY = os.environ.get("SECRET_KEY", "")
AD_CUSTOMER_ID = os.environ.get("CUSTOMER_ID", "")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

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

# ✨ [신규 하이브리드 엔진] 가짜 한국 IP + 모바일 위장 + API 백업
def get_real_store_rank(keyword, target_store="스터디박스"):
    # 가짜 한국 IP 생성
    fake_ip = f"211.{random.randint(10, 250)}.{random.randint(10, 250)}.{random.randint(10, 250)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "X-Forwarded-For": fake_ip,
        "Accept-Language": "ko-KR,ko;q=0.9"
    }
    
    # 1. 모바일 쇼핑 위장 스크래핑 시도
    try:
        url = f"https://msearch.shopping.naver.com/search/all?query={urllib.parse.quote(keyword)}"
        res = requests.get(url, headers=headers, timeout=5)
        
        if "captcha" not in res.text.lower() and "비정상적인" not in res.text:
            if target_store in res.text:
                names = re.findall(r'"mallName":"([^"]+)"', res.text)
                for idx, name in enumerate(names, start=1):
                    if target_store in name: return str(idx)
                return "순위 밖"
    except Exception:
        pass

    # 2. 스크래핑이 차단당했거나 실패하면 API로 즉시 전환 (폴백)
    try:
        if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
            api_headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
            for start_idx in [1, 101]: # API는 빠르니까 200위까지만 검사
                api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword)}&display=100&start={start_idx}"
                api_res = requests.get(api_url, headers=api_headers, timeout=5)
                if api_res.status_code == 200:
                    for idx, item in enumerate(api_res.json().get('items', [])):
                        if target_store in item.get('mallName', ''):
                            return str(start_idx + idx)
                time.sleep(0.1)
    except Exception:
        return "탐색 실패"

    return "순위 밖"

def analyze_book(keyword, fetch_isbn=False, min_search_volume=0):
    search_volume = 0
    try:
        uri = '/keywordstool'
        clean_keyword = keyword.replace(" ", "")
        params = {'hintKeywords': clean_keyword, 'showDetail': '1'}
        headers = get_ad_header('GET', uri)
        res = requests.get(f"https://api.naver.com{uri}", params=params, headers=headers, timeout=5)
        
        if res.status_code == 200:
            data_list = res.json().get('keywordList', [])
            for item in data_list:
                api_kw = item.get('relKeyword', '').replace(" ", "")
                if api_kw.lower() == clean_keyword.lower():
                    pc = item.get('monthlyPcQcCnt', 0)
                    mo = item.get('monthlyMobileQcCnt', 0)
                    if isinstance(pc, str): pc = 0
                    if isinstance(mo, str): mo = 0
                    search_volume = pc + mo
                    break
    except:
        search_volume = 0

    pc_link = f"https://search.naver.com/search.naver?where=nexearch&query={urllib.parse.quote(keyword)}"
    grade = ""
    reason = ""
    seller_count = 0
    shipping_fee = "-" 

    try:
        req_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        html_res = requests.get(pc_link, headers=req_headers, timeout=5)
        soup = BeautifulSoup(html_res.text, "html.parser")
        main_pack = soup.find(id="main_pack")
        
        if not main_pack:
            if "captcha" in html_res.text.lower() or "비정상적인" in html_res.text:
                grade = "오류"
                reason = "네이버 봇 차단 (일시적 접근 제한)"
            else:
                grade = "C (검색불가)"
                reason = "도서 검색결과 없음"
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
                if main_pack.find(class_=re.compile(r'cs_book|sp_book')):
                    is_book_card_exist = True
                else:
                    for bx in main_pack.find_all("div", class_="api_subject_bx"):
                        title_tag = bx.find(class_=re.compile(r'api_title|title'))
                        if title_tag:
                            title_text = title_tag.get_text(strip=True).replace(" ", "")
                            if "도서" in title_text or "책정보" in title_text:
                                is_book_card_exist = True
                                break
                
                if is_book_card_exist:
                    if search_volume >= min_search_volume:
                        grade = "A (황금 🏆)"
                        reason = "대표카드 아님 (단독 노출)"
                    else:
                        grade = "C (검색량 부족)"
                        reason = f"단독 노출 (단, 검색량 {min_search_volume} 미만)"
                else:
                    grade = "C (검색불가)"
                    reason = "도서 영역 없음"

    except:
        grade = "오류"
        reason = "일시적 스크래핑 실패"

    isbn = "-"
    if grade == "B (일반)" and fetch_isbn:
        try:
            api_headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
            api_keyword = keyword
            if api_keyword.endswith("책") and len(api_keyword) > 1: api_keyword = api_keyword[:-1]
            book_api_url = f"https://openapi.naver.com/v1/search/book.json?query={urllib.parse.quote(api_keyword)}&display=20"
            book_res = requests.get(book_api_url, headers=api_headers, timeout=5)
            
            items = []
            if book_res.status_code == 200: items = book_res.json().get('items', [])
            if not items and api_keyword != keyword:
                book_api_url = f"https://openapi.naver.com/v1/search/book.json?query={urllib.parse.quote(keyword)}&display=20"
                book_res = requests.get(book_api_url, headers=api_headers, timeout=5)
                if book_res.status_code == 200: items = book_res.json().get('items', [])

            for item in items:
                isbn_raw = item.get('isbn', '')
                isbns = isbn_raw.split()
                found_valid = False
                for candidate in reversed(isbns):
                    if candidate.startswith('9') or candidate.startswith('8'):
                        isbn = candidate
                        found_valid = True
                        break
                if found_valid: break
        except:
            isbn = "조회 실패"

    store_rank = get_real_store_rank(keyword, "스터디박스")

    return {
        "keyword": keyword,
        "search_volume": search_volume,
        "seller_count": seller_count if seller_count > 0 else "-",
        "grade": grade,
        "reason": reason,
        "isbn": isbn,
        "link": pc_link,
        "shipping_fee": shipping_fee,
        "store_rank": store_rank
    }

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
        .toggle-wrapper { display: flex; align-items: center; margin-right: 15px; cursor: pointer; font-weight: bold; font-size: 14px; }
        .switch { position: relative; display: inline-block; width: 44px; height: 24px; margin-right: 8px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 24px; }
        .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #007bff; }
        input:checked + .slider:before { transform: translateX(20px); }
        .progress-container { margin-top: 15px; padding: 15px; background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 5px; display: none; }
        .progress-text { font-weight: bold; margin-bottom: 8px; font-size: 16px; color: #333; }
        .progress-bar-bg { width: 100%; background-color: #e9ecef; border-radius: 5px; height: 20px; overflow: hidden; }
        .progress-bar-fill { width: 0%; height: 100%; background-color: #007bff; transition: width 0.4s ease; }
        table { width: 100%; border-collapse: collapse; text-align: center; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 8px; }
        th { background-color: #f2f2f2; position: sticky; top: 0; }
        .grade-a { background-color: #e6f7ff; }
        .grade-c { background-color: #fcfcfc; color: #777; }
        .table-container { max-height: 600px; overflow-y: auto; margin-top: 10px; border-bottom: 1px solid #ddd; display: none; }
        .filter-box { display: flex; align-items: center; margin-right: 15px; font-weight: bold; font-size: 14px; background: #e9ecef; padding: 5px 10px; border-radius: 5px;}
        .filter-box input { width: 60px; padding: 5px; border: 1px solid #ccc; border-radius: 4px; text-align: center; margin: 0 5px; font-weight: bold;}
    </style>
</head>
<body>
    <h1>📚 도서 키워드 통합 분석기 (ISBN 최적화)</h1>
    
    <div class="input-area">
        <textarea id="keywordInput" rows="10" cols="70" placeholder="책 제목들을 한 줄에 하나씩 입력하세요"></textarea>
        <div class="stats">입력된 키워드: 총 <span id="countDisplay" style="color: blue;">0</span> 건</div>
        <div style="display: flex; align-items: center; margin-top: 10px;">
            <label class="toggle-wrapper">
                <div class="switch"><input type="checkbox" id="isbnToggle" checked><span class="slider"></span></div>
                B등급 ISBN (켜짐)
            </label>
            <div class="filter-box">
                <label for="minVolume">A등급 최소 검색량:</label>
                <input type="number" id="minVolume" value="0" min="0"> 이상
            </div>
            <select id="sortOption">
                <option value="original">입력 순서대로 표시 (원본)</option>
                <option value="grade">A등급 우선 정렬 (A → C → B)</option>
            </select>
            <button id="submitBtn" class="btn btn-submit" onclick="startAnalysis()">일괄 분석 시작</button>
        </div>
    </div>

    <div id="progressContainer" class="progress-container">
        <div id="progressText" class="progress-text">대기 중...</div>
        <div class="progress-bar-bg"><div id="progressBar" class="progress-bar-fill"></div></div>
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
                    <th>ISBN (B등급)</th>
                    <th>링크</th>
                </tr>
            </thead>
            <tbody id="resultBody"></tbody>
        </table>
    </div>

    <script>
        const textarea = document.getElementById('keywordInput');
        const countDisplay = document.getElementById('countDisplay');
        const sortOptionSelect = document.getElementById('sortOption');
        const isbnToggle = document.getElementById('isbnToggle');

        isbnToggle.addEventListener('change', function() {
            this.parentElement.nextSibling.textContent = this.checked ? " B등급 ISBN (켜짐)" : " B등급 ISBN (꺼짐)";
        });

        function updateCount() {
            const lines = textarea.value.split('\\n').filter(line => line.trim() !== '');
            countDisplay.textContent = lines.length;
        }
        textarea.addEventListener('input', updateCount);

        sortOptionSelect.addEventListener('change', function() { applyCurrentSort(); });

        function applyCurrentSort() {
            const tbody = document.getElementById('resultBody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const sortOption = document.getElementById('sortOption').value;

            if (sortOption === 'grade') {
                rows.sort((a, b) => {
                    const textA = a.querySelector('td:nth-child(4) span').innerText;
                    const textB = b.querySelector('td:nth-child(4) span').innerText;
                    let scoreA = textA.includes('A') ? 1 : (textA.includes('C') ? 2 : 3);
                    let scoreB = textB.includes('A') ? 1 : (textB.includes('C') ? 2 : 3);
                    if (scoreA === scoreB) return parseInt(a.getAttribute('data-index')) - parseInt(b.getAttribute('data-index'));
                    return scoreA - scoreB;
                });
                tbody.innerHTML = '';
                rows.forEach(row => tbody.appendChild(row));
                document.getElementById('tableContainer').scrollTop = 0;
            } else {
                rows.sort((a, b) => parseInt(a.getAttribute('data-index')) - parseInt(b.getAttribute('data-index')));
                tbody.innerHTML = '';
                rows.forEach(row => tbody.appendChild(row));
            }
        }

        async function startAnalysis() {
            const btn = document.getElementById('submitBtn');
            const keywords = textarea.value.split('\\n').map(k => k.trim()).filter(k => k !== '');
            const total = keywords.length;
            const fetchIsbn = isbnToggle.checked; 
            const minVol = parseInt(document.getElementById('minVolume').value) || 0;

            if (total === 0) { alert('키워드를 입력해주세요!'); return; }

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
                        body: JSON.stringify({ keyword: kw, fetch_isbn: fetchIsbn, min_search_volume: minVol })
                    });
                    rowData = await response.json();
                } catch (error) {
                    rowData = { keyword: kw, search_volume: 0, seller_count: "-", grade: "오류", reason: "네트워크 실패", isbn: "-", link: "#", webhook_status: "통신 실패" };
                }

                rowData.original_index = i;
                appendRow(rowData);

                const percent = Math.round(((i + 1) / total) * 100);
                document.getElementById('progressBar').style.width = percent + '%';
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
            let reasonHtml = r.reason;

            if (isGradeA) {
                gradeColor = 'blue';
                let whMsg = r.webhook_status || '응답 없음';
                let whColor = whMsg.includes('성공') ? 'green' : 'red';
                reasonHtml += `<br><span style="color:${whColor}; font-size:0.85em; font-weight:bold;">[스터디박스 전송: ${whMsg}]</span>`;
            }
            else if (isGradeC) gradeColor = '#f0ad4e'; 
            else if (r.grade.includes('오류')) gradeColor = 'red';

            tr.innerHTML = `
                <td>${r.keyword}</td>
                <td>${svFormat}</td>
                <td><b style="color:#d9534f;">${r.seller_count}</b></td>
                <td><span style="color: ${gradeColor}; font-weight:bold;">${r.grade}</span></td>
                <td style="color: gray; font-size: 0.9em;">${reasonHtml}</td>
                <td style="font-family: monospace; color: #555;">${r.isbn || '-'}</td>
                <td><a href="${r.link}" target="_blank">확인하기</a></td>
            `;
            tbody.appendChild(tr);
            applyCurrentSort();
        }

        function downloadExcel() {
            let csv = '\uFEFF'; 
            let rows = document.querySelectorAll("#resultTable tr");
            for (let i = 0; i < rows.length; i++) {
                let row = [], cols = rows[i].querySelectorAll("td, th");
                for (let j = 0; j < cols.length; j++) {
                    let data = "";
                    if (cols[j].querySelector("a")) {
                        data = cols[j].querySelector("a").href;
                    } else {
                        data = cols[j].innerText.replace(/"/g, '""').replace(/\n/g, " "); 
                        if (j === 5 && data !== "-" && data !== "ISBN (B등급)") data = '="' + data + '"';
                    }
                    row.push('"' + data + '"');
                }
                csv += row.join(",") + "\n";
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
    fetch_isbn = data.get("fetch_isbn", False)
    min_search_volume = int(data.get("min_search_volume", 0))
    
    result = analyze_book(keyword, fetch_isbn=fetch_isbn, min_search_volume=min_search_volume)
    result['webhook_status'] = '대기'
    
    grade = result.get("grade", "")
    if "A" in grade:
        webhook_url = os.environ.get("STUDYBOX_WEBHOOK_URL", "").strip()
        if not webhook_url:
            result['webhook_status'] = '환경변수 누락 (전송불가)'
        else:
            try:
                res = requests.post(webhook_url, json=result, timeout=5)
                if res.status_code == 200:
                    result['webhook_status'] = '성공!'
                else:
                    result['webhook_status'] = f'서버 거절 ({res.status_code})'
            except:
                result['webhook_status'] = '통신 에러'

    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
