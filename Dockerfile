FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UPLOAD_DIR=/app/uploads \
    LOG_DIR=/app/logs

# cryptography/PyMySQL 등 네이티브 확장 빌드용. 빌드 후 apt 캐시는 지운다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# 루트가 아닌 사용자로 실행한다.
RUN useradd --create-home --shell /bin/false stockflow \
    && mkdir -p /app/uploads /app/logs \
    && chown -R stockflow:stockflow /app
USER stockflow

EXPOSE 51000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-51000}/health" || exit 1

# run.py 는 waitress(프로덕션 WSGI 서버)로 기동한다. Flask 개발 서버는 FLASK_DEBUG=1 일 때만.
CMD ["python", "run.py"]
