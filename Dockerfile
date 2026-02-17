FROM python:3.11-slim

# Chromium 설치
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# 여기 중요 👇
CMD sh -c "gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --timeout 600"
