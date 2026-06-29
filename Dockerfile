FROM python:3.9-slim

WORKDIR /app

# 必要な依存関係 + ffmpeg をまとめてインストール
RUN apt-get update && apt-get install -y \
    mecab libmecab-dev mecab-ipadic-utf8 build-essential \
    curl xz-utils file autoconf automake libtool pkg-config \
    ffmpeg \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

ENV SSL_CERT_FILE=/usr/local/lib/python3.9/site-packages/certifi/cacert.pem

COPY . .

CMD ["python", "-u", "app.py"]
