# UNTESTED (no Docker on the dev machine). Build context is the repo root.
FROM node:22-slim
WORKDIR /app
COPY contracts /contracts
COPY m1_ledger/gateway/package*.json /app/
RUN npm ci --omit=dev
COPY m1_ledger/gateway/src /app/src
ENV CONTRACTS_DIR=/contracts
EXPOSE 8004
CMD ["node", "src/main.ts"]
