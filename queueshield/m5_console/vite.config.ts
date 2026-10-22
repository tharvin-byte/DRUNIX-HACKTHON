import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The console reads ../contracts/fixtures for MOCK fallback, so the dev server may serve the parent folder.
export default defineConfig({
  plugins: [react()],
  server: { port: 8000, host: "127.0.0.1", fs: { allow: [".."] } },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
