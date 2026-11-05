import type { Action, IncidentStatus, Severity } from "./types";

export const SEVERITY_LABEL: Record<Severity, string> = { baixo: "Baixo", medio: "Médio", alto: "Alto", critico: "Crítico" };
export const SEVERITY_CLASS: Record<Severity, string> = {
  baixo: "bg-low-bg text-low", medio: "bg-med-bg text-med", alto: "bg-high-bg text-high", critico: "bg-crit-bg text-crit",
};
export const STATUS_LABEL: Record<IncidentStatus, string> = { aberto: "Aberto", "em analise": "Em análise", resolvido: "Resolvido", "falso positivo": "Falso positivo" };
export const STATUSES = Object.keys(STATUS_LABEL) as IncidentStatus[];
export const ACTION_LABEL: Record<Action, string> = {
  allow: "Permitir", mask: "Mascarar", block: "Bloquear", ask_justification: "Pedir justificativa", alert: "Alertar",
};
export const ROLE_LABEL = { admin: "Administrador", analista: "Analista", auditor: "Auditor", leitura: "Leitura" } as const;
export const APP_LABEL: Record<string, string> = {
  claude_code: "Claude Code", gemini_web: "Gemini (web)", copilot_web: "Copilot (web)", claude_code_import: "Claude Code (histórico importado)", github_copilot_cli: "GitHub Copilot CLI", codex_cli: "Codex (CLI)", chatgpt_web: "ChatGPT (web)", claude_web: "Claude (web)", claude_ai: "Claude Enterprise (claude.ai)", cowork: "Claude Cowork", cursor: "Cursor",
};

export const appLabel = (a: string) => APP_LABEL[a] ?? a;

/** Severidade a partir do score (mesma régua da API: 80+ crítico, 60+ alto, 30+ médio). */
export function severityOf(score: number): Severity {
  return score >= 80 ? "critico" : score >= 60 ? "alto" : score >= 30 ? "medio" : "baixo";
}

export const CHANNEL_LABEL: Record<string, string> = {
  webhook: "Webhook genérico (JSON assinado)", slack: "Slack (webhook de entrada)", teams: "Microsoft Teams (webhook)",
  email: "E-mail (SMTP)", syslog_cef: "Syslog em CEF (SIEM)", siem_webhook: "Webhook de eventos para SIEM (JSON assinado)",
};
export const CHANNEL_STATUS_LABEL: Record<string, string> = { real: "REAL", parcial: "PARCIAL", experimental: "EXPERIMENTAL" };
export const CHANNEL_TARGET_HINT: Record<string, string> = {
  webhook: "URL https pública", slack: "URL do webhook de entrada (https)", teams: "URL do webhook do Workflows (https)", email: "endereço de e-mail",
  syslog_cef: "host:porta do coletor", siem_webhook: "URL https pública",
};
export const REPORT_KIND_LABEL = { executivo: "Executivo", lgpd: "Conformidade LGPD", piloto: "Final do piloto" } as const;

/** O que a pessoa pediu ao assistente (regras locais; ver packages/detection/src/promptshield_detection/intents.py). */
export const INTENT_LABEL: Record<string, string> = {
  resumir: "Resumir", traduzir: "Traduzir", revisar_corrigir: "Revisar ou corrigir", gerar_codigo: "Gerar código", explicar: "Explicar",
  reescrever_melhorar: "Reescrever ou melhorar", analisar_extrair: "Analisar ou extrair", validar_verificar: "Validar ou verificar",
  redigir_texto: "Redigir texto", declara_confidencial: "Declara que é confidencial",
};
export const intentLabel = (i: string) => INTENT_LABEL[i] ?? i;
/** Tipos de trecho sensível que o motor reconhece; o que não está aqui aparece com o nome técnico. */
export const SPAN_LABEL: Record<string, string> = {
  aws_access_key: "Chave AWS", cpf: "CPF", cnpj: "CNPJ", email: "E-mail", phone: "Telefone", card: "Cartão", conn_string: "String de conexão",
  ip: "Endereço IP", internal_host: "Host interno", user_path: "Usuário em caminho de arquivo", private_key: "Chave privada", jwt: "Token JWT", github_token: "Token do GitHub", password: "Senha",
};
export const spanLabel = (t: string) => SPAN_LABEL[t] ?? t;
export const KIND_LABEL: Record<string, string> = { prompt: "Prompt", response: "Resposta", tool_call: "Ação do agente", tool_result: "Resultado de ação", file_upload: "Arquivo enviado" };
