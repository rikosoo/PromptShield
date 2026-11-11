import type { LicenseStateId, LicenseStatus } from "./types";

export interface LicenseNotice { level: "crit" | "warn"; title: string; text: string; href: string }

export const STATE_LABEL: Record<LicenseStateId, string> = {
  nao_ativado: "Não ativado", ativo: "Ativo", sem_contato: "Sem contato com o licenciamento", em_tolerancia: "Em tolerância", expirado: "Expirado", encerrado: "Encerrado", suspenso: "Suspenso",
};

/** O que cada estado permite, em palavras que o administrador entende (espelha packages/licensing/states.py; nada apaga dados). */
export const STATE_EFFECT: Record<LicenseStateId, string> = {
  nao_ativado: "Sem inspeção e sem matrícula de máquinas até informar o código de ativação. Consulta e exportação funcionam.",
  ativo: "Tudo funciona conforme o contrato.",
  sem_contato: "Tudo funciona com a autorização local, que ainda vale. O servidor tenta renovar sozinho.",
  em_tolerancia: "Tudo funciona. O contrato venceu e há um prazo para regularizar.",
  expirado: "Novas máquinas não podem ser matriculadas. A inspeção, a consulta e a exportação continuam.",
  encerrado: "Novas máquinas não podem ser matriculadas. A inspeção segue o que o contrato prevê; consulta e exportação continuam.",
  suspenso: "Faltou a validação com o fornecedor por muito tempo: a inspeção está parada e alterações estão bloqueadas. Consulta e exportação continuam. Volta sozinha na próxima validação bem-sucedida.",
};

export const RENEWAL_WARNING_DAYS = 30;

/** Dias inteiros até o fim do contrato (negativo se já passou); null sem data. */
export function daysToContractEnd(s: LicenseStatus, now: Date): number | null {
  if (!s.contract_end) return null;
  return Math.floor((new Date(s.contract_end).getTime() - now.getTime()) / 86_400_000);
}

/** Faixa de aviso para o console. Licenciamento desligado (SaaS/desenvolvimento) não mostra nada; ativo só avisa perto do fim do contrato. */
export function licenseNotice(s: LicenseStatus | undefined | null, now: Date = new Date()): LicenseNotice | null {
  if (!s || s.mode !== "onprem") return null;
  const href = "/license";
  if (s.state === "ativo") {
    const d = daysToContractEnd(s, now);
    if (d === null || d > RENEWAL_WARNING_DAYS || d < 0) return null;
    return { level: "warn", title: "Contrato perto do fim",
      text: d === 0 ? "O contrato termina hoje. Renove com o fornecedor para evitar a tolerância e a expiração." : `O contrato termina em ${d} dia${d === 1 ? "" : "s"}. Renove com o fornecedor para evitar a tolerância e a expiração.`, href };
  }
  switch (s.state) {
    case "nao_ativado": return { level: "crit", title: "Instalação sem ativação", text: s.message, href };
    case "sem_contato": return { level: "warn", title: "Sem contato com o licenciamento", text: s.message, href };
    case "em_tolerancia": return { level: "warn", title: "Contrato vencido, em tolerância", text: s.message, href };
    case "expirado": return { level: "crit", title: "Licença expirada", text: s.message, href };
    case "suspenso": return { level: "crit", title: "Licença suspensa: inspeção parada", text: s.message, href };
    case "encerrado": return { level: "crit", title: s.inspecting ? "Contrato encerrado" : "Contrato encerrado: inspeção parada", text: s.message, href };
  }
}
