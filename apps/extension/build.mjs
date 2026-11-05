// Uso: node build.mjs [--dev | --sideload]
//  --sideload -> dist/sideload : instalação por sensor (carregar sem compactação): só chatgpt.com e claude.ai, lê promptshield-config.json
//                                gravado pelo sensor na própria pasta, aceita API em http (teste), ID da extensão FIXO (chave pública no manifesto)
//  produção -> dist/prod : só chatgpt.com e claude.ai, só configuração gerenciada, API apenas em https
//  --dev    -> dist/dev  : acrescenta página local de teste (127.0.0.1/localhost), configuração em storage.local e API em http
import { build } from "esbuild";
import { copyFileSync, mkdirSync, rmSync, writeFileSync, readFileSync } from "node:fs";

const dev = process.argv.includes("--dev");
const sideload = process.argv.includes("--sideload");
const out = dev ? "dist/dev" : sideload ? "dist/sideload" : "dist/prod";
const version = JSON.parse(readFileSync("package.json", "utf8")).version;
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

await build({
  entryPoints: { background: "src/background.ts", content: "src/content.ts" },
  outdir: out,
  bundle: true,
  format: "iife",
  target: "chrome116",
  minify: !dev,
  sourcemap: dev,
  define: { __DEV__: String(dev), __SIDELOAD__: String(sideload) },
  logLevel: "warning",
});

const matches = ["https://chatgpt.com/*", "https://claude.ai/*", "https://gemini.google.com/*", "https://copilot.microsoft.com/*", "https://copilot.com/*"];
if (dev) matches.push("http://127.0.0.1/*", "http://localhost/*");

const manifest = {
  manifest_version: 3,
  name: dev ? "PromptShield (desenvolvimento)" : sideload ? "PromptShield (instalado pelo sensor)" : "PromptShield",
  version,
  description: "Monitora, com aviso visível, prompts enviados a ferramentas de IA nos domínios definidos pela empresa.",
  minimum_chrome_version: "116",
  permissions: ["storage", "identity", "identity.email", "alarms"],
  background: { service_worker: "background.js" },
  content_scripts: [{ matches, js: ["content.js"], run_at: "document_start", all_frames: false }],
  storage: { managed_schema: "managed_schema.json" },
};
if (sideload) manifest.key = readFileSync("sideload-public-key.txt", "utf8").trim();   // ID fixo: o servidor libera o CORS desta origem
writeFileSync(`${out}/manifest.json`, JSON.stringify(manifest, null, 2) + "\n");
copyFileSync("managed_schema.json", `${out}/managed_schema.json`);
console.log(`extensão ${dev ? "de desenvolvimento" : sideload ? "do sensor (sideload)" : "de produção"} em ${out}`);
