import os
import time
import random
import hmac
import hashlib
import base64
import requests
import urllib.parse
from flask import Flask, request, render_template_string, Response, stream_with_context

app = Flask(__name__)

# Railway 환경변수 설정 확인
ACCESS_KEY = os.environ.get("ACCESS_KEY")
SECRET_KEY = os.environ.get("SECRET_KEY")
CUSTOMER_ID = os.environ.get("CUSTOMER_ID")

# 광고 API 인증 헤더 생성 함수
def get_header(method, uri, api_key, secret_key, customer_id):
    timestamp = str(int(time.time() * 1000))
    signature = hmac.new(
        secret_key.encode(),
        f"{timestamp}.{method}.{uri}".encode(),
        hashlib.sha256
    ).digest()
    
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Timestamp": timestamp,
        "X-API-KEY": api_key,
        "X-Customer": str(customer_id),
        "X-Signature": base64.b64encode(signature).decode()
    }

def get_real_search_volume(keyword):
    """네이버 검색광고 API를 사용하여 실제 월간 검색량을 가져옵니다."""
    uri = '/keywordstool'
    method = 'GET'
    params = {'hintKeywords': keyword, 'showDetail': '1'}
    
    try:
        headers = get_header(method, uri, ACCESS_KEY, SECRET_KEY, CUSTOMER_ID)
        full_url = f"https://api.naver.com{uri}?hintKeywords={urllib.parse.quote(keyword)}&showDetail=1"
        
        res = requests.get(full_url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            if data.get('keywordList'):
                # 입력한 키워드와 정확히 일치하는 데이터 찾기
                target = data['keywordList'][0]
                # PC + 모바일 검색량 합산 (숫자가 '10미만'으로 올 경우 대비)
                pc_vol = target.get('monthlyPcQcCnt', 0)
                mo_vol = target.get('monthlyMobileQcCnt', 0)
                
                # '10미만' 텍스트 처리
                pc_vol = 5 if str(pc_vol) == '< 10' else int(pc_vol)
                mo_vol = 5 if str(mo_vol) == '< 10' else int(mo_vol)
                
                total_vol = pc_vol + mo_vol
                return total_vol
    except Exception as e:
        print(f"API Error: {e}")
    return 0

# --- UI 및 서버 로직 ---

HTML_HEAD = """
<!DOCTYPE html>
<html>
<head>
    <title>Book 통합 분석기 PRO</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; padding: 20px; background-color: #f0f2f5; }
        .container { max-width: 1100px; margin: 0 auto; background: white; padding: 30px; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        textarea { width: 100%; border: 2px solid #ddd; border-radius: 10px; padding: 15px; font-size: 15px; margin-bottom: 10px; box-sizing: border-box; }
        button { background-color: #03c75a; color: white; border: none; padding: 15px 30px; border-radius: 10px; cursor: pointer; font-size: 16px; font-weight: bold; width: 100%; }
        .status { margin: 20px 0; padding: 15px; background: #e7f3ff; border-left: 5px solid #2b82d9; border-radius: 5px; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border-bottom: 1px solid #eee; padding: 15px; text-align: center; }
        th { background-color: #f8f9fa; color: #333; }
        .grade-a { color: #2ecc71; font-weight: bold; }
        .grade-b { color: #e74c3c; font-weight: bold; }
        .link-btn { display: inline-block; padding: 5px 10px; background: #eee; border-radius: 5px; text-decoration: none; color: #333; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 실시간 검색량 기반 분석기</h1>
        <form method="POST">
            <textarea name="keywords" rows="6" placeholder="분석할 책 제목들을 입력하세요">{{keywords}}</textarea>
            <button type="submit">실제 검색량 일괄 조회</button>
        </form>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "GET":
        return render_template_string(HTML_HEAD + "</div></body></html>", keywords="")

    keywords_text = request.form.get("keywords", "")
    keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]

    def generate():
        yield HTML_HEAD.replace("{{keywords}}", keywords_text)
        yield f'<div id="progress" class="status">네이버 광고 API 데이터 수집 중...</div>'
        yield '<table><tr><th>키워드</th><th>월간 총검색량</th><th>분류</th><th>링크</th></tr>'
        
        for i, keyword in enumerate(keywords):
            volume = get_real_search_volume(keyword)
            
            # 등급 분류 로직 (예: 검색량 500 미만은 경쟁력 있는 A, 그 이상은 B)
            grade = "A" if 0 < volume < 500 else "B"
            grade_class = "grade-a" if grade == "A" else "grade-b"
            
            search_link = f"https://search.naver.com/search.naver?query={urllib.parse.quote(keyword)}"
            
            yield f"""
            <tr>
                <td>{keyword}</td>
                <td>{format(volume, ',')}</td>
                <td class="{grade_class}">{grade}</td>
                <td><a href="{search_link}" class="link-btn" target="_blank">검색결과</a></td>
            </tr>
            """
            yield f"<script>document.getElementById('progress').innerHTML = '분석 완료: {i+1} / {len(keywords)}건';</script>"
            time.sleep(0.2) # API 속도 조절
            
        yield "</table></div></body></html>"

    return Response(stream_with_context(generate()))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
