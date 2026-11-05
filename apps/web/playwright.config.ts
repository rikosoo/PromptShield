import { defineConfig } from "@playwright/test";

const API = 8099, WEB = 3099;
const py = process.env.PS_PYTHON ?? "../../.venv/bin/python";

// Pré-requisito: `npm run build`. Usa DATABASE_URL_TEST (banco de TESTE: é apagado e recriado) e CHROMIUM_PATH.
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${WEB}`, launchOptions: { executablePath: process.env.CHROMIUM_PATH || undefined } },
  webServer: [
    { command: `${py} ../api/scripts/e2e_stack.py --port ${API}`, url: `http://127.0.0.1:${API}/health`, timeout: 180_000, reuseExistingServer: false, stdout: "pipe" },
    {
      command: `npx next start -p ${WEB}`, url: `http://127.0.0.1:${WEB}/login`, timeout: 60_000, reuseExistingServer: false,
      env: { API_INTERNAL_URL: `http://127.0.0.1:${API}`, AUTH_MODE: "mock", PUBLIC_BASE_URL: `http://127.0.0.1:${WEB}` },
    },
  ],
});
