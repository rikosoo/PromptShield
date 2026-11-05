"""Mede a latência do endpoint dos inference hooks (só o NOSSO servidor: sem rede da Anthropic, sem TLS).

Recria o esquema em DATABASE_URL_TEST (banco de TESTE: é apagado), sobe a API real com uvicorn, cria um tenant com segredo e
chave de API, e envia requisições assinadas com conversas sintéticas que crescem a cada turno (o protocolo reenvia a transcrição
inteira). Uso: DATABASE_URL_TEST=... python apps/api/scripts/bench_inference_hook.py [--conversations 30] [--turns 8] [--workers 1]
"""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy.engine import make_url

API_DIR = Path(__file__).resolve().parents[1]
APP_PW = "bench-app-role-password"
SECRET = "whsec_" + base64.b64encode(os.urandom(32)).decode()
AWS = "AKIA" + "Z7QW4XK2M9PLR3TN"  # chave sintética


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8098)
    ap.add_argument("--conversations", type=int, default=30)
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--workers", type=int, default=1, help="conversas em paralelo")
    ap.add_argument("--mode", default="enforce", choices=["shadow", "enforce"])
    args = ap.parse_args()
    admin_url = os.environ["DATABASE_URL_TEST"]
    app_url = make_url(admin_url).set(username="promptshield_app", password=APP_PW).render_as_string(hide_password=False)
    os.environ.update({"ADMIN_DATABASE_URL": admin_url, "DATABASE_URL": app_url, "APP_DB_PASSWORD": APP_PW,
                       "ORIGINAL_TEXT_MASTER_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode()})
    sys.path.insert(0, str(API_DIR))
    for step in ("downgrade base", "upgrade head"):
        subprocess.run([sys.executable, "-m", "alembic", *step.split()], cwd=API_DIR, check=True)

    from promptshield_inference_hooks.signature import sign
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app import crypto
    from app.cli import create_tenant
    from app.models import InferenceHookConfig

    with Session(create_engine(admin_url)) as s, s.begin():
        t = create_tenant(s, "Tenant de medição (sintético)", "bench", "admin@bench.example.com")
        tid = uuid.UUID(t["tenant_id"])
        s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        s.add(InferenceHookConfig(tenant_id=tid, mode=args.mode, scope="full", secret_ciphertext=crypto.encrypt_secret(tid, SECRET)))
        s.execute(text("UPDATE policies SET mode = 'enforce'"))
    key = t["api_key"]

    import uvicorn

    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            c = http.client.HTTPConnection("127.0.0.1", args.port, timeout=2)
            c.request("GET", "/health")
            if c.getresponse().status == 200:
                break
        except OSError:
            time.sleep(0.1)

    lat: dict[str, list[float]] = {"prompt": [], "tool_call": []}
    verdicts: dict[str, int] = {}
    lock = threading.Lock()
    paragraph = "Preciso de ajuda com o relatório trimestral do departamento. " * 12  # ~700 caracteres por mensagem

    def conversation(n: int) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", args.port, timeout=15)
        history: list[dict] = []
        session = f"bench-{n}-{uuid.uuid4().hex[:6]}"
        for turn in range(args.turns):
            risky = turn == args.turns - 1 and n % 5 == 0
            text_in = f"{paragraph} turno {turn} da conversa {n}" + (f" a chave é {AWS}" if risky else "")
            history.append({"role": "user", "content": [{"type": "text", "text": text_in}]})
            for ftype, messages in (("prompt", history), ("tool_call", [{"role": "assistant", "content": [
                    {"type": "text", "text": "vou executar"}, {"type": "tool_use", "id": f"t{n}-{turn}", "tool_name": "bash",
                                                                "input": {"command": f"ls -la /tmp/projeto{turn}"}, "tool_info": {"type": "client"}}]}])):
                rid = f"req_{uuid.uuid4().hex}"
                body = json.dumps({"type": ftype, "request_id": rid, "tenant_id": "11111111-1111-1111-1111-111111111111",
                                   "actor": {"type": "user", "id": f"user_{n}", "email_address": f"pessoa{n}@bench.example.com"},
                                   "source": {"application": "claude-ai"}, "session_id": session, "model": "claude-sonnet-4-5",
                                   "messages": messages, "metadata": {}}).encode()
                ts = int(time.time())
                headers = {"Content-Type": "application/json", "X-API-Key": key, "webhook-id": rid, "webhook-timestamp": str(ts),
                           "webhook-signature": sign(SECRET, rid, ts, body)}
                t0 = time.perf_counter()
                conn.request("POST", "/v1/inference-hook", body=body, headers=headers)
                resp = conn.getresponse()
                data = json.loads(resp.read())
                ms = (time.perf_counter() - t0) * 1000
                assert resp.status == 200, resp.status
                with lock:
                    lat[ftype].append(ms)
                    verdicts[data["action"]] = verdicts.get(data["action"], 0) + 1
            if risky:
                history.pop()  # o usuário edita a mensagem negada

    start = time.perf_counter()
    threads = []
    for n in range(args.conversations):
        while sum(t.is_alive() for t in threads) >= args.workers:
            time.sleep(0.01)
        th = threading.Thread(target=conversation, args=(n,))
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    wall = time.perf_counter() - start
    server.should_exit = True

    print(f"\nmodo={args.mode} conversas={args.conversations} turnos={args.turns} em paralelo={args.workers} "
          f"({sum(len(v) for v in lat.values())} requisições em {wall:.1f}s); vereditos: {verdicts}")
    for k, v in lat.items():
        print(f"  {k:9s} n={len(v):4d}  p50={statistics.median(v):6.1f} ms  p95={pct(v, 0.95):6.1f} ms  p99={pct(v, 0.99):6.1f} ms  max={max(v):6.1f} ms")
    allv = lat["prompt"] + lat["tool_call"]
    print(f"  {'todas':9s} n={len(allv):4d}  p50={statistics.median(allv):6.1f} ms  p95={pct(allv, 0.95):6.1f} ms  p99={pct(allv, 0.99):6.1f} ms")


if __name__ == "__main__":
    main()
