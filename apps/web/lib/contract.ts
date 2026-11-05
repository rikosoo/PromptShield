import type { Contract } from "./types";

export interface ContractNotice { level: "crit" | "warn"; title: string; text: string }

/** Aviso de contrato para o administrador. A decisão de suspender é do fornecedor; aqui só se mostra o estado e o que fazer. */
export function contractNotice(c: Contract | undefined | null): ContractNotice | null {
  if (!c) return null;
  if (c.suspended) {
    return { level: "crit", title: "Contrato suspenso",
      text: `A coleta e as alterações estão paradas; seus dados continuam guardados e você pode consultar e exportar.${c.suspended_reason ? ` Motivo informado: ${c.suspended_reason}.` : ""} Fale com o fornecedor para reativar.` };
  }
  if (c.expired) {
    return { level: "crit", title: "Licença vencida",
      text: "Novas máquinas não podem ser matriculadas e o contrato pode ser suspenso. As máquinas já instaladas continuam enviando por enquanto. Fale com o fornecedor para renovar." };
  }
  if (c.days_to_expiry !== null && c.days_to_expiry <= 15) {
    return { level: "warn", title: "Licença perto de vencer",
      text: c.days_to_expiry <= 0 ? "A licença vence hoje." : `A licença vence em ${c.days_to_expiry} dia${c.days_to_expiry === 1 ? "" : "s"}. Renove para evitar a suspensão.` };
  }
  return null;
}
