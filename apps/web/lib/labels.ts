import type { Action, IncidentStatus, Severity } from "./types";

export const SEVERITY_LABEL: Record<Severity, string> = { baixo: "Baixo", medio: "Moderado", alto: "Alto", critico: "Crítico" };
export const SEVERITY_CLASS: Record<Severity, string> = {
  baixo: "bg-low-bg text-low", medio: "bg-med-bg text-med", alto: "bg-high-bg text-high", critico: "bg-crit-bg text-crit",
};
export const STATUS_LABEL: Record<IncidentStatus, string> = { aberto: "Aberto", "em analise": "Em análise", resolvido: "Resolvido", "falso positivo": "Falso positivo" };
export const STATUSES = Object.keys(STATUS_LABEL) as IncidentStatus[];
export const ACTION_LABEL: Record<Action, string> = {
  allow: "Permitir", mask: "Mascarar", block: "Bloquear", ask_justification: "Pedir justificativa", alert: "Alertar",
};
export const ROLE_LABEL = { admin: "Administrador", analista: "Analista", auditor: "Auditor", leitura: "Leitura" } as const;
/** O que cada função pode fazer no console (conferido nas rotas da API). */
export const ROLE_CAN: Record<keyof typeof ROLE_LABEL, string> = {
  admin: "Tudo: consulta, trata incidentes, pede o texto original, configura políticas, privacidade, canais, chaves, dispositivos e colaboradores.",
  analista: "Consulta tudo, trata incidentes (status e responsável), pede o texto original com justificativa, simula políticas e revisa análises. Não altera configurações.",
  auditor: "Consulta tudo, exporta dados e vê o registro de auditoria. Não trata incidentes nem vê o texto original.",
  leitura: "Só consulta os painéis, os prompts e os incidentes. Não altera nem exporta nada.",
};
export const APP_LABEL: Record<string, string> = {
  claude_code: "Claude Code", gemini_web: "Gemini (web)", copilot_web: "Copilot (web)", claude_code_import: "Claude Code (histórico importado)", github_copilot_cli: "GitHub Copilot CLI", codex_cli: "Codex (CLI)", chatgpt_web: "ChatGPT (web)", claude_web: "Claude (web)", claude_ai: "Claude Enterprise (claude.ai)", cowork: "Claude Cowork", cursor: "Cursor",
};

export const appLabel = (a: string) => APP_LABEL[a] ?? a;

/** Severidade a partir do score (mesma régua da API: 80+ crítico, 60+ alto, 30+ médio). */
export function severityOf(score: number): Severity {
  return score >= 70 ? "critico" : score >= 50 ? "alto" : score >= 25 ? "medio" : "baixo";     // mesmas faixas do motor: 0-24, 25-49, 50-69, 70-100
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
export const ALERT_STATUS_LABEL: Record<string, string> = {
  sem_alerta: "Sem alerta", novo: "Novo", em_analise: "Em análise", falso_positivo: "Falso positivo", resolvido: "Resolvido",
};
export const ALERT_STATUS_CLASS: Record<string, string> = {
  sem_alerta: "text-muted", novo: "bg-med-bg text-med", em_analise: "bg-med-bg text-med", falso_positivo: "bg-low-bg text-low", resolvido: "bg-low-bg text-low",
};
/** Nível de alerta (passivo: nenhum nível bloqueia, altera ou interrompe nada). */
export const ALERT_LEVEL_LABEL: Record<string, string> = { informational: "Informativo", attention: "Atenção", high: "Alto", critical: "Crítico" };
export const SPAN_LABEL: Record<string, string> = {
  declared_token: "Token ou chave", agencia: "Agência bancária", conta_bancaria: "Conta bancária", cartao: "Cartão", cvv: "CVV", pix: "Chave Pix",
  private_key_body: "Chave privada", promptshield_key: "Chave do PromptShield", promptshield_enroll_token: "Token de matrícula do PromptShield", high_entropy: "Valor secreto",
  aws_access_key: "Chave AWS", cpf: "CPF", cnpj: "CNPJ", email: "E-mail", phone: "Telefone", card: "Cartão", conn_string: "String de conexão",
  ip: "Endereço IP", internal_host: "Host interno", user_path: "Usuário em caminho de arquivo", private_key: "Chave privada", jwt: "Token JWT", github_token: "Token do GitHub", password: "Senha",
};
export const spanLabel = (t: string) => SPAN_LABEL[t] ?? t;
export const KIND_LABEL: Record<string, string> = { prompt: "Prompt", response: "Resposta", tool_call: "Ação do agente", tool_result: "Resultado de ação", file_upload: "Arquivo enviado" };
