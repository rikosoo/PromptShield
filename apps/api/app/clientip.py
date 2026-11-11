"""IP de origem de uma requisição, com cabeçalho de proxy SÓ quando o administrador configurou quantos proxies de confiança existem à frente da API.

Por padrão (`TRUSTED_PROXY_HOPS=0`) o cabeçalho `X-Forwarded-For` é IGNORADO: quem fala direto com a API poderia forjá-lo para escapar do limite ou
para pôr a culpa em outro IP. Com N proxies de confiança, vale a N-ésima entrada contada da DIREITA (a que o seu proxy mais próximo acrescentou);
valores que não são IP, ou cabeçalho com menos entradas que o esperado, voltam para o endereço da conexão."""
from __future__ import annotations

import ipaddress

from fastapi import Request

from app.config import settings


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
