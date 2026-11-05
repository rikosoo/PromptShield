"""Administração pelo fornecedor (venda e renovação manuais). Saída em português; o código de ativação aparece UMA vez."""
from __future__ import annotations

import argparse
import base64
import sys
import uuid

from promptshield_licensing import generate_signing_key, public_key_b64
from promptshield_licensing.crypto import private_pem
from sqlalchemy import select

from lic_service import service
from lic_service.db import session_scope
from lic_service.models import ActivationCode, AuditEntry, Contract, Customer, Installation, IssuedAuthorization


def _contract(s, ref: str) -> Contract:
    try:
        c = s.get(Contract, uuid.UUID(ref))
    except ValueError:
        c = None
    if c is None:
        raise SystemExit(f"contrato não encontrado: {ref}")
    return c


def _fmt(dt) -> str:
    return dt.strftime("%d/%m/%Y %H:%M") if dt else "—"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m lic_service.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-key", help="gera a chave de assinatura do fornecedor (guarde a privada como segredo; a pública vai no produto do cliente)")
    c = sub.add_parser("create-customer"); c.add_argument("--name", required=True); c.add_argument("--email")  # noqa: E702
    k = sub.add_parser("create-contract", help="cadastra um contrato (pendente: o prazo conta a partir da ativação)")
    k.add_argument("--customer", required=True, help="id do cliente"); k.add_argument("--devices", type=int, required=True)  # noqa: E702
    k.add_argument("--months", type=int, required=True); k.add_argument("--tolerance-days", type=int, default=15)  # noqa: E702
    k.add_argument("--on-end", choices=["stop_inspection", "keep_inspection"], default="stop_inspection", help="o que acontece com a inspeção se o contrato for ENCERRADO")
    k.add_argument("--auth-days", type=int, default=7, help="validade de cada autorização sem renovar"); k.add_argument("--note")  # noqa: E702
    i = sub.add_parser("issue-code", help="gera o código de ativação de uso único"); i.add_argument("--contract", required=True); i.add_argument("--days", type=int, default=7)  # noqa: E702
    sub.add_parser("contracts", help="lista contratos, estado e última comunicação")
    sh = sub.add_parser("show"); sh.add_argument("--contract", required=True)  # noqa: E702
    cl = sub.add_parser("close", help="encerra o contrato (a instalação fica sabendo na próxima renovação)"); cl.add_argument("--contract", required=True); cl.add_argument("--reason", required=True)  # noqa: E702
    ro = sub.add_parser("reopen"); ro.add_argument("--contract", required=True)  # noqa: E702
    ex = sub.add_parser("extend", help="renova o contrato por mais N meses"); ex.add_argument("--contract", required=True); ex.add_argument("--months", type=int, required=True)  # noqa: E702
    de = sub.add_parser("set-devices"); de.add_argument("--contract", required=True); de.add_argument("--devices", type=int, required=True)  # noqa: E702
    ub = sub.add_parser("unbind", help="desvincula a instalação (troca de servidor); exige novo código"); ub.add_argument("--contract", required=True)  # noqa: E702
    au = sub.add_parser("audit"); au.add_argument("--contract")  # noqa: E702
    a = ap.parse_args(argv)
    now = service.utcnow()

    if a.cmd == "gen-key":
        key = generate_signing_key()
        print("LICENSE_SIGNING_KEY=" + base64.b64encode(private_pem(key)).decode())
        print(f"# chave pública (vai no produto do cliente como LICENSE_PUBLIC_KEY): {public_key_b64(key)}", file=sys.stderr)
        return
    with session_scope() as s:
        if a.cmd == "create-customer":
            print("cliente:", service.create_customer(s, a.name, a.email).id)
        elif a.cmd == "create-contract":
            cust = s.get(Customer, uuid.UUID(a.customer))
            if cust is None:
                raise SystemExit("cliente não encontrado")
            k = service.create_contract(s, cust, a.devices, a.months, tolerance_days=a.tolerance_days, on_end=a.on_end, validity_days=a.auth_days, note=a.note)
            print("contrato:", k.id, "(pendente; gere o código com issue-code)")
        elif a.cmd == "issue-code":
            code = service.issue_code(s, _contract(s, a.contract), now, a.days)
            print(f"código de ativação (aparece uma vez, vale {a.days} dia(s), uso único):\n{code}")
        elif a.cmd == "contracts":
            for k, name in s.execute(select(Contract, Customer.name).join(Customer, Customer.id == Contract.customer_id).order_by(Contract.created_at)).all():
                inst = s.execute(select(Installation).where(Installation.contract_id == k.id, Installation.unbound_at.is_(None))).scalar()
                last = inst.last_seen_at if inst else None
                print(f"{k.id}  {name:24s} {k.status:9s} máquinas {k.max_devices:5d}  fim {_fmt(k.ends_at)}  instalação {'sim' if inst else 'não'}  último contato {_fmt(last)}")
        elif a.cmd == "show":
            k = _contract(s, a.contract)
            print(f"contrato {k.id}: {k.status}, {k.max_devices} máquinas, {k.term_months} meses, tolerância {k.tolerance_days} dia(s), ao encerrar: {k.on_end}")
            print(f"início {_fmt(k.starts_at)}  fim {_fmt(k.ends_at)}  encerrado {_fmt(k.closed_at)} {k.close_reason or ''}")
            for ac in s.execute(select(ActivationCode).where(ActivationCode.contract_id == k.id)).scalars():
                print(f"  código {ac.prefix}…  expira {_fmt(ac.expires_at)}  {'USADO ' + _fmt(ac.used_at) if ac.used_at else 'não usado'}")
            for inst in s.execute(select(Installation).where(Installation.contract_id == k.id)).scalars():
                print(f"  instalação {inst.installation_id} {inst.hostname or ''}  {'ATIVA' if inst.unbound_at is None else 'desvinculada'}  último contato {_fmt(inst.last_seen_at)}  máquinas {inst.last_device_count}")
            last = s.execute(select(IssuedAuthorization).where(IssuedAuthorization.contract_id == k.id).order_by(IssuedAuthorization.serial.desc()).limit(1)).scalar()
            if last:
                print(f"  última autorização: nº {last.serial} ({last.kind}, {last.status}) vale até {_fmt(last.auth_expires)}")
        elif a.cmd == "close":
            service.close_contract(s, _contract(s, a.contract), a.reason, now)
            print("encerrado")
        elif a.cmd == "reopen":
            service.reopen_contract(s, _contract(s, a.contract), now)
            print("reaberto")
        elif a.cmd == "extend":
            service.extend_contract(s, _contract(s, a.contract), a.months)
            print("renovado")
        elif a.cmd == "set-devices":
            service.set_devices(s, _contract(s, a.contract), a.devices)
            print("ok (a instalação vê na próxima renovação)")
        elif a.cmd == "unbind":
            service.unbind(s, _contract(s, a.contract), now)
            print("desvinculada; gere um código novo")
        elif a.cmd == "audit":
            q = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(50)
            if a.contract:
                q = q.where(AuditEntry.contract_id == uuid.UUID(a.contract))
            for e in s.execute(q).scalars():
                print(f"{_fmt(e.at)}  {e.actor[:12]:12s} {e.action:24s} {e.detail}")


if __name__ == "__main__":
    try:
        main()
    except service.ServiceError as exc:
        raise SystemExit(f"erro: {exc.detail}") from exc
