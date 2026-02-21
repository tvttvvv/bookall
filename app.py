from flask import Flask, request, render_template_string, Response, stream_with_context
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
import time
import random
import os

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9"
}

# HTML 템플릿 수정: '결과수' -> '총검색량'
HTML_HEAD = """
<!DOCTYPE html>
<html>
<head>
    <title>Book 통합 분석기</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; padding: 20px; background-color: #f8f9fa; }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        textarea { width: 100%; border: 1px solid #ddd; border-radius: 5px; padding: 10px; resize: vertical; }
        button { background-color: #03c75a; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #eee; padding: 12px; text-align: left; }
        th { background-color: #f4f4f4; color: #333; }
        .grade-a { color: #2ecc71; font-weight: bold; } /* A등급: 초록색 */
        .grade-b { color: #e74c3c; font-weight: bold; } /* B등급: 빨간색 */
        .status { margin-bottom: 15px; padding: 15px; background: #e7f3ff; border-left: 5px solid #2b82d9; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 Book 통합 분석기</h1>
        <form method="POST">
            <textarea name="keywords" rows="8" placeholder="책 제목을 한 줄에 하나씩 입력하세요">{{keywords}}</textarea><br><br>
            <button type="submit">일괄 분류 시작</button>
        </form>
        <hr>
"""

def extract_search_volume(soup):
    """네이버 검색 결과 수(총검색량) 추출 로직 개선"""
    try:
        # 네이버의 다양한 검색 결과 숫자 표시 영역 탐색
        selectors = [
            ".title_area .num", 
            ".api_txt_lines.total_area .num",
            ".sp_ntotal .num",
            ".search_number"
        ]
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text()
                match = re.search(r'([\d,]+)', text)
                if match:
                    return int(match.group(1).replace(",", ""))
    except:
        pass
    return 0

def extract_seller_count(soup):
    """판매처 개수 추출 로직 개선"""
    seller_total = 0
    has_card = False
    
    # 네이버 쇼핑 및 도서 섹션 특정
    # '쇼핑' 혹은 '도서' 검색 결과가 있는지 확인
    shop_section = soup.select_one(".api_subject_bx, .shop_pack, .book_section")
    
    if shop_section:
        text = shop_section.get_text(" ", strip=True)
        # '판매처 123' 또는 '판매 123' 패턴 매칭
        matches = re.findall(r'(?:판매처|판매)\s*([\d,]+)', text)
        if matches:
            has_card = True
            for m in matches:
                seller_total += int(m.replace(",", ""))
        elif "네이버 쇼핑" in text or "도서" in text:
            # 판매처 숫자는 없지만 쇼핑/도서 영역이 명확히 존재하는 경우
            has_card = True
            
    return seller_total, has_card

def analyze_keyword(keyword):
    encoded = urllib.parse.quote(keyword)
    # nexearch(통합검색) 대신 shop(쇼핑) 검색이 판매처 확인에 더 정확할 수 있으나, 
    # 요구사항에 맞춰 통합검색을 유지하되 패턴을 강화함
    url = f"https://search.naver.com/search.naver?where=nexearch&query={encoded}"
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        search_volume = extract_search_volume(soup)
        seller_count, has_card = extract_seller_count(soup)

        # 등급 판정 로직 수정 (보수적 판정)
        # 판매처가 아예 없고, 쇼핑 카드조차 발견되지 않아야 A등급
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
        return {"keyword": f"{keyword}(에러)", "search_volume": 0, "seller_count": 0, "grade": "B", "link": url}

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "GET":
        return render_template_string(HTML_HEAD + "</div></body></html>", keywords="")

    keywords_text = request.form.get("keywords", "")
    keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
    
    def generate():
        yield HTML_HEAD.replace("{{keywords}}", keywords_text)
        yield '<div id="progress" class="status">데이터 수집을 시작합니다...</div>'
        yield '<table><tr><th>키워드</th><th>총검색량</th><th>판매처</th><th>등급</th><th>링크</th></tr>'
        
        total = len(keywords)
        for i, keyword in enumerate(keywords):
            result = analyze_keyword(keyword)
            
            grade_class = "grade-a" if result['grade'] == "A" else "grade-b"
            # 결과 숫자 0일 때 가독성을 위해 쉼표 포맷팅 적용
            vol_display = format(result['search_volume'], ',')
            
            yield f"""
            <tr>
                <td>{result['keyword']}</td>
                <td>{vol_display}</td>
                <td>{result['seller_count']}</td>
                <td class="{grade_class}">{result['grade']}</td>
                <td><a href="{result['link']}" target="_blank">열기</a></td>
            </tr>
            """
            yield f"<script>document.getElementById('progress').innerHTML = '진행 상황: {i+1} / {total} 완료';</script>"
            time.sleep(random.uniform(1.2, 2.5)) # 차단 방지 대기
            
        yield "</table></div></body></html>"

    return Response(stream_with_context(generate()))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
