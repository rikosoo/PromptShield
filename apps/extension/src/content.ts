/**
 * Content script. Só age em domínios configurados. Lê o texto APENAS no momento do envio
 * (Enter ou clique em enviar); nunca tecla por tecla, nunca em outros sites.
 */
import { createTracker, infoOf } from "./attachments";
import { readText } from "./editor";
import { siteFor } from "./sites";
import type { SiteModule } from "./sites/types";
import { hostMatches } from "./config";
import { setIndicator, showIndicator, uiHost } from "./ui";
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

async function start(): Promise<void> {
  const site = siteFor(location.hostname);
  if (!site) return; // site sem módulo: a extensão não faz nada

  // Os ouvintes entram já; a configuração pode demorar alguns segundos na primeira leitura da política gerenciada.
  // Enquanto não se sabe se o domínio é monitorado, o texto é lido mas só vai à API depois da configuração (o envio do usuário nunca espera).
  let active: boolean | null = null;
  let cfg: PublicConfig = { configured: false, domains: [], failMode: "open" };   // failMode existe na configuração, mas o produto é passivo: nunca bloqueia
  const ready = send<PublicConfig>({ type: "getPublicConfig" }).then((res) => {
    active = res.ok && hostMatches(location.hostname, res.data.domains);
    if (res.ok) cfg = res.data;
    if (active) {
      showIndicator(cfg.policyUrl);
      if (!cfg.configured) setIndicator("warning", "PromptShield: sem configuração da empresa; nada é enviado.");
      watchHealth(site);
    }
  });

  // PASSIVO: a extensão só OBSERVA. Lê o texto no instante do envio (Enter ou clique), antes do site limpar o campo, e DEIXA O ENVIO SEGUIR
  // na hora: nada de preventDefault, nada de segurar o prompt até a API responder, nada de diálogo, nada de alterar o texto. A análise vai em
  // segundo plano; se a API estiver fora do ar, o prompt do usuário não é afetado (só deixa de ser registrado, e o indicador avisa).
  const files = createTracker();
  let last = { text: "", at: 0 };

  function observe(input: HTMLElement | null): void {
    if (!input || active === false) return;
    const text = readText(input);
    const list = files.list();
    if (!text.trim() && !list.length) return;               // só arquivo, sem texto, também é registrado
    const now = Date.now();
    if (text === last.text && now - last.at < 2000) return;   // Enter e clique no mesmo envio contam uma vez só
    last = { text, at: now };
    files.clear();
    void report(text, list);
  }

  async function report(text: string, list: ReturnType<typeof files.list>): Promise<void> {
    try {
      await ready;                                            // só a configuração; o envio do usuário já seguiu
      if (!active) return;
      setIndicator("inspecting");
      const res = await send<ApiResult>({ type: "analyze", app: site!.app, text, sessionPath: location.pathname, files: list });
      if (res.ok) {
        setIndicator("active");
      } else if (res.error === INSPECTION_STOPPED) {          // licença/contrato parou a inspeção: avisa, nunca interfere no trabalho
        setIndicator("warning", "PromptShield: a inspeção está PARADA pela licença ou contrato da empresa; este envio não foi inspecionado. Fale com o administrador.");
      } else {
        setIndicator("warning", "PromptShield: sem conexão com o servidor; este envio não foi registrado. O seu envio não foi afetado.");
      }
    } catch {
      /* a observação nunca pode afetar a página */
    }
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
    if (input && input.contains(e.target as Node) && site.isSubmitKey(e)) observe(input);
  }, true);

  window.addEventListener("click", (e) => {
    if (!e.isTrusted) return; // cliques sintéticos (do próprio envio liberado) passam
    const btn = site.findSend(document);
    if (btn && e.target instanceof Node && btn.contains(e.target)) observe(site.findInput(document));
  }, true);

  window.addEventListener("submit", (e) => {
    const input = site.findInput(document);
    if (e.target instanceof HTMLFormElement && input && e.target.contains(input)) observe(input);
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
