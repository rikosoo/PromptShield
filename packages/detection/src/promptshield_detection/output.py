"""Resultado padronizado do motor 2.0 (monitoramento PASSIVO: o PromptShield só observa, analisa, registra e alerta).

`to_v2` junta o que o motor achou numa estrutura estável para o painel, o SIEM e o analista. Regras:
  - NUNCA sai o valor secreto: a evidência é sempre a máscara ("[TOKEN]", "[CPF]"...);
  - `action` é sempre "monitor": nada aqui bloqueia, altera ou interrompe um prompt;
  - a recomendação é um TEXTO para o analista; nenhuma recomendação é executada automaticamente;
  - `confidence` é a do achado mais forte (confiança de regra, não probabilidade calibrada: não há dados reais para calibrar).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .scoring import ENGINE_VERSION, THRESHOLD, severity_for
from .taxonomy import load

SEVERITY_EN = {"baixo": "low", "medio": "moderate", "alto": "high", "critico": "critical"}
ALERT_EN = {"baixo": "informational", "medio": "attention", "alto": "high", "critico": "critical"}
_RISK_TO_SEVERITY = {"baixo": "baixo", "medio": "medio", "alto": "alto", "critico": "critico"}

TYPE_NAME = {
    "declared_token": "POSSIBLE_API_TOKEN", "high_entropy": "POSSIBLE_API_TOKEN", "password": "PASSWORD", "aws_access_key": "AWS_ACCESS_KEY",
    "aws_secret_key": "AWS_SECRET_KEY", "gcp_api_key": "GCP_API_KEY", "github_token": "GITHUB_TOKEN", "gitlab_token": "GITLAB_TOKEN", "jwt": "JWT",
    "bearer_token": "BEARER_TOKEN", "private_key": "PRIVATE_KEY", "private_key_body": "PRIVATE_KEY", "conn_string": "CONNECTION_STRING",
    "promptshield_key": "PROMPTSHIELD_API_KEY", "promptshield_enroll_token": "PROMPTSHIELD_ENROLL_TOKEN", "cartao": "PAYMENT_CARD", "cvv": "CARD_CVV",
    "conta_bancaria": "BANK_ACCOUNT", "agencia": "BANK_BRANCH", "pix": "PIX_KEY", "iban": "IBAN", "routing": "BANK_ROUTING", "cpf": "CPF", "cnpj": "CNPJ",
    "rg": "RG", "documento": "PERSONAL_DOCUMENT", "email": "EMAIL", "telefone": "PHONE", "endereco": "ADDRESS", "cep": "POSTAL_CODE",
    "ip": "IP_ADDRESS", "internal_host": "INTERNAL_HOST", "code_shared": "SOURCE_CODE_SHARED",
}
CATEGORY_NAME = {
    "injection_direta": "PROMPT_INJECTION", "injection_indireta": "INDIRECT_PROMPT_INJECTION", "jailbreak": "JAILBREAK_ATTEMPT",
    "extracao_system_prompt": "SYSTEM_PROMPT_EXTRACTION", "exfiltracao_ferramenta": "POSSIBLE_EXFILTRATION", "envenenamento_mcp": "TOOL_POISONING",
    "rede_externa": "EXTERNAL_NETWORK_OR_REMOTE_SCRIPT", "shell_destrutivo": "DESTRUCTIVE_COMMAND", "leitura_env": "CREDENTIAL_FILE_ACCESS",
    "codigo_proprietario": "SOURCE_CODE_EXPOSURE", "instalacao_pacote": "PACKAGE_INSTALL", "alteracao_permissao": "PERMISSION_CHANGE",
}
IMPACT = {
    "segredo": "Acesso indevido a sistemas, contas ou dados se a credencial for real e tiver sido exposta a uma ferramenta de IA.",
    "financeiro": "Fraude financeira ou vazamento de dados de pagamento e de conta bancária.",
    "pii": "Exposição de dados pessoais de titulares (LGPD/GDPR) a um terceiro que processa o prompt.",
    "rede_externa": "Execução de código de origem não verificada ou envio de dados para um destino externo.",
    "exfiltracao_ferramenta": "Saída de dados da empresa por uma ferramenta de IA ou de agente.",
    "codigo_proprietario": "Perda de propriedade intelectual e exposição de lógica interna.",
}
RECOMMENDATION = {
    "segredo": "Verificar se a credencial é real e, se confirmado, avaliar sua revogação conforme o processo de resposta a incidentes da organização.",
    "financeiro": "Verificar se os dados bancários ou do cartão são reais e orientar o usuário conforme a política da organização; avaliar comunicação ao banco, se confirmado.",
    "pii": "Verificar se são dados reais de titulares e se o compartilhamento tem base legal; registrar conforme o processo de privacidade da organização.",
    "rede_externa": "Verificar o destino e a origem do comando; confirmar com o usuário se foi uma tentativa legítima, sem presumir ataque.",
    "exfiltracao_ferramenta": "Investigar para onde e o quê foi enviado; correlacionar com outros eventos do mesmo usuário e da mesma sessão.",
    "injection_direta": "Revisar o contexto: pode ser teste legítimo de segurança ou tentativa de contornar políticas da ferramenta de IA.",
    "injection_indireta": "Identificar a origem do conteúdo (documento, página ou resultado de ferramenta) que carregou a instrução.",
    "extracao_system_prompt": "Revisar o contexto: tentativa de obter instruções internas da ferramenta de IA.",
    "jailbreak": "Revisar o contexto: tentativa de remover restrições da ferramenta de IA.",
}
CODE_IMPACT = "O código pode ser propriedade intelectual da empresa (lógica interna, credenciais embutidas, estrutura de sistemas) e agora está com uma ferramenta de IA."
CODE_RECOMMENDATION = ("Risco baixo, apenas informativo: verificar se o código é proprietário ou traz lógica interna da empresa e se o uso desta ferramenta de IA "
                       "é permitido pela política da organização.")
DEFAULT_RECOMMENDATION = "Revisar o contexto do prompt e decidir, conforme a política da organização, se há necessidade de acompanhamento."
NO_AUTO = "Nenhuma recomendação é executada automaticamente."


def finding_type(row: Mapping[str, Any]) -> str:
    t = str(row.get("type") or "")
    return TYPE_NAME.get(t) or CATEGORY_NAME.get(str(row.get("category") or "")) or (t or str(row.get("category") or "UNKNOWN")).upper()


def _finding_severity(category: str, confidence: float) -> str:
    cats = load()
    base = _RISK_TO_SEVERITY.get(cats[category].risco_padrao, "medio") if category in cats else "medio"
    if confidence < 0.7:     # confiança menor rebaixa um degrau: um possível dado não vale como um confirmado
        base = {"critico": "alto", "alto": "medio", "medio": "baixo", "baixo": "baixo"}[base]
    return base


def to_v2(*, risk_score: int, categories: Sequence[Mapping[str, Any]], findings: Sequence[Mapping[str, Any]], masked_prompt: str,
          reasons: Sequence[Mapping[str, Any]] = (), engine_version: str = ENGINE_VERSION) -> dict[str, Any]:
    sev = severity_for(int(risk_score))
    rows = []
    for f in findings:
        conf = float(f.get("confidence", 0))
        if conf < THRESHOLD:
            continue
        cat = str(f.get("category") or "")
        is_code = f.get("type") == "code_shared"
        fsev = f.get("severity") if f.get("severity") in SEVERITY_EN else _finding_severity(cat, conf)     # o achado pode trazer a própria severidade (código = baixo)
        rows.append({"type": finding_type(f), "category": cat, "severity": SEVERITY_EN[fsev], "confidence": round(conf, 2),
                     "reason": f.get("rule"), "evidence": f.get("evidence"), "impact": CODE_IMPACT if is_code else IMPACT.get(cat)})
    top = max(categories, key=lambda c: c.get("confidence", 0), default=None)
    ranked = sorted(reasons, key=lambda r: -int(r.get("contribution", 0)))
    lead = next((r.get("category") for r in ranked if r.get("category")), top["id"] if top else None)
    only_code = any(r["type"] == "SOURCE_CODE_SHARED" for r in rows) and all(r["category"] in ("codigo_proprietario", "revisao_codigo") for r in rows) and sev == "baixo"   # só código (ou pedido de revisão dele), risco baixo
    rec = CODE_RECOMMENDATION if only_code else (RECOMMENDATION.get(lead or "", DEFAULT_RECOMMENDATION) if rows else "Sem achados: nenhuma ação recomendada.")
    return {
        "risk_score": int(risk_score),
        "severity": SEVERITY_EN[sev],
        "monitoring_mode": "passive",
        "detected_categories": list(dict.fromkeys(r["type"] for r in rows)),
        "confidence": max((r["confidence"] for r in rows), default=0.0),
        "alert_level": ALERT_EN[sev],
        "action": "monitor",
        "masked_prompt": masked_prompt,
        "findings": rows,
        "reasons": [{"rule": r.get("rule"), "contribution": r.get("contribution")} for r in ranked],
        "recommendation": f"{rec} {NO_AUTO}" if rows else rec,
        "engine_version": engine_version,
    }


def from_analysis(a: Any) -> dict[str, Any]:
    """A partir do resultado do motor (`Analysis`)."""
    return to_v2(risk_score=a.risk["score"], categories=a.categories, findings=a.findings, masked_prompt=a.masked_text, reasons=a.risk.get("reasons", []),
                 engine_version=a.engine_version or ENGINE_VERSION)
