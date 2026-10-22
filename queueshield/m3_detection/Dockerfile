# UNTESTED (no Docker on the dev machine). Build context is the repo root so contracts/ can be copied in.
FROM python:3.11-slim
WORKDIR /app
COPY contracts /contracts
COPY m3_detection/pyproject.toml /app/
COPY m3_detection/qdet /app/qdet
COPY m3_detection/config /app/config
RUN pip install --no-cache-dir . && pip install --no-cache-dir httpx-sse
ENV CONTRACTS_DIR=/contracts
EXPOSE 8002
CMD ["uvicorn", "--factory", "qdet.api:create_app", "--host", "0.0.0.0", "--port", "8002"]
