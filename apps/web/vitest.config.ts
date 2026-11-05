import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./", import.meta.url)) } },
  test: { include: ["lib/**/*.test.ts"], environment: "node" },   // os testes ponta a ponta (Playwright) ficam em tests/e2e
});
