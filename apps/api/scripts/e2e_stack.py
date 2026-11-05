"""Sobe a API de verdade para os testes ponta a ponta do console (Playwright).

Recria o esquema em DATABASE_URL_TEST (dono/superuser do banco de TESTE: ele é apagado), cria dois tenants,
usuários de cada papel, gera dados de exemplo no primeiro e serve a API. NUNCA aponte para um banco com dados.
Uso: DATABASE_URL_TEST=... python apps/api/scripts/e2e_stack.py --port 8099
"""
from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

API_DIR = Path(__file__).resolve().parents[1]
APP_PW = "e2e-app-role-password"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--count", type=int, default=300)
    args = ap.parse_args()
    admin_url = os.environ["DATABASE_URL_TEST"]
    app_url = make_url(admin_url).set(username="promptshield_app", password=APP_PW).render_as_string(hide_password=False)
    os.environ.update({
        "ADMIN_DATABASE_URL": admin_url, "DATABASE_URL": app_url, "APP_DB_PASSWORD": APP_PW,
        "OIDC_MODE": "mock", "OIDC_MOCK_SECRET": "e2e-mock-secret-with-more-than-32-chars",
        # só no banco de teste: o webhook de teste do console aponta para um servidor local
        "ALLOW_INSECURE_WEBHOOKS": "true", "ALLOW_PRIVATE_WEBHOOK_TARGETS": "true",
        "ORIGINAL_TEXT_MASTER_KEY": base64.urlsafe_b64encode(b"e2e-master-key-32-bytes-long!!!!"[:32]).decode(),
    })
    sys.path.insert(0, str(API_DIR))
    for step in ("downgrade base", "upgrade head"):
        subprocess.run([sys.executable, "-m", "alembic", *step.split()], cwd=API_DIR, check=True)

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.cli import create_tenant
    from app.demo import seed_demo
    from app.models import User

    with Session(create_engine(admin_url)) as s, s.begin():
        create_tenant(s, "Empresa Exemplo S.A.", "exemplo", "admin@empresa-exemplo.com.br")
        other = create_tenant(s, "Empresa Vazia Ltda.", "vazia", "admin@empresa-vazia.example.com")
        create_tenant(s, "Empresa Suspensa Ltda.", "suspensa", "admin@empresa-suspensa.example.com")
        tid = s.execute(text("SELECT id FROM tenants WHERE slug = 'exemplo'")).scalar_one()
        s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        for role in ("analista", "auditor", "leitura"):
            s.add(User(tenant_id=tid, email=f"{role}@empresa-exemplo.com.br", role=role, display_name=role.capitalize()))
        s.flush()
        print("tenant vazio:", other["tenant_id"], flush=True)
        from app.cli import set_suspension

        set_suspension(s, "suspensa", True, "fatura em atraso")
    with Session(create_engine(admin_url)) as s, s.begin():
        print(seed_demo(s, "exemplo", days=14, count=args.count), flush=True)

    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
