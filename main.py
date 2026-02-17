from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import os

app = FastAPI()

job = {
    "total": 0,
    "done": 0,
    "results": [],
    "start_time": None
}

class InputData(BaseModel):
    keywords: list[str]


def check_seller_count(keyword):
    url = "https://search.shopping.naver.com/search/all"
    params = {"query": keyword}

    try:
        res = requests.get(url, params=params, timeout=10)
        html = res.text
        soup = BeautifulSoup(html, "html.parser")
    except:
        return keyword, 0, "B"

    text = soup.get_text()

    seller_count = 0

    # 판매처 숫자 탐지
    import re
    matches = re.findall(r"판매처\s?(\d+)", text)

    if matches:
        seller_count = int(matches[0])

    if seller_count == 0:
        grade = "A"
    else:
        grade = "B"

    return keyword, seller_count, grade


def run_job(keywords):
    job["total"] = len(keywords)
    job["done"] = 0
    job["results"] = []
    job["start_time"] = time.time()

    for kw in keywords:
        result = check_seller_count(kw)
        job["results"].append(result)
        job["done"] += 1


@app.post("/start")
def start(data: InputData, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_job, data.keywords)
    return {"status": "started"}


@app.get("/progress")
def progress():
    total = job["total"]
    done = job["done"]

    if done == 0:
        remaining = 0
    else:
        elapsed = time.time() - job["start_time"]
        avg = elapsed / done
        remaining = int(avg * (total - done))

    return {
        "total": total,
        "done": done,
        "remaining_seconds": remaining
    }


@app.get("/results")
def results(order: str = "original"):
    data = job["results"]

    if order == "A":
        data = sorted(data, key=lambda x: (x[2] != "A", x[1]))

    return data


@app.get("/download")
def download(order: str = "original"):
    data = job["results"]

    if order == "A":
        data = sorted(data, key=lambda x: (x[2] != "A", x[1]))

    df = pd.DataFrame(data, columns=["키워드", "판매처수", "분류"])
    file_path = "result.xlsx"
    df.to_excel(file_path, index=False)

    return FileResponse(file_path)
