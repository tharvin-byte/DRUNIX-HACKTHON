# UNTESTED (no Docker on the dev machine). Build context is the repo root so contracts/ can be copied in.
FROM python:3.11-slim
WORKDIR /app
COPY contracts /contracts
COPY m2_simulator/pyproject.toml /app/
COPY m2_simulator/qsim /app/qsim
COPY m2_simulator/config /app/config
RUN pip install --no-cache-dir .
ENV CONTRACTS_DIR=/contracts
EXPOSE 8001
CMD ["uvicorn", "--factory", "qsim.api:create_app", "--host", "0.0.0.0", "--port", "8001"]
