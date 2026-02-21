from flask import Flask, request, render_template_string
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
    # 1. 총 검색량 조회
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

    # 2. 화면 크롤링 (A/B 분류)
    link = f"https://search.naver.com/search.naver?where=nexearch&query={urllib.parse.quote(keyword)}"
    grade = ""
    reason = ""
    seller_count = 0

    try:
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://www.naver.com/"
        }
        html_res = requests.get(link, headers=req_headers, timeout=5)
        soup = BeautifulSoup(html_res.text, "html.parser")

        book_area = soup.find(class_=re.compile(r'cs_book|sp_book'))
        
        if not book_area:
            for bx in soup.find_all("div", class_="api_subject_bx"):
                title_tag = bx.find(class_=re.compile(r'api_title|title'))
                if title_tag and ('도서' in title_tag.get_text() or '책정보' in title_tag.get_text()):
                    book_area = bx
                    break

        if book_area:
            book_text = book_area.get_text(separator=" ", strip=True)
            match = re.search(r'(?:도서\s*)?판매처\s*([\d,]+)', book_text)
            
            if match:
                seller_count = int(match.group(1).replace(',', ''))
                grade = "B (일반)"
                reason = f"대표카드 묶임 (판매처 {seller_count}개)"
            else:
                grade = "A (황금 🏆)"
                reason = "대표카드 아님 (단독 노출)"
        else:
            page_text = soup.get_text(separator=" ", strip=True)
            match_fallback = re.search(r'도서\s*판매처\s*([\d,]+)', page_text)
            if match_fallback:
                seller_count = int(match_fallback.group(1).replace(',', ''))
                grade = "B (일반)"
                reason = f"대표카드 묶임 (판매처 {seller_count}개)"
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
        "link": link
    }

# --- 웹 페이지 템플릿 (UI 및 자바스크립트 추가) ---
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Book 분석기 Pro</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; padding: 20px; }
        .input-area { margin-bottom: 20px; }
        .stats { font-weight: bold; color: #333; margin-bottom: 10px; }
        .btn { padding: 10px 20px; font-weight: bold; cursor: pointer; margin-right: 10px; }
        .btn-excel { background-color: #28a745; color: white; border: none; border-radius: 5px; }
        .btn-submit { background-color: #007bff; color: white; border: none; border-radius: 5px; }
        table { width: 100%; border-collapse: collapse; text-align: center; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 8px; }
        th { background-color: #f2f2f2; }
        .grade-a { background-color: #e6f7ff; }
    </style>
</head>
<body>
    <h1>📚 도서 키워드 통합 분석기</h1>
    
    <div class="input-area">
        <form method="POST">
            <textarea id="keywordInput" name="keywords" rows="10" cols="70" placeholder="책 제목들을 한 줄에 하나씩 입력하세요">{{keywords}}</textarea>
            <div class="stats">입력된 키워드: 총 <span id="countDisplay" style="color: blue;">0</span> 건</div>
            <button type="submit" class="btn btn-submit">일괄 분석 시작</button>
        </form>
    </div>

    {% if results %}
    <hr>
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <h3>분류 결과 (A등급 우선 정렬됨)</h3>
        <button onclick="downloadExcel()" class="btn btn-excel">📥 엑셀로 다운로드</button>
    </div>
    
    <table id="resultTable">
        <tr>
            <th>키워드</th>
            <th>월간 총 검색량</th>
            <th>판매처 수</th>
            <th>분류 등급</th>
            <th>분류 이유 (참고용)</th>
            <th>링크</th>
        </tr>
        {% for r in results %}
        <tr class="{{ 'grade-a' if 'A' in r.grade else '' }}">
            <td>{{r.keyword}}</td>
            <td>{{ "{:,}".format(r.search_volume) if r.search_volume > 0 else 0 }}</td>
            <td><b style="color:#d9534f;">{{ r.seller_count }}</b></td>
            <td><span style="color: {{ 'blue' if 'A' in r.grade else 'black' }}; font-weight:bold;">{{r.grade}}</span></td>
            <td style="color: gray; font-size: 0.9em;">{{r.reason}}</td>
            <td><a href="{{r.link}}" target="_blank">확인하기</a></td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}

    <script>
        // 1. 실시간 입력 건수 세기 로직
        const textarea = document.getElementById('keywordInput');
        const countDisplay = document.getElementById('countDisplay');

        function updateCount() {
            // 빈 줄을 제외하고 실제 글자가 있는 줄만 카운트
            const lines = textarea.value.split('\\n').filter(line => line.trim() !== '');
            countDisplay.textContent = lines.length;
        }

        // 입력할 때마다 숫자 업데이트
        textarea.addEventListener('input', updateCount);
        // 페이지 로딩 시 초기 숫자 세팅
        window.addEventListener('DOMContentLoaded', updateCount);

        // 2. 엑셀(CSV) 다운로드 로직
        function downloadExcel() {
            let csv = '\\uFEFF'; // 한글 깨짐 방지용 BOM
            let rows = document.querySelectorAll("#resultTable tr");
            
            for (let i = 0; i < rows.length; i++) {
                let row = [], cols = rows[i].querySelectorAll("td, th");
                
                for (let j = 0; j < cols.length; j++) {
                    let data = "";
                    // 링크 칼럼(<a>태그)일 경우 '확인하기' 대신 실제 URL 주소를 추출
                    if (cols[j].querySelector("a")) {
                        data = cols[j].querySelector("a").href;
                    } else {
                        data = cols[j].innerText.replace(/"/g, '""'); // 따옴표 처리
                    }
                    row.push('"' + data + '"');
                }
                csv += row.join(",") + "\\n";
            }
            
            // CSV 파일 생성 및 다운로드 실행
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

@app.route("/", methods=["GET", "POST"])
def home():
    results = []
    keywords_text = ""
    if request.method == "POST":
        keywords_text = request.form.get("keywords", "")
        keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
        
        for keyword in keywords:
            results.append(analyze_book(keyword))
            time.sleep(0.5) 

        # 3. A등급 우선 정렬 로직 (알파벳 순 정렬: 'A'가 'B'보다 무조건 앞섬)
        results.sort(key=lambda x: x['grade'])

    return render_template_string(TEMPLATE, results=results, keywords=keywords_text)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
