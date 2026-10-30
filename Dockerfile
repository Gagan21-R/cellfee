# CELLFEE web app: story page (/), dashboard (/dashboard/), API (/api/...).  Listens on $PORT (default 7860).
# Build:  docker build -t cellfee .      Run:  docker run -p 7860:7860 --env-file .env cellfee
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUTF8=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=7860 CELLFEE_WARM_OCR=0
# libgl1 / libglib2.0-0: OpenCV (report OCR); libgomp1: XGBoost
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .
COPY --from=web /app/frontend/dist ./frontend/dist
# run as a normal user that can write the marketplace database and evidence records
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user
EXPOSE 7860
WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn cellfee.api:app --host 0.0.0.0 --port ${PORT}"]
