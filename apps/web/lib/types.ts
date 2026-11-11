/** Formatos devolvidos pela API (apps/api). Nenhum valor fixo: tudo vem de /v1/*. */
export type Role = "admin" | "analista" | "auditor" | "leitura";
export type Severity = "baixo" | "medio" | "alto" | "critico";
export type IncidentStatus = "aberto" | "em analise" | "resolvido" | "falso positivo";
export type Action = "allow" | "mask" | "block" | "ask_justification" | "alert";

export interface Me { kind: string; id: string; tenant_id: string; role: Role | null; email: string | null; local_auth?: boolean; must_change_password?: boolean; has_password?: boolean }
export interface Tenant {
  id: string; name: string; failure_mode: "open" | "closed"; retention_days: number; store_original: boolean;
  policy_url: string | null; monitored_domains: string[]; contract?: Contract; monitoring_mode?: "passive" | "legacy_enforcement"; is_demo: boolean; volume_threshold_per_hour: number; original_retention_days: number; omit_text_categories: string[];
}
export interface Contract { suspended: boolean; suspended_at: string | null; suspended_reason: string | null; license_expires_at: string | null; days_to_expiry: number | null; expired: boolean }
export type LicenseStateId = "nao_ativado" | "ativo" | "sem_contato" | "em_tolerancia" | "expirado" | "encerrado" | "suspenso";
export interface LicenseStatus {
  mode: "off" | "onprem"; state: LicenseStateId; message: string; can_enroll: boolean; inspecting: boolean;
  deadline?: string | null; days_left?: number | null; max_devices?: number | null; installation_id?: string | null; server_configured?: boolean;
  customer?: string | null; serial?: number | null; on_end?: "stop_inspection" | "keep_inspection" | null;
  contract_start?: string | null; contract_end?: string | null; tolerance_end?: string | null; auth_expires?: string | null;
  last_success_at?: string | null; last_attempt_at?: string | null; last_attempt_failed?: boolean; last_error?: string | null; problem?: string | null;
}
export interface Category { id: string; confidence: number }
export interface TaxonomyItem { id: string; nome: string; grupo: string; risco_padrao: string }

export interface Overview {
  days: number;
  high_risk_threshold: number;
  totals: {
    events: number; high_risk: number; with_code: number; with_sensitive: number; agent_actions: number; blocked: number; would_block: number; users: number;
    credentials: number; personal_data: number; financial_data: number; injections: number; alerts: number;
  };
  alert_min: number;
  top_users: { user_id: string; alerts: number; max_score: number }[];
  monthly: { month: string; events: number; alerts: number; high_risk: number }[];
  daily: { date: string; events: number; high_risk: number }[];
  by_department: { department: string; events: number; high_risk: number }[];
  by_app: { app: string; corporate: number; personal: number; sensitive: number }[];
}

export type AlertStatus = "sem_alerta" | "novo" | "em_analise" | "falso_positivo" | "resolvido";
export interface V2Finding { type: string; category: string; severity: string; confidence: number; reason: string | null; evidence: string | null; impact: string | null }
/** Resultado padronizado do motor 2.0 (monitoramento passivo): nunca traz o valor secreto, só a evidência mascarada. */
export interface AnalysisV2 {
  risk_score: number; severity: string; monitoring_mode: "passive"; detected_categories: string[]; confidence: number; alert_level: string; action: "monitor";
  masked_prompt: string; findings: V2Finding[]; reasons: { rule: string; contribution: number }[]; recommendation: string; engine_version: string;
}

export interface PromptRow {
  event_id: string; occurred_at: string; app: string; channel: string; user_id: string; department: string | null; kind: string;
  personal_account: boolean; masked_text: string; attachments?: { name: string; size: number | null; mime: string | null }[]; has_original: boolean; categories: Category[];
  flags: { has_code: boolean; has_sensitive: boolean; is_agent_action: boolean; intents?: string[]; has_attachments?: boolean; keyword_hits?: string[] };
  tool_name?: string | null; session_id?: string | null; spans?: { type: string; masked: string }[];
  risk_score: number; reasons: { rule: string; contribution: number; category?: string }[];
  decision: Action; would_decide: Action; policy_hits: { policy_id: string; name: string; action: string; mode: string; excepted?: string }[];
  incident_id: string | null;
  severity: Severity; alert_status: AlertStatus; engine_version?: string | null;
  feedback?: Feedback | null;
}

export type Verdict = "correta" | "falso_positivo" | "faltou";
export interface Feedback { verdict: Verdict; wrong_categories: string[]; missing_categories: string[]; note: string | null; updated_at: string }
export interface QualitySummary {
  days: number; events: number; reviewed: number; coverage: number; verdicts: Record<Verdict, number>; min_for_estimate: number; note: string;
  categories: { id: string; nome: string; reviewed: number; wrong: number; missed: number; precision_estimate: number | null }[];
}

export interface Incident {
  id: string; severity: Severity; status: IncidentStatus; assignee_id: string | null; assignee_email: string | null; confidence: number;
  created_at: string; event_id: string; user_id: string; app: string; department: string | null; personal_account: boolean;
  masked_text: string; has_original: boolean; categories: Category[]; keyword_hits?: string[]; risk_score: number;
  reasons: { rule: string; contribution: number }[]; decision: Action; would_decide: Action;
  timeline?: { at: string; what: string }[]; recommendations?: string[];
}

export interface Policy {
  id: string; name: string; description: string | null; enabled: boolean; scope: Record<string, string[]>;
  match: { categories?: string[]; min_confidence?: number; min_score?: number }; action: Action; mode: "monitor" | "enforce";
  version: number; updated_at: string;
}
export type PolicyDraft = Omit<Policy, "id" | "version" | "updated_at">;

export interface Simulation {
  days: number; events_in_period: number; events_evaluated: number; truncated: boolean; matched: number; matched_users: number;
  would_be_stronger_than_current: number; examples: { event_id: string; user_id: string; risk_score: number; masked_text: string; current_decision: string }[];
  action: string; mode: string; note: string;
}
export interface DirectoryUser { id: string; email: string; display_name: string | null; role: Role }

export interface RiskUser { user_id: string; department: string | null; score: number; reasons: { rule: string; contribution: number }[]; events: number; high_events: number; series: number[] }
export interface RiskDept { department: string; score: number; users: number; users_high: number; events: number; series: number[] }
export interface RiskStats { score_version: string; disclaimer: string; days: string[]; users: RiskUser[]; departments: RiskDept[] }

export interface AlertRow {
  id: string; rule: string; rule_label: string; severity: Severity; title: string; user_id: string; department: string | null;
  count: number; first_seen: string; last_seen: string; incident_id: string | null; score: number | null; categories: string[];
}
export type ChannelKind = "webhook" | "slack" | "teams" | "email" | "syslog_cef" | "siem_webhook";
export interface Channel {
  id: string; kind: ChannelKind; name: string; target: string; enabled: boolean; integration_status: "real" | "parcial" | "experimental";
  min_severity: Severity | null; min_score: number | null; proto: string | null; has_secret: boolean; outbox: Record<string, number>;
}
export interface ReportRow { id: string; kind: "executivo" | "lgpd" | "piloto"; format: "pdf" | "csv"; period_start: string; period_end: string; sha256: string; created_by: string; created_at: string; size: number; scheduled: boolean }
export interface ScheduleRow { id: string; kind: "executivo" | "lgpd" | "piloto"; format: "pdf" | "csv"; frequency: "mensal" | "semanal"; recipients: string[]; enabled: boolean; last_period_end: string | null }

export interface InferenceHookConfig {
  mode: "shadow" | "enforce"; scope: "full" | "latest"; evaluate_tool_calls: boolean; has_secret: boolean; previous_secret_active: boolean;
  rejected_count: number; last_rejected_at: string | null; last_request_at: string | null; last_test_at: string | null;
  endpoint_path: string; budget_ms: number; integration_status: string; notice: string;
  stats_24h: { requests: number; denied: number; would_deny: number; failures: number; skipped_attachments: number; p95_ms: number; max_ms: number };
}

export interface PilotSummary {
  started_at: string | null; pilot_days: number; day: number | null; ends_at: string | null; days_remaining: number | null;
  coverage: { active_users: number; expected_users: number | null; rate: number | null; by_department: { department: string; users: number }[];
              by_channel: { channel: string; app: string; users: number; events: number }[] };
  totals: { events: number; high_risk: number; enforced_decisions: number; would_act: number };
  false_positive: { reviewed: number; pending: number; false_positive: number; true_positive: number; unsure: number; decided: number; rate: number | null;
                    ci95: [number, number] | null; small_sample: boolean; min_reviews: number; scope: string };
  time_to_first_alert_seconds: number | null; first_alert_at: string | null; first_incident_at: string | null; monitor_only: boolean;
}
export interface ReviewItem { id: string; sample_id: string; label: string | null; user_id: string; app: string; kind: string; masked_text: string;
  categories: Category[]; risk_score: number; decision: Action; would_decide: Action }
export interface DataMap {
  retention_days: number; original_text_stored: boolean; original_retention_days: number; last_retention_run: string | null; audit_log: string;
  counts: { events: number; events_with_original: number; distinct_monitored_people: number; alerts: number; reports: number; console_users: number; oldest_event_received_at: string | null };
}
export interface ApiKeyRow { id: string; name: string; prefix: string; status: string; revoked: boolean; created_at: string; expires_at: string | null; last_used_at: string | null }

export interface EnrollTokenRow { id: string; name: string; prefix: string; status: string; uses: number; max_uses: number | null; expires_at: string; created_at: string }
export interface License { max_devices: number | null; active_seats: number; window_days: number; level: "ok" | "alerta" | "esgotada"; expired: boolean; expires_at: string | null }
export interface AppActivity { events_7d: number; events_30d: number; last_at: string }
export interface DeviceRow {
  counts_toward_license?: boolean; id: string; hostname: string; os: string | null; client_version: string | null; tools: string[]; enrolled_at: string;
  last_seen_at: string | null; revoked: boolean; ias?: string[]; activity?: Record<string, AppActivity>;
  last_user?: string | null; last_department?: string | null; last_user_at?: string | null; users_30d?: number;
}
export interface DevicesOut { devices: DeviceRow[]; active: number; coverage: Record<string, number>; ias_coverage?: Record<string, number>; license: License }

export interface SignalsOut { span_types: Record<string, number>; intents: Record<string, number>; kinds: Record<string, number>; tools: Record<string, number> }
export interface PersonRow { user_id: string; department: string | null; groups?: string[]; events: number; high_risk: number; max_risk: number; avg_risk: number; last_seen: string }

export interface UserGroup { id: string; name: string; description: string | null; members: number; created_at: string }
export interface UserGroupDetail extends UserGroup { member_ids: string[] }
export type ExceptionState = "vigente" | "vencida" | "revogada";
export interface PolicyExceptionRow {
  id: string; policy_id: string; policy_name: string | null; user_id: string | null; group: string | null; reason: string;
  expires_at: string; created_by: string; created_at: string; revoked_at: string | null; state: ExceptionState;
}
export interface KeywordRow { id: string; term: string; whole_word: boolean; fuzzy: boolean; score: number | null; enabled: boolean; note: string | null; created_by: string; created_at: string }
export interface AllowlistRow { id: string; kind: "host"; value: string; note: string | null; created_by: string; created_at: string }

export interface Collaborator { id: string; email: string; display_name: string | null; role: "admin" | "analista" | "auditor" | "leitura"; department: string | null; active: boolean; created_at: string; is_me: boolean; has_password?: boolean; must_change_password?: boolean; locked?: boolean }
