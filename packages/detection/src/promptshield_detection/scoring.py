"""Score 0-100 explicável e versionado. Mesmo evento, mesmo score e mesmos motivos.

Motor 2.0 (2026-11-05): faixas 0-24 baixo, 25-49 moderado, 50-69 alto, 70-100 crítico; correlação entre indicadores; piso para credencial
de alta confiança (um indicador crítico nunca é diluído por outros de risco baixo); pesos por categoria configuráveis por empresa.
O score é uma ESTIMATIVA de risco, não uma probabilidade de incidente."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import Finding, Reason
from .taxonomy import Category

ENGINE_VERSION = "2.0"
SCORE_VERSION = "2026-11-c"   # 2026-11-c: motor 2.0 (declarações em linguagem natural, correlação, piso de credencial, novas faixas)
# 2026-11-b: credenciais do próprio PromptShield (ps_, pse_) e comando que baixa e executa script (irm | iex, curl | sh)
# 2026-11-a: infraestrutura no texto (IP, host interno, caminho com usuário, arquivo de negócio)
THRESHOLD = 0.5  # confiança mínima para a categoria contar
SECONDARY_FACTOR = 0.3
AGENT_ACTION_BONUS = 10
PERSONAL_ACCOUNT_BONUS = 10

# severidade e nível de alerta (alertas são PASSIVOS: nenhum nível bloqueia, altera ou interrompe nada)
HIGH_RISK_MIN, CRITICAL_MIN = 50, 70          # faixas: 0-24 baixo, 25-49 moderado (interno: "medio"), 50-69 alto, 70-100 crítico
SEVERITY_BANDS = ((CRITICAL_MIN, "critico"), (HIGH_RISK_MIN, "alto"), (25, "medio"), (0, "baixo"))
ALERT_LEVEL = {"baixo": "informativo", "medio": "atencao", "alto": "alto", "critico": "critico"}

# piso: credencial com esta confiança vale pelo menos este score, qualquer que seja o resto do prompt e o peso configurado
CREDENTIAL_FLOORS = ((0.9, 75, "Credencial de alta confiança (piso crítico)"), (0.8, 70, "Credencial com contexto explícito (piso crítico)"))
MAX_CORRELATION = 25
# código compartilhado: risco BAIXO (faixa informativa), mas sempre sinalizado como possível código sensível da empresa
CODE_SHARED_SCORE = 15
CODE_SHARED_RULE = "Código-fonte compartilhado: pode ser código sensível da empresa"
SECRET_SPANS = {"private_key", "private_key_body"}
SENSITIVE_SPAN_CATEGORIES = {"segredo", "pii", "financeiro"}


def severity_for(score: int) -> str:
    return next(name for floor, name in SEVERITY_BANDS if score >= floor)


def correlate(best: Mapping[str, Finding], findings: Iterable[Finding], has_code: bool = False, external_url: bool = False) -> list[tuple[str, int]]:
    """Combinações de indicadores que valem mais que a soma das partes. Cada regra aparece UMA vez, com o motivo."""
    ok = [f for f in findings if f.confidence >= THRESHOLD]
    types = {f.span_type for f in ok if f.span_type}

    def has(cat: str) -> bool:
        return cat in best and best[cat].confidence >= THRESHOLD

    out: list[tuple[str, int]] = []
    if has("segredo") and (has("rede_externa") or has("exfiltracao_ferramenta") or external_url):
        out.append(("Correlação: credencial junto de destino externo", 10))
    if "password" in types and "email" in types:
        out.append(("Correlação: e-mail e senha no mesmo prompt", 12))
    if has("financeiro") and has("pii"):
        out.append(("Correlação: dados bancários junto de dados pessoais", 10))
    if has("segredo") and (has_code or has("codigo_proprietario")):
        out.append(("Correlação: credencial junto de código-fonte", 10))
    if types & SECRET_SPANS and (has("arquitetura") or has("iac") or types & {"ip", "internal_host"}):
        out.append(("Correlação: chave privada junto de infraestrutura", 15))
    n_sensitive = sum(1 for f in ok if f.span_type and f.category in SENSITIVE_SPAN_CATEGORIES)
    if n_sensitive >= 10:
        out.append((f"Correlação: grande volume de dados sensíveis ({n_sensitive} trechos)", 12))
    elif n_sensitive >= 5:
        out.append((f"Correlação: vários dados sensíveis no mesmo prompt ({n_sensitive} trechos)", 8))
    total = 0
    capped: list[tuple[str, int]] = []
    for rule, bonus in out:
        bonus = min(bonus, MAX_CORRELATION - total)
        if bonus > 0:
            capped.append((rule, bonus))
            total += bonus
    return capped


def score(best: dict[str, Finding], cats: dict[str, Category], is_agent_action: bool,
          personal_account: bool, *, findings: Iterable[Finding] = (), weights: Mapping[str, int] | None = None,
          has_code: bool = False, external_url: bool = False, code_shared: bool = False) -> tuple[int, list[Reason]]:
    contribs: list[tuple[float, str, str]] = []
    for cid, f in best.items():
        if f.confidence < THRESHOLD:
            continue
        w = cats[cid].weight if not weights or cid not in weights else max(0, min(100, int(weights[cid])))
        contribs.append((w * f.confidence, cid, f.rule))
    contribs.sort(key=lambda x: (-x[0], x[1]))
    reasons: list[Reason] = []
    total = 0.0
    for i, (value, cid, rule) in enumerate(contribs):
        part = value if i == 0 else value * SECONDARY_FACTOR
        total += part
        reasons.append(Reason(rule=rule, contribution=round(part), category=cid))
    if total > 0 and is_agent_action:
        total += AGENT_ACTION_BONUS
        reasons.append(Reason("Ação de agente (contexto)", AGENT_ACTION_BONUS))
    if total > 0 and personal_account:
        total += PERSONAL_ACCOUNT_BONUS
        reasons.append(Reason("Conta pessoal (contexto)", PERSONAL_ACCOUNT_BONUS))
    for rule, bonus in correlate(best, findings, has_code, external_url):
        total += bonus
        reasons.append(Reason(rule, bonus))
    secret = best.get("segredo")
    if secret is not None:
        for conf, floor, rule in CREDENTIAL_FLOORS:
            if secret.confidence >= conf:
                if total < floor:
                    reasons.append(Reason(rule, round(floor - total), "segredo"))
                    total = float(floor)
                break
    if code_shared and total < CODE_SHARED_SCORE:
        reasons.append(Reason(CODE_SHARED_RULE, round(CODE_SHARED_SCORE - total), "codigo_proprietario"))
        total = float(CODE_SHARED_SCORE)
    return min(100, round(total)), reasons
