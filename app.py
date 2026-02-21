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

    # 2. 화면 크롤링 (Railway 봇 차단 우회를 위해 '모바일' 환경으로 위장 접속)
    pc_link = f"https://search.naver.com/search.naver?where=nexearch&query={urllib.parse.quote(keyword)}"
    scrape_url = f"https://m.search.naver.com/search.naver?where=m&query={urllib.parse.quote(keyword)}"
    grade = ""
    reason = ""
    seller_count = 0

    try:
        # 최신 안드로이드 스마트폰 크롬 브라우저로 완벽 위장
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://m.naver.com/"
        }
        html_res = requests.get(scrape_url, headers=req_headers, timeout=5)
        soup = BeautifulSoup(html_res.text, "html.parser")
        page_text = soup.get_text(separator=" ", strip=True)

        # 네이버가 봇을 감지하고 차단 화면을 띄웠는지 확인
        if "비정상적인 인터넷 환경" in page_text or "자동 입력 방지" in page_text or "캡차" in page_text:
            grade = "오류"
            reason = "서버 IP 네이버 차단됨 (모바일 우회 실패)"
        else:
            # 모바일 도서 영역 찾기
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
                # 책 관련 필수 단어가 있는지 한 번 더 교차 검증 (뉴스 기사 등 오탐 방지)
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
        "link": pc_link # 엑셀 다운로드나 클릭 시에는 보기 편한 PC 화면으로 이동
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
        .btn { padding: 10px 20px; font-weight: bold; cursor: pointer; margin-right: 10px; }
        .btn-excel { background-color: #28a745; color: white; border: none; border-radius: 5px; }
        .btn-submit { background-color: #007bff; color: white; border: none; border-radius: 5px; }
        select { padding: 9px; font-size: 15px; border-radius: 5px; margin-right: 10px; }
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
            
            <div style="display: flex; align-items: center; margin-top: 10px;">
                <select name="sort_option">
                    <option value="original" {% if sort_option == 'original' %}selected{% endif %}>입력 순서대로 (원본)</option>
                    <option value="grade" {% if sort_option == 'grade' %}selected{% endif %}>A등급 우선 정렬 (A순서)</option>
                </select>
                <button type="submit" class="btn btn-submit">일괄 분석 시작</button>
            </div>
        </form>
    </div>

    {% if results %}
    <hr>
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <h3>분류 결과</h3>
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
            <td><span style="color: {{ 'blue' if 'A' in r.grade else 'red' if r.grade == '오류' else 'black' }}; font-weight:bold;">{{r.grade}}</span></td>
            <td style="color: gray; font-size: 0.9em;">{{r.reason}}</td>
            <td><a href="{{r.link}}" target="_blank">확인하기</a></td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}

    <script>
        const textarea = document.getElementById('keywordInput');
        const countDisplay = document.getElementById('countDisplay');

        function updateCount() {
            const lines = textarea.value.split('\\n').filter(line => line.trim() !== '');
            countDisplay.textContent = lines.length;
        }

        textarea.addEventListener('input', updateCount);
        window.addEventListener('DOMContentLoaded', updateCount);

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

@app.route("/", methods=["GET", "POST"])
def home():
    results = []
    keywords_text = ""
    sort_option = "original"
    
    if request.method == "POST":
        keywords_text = request.form.get("keywords", "")
        sort_option = request.form.get("sort_option", "original") 
        keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
        
        for keyword in keywords:
            results.append(analyze_book(keyword))
            time.sleep(0.6) # 모바일 봇 탐지 회피를 위해 0.1초 미세 조정

        if sort_option == "grade":
            results.sort(key=lambda x: x['grade'])

    return render_template_string(
        TEMPLATE, 
        results=results, 
        keywords=keywords_text,
        sort_option=sort_option 
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
