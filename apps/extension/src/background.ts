/** Service worker: guarda a chave de API, fala com a API e valida quem pergunta. O content script nunca vê a chave. */
import { getRemoteConfig, postEvent, postJustification, buildEvent } from "./api";
import { hostMatches, mergeConfig, toPublic, type RemoteConfig } from "./config";
import type { FullConfig, Request, Response } from "./types";

const REFRESH_ALARM = "ps-refresh-config";

// A primeira leitura do armazenamento gerenciado leva alguns segundos (medido: ~3 s em Chromium 141); depois cai para ~1 ms.
// Por isso a leitura começa assim que o service worker sobe e fica em cache; mudanças de política invalidam o cache.
let managedCache: Promise<Record<string, unknown>> | null = null;

function readManaged(): Promise<Record<string, unknown>> {
  managedCache ??= (chrome.storage.managed.get(null) as Promise<Record<string, unknown>>).catch(() => ({})); // sem política gerenciada
  return managedCache;
}

async function managed(): Promise<Record<string, unknown>> {
  let out = await readManaged();
  if (__DEV__) {
    // só no build de desenvolvimento/teste: configuração local no lugar da política gerenciada
    const { devConfig } = (await chrome.storage.local.get("devConfig")) as { devConfig?: Record<string, unknown> };
    out = { ...devConfig, ...out };
  }
  if (__SIDELOAD__) {
    // instalação por sensor: o sensor grava promptshield-config.json na pasta da extensão; a política gerenciada, se existir, vence
    try {
      const file = (await (await fetch(chrome.runtime.getURL("promptshield-config.json"))).json()) as Record<string, unknown>;
      out = { ...file, ...out };
    } catch { /* arquivo ausente: a extensão fica sem configuração e avisa na tela */ }
  }
  return out;
}

chrome.storage.onChanged.addListener((_changes, area) => {
  if (area === "managed") managedCache = null;
});
void readManaged();

async function loadConfig(): Promise<FullConfig> {
  const { remote } = (await chrome.storage.local.get("remote")) as { remote?: RemoteConfig };
  return mergeConfig(await managed(), remote, __DEV__ || __SIDELOAD__);
}

async function installId(): Promise<string> {
  const { installId: id } = (await chrome.storage.local.get("installId")) as { installId?: string };
  if (id) return id;
  const fresh = crypto.randomUUID();
  await chrome.storage.local.set({ installId: fresh });
  return fresh;
}

async function profileEmail(): Promise<string> {
  try {
    const info = await chrome.identity.getProfileUserInfo({ accountStatus: "ANY" as chrome.identity.AccountStatus });
    return info.email || "";
  } catch {
    return "";
  }
}

async function refreshRemote(): Promise<void> {
  const cfg = await loadConfig();
  if (!cfg.apiUrl || !cfg.apiKey) return;
  try {
    const r = await getRemoteConfig(cfg);
    await chrome.storage.local.set({ remote: { domains: r.domains, policy_url: r.policy_url, failure_mode: r.failure_mode, fetchedAt: Date.now() } });
  } catch {
    /* mantém o último valor conhecido */
  }
}

function senderAllowed(sender: chrome.runtime.MessageSender, cfg: FullConfig): boolean {
  if (sender.id !== chrome.runtime.id || !sender.url) return false;
  try {
    return hostMatches(new URL(sender.url).hostname, cfg.domains);
  } catch {
    return false;
  }
}

async function handle(msg: Request, sender: chrome.runtime.MessageSender): Promise<Response> {
  try {
    const cfg = await loadConfig();
    if (!senderAllowed(sender, cfg)) return { ok: false, error: "origem não permitida" };
    if (msg.type === "getPublicConfig") return { ok: true, data: toPublic(cfg) };
    if (msg.type === "analyze") {
      const event = buildEvent({ app: msg.app, text: msg.text, sessionPath: msg.sessionPath, files: msg.files }, cfg, await installId(), await profileEmail());
      return { ok: true, data: await postEvent(cfg, event) };
    }
    if (msg.type === "justify") {
      await postJustification(cfg, msg.eventId, msg.justification);
      return { ok: true, data: null };
    }
    return { ok: false, error: "mensagem desconhecida" };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

chrome.runtime.onMessage.addListener((msg: Request, sender, sendResponse) => {
  handle(msg, sender).then(sendResponse);
  return true; // resposta assíncrona
});
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(REFRESH_ALARM, { periodInMinutes: 30 });
  void refreshRemote();
});
chrome.runtime.onStartup.addListener(() => void refreshRemote());
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === REFRESH_ALARM) void refreshRemote();
});
