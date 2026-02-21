from flask import Flask, request, render_template_string, Response, stream_with_context
import requests
import re
import urllib.parse
import time
import random
import os

app = Flask(__name__)

# Railway 환경변수에서 API 키 가져오기
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

HEADERS = {
    "X-Naver-Client-Id": NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
}

HTML_HEAD = """
<!DOCTYPE html>
<html>
<head>
    <title>Book 통합 분석기 Pro</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; padding: 20px; background-color: #f4f7f6; }
        .container { max-width: 1100px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
        textarea { width: 100%; border: 1.5px solid #ddd; border-radius: 8px; padding: 15px; font-size: 14px; margin-bottom: 10px; }
        button { background-color: #03c75a; color: white; border: none; padding: 12px 25px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .status { margin: 20px 0; padding: 15px; background: #e8f5e9; border-left: 5px solid #03c75a; border-radius: 4px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background: white; }
        th, td { border: 1px solid #eee; padding: 15px; text-align: center; }
        th { background-color: #f8f9fa; color: #555; font-weight: 600; }
        .grade-a { color: #2ecc71; font-weight: bold; background: #f0fff4; }
        .grade-b { color: #e74c3c; font-weight: bold; }
        a { color: #03c75a; text-decoration: none; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 Book 통합 분석기</h1>
        <form method="POST">
            <textarea name="keywords" rows="8" placeholder="책 제목들을 입력하세요 (엔터로 구분)">{{keywords}}</textarea><br>
            <button type="submit">일괄 검색 및 분류 시작</button>
        </form>
"""

def get_naver_data(keyword):
    """네이버 도서 API를 사용하여 정확한 검색량과 링크를 가져옵니다."""
    encoded_query = urllib.parse.quote(keyword)
    # 검색량(total)을 알기 위해 도서 검색 API 사용
    url = f"https://openapi.naver.com/v1/search/book.json?query={encoded_query}&display=1"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            total_count = data.get("total", 0) # 이것이 진짜 '총검색량'입니다.
            
            # 등급 분류 로직: 
            # 검색량이 100개 미만이면 경쟁이 적은 A등급, 그 이상은 B등급 (기준은 수정 가능)
            # 혹은 도서 정보가 아예 없으면 A등급
            grade = "A" if total_count < 100 else "B"
            
            # 실제 네이버 검색창 링크
            search_link = f"https://search.naver.com/search.naver?where=nexearch&query={encoded_query}"
            
            return {
                "keyword": keyword,
                "search_volume": total_count,
                "seller_count": "-", # API로는 판매처 수를 정확히 알기 어렵지만 필요시 크롤링 병행 가능
                "grade": grade,
                "link": search_link
            }
    except Exception as e:
        print(f"Error: {e}")
    
    return {"keyword": keyword, "search_volume": 0, "seller_count": 0, "grade": "B", "link": "#"}

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "GET":
        return render_template_string(HTML_HEAD + "</div></body></html>", keywords="")

    keywords_text = request.form.get("keywords", "")
    keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
    
    def generate():
        yield HTML_HEAD.replace("{{keywords}}", keywords_text)
        yield f'<div id="progress" class="status">전체 {len(keywords)}권 분석 중...</div>'
        yield '<table><tr><th>키워드</th><th>총검색량</th><th>판매처</th><th>등급</th><th>링크</th></tr>'
        
        for i, keyword in enumerate(keywords):
            res = get_naver_data(keyword)
            
            grade_class = "grade-a" if res['grade'] == "A" else "grade-b"
            
            yield f"""
            <tr>
                <td>{res['keyword']}</td>
                <td>{res['search_volume']:,}</td>
                <td>{res['seller_count']}</td>
                <td class="{grade_class}">{res['grade']}</td>
                <td><a href="{res['link']}" target="_blank">열기</a></td>
            </tr>
            """
            # 실시간 진행상황 업데이트
            yield f"<script>document.getElementById('progress').innerHTML = '진행 상황: {i+1} / {len(keywords)} 완료';</script>"
            time.sleep(0.1) # API는 크롤링보다 빨라도 되지만 안정성을 위해 약간 대기
            
        yield "</table></div></body></html>"

    return Response(stream_with_context(generate()))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
