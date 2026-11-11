"""IP de origem, com X-Forwarded-For SÓ se o administrador disse quantos proxies de confiança há à frente (TRUSTED_PROXY_HOPS; padrão 0 = ignora o cabeçalho,
que quem fala direto com o serviço poderia forjar). Vale a N-ésima entrada contada da direita; valor que não é IP, ou cabeçalho curto, volta ao endereço da conexão."""
from __future__ import annotations

import ipaddress

from fastapi import Request

from lic_service.config import settings


def client_ip(request: Request, hops: int | None = None) -> str:
    peer = request.client.host if request.client else "?"
    n = settings.trusted_proxy_hops if hops is None else hops
    if n <= 0:
        return peer
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(parts) < n:
        return peer
    try:
        return str(ipaddress.ip_address(parts[-n]))
    except ValueError:
        return peer
