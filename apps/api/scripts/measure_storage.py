"""Mede o tamanho REAL no PostgreSQL de cada prompt guardado (e projeta 30 dias). DADOS SINTÉTICOS (simulados), banco DESCARTÁVEL.

Cria o banco `<nome>_sizing`, aplica as migrações, envia N eventos sintéticos pela API de verdade (mistura de tamanhos de texto e de achados), mede
tabelas+índices e o `pg_dump` (tamanho do backup) e APAGA o banco. Uso:
    DATABASE_URL_TEST=postgresql+psycopg://postgres@/postgres?host=/tmp&port=5433 python apps/api/scripts/measure_storage.py --events 4000 [--store-original]
A distribuição de tamanhos é uma SUPOSIÇÃO (veja MIX); troque pela sua depois de medir um piloto real."""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

API_DIR = Path(__file__).resolve().parents[1]
APP_PW = "sizing-app-role-password"
# (peso, caracteres típicos do texto, descrição). SUPOSIÇÃO: conversa curta, pedido médio, colagem de código/documento, colagem enorme.
MIX = [(0.55, 250, "pergunta curta"), (0.30, 1500, "pedido médio"), (0.12, 6000, "colagem de código/documento"), (0.03, 20000, "colagem enorme")]
WORDS = ("cliente contrato projeto relatório servidor deploy banco dados função erro teste versão ambiente produção rede acesso usuário senha "
         "análise resumo proposta reunião prazo entrega pagamento fatura equipe sistema modelo código revisão configuração integração").split()
SECRETS = ["use AKIAZ7QW4XK2M9PLR3TN no deploy", "CPF 111.444.777-35 do cliente", "token ghp_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "email maria.silva@exemplo.test"]


def text_of(n: int, rng: random.Random) -> str:
    out, size = [], 0
    while size < n:
        w = rng.choice(WORDS) + rng.choice(["", "", ".", ",", " de", " do"])
        out.append(w)
        size += len(w) + 1
    return " ".join(out)[:n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=4000)
    ap.add_argument("--store-original", action="store_true", help="guarda também o texto original cifrado (recurso opcional do tenant)")
    ap.add_argument("--sensitive", type=float, default=0.15, help="fração de prompts com dado sensível (SUPOSIÇÃO)")
    a = ap.parse_args()
    base = make_url(os.environ["DATABASE_URL_TEST"])
    name = "ps_sizing"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        c.execute(text(f"CREATE DATABASE {name}"))
    admin_url = base.set(database=name).render_as_string(hide_password=False)
    app_url = base.set(database=name, username="promptshield_app", password=APP_PW).render_as_string(hide_password=False)
    os.environ.update({"ADMIN_DATABASE_URL": admin_url, "DATABASE_URL": app_url, "APP_DB_PASSWORD": APP_PW, "OIDC_MODE": "off",
                       "RATE_LIMIT_KEY_PER_MINUTE": "0", "LOG_JSON": "false",
                       "ORIGINAL_TEXT_MASTER_KEY": base64.urlsafe_b64encode(b"sizing-master-key-32-bytes-long!!"[:32]).decode()})
    sys.path.insert(0, str(API_DIR))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, check=True, capture_output=True)
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.cli import create_tenant
    from app.main import app

    eng = create_engine(admin_url)
    with Session(eng) as s, s.begin():
        info = create_tenant(s, "Empresa Simulada", "empresa-simulada", "admin@simulada.example.com")
        if a.store_original:
            s.execute(text("UPDATE tenants SET store_original = true WHERE id = :t"), {"t": info["tenant_id"]})
    rng = random.Random(7)
    client, hdr = TestClient(app), {"X-API-Key": info["api_key"]}
    weights, sizes = [m[0] for m in MIX], [m[1] for m in MIX]
    sent = chars = 0
    for i in range(a.events):
        kind, n = ("tool_call", 120) if rng.random() < 0.2 else ("prompt", rng.choices(sizes, weights)[0])
        t = text_of(int(n * rng.uniform(0.6, 1.4)), rng)
        if kind == "prompt" and rng.random() < a.sensitive:
            t = rng.choice(SECRETS) + " " + t
        ev = {"event_id": str(uuid.uuid4()), "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "source": {"channel": "browser", "app": "chatgpt_web", "integration_status": "partial"},
              "actor": {"user_id": f"user-{rng.randrange(200):03d}", "department": rng.choice(["Engenharia", "Financeiro", "Comercial", "RH"]), "device_id": f"dev-{rng.randrange(200):03d}"},
              "kind": kind, "content": {"text": t, "tool_name": "Bash" if kind == "tool_call" else None}, "context": {"session_id": f"s{rng.randrange(5000)}", "personal_account": False}}
        r = client.post("/v1/events", json=ev, headers=hdr)
        if r.status_code != 200:
            raise SystemExit(f"evento {i} recusado: {r.status_code} {r.text[:200]}")
        sent += 1
        chars += len(t)
    with create_engine(admin_url, isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text("VACUUM ANALYZE"))
    with eng.connect() as c:
        rows = c.execute(text("""SELECT relname, pg_total_relation_size(c.oid) AS total, pg_relation_size(c.oid) AS heap, c.reltuples::bigint AS rows
                                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'
                                 AND pg_total_relation_size(c.oid) > 65536 ORDER BY 2 DESC""")).all()
        db_total = c.execute(text("SELECT pg_database_size(current_database())")).scalar()
        empty = c.execute(text("SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'")).scalar()
    host = base.query.get("host") or base.host or "localhost"
    dump = subprocess.run(["pg_dump", "-Fc", "-h", str(host), "-p", str(base.query.get("port") or base.port or 5432), "-U", base.username or "postgres", name],
                          capture_output=True, check=True, env={**os.environ, "PGPASSWORD": base.password or ""}).stdout
    out = {"events": sent, "store_original": a.store_original, "avg_text_chars": round(chars / sent), "sensitive_fraction": a.sensitive,
           "tables_total_bytes": int(empty), "bytes_per_event_all_tables": round(int(empty) / sent), "dump_custom_bytes": len(dump), "dump_bytes_per_event": round(len(dump) / sent),
           "database_size_bytes": int(db_total),
           "tables": [{"table": r[0], "total_bytes": int(r[1]), "per_event": round(int(r[1]) / sent), "rows": int(r[3])} for r in rows[:8]]}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


if __name__ == "__main__":
    main()
