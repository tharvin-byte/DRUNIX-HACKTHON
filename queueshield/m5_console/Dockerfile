# UNTESTED (no Docker on the dev machine). Build context is the repo root.
FROM node:22-slim AS build
WORKDIR /app
COPY contracts /contracts
COPY m5_console/package*.json /app/m5_console/
RUN cd m5_console && npm ci
COPY m5_console /app/m5_console
RUN cd m5_console && npx vite build
FROM node:22-slim
WORKDIR /app
COPY --from=build /app/m5_console /app/m5_console
WORKDIR /app/m5_console
EXPOSE 8000
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "8000"]
