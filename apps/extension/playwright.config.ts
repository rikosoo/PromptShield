import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 45_000,
  expect: { timeout: 15_000 },   // a 1ª leitura da política gerenciada leva ~3 s
  workers: 1,               // um Chromium com a extensão por teste; sem paralelismo para não disputar portas
  reporter: [["list"]],
});
