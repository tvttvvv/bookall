from flask import Flask, request, render_template_string, Response, stream_with_context
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
import time
import random

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9"
}

# 상단 디자인 및 테이블 시작 부분
HTML_HEAD = """
<!DOCTYPE html>
<html>
<head>
    <title>Book 통합 분석기</title>
    <style>
        body { font-family: sans-serif; padding: 20px; line-height: 1.6; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background-color: #f4f4f4; }
        .grade-a { color: blue; font-weight: bold; }
        .grade-b { color: red; }
        .status { margin-bottom: 10px; padding: 10px; background: #e7f3ff; border-radius: 5px; }
    </style>
</head>
<body>
    <h1>📚 Book 통합 분석기</h1>
    <form method="POST">
        <textarea name="keywords" rows="10" cols="70" placeholder="책 제목을 한 줄에 하나씩 입력하세요">{{keywords}}</textarea><br><br>
        <button type="submit">일괄 분류 시작</button>
    </form>
    <hr>
"""

def extract_search_volume(soup):
    try:
        # 네이버 검색 결과 수 추출 (정확한 검색량은 API가 필요하지만, 웹 결과 수로 대체하는 로직)
        total = soup.select_one(".title_area .num, .sp_ntotal .num, .total_area .num")
        if total:
            text = total.get_text()
            match = re.search(r'([\d,]+)', text)
            if match:
                return int(match.group(1).replace(",", ""))
    except:
        pass
    return 0

def extract_seller_count(soup):
    seller_total = 0
    has_card = False
    
    # 네이버 쇼핑/도서 영역 감지
    card = soup.select_one(".api_subject_bx, .book_section, .shop_pack")
    if card:
        has_card = True
        text = card.get_text(" ", strip=True)
        # '판매처 123' 형태의 텍스트 추출
        matches = re.findall(r'판매처\s*([\d,]+)', text)
        for m in matches:
            seller_total += int(m.replace(",", ""))
    
    return seller_total, has_card

def analyze_keyword(keyword):
    encoded = urllib.parse.quote(keyword)
    url = f"https://search.naver.com/search.naver?where=nexearch&query={encoded}"
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status() # HTTP 에러 발생 시 예외 처리
        soup = BeautifulSoup(res.text, "html.parser")

        search_volume = extract_search_volume(soup)
        seller_count, has_card = extract_seller_count(soup)

        # 등급 판정 로직 보완
        if seller_count == 0 and not has_card:
            grade = "A"
        else:
            grade = "B"

        return {
            "keyword": keyword,
            "search_volume": search_volume,
            "seller_count": seller_count,
            "grade": grade,
            "link": url
        }
    except Exception as e:
        return {
            "keyword": f"{keyword} (에러: {str(e)})",
            "search_volume": 0,
            "seller_count": 0,
            "grade": "-",
            "link": url
        }

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "GET":
        return render_template_string(HTML_HEAD + "</body></html>", keywords="")

    keywords_text = request.form.get("keywords", "")
    keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
    
    # 실시간 응답을 위한 제너레이터 함수
    def generate():
        yield HTML_HEAD.replace("{{keywords}}", keywords_text)
        yield '<div id="progress" class="status">분석 시작 중...</div>'
        yield '<table><tr><th>키워드</th><th>결과수</th><th>판매처</th><th>등급</th><th>링크</th></tr>'
        
        total = len(keywords)
        for i, keyword in enumerate(keywords):
            result = analyze_keyword(keyword)
            
            # 한 줄씩 표에 추가 (HTML 스트리밍)
            grade_class = "grade-a" if result['grade'] == "A" else "grade-b"
            row = f"""
            <tr>
                <td>{result['keyword']}</td>
                <td>{result['search_volume']:,}</td>
                <td>{result['seller_count']}</td>
                <td class="{grade_class}">{result['grade']}</td>
                <td><a href="{result['link']}" target="_blank">열기</a></td>
            </tr>
            """
            yield row
            
            # 진행 상태 업데이트 (자바스크립트 사용)
            progress_script = f"<script>document.getElementById('progress').innerHTML = '진행 상황: {i+1} / {total} 완료 (남은 개수: {total-(i+1)})';</script>"
            yield progress_script
            
            # 네이버 차단 방지를 위한 랜덤 대기
            time.sleep(random.uniform(1.0, 2.0))
            
        yield "</table><p>모든 분석이 완료되었습니다.</p></body></html>"

    return Response(stream_with_context(generate()))

if __name__ == "__main__":
    # Railway 등 배포 환경을 위한 포트 설정
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
