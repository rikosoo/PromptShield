import type { UpdateNotice, UpdatesInfo } from "./types";

export const UPDATE_STATUS_LABEL: Record<string, string> = {
  available: "Disponível", approved: "Download aprovado (aguardando o servidor)", downloading: "Baixando", ready: "Pronta para instalar",
  failed: "Falhou", staged: "Guardado, sem efeito",
};
export const PACK_STATUS_LABEL: Record<string, string> = { staged: "Guardado (sem efeito)", shadow: "Em sombra (só registra)", active: "Ativo", retired: "Desativado" };

/** Faixa para o administrador: só quando há algo que exige decisão ou deu problema. */
export function updatesNotice(u?: UpdatesInfo | null): { level: "info" | "warn"; text: string } | null {
  if (!u || u.mode !== "onprem") return null;
  const a: UpdateNotice | null | undefined = u.app?.notice;
  if (a && a.status === "available") return { level: a.security ? "warn" : "info", text: `Versão ${a.version} disponível${a.security ? " (correção de segurança)" : ""}.` };
  if (a && a.status === "ready") return { level: "info", text: `Versão ${a.version} baixada e conferida: falta instalar no servidor.` };
  if (a && a.status === "failed") return { level: "warn", text: `O download da versão ${a.version} falhou.` };
  const r = u.rules?.notice;
  if (r && r.status === "available") return { level: "info", text: `Pacote de regras ${r.version} disponível.` };
  return null;
}

export const bytes = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
