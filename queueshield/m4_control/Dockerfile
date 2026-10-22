# UNTESTED (no Docker on the dev machine). Build context is the repo root so contracts/ can be copied in.
FROM python:3.11-slim
WORKDIR /app
COPY contracts /contracts
COPY m4_control/pyproject.toml /app/
COPY m4_control/qctl /app/qctl
COPY m4_control/config /app/config
RUN pip install --no-cache-dir . && pip install --no-cache-dir httpx-sse
ENV CONTRACTS_DIR=/contracts
EXPOSE 8003
CMD ["uvicorn", "--factory", "qctl.api:create_app", "--host", "0.0.0.0", "--port", "8003"]
