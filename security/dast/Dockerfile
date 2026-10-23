# CI-only image: deliberately does not copy data/, config files or user workspaces.
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY lib/ lib/
COPY tools/ tools/
COPY services/ services/
COPY transport/ transport/
COPY evals/ evals/
COPY templates/ templates/
COPY server.py tools.json ./
COPY --from=frontend /frontend/dist frontend/dist/
COPY security/dast/start.py /app/dast_start.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/sandbox
USER 10001:10001
CMD ["python", "/app/dast_start.py"]
