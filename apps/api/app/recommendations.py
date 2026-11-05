"""Recomendação de resposta por categoria (texto em português para o analista). Regras fixas e versionadas com o código."""
from __future__ import annotations

from typing import Any

BY_CATEGORY: dict[str, str] = {
    "segredo": "Revogar e rotacionar a credencial exposta agora; conferir se ela foi usada e orientar o usuário a usar um cofre de segredos.",
    "pii": "Orientar o usuário sobre dados pessoais em ferramentas de IA (LGPD); avaliar se o dado precisa ser comunicado ao encarregado (DPO).",
    "financeiro": "Confirmar se o dado financeiro era do próprio usuário ou de cliente; avaliar bloqueio de cartões e comunicação ao financeiro.",
    "saude": "Dado de saúde é sensível pela LGPD: acionar o encarregado (DPO) e avaliar a necessidade de comunicação.",
    "shell_destrutivo": "Contatar o usuário e o dono do agente; conferir se o comando chegou a rodar; limitar as permissões de shell do agente.",
    "leitura_env": "Verificar se a credencial lida saiu do ambiente; rotacionar as chaves do arquivo e restringir o acesso do agente a esses caminhos.",
    "exfiltracao_ferramenta": "Tratar como possível vazamento: isolar o agente, revogar tokens e revisar o destino do envio.",
    "injection_indireta": "Identificar a origem do conteúdo (arquivo, página ou ferramenta) e removê-la; revisar o que o agente fez depois.",
    "injection_direta": "Revisar a conversa; se houve tentativa deliberada, orientar o usuário e avaliar política de uso.",
    "envenenamento_mcp": "Desativar o servidor ou a ferramenta MCP suspeita e revisar as ações do agente após a chamada.",
    "rede_externa": "Conferir o destino; se legítimo, incluir na lista permitida; se não, bloquear e investigar o agente.",
    "instalacao_pacote": "Verificar a reputação do pacote e da origem; exigir repositório aprovado.",
    "alteracao_permissao": "Reverter a alteração de permissão e revisar quem a pediu.",
    "escrita_fora_projeto": "Conferir o arquivo alterado fora do projeto e restaurar, se necessário.",
}
DEFAULT = "Revisar o contexto com o usuário e decidir entre orientação, exceção ou ajuste da política."


def recommend(categories: list[dict[str, Any]], decision: str, would_decide: str) -> list[str]:
    out = [BY_CATEGORY[c["id"]] for c in sorted(categories, key=lambda c: -c["confidence"])
           if c["confidence"] >= 0.5 and c["id"] in BY_CATEGORY]
    if would_decide in ("block", "mask", "ask_justification") and decision == "allow":
        out.append("A política estava em modo monitorar: o envio não foi impedido. Considere passar a política para aplicar depois de revisar os falsos positivos.")
    return out or [DEFAULT]
