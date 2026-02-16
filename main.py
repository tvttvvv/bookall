import os
import hashlib
import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")


@app.get("/")
def root():
    return {"message": "📚 bookall Python 통합 서버 정상 작동중"}


# ------------------------------
# 네이버 도서 검색
# ------------------------------
def search_books(keyword: str):
    url = "https://openapi.naver.com/v1/search/book.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": keyword,
        "display": 5
    }

    response = requests.get(url, headers=headers, params=params)
    return response.json().get("items", [])


# ------------------------------
# 검색량 (현재는 해시 기반 안정적 값)
# ------------------------------
def get_search_volume(keyword: str):
    hash_object = hashlib.md5(keyword.encode())
    seed = int(hash_object.hexdigest()[:8], 16)

    pc = (seed % 4000) + 500
    mobile = (seed % 6000) + 1000

    return pc + mobile


# ------------------------------
# 판매처 개수 (현재 기본값)
# ------------------------------
def get_store_count():
    return 3


# ------------------------------
# 통합 검색 API
# ------------------------------
@app.get("/search")
def search(keyword: str = Query(...)):

    books = search_books(keyword)

    results = []

    for item in books:
        clean_title = item["title"].replace("<b>", "").replace("</b>", "")

        total = get_search_volume(clean_title)
        store_count = get_store_count()

        results.append({
            "title": clean_title,
            "total": total,
            "storeCount": store_count,
            "category": item.get("category", "기타"),
            "link": item.get("link")
        })

    return results
