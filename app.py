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

# --- 광고 API 설정 (Railway 환경 변수) ---
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
    scrape_url = f"https://m.search.naver.com/search.naver?where=m&query={urllib.parse.quote(keyword)}"
    grade = ""
    reason = ""
    seller_count = 0

    try:
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://m.naver.com/"
        }
        html_res = requests.get(scrape_url, headers=req_headers, timeout=5)
        soup = BeautifulSoup(html_res.text, "html.parser")
        page_text = soup.get_text(separator=" ", strip=True)

        if "비정상적인 인터넷 환경" in page_text or "자동 입력 방지" in page_text or "캡차" in page_text:
            grade = "오류"
            reason = "서버 IP 네이버 차단됨 (모바일 우회 실패)"
        else:
            book_area = soup.find(class_=re.compile(r'cs_book|sp_book|book_info|api_subject_bx'))
            
            if not book_area:
                for bx in soup.find_all("section", class_="sc_new"):
                    title_tag = bx.find(class_=re.compile(r'api_title|title'))
                    if title_tag and ('도서' in title_tag.get_text() or '책' in title_tag.get_text()):
                        book_area = bx
                        break

            target_text = book_area.get_text(separator=" ", strip=True) if book_area else page_text
            
            match = re.search(r'(판매처|판매자|판매몰|쇼핑몰)\s*([\d,]+)', target_text)
            
            if match:
                seller_word = match.group(1)
                seller_count = int(match.group(2).replace(',', ''))
                grade = "B (일반)"
                reason = f"대표카드 묶임 ({seller_word} {seller_count}개)"
            else:
                is_real_book = ("저자" in target_text or "출판" in target_text or "발행" in target_text)
                if book_area and is_real_book:
                    grade = "A (황금 🏆)"
                    reason = "대표카드 아님 (단독 노출)"
                elif "저자" in page_text and ("출판" in page_text or "발행" in page_text) and "도서" in page_text:
                    grade = "A (황금 🏆)"
                    reason = "대표카드 아님 (전체 텍스트 우회)"
                else:
                    grade = "B (일반)"
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

# --- 웹 페이지 템플릿 (단일 페이지, 비동기 통신 적용) ---
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
        
        /* 프로그레스 바 스타일 추가 */
        .progress-container { margin-top: 15px; padding: 15px; background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 5px; display: none; }
        .progress-text { font-weight: bold; margin-bottom: 8px; font-size: 16px; color: #333; }
        .progress-bar-bg { width: 100%; background-color: #e9ecef; border-radius: 5px; height: 20px; overflow: hidden; }
        .progress-bar-fill { width: 0%; height: 100%; background-color: #007bff; transition: width 0.4s ease; }
        
        table { width: 100%; border-collapse: collapse; text-align: center; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 8px; }
        th { background-color: #f2f2f2; position: sticky; top: 0; }
        .grade-a { background-color: #e6f7ff; }
        
        /* 테이블이 너무 길어질 경우 스크롤 생성 */
        .table-container { max-height: 600px; overflow-y: auto; margin-top: 10px; border-bottom: 1px solid #ddd; display: none; }
    </style>
</head>
<body>
    <h1>📚 도서 키워드 통합 분석기 (실시간 처리)</h1>
    
    <div class="input-area">
        <textarea id="keywordInput" rows="10" cols="70" placeholder="책 제목들을 한 줄에 하나씩 입력하세요"></textarea>
        <div class="stats">입력된 키워드: 총 <span id="countDisplay" style="color: blue;">0</span> 건</div>
        
        <div style="display: flex; align-items: center; margin-top: 10px;">
            <select id="sortOption">
                <option value="original">입력 순서대로 표시 (원본)</option>
                <option value="grade">A등급 우선 정렬 (완료 후 자동정렬)</option>
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
        // 1. 글자 수(건수) 실시간 세기
        const textarea = document.getElementById('keywordInput');
        const countDisplay = document.getElementById('countDisplay');

        function updateCount() {
            const lines = textarea.value.split('\\n').filter(line => line.trim() !== '');
            countDisplay.textContent = lines.length;
        }
        textarea.addEventListener('input', updateCount);

        // 2. 비동기 실시간 분석 로직
        async function startAnalysis() {
            const btn = document.getElementById('submitBtn');
            const keywordsText = textarea.value;
            const keywords = keywordsText.split('\\n').map(k => k.trim()).filter(k => k !== '');
            const total = keywords.length;
            const sortOption = document.getElementById('sortOption').value;

            if (total === 0) {
                alert('키워드를 입력해주세요!');
                return;
            }

            // UI 초기화 및 시작 준비
            btn.disabled = true;
            btn.innerText = "분석 진행 중...";
            document.getElementById('progressContainer').style.display = 'block';
            document.getElementById('resultHeader').style.display = 'flex';
            document.getElementById('tableContainer').style.display = 'block';
            
            const tbody = document.getElementById('resultBody');
            tbody.innerHTML = ''; // 기존 결과 지우기
            document.getElementById('progressBar').style.width = '0%';

            // 키워드 하나씩 서버에 전송 후 결과 받기
            for (let i = 0; i < total; i++) {
                const kw = keywords[i];
                
                // 진행률 UI 업데이트
                document.getElementById('progressText').innerText = `[${i + 1} / ${total}] "${kw}" 분석 중...`;
                
                try {
                    // 서버 API 호출
                    const response = await fetch('/api/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ keyword: kw })
                    });
                    
                    const result = await response.json();
                    appendRow(result); // 성공 시 테이블에 행 추가
                    
                } catch (error) {
                    console.error('Error:', error);
                    // 에러 발생 시 임시 행 추가
                    appendRow({
                        keyword: kw, search_volume: 0, seller_count: "-",
                        grade: "오류", reason: "네트워크 통신 실패", link: "#"
                    });
                }

                // 게이지 바 업데이트
                const percent = Math.round(((i + 1) / total) * 100);
                document.getElementById('progressBar').style.width = percent + '%';
                
                // 네이버 봇 차단 방지를 위해 자바스크립트 단에서 0.6초 대기
                await new Promise(r => setTimeout(r, 600));
            }

            // 모든 분석이 끝났을 때
            document.getElementById('progressText').innerText = `✅ 분석 완료! (총 ${total}건)`;
            btn.disabled = false;
            btn.innerText = "일괄 분석 시작";

            // 정렬 옵션에 따라 마무리 정렬 처리
            if (sortOption === 'grade') {
                sortTableByGrade();
            }
        }

        // 3. 테이블에 결과 한 줄씩 추가하는 함수
        function appendRow(r) {
            const tbody = document.getElementById('resultBody');
            const tr = document.createElement('tr');
            
            const isGradeA = r.grade.includes('A');
            if (isGradeA) tr.className = 'grade-a';

            const svFormat = r.search_volume > 0 ? r.search_volume.toLocaleString() : '0';
            
            let gradeColor = 'black';
            if (isGradeA) gradeColor = 'blue';
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
            
            // 새 항목이 추가될 때마다 테이블 스크롤을 가장 아래로 내림
            const container = document.getElementById('tableContainer');
            container.scrollTop = container.scrollHeight;
        }

        // 4. A등급 우선 정렬 함수
        function sortTableByGrade() {
            const tbody = document.getElementById('resultBody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            
            rows.sort((a, b) => {
                const gradeA = a.querySelector('td:nth-child(4) span').innerText;
                const gradeB = b.querySelector('td:nth-child(4) span').innerText;
                // 'A'가 'B'보다 문자열 순서가 빠르므로 정상 작동
                if (gradeA < gradeB) return -1;
                if (gradeA > gradeB) return 1;
                return 0;
            });
            
            // 기존 돔 요소를 재배치
            rows.forEach(row => tbody.appendChild(row));
            
            // 정렬 후엔 스크롤 맨 위로 올려주기
            document.getElementById('tableContainer').scrollTop = 0;
            alert("A등급 우선으로 표가 정렬되었습니다!");
        }

        // 5. 엑셀 다운로드 로직 (기존과 동일)
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

# HTML 껍데기를 렌더링하는 기본 페이지
@app.route("/", methods=["GET"])
def home():
    return render_template_string(TEMPLATE)

# 자바스크립트가 비동기(AJAX)로 하나씩 요청을 보낼 API 엔드포인트
@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json()
    keyword = data.get("keyword", "")
    
    # 1개의 키워드를 검사하고 결과를 딕셔너리로 반환
    result = analyze_book(keyword)
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
