"""Operação: cria tenant com admin, chave de API e políticas padrão (todas em modo monitor).

    python -m app.cli create-tenant --name "Empresa" --slug empresa --admin-email admin@empresa.com.br

Usa ADMIN_DATABASE_URL (dono do banco). A chave de API é impressa uma única vez.
"""
from __future__ import annotations

import argparse
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApiKey, Tenant, User
from app.security import generate_api_key
from app.services import seed_default_policies


def create_tenant(session: Session, name: str, slug: str, admin_email: str, key_name: str = "coletor-padrao") -> dict[str, str]:
    tenant_id = uuid.uuid4()
    session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    session.add(Tenant(id=tenant_id, name=name, slug=slug))
    session.flush()
    admin = User(tenant_id=tenant_id, email=admin_email, role="admin", display_name="Administrador")
    session.add(admin)
    key, prefix, digest = generate_api_key()
    session.add(ApiKey(tenant_id=tenant_id, name=key_name, prefix=prefix, key_hash=digest, scopes=["ingest"]))
    seed_default_policies(session, tenant_id)
    session.flush()
    return {"tenant_id": str(tenant_id), "admin_user_id": str(admin.id), "api_key": key}


def set_suspension(session: Session, slug: str, suspended: bool, reason: str | None = None) -> dict:
    """Suspende ou reativa uma empresa (só o fornecedor, pelo CLI). Reversível: nenhum dado é apagado. Fica na auditoria da empresa."""
    from datetime import datetime, timezone

    from app import audit_system

    tid = session.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug}).scalar_one_or_none()
    if tid is None:
        raise SystemExit(f"empresa não encontrada: {slug}")
    session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
    t = session.get(Tenant, tid)
    was = t.suspended_at is not None
    t.suspended_at = datetime.now(timezone.utc) if suspended and not was else (t.suspended_at if suspended else None)
    t.suspended_reason = (reason or "")[:200] or None if suspended else None
    session.flush()
    audit_system.write(session, tid, "tenant.suspend" if suspended else "tenant.resume", "tenant", str(tid),
                       {"reason": t.suspended_reason, "was_suspended": was}, actor_id="fornecedor")
    return {"slug": slug, "suspended": suspended, "was_suspended": was, "reason": t.suspended_reason}


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-tenant")
    c.add_argument("--name", required=True)
    c.add_argument("--slug", required=True)
    c.add_argument("--admin-email", required=True)
    d = sub.add_parser("seed-demo", help="gera eventos SINTÉTICOS e marca o tenant como demonstração")
    d.add_argument("--slug", required=True)
    d.add_argument("--days", type=int, default=14)
    d.add_argument("--count", type=int, default=400)
    u = sub.add_parser("create-user")
    u.add_argument("--slug", required=True)
    u.add_argument("--email", required=True)
    u.add_argument("--role", required=True, choices=["admin", "analista", "auditor", "leitura"])
    lic = sub.add_parser("set-license", help="define o limite de máquinas ativas (45 dias) e a validade da licença de uma empresa (só o fornecedor)")
    lic.add_argument("--slug", required=True)
    g = lic.add_mutually_exclusive_group()
    g.add_argument("--max-devices", type=int, help="limite de máquinas ativas; 0 bloqueia novas matrículas")
    g.add_argument("--unlimited", action="store_true", help="remove o limite")
    e = lic.add_mutually_exclusive_group()
    e.add_argument("--expires", help="validade AAAA-MM-DD (UTC, fim do dia)")
    e.add_argument("--no-expiry", action="store_true", help="remove a validade")
    sp = sub.add_parser("suspend", help="suspende uma empresa (inadimplência/encerramento): para a coleta e as alterações, mantém os dados (reversível)")
    sp.add_argument("--slug", required=True)
    sp.add_argument("--reason", default="", help="texto curto que o administrador da empresa vê no console (ex.: fatura em atraso)")
    rs = sub.add_parser("resume", help="reativa uma empresa suspensa")
    rs.add_argument("--slug", required=True)
    sub.add_parser("tenants", help="lista as empresas: situação do contrato, validade, limite e máquinas ativas (só o fornecedor)")
    sub.add_parser("rewrap-keys", help="troca a chave mestra: reembrulha as chaves de dados (lê OLD_MASTER_KEY e NEW_MASTER_KEY do ambiente)")
    args = ap.parse_args()
    url = settings.admin_database_url or settings.database_url
    if args.cmd == "seed-demo":
        from app.demo import seed_demo

        with Session(create_engine(url)) as s, s.begin():
            print(seed_demo(s, args.slug, args.days, args.count))
        return
    if args.cmd == "set-license":
        from datetime import datetime, timedelta, timezone

        from app import license as lic_mod

        with Session(create_engine(url)) as s, s.begin():
            tid = s.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": args.slug}).scalar_one_or_none()
            if tid is None:
                raise SystemExit(f"empresa não encontrada: {args.slug}")
            s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
            t = s.get(Tenant, tid)
            if args.max_devices is not None:
                if args.max_devices < 0:
                    raise SystemExit("--max-devices precisa ser 0 ou mais")
                t.max_devices = args.max_devices
            if args.unlimited:
                t.max_devices = None
            if args.expires:
                t.license_expires_at = datetime.strptime(args.expires, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            if args.no_expiry:
                t.license_expires_at = None
            s.flush()
            print(lic_mod.summary(s, t))
        return
    if args.cmd in ("suspend", "resume"):
        with Session(create_engine(url)) as s, s.begin():
            print(set_suspension(s, args.slug, args.cmd == "suspend", getattr(args, "reason", None)))
        return
    if args.cmd == "tenants":
        from app import license as lic_mod

        with Session(create_engine(url)) as s, s.begin():
            for tid, slug, name in s.execute(text("SELECT id, slug, name FROM tenants ORDER BY created_at")).all():
                s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
                t = s.get(Tenant, tid)
                info = lic_mod.summary(s, t)
                state = "SUSPENSA" if t.suspended_at else "vencida" if info["expired"] else "ativa"
                print(f"{slug:24s} {state:9s} máquinas {info['active_seats']}/{info['max_devices'] if info['max_devices'] is not None else '∞'}  "
                      f"validade {info['expires_at'] or '—'}  {name}")
        return
    if args.cmd == "rewrap-keys":
        import os

        from app import crypto

        old, new = os.environ.get("OLD_MASTER_KEY"), os.environ.get("NEW_MASTER_KEY")
        if not old or not new or old == new:
            raise SystemExit("defina OLD_MASTER_KEY e NEW_MASTER_KEY (diferentes), em base64 urlsafe de 32 bytes")
        with Session(create_engine(url)) as s, s.begin():
            print("chaves reembrulhadas:", crypto.rewrap_keys(s, old, new))
        return
    if args.cmd == "create-user":
        with Session(create_engine(url)) as s, s.begin():
            tid = s.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": args.slug}).scalar_one()
            s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
            s.add(User(tenant_id=tid, email=args.email, role=args.role))
        print("criado:", args.email, args.role)
        return
    with Session(create_engine(url)) as s, s.begin():
        out = create_tenant(s, args.name, args.slug, args.admin_email)
    print(f"tenant_id:  {out['tenant_id']}\nadmin:      {args.admin_email}\napi_key:    {out['api_key']}\n"
          "Guarde a chave agora: ela não pode ser recuperada.")


if __name__ == "__main__":
    main()
