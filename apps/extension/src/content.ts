/**
 * Content script. Só age em domínios configurados. Lê o texto APENAS no momento do envio
 * (Enter ou clique em enviar); nunca tecla por tecla, nunca em outros sites.
 */
import { createTracker, infoOf } from "./attachments";
import { failurePlan, planFor, type Plan } from "./decision";
import { readText, writeText } from "./editor";
import { siteFor } from "./sites";
import type { SiteModule } from "./sites/types";
import { hostMatches } from "./config";
import { setIndicator, showIndicator, showPlan, uiHost } from "./ui";
import { INSPECTION_STOPPED, type ApiResult, type PublicConfig, type Request, type Response } from "./types";

function send<T>(msg: Request): Promise<Response<T>> {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(msg, (r: Response<T> | undefined) => {
        resolve(r ?? { ok: false, error: chrome.runtime.lastError?.message ?? "sem resposta da extensão" });
      });
    } catch (e) {
      resolve({ ok: false, error: e instanceof Error ? e.message : String(e) });
    }
  });
}

const HEALTH_MS = __DEV__ ? 400 : 5000;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function start(): Promise<void> {
  const site = siteFor(location.hostname);
  if (!site) return; // site sem módulo: a extensão não faz nada

  // Os ouvintes entram já; a configuração pode demorar alguns segundos na primeira leitura da política gerenciada.
  // Enquanto não se sabe se o domínio é monitorado, um envio fica retido até a resposta (nunca passa sem decisão).
  let active: boolean | null = null;
  let cfg: PublicConfig = { configured: false, domains: [], failMode: "open" };
  const ready = send<PublicConfig>({ type: "getPublicConfig" }).then((res) => {
    active = res.ok && hostMatches(location.hostname, res.data.domains);
    if (res.ok) cfg = res.data;
    if (active) {
      showIndicator(cfg.policyUrl);
      if (!cfg.configured) setIndicator("warning", "PromptShield: sem configuração da empresa; nada é enviado.");
      watchHealth(site);
    }
  });

  let bypass = false;
  let busy = false;
  const files = createTracker();

  async function submit(): Promise<void> {
    bypass = true;
    try {
      const deadline = Date.now() + 1500;
      let btn = site!.findSend(document);
      while (btn && (btn as HTMLButtonElement).disabled && Date.now() < deadline) {
        await sleep(50);
        btn = site!.findSend(document);
      }
      if (btn) btn.click();
      else site!.findInput(document)?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      await sleep(0);
    } finally {
      setTimeout(() => (bypass = false), 300);
    }
  }

  async function guard(input: HTMLElement): Promise<void> {
    busy = true;
    try {
      const text = readText(input);
      await ready;
      if (!active) {            // domínio não monitorado: libera o envio retido sem enviar nada à API
        await submit();
        return;
      }
      setIndicator("inspecting");
      const res = await send<ApiResult>({ type: "analyze", app: site!.app, text, sessionPath: location.pathname, files: files.list() });
      let plan: Plan;
      let result: ApiResult | null = null;
      if (res.ok) {
        result = res.data;
        plan = planFor(result);
        setIndicator("active");
      } else {
        const stopped = res.error === INSPECTION_STOPPED;       // licença/contrato parou a inspeção: nunca bloqueia o trabalho, mesmo em modo fechado
        plan = failurePlan(stopped ? "open" : cfg.failMode);
        setIndicator("warning", stopped ? "PromptShield: a inspeção está PARADA pela licença ou contrato da empresa; este envio não foi inspecionado. Fale com o administrador."
          : cfg.failMode === "closed" ? "PromptShield: não foi possível verificar; envios bloqueados." : "PromptShield: sem conexão; enviado sem inspeção.");
      }
      const out = await showPlan(plan, "Não foi possível verificar este prompt com a política da empresa. O envio foi bloqueado.");
      if (out.action === "cancel") return;
      if (out.action === "send_masked" && result) writeText(input, result.masked_text);
      if (out.action === "justify" && result) {
        const j = await send<null>({ type: "justify", eventId: result.event_id, justification: out.text });
        if (!j.ok) {
          setIndicator("warning", "PromptShield: não foi possível registrar a justificativa; envio cancelado.");
          return;
        }
      }
      await submit();
      files.clear();
    } finally {
      busy = false;
    }
  }

  function intercept(e: Event, input: HTMLElement | null): void {
    if (bypass || !input || active === false) return;
    if (!readText(input).trim() && !files.list().length) return;   // só arquivo, sem texto, também é inspecionado
    e.preventDefault();
    e.stopImmediatePropagation();
    if (busy) return;
    void guard(input);
  }

  // anexos: só registra nome/tamanho/tipo; não impede nem altera o anexo. Sem exigir isTrusted: o seletor de arquivos do
  // navegador e os sites (React) disparam eventos que nem sempre são "confiáveis", e uma página falsa só poderia acrescentar nomes ao próprio relatório.
  const remember = (list: FileList | null | undefined) => { if (active !== false) files.add(infoOf(list)); };
  window.addEventListener("change", (e) => {
    if (e.target instanceof HTMLInputElement && e.target.type === "file") remember(e.target.files);
  }, true);
  window.addEventListener("drop", (e) => remember(e.dataTransfer?.files), true);
  window.addEventListener("paste", (e) => remember(e.clipboardData?.files), true);

  window.addEventListener("keydown", (e) => {
    if (e.target === uiHost() || !e.isTrusted) return;
    const input = site.findInput(document);
    if (input && input.contains(e.target as Node) && site.isSubmitKey(e)) intercept(e, input);
  }, true);

  window.addEventListener("click", (e) => {
    if (!e.isTrusted) return; // cliques sintéticos (do próprio envio liberado) passam
    const btn = site.findSend(document);
    if (btn && e.target instanceof Node && btn.contains(e.target)) intercept(e, site.findInput(document));
  }, true);

  window.addEventListener("submit", (e) => {
    const input = site.findInput(document);
    if (e.target instanceof HTMLFormElement && input && e.target.contains(input)) intercept(e, input);
  }, true);
}

/** Se o site mudar e o campo não for mais encontrado, avisa na tela em vez de fingir que monitora. */
function watchHealth(site: SiteModule): void {
  let tries = 0;
  let warned = false; // só desfaz o aviso que ele mesmo colocou (não apaga "sem conexão" nem "sem configuração")
  const timer = setInterval(() => {
    tries++;
    if (site.findInput(document)) {
      if (warned) {
        setIndicator("active");
        warned = false;
      }
      if (tries > 1) clearInterval(timer);
      return;
    }
    if (tries >= 3 && !warned) {
      setIndicator("warning", "PromptShield: campo de prompt não encontrado neste site; o monitoramento pode estar inativo.");
      warned = true;
    }
    if (tries >= 24) clearInterval(timer);
  }, HEALTH_MS);
}

void start();
