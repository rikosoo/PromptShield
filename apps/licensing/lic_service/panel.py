"""Painel web do fornecedor (/painel): visão dos contratos e alertas, edição de prazos e condições, código de ativação, pacotes para download e auditoria.

Só existe com PANEL_ENABLED=true. Feito para UMA pessoa (ou poucas) da sua empresa: ponha atrás de VPN/lista de IPs e de HTTPS (docs/painel-fornecedor.md).
Páginas em HTML gerado no servidor (Jinja2 com escape automático: nada de `|safe`), formulários comuns, sem JavaScript. Toda alteração: sessão assinada,
cabeçalho de origem conferido, token CSRF e registro na auditoria com o e-mail de quem fez."""
from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from lic_service import packages, panel_auth, service
from lic_service.config import settings
from lic_service.db import session_scope
from lic_service.models import ActivationCode, Admin, AuditEntry, Contract, Customer, Installation, IssuedAuthorization, Release

router = APIRouter(prefix="/painel", include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
BRT = timezone(timedelta(hours=-3))          # horário de Brasília (sem horário de verão desde 2019)
SESSION_COOKIE, FLASH_COOKIE = "lic_session", "lic_flash"
LOGIN_ERROR = "E-mail, senha ou código incorretos, ou acesso bloqueado por tentativas seguidas (tente de novo em alguns minutos)."


def _dt(v: datetime | None, with_time: bool = True) -> str:
    if v is None:
        return "—"
    return v.astimezone(BRT).strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def _since(v: datetime | None, now: datetime) -> str:
    if v is None:
        return "nunca"
    d = now - v
    if d < timedelta(hours=1):
        return "agora há pouco"
    return f"há {d.days} dia(s)" if d >= timedelta(days=1) else f"há {int(d.total_seconds() // 3600)} h"


templates.env.filters["dt"] = _dt
templates.env.filters["d"] = lambda v: _dt(v, False)
templates.env.filters["since"] = _since
templates.env.filters["size"] = packages.fmt_size


def _on() -> None:
    if not settings.panel_enabled:
        raise HTTPException(404)


@dataclass(frozen=True)
class Auth:
    admin_id: uuid.UUID
    email: str
    csrf: str


def _go(url: str) -> HTTPException:
    return HTTPException(303, headers={"Location": url})


def _auth(request: Request) -> Auth:
    _on()
    data = panel_auth.read_session(request.cookies.get(SESSION_COOKIE))
    if not data:
        raise _go("/painel/entrar")
    with session_scope() as s:
        a = s.get(Admin, uuid.UUID(data["a"])) if data.get("a") else None
        if a is None or not a.active or a.password_version != data.get("pv"):
            raise _go("/painel/entrar")
        return Auth(a.id, a.email, str(data["csrf"]))


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
        raise HTTPException(403, "origem não permitida")


def _check(request: Request, auth: Auth, csrf: str) -> None:
    _same_origin(request)
    if not hmac.compare_digest(csrf or "", auth.csrf):
        raise HTTPException(403, "pedido recusado (token inválido); recarregue a página")


def _cookie_kw(max_age: int) -> dict[str, Any]:
    return dict(httponly=True, samesite="strict", secure=settings.panel_cookie_secure, path="/painel", max_age=max_age)


def _flash(resp: Response, text: str, ok: bool = True) -> Response:
    resp.set_cookie(FLASH_COOKIE, panel_auth.sign_payload({"t": text, "ok": ok}, 120, b"flash"), **_cookie_kw(120))
    return resp


def _render(request: Request, name: str, auth: Auth | None, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    flash = panel_auth.read_payload(request.cookies.get(FLASH_COOKIE), b"flash")
    resp = templates.TemplateResponse(request, name, {"auth": auth, "csrf": auth.csrf if auth else "", "now": service.utcnow(), "flash": flash, **ctx}, status_code=status_code)
    if flash:
        resp.delete_cookie(FLASH_COOKIE, path="/painel")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'"
    return resp


def _opt_int(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v else None


def _int(v: str, label: str) -> int:
    try:
        return int(v.strip())
    except ValueError as exc:
        raise service.ServiceError("bad_number", f"{label}: informe um número inteiro") from exc


def _contract(s, cid: str) -> Contract:
    try:
        k = s.get(Contract, uuid.UUID(cid))
    except ValueError:
        k = None
    if k is None:
        raise HTTPException(404, "contrato não encontrado")
    return k


def _back(cid: str, auth_msg: str | None = None, ok: bool = True) -> RedirectResponse:
    r = RedirectResponse(f"/painel/contratos/{cid}", 303)
    return _flash(r, auth_msg, ok) if auth_msg else r  # type: ignore[return-value]


# ---------------------------------------------------------------- entrar e sair
@router.get("")
@router.get("/")
def home(request: Request) -> Response:
    _on()
    return RedirectResponse("/painel/visao-geral", 303)


@router.get("/entrar", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    _on()
    return _render(request, "login.html", None, totp_required=settings.panel_require_totp)


@router.post("/entrar")
def login(request: Request, email: str = Form(""), password: str = Form(""), code: str = Form("")) -> Response:
    _on()
    _same_origin(request)
    ip = request.client.host if request.client else "?"
    if panel_auth.too_many(f"ip:{ip}", 20) or panel_auth.too_many(f"mail:{email.strip().lower()}", 10) or panel_auth.too_many("all", 200):
        return _render(request, "login.html", None, 429, error="Muitas tentativas; aguarde um minuto.", totp_required=settings.panel_require_totp)
    now = service.utcnow()
    ok, cookie, csrf = False, "", ""
    with session_scope() as s:
        a = s.execute(select(Admin).where(func.lower(Admin.email) == email.strip().lower(), Admin.active.is_(True))).scalar()
        locked = a is not None and a.locked_until is not None and a.locked_until > now
        pw_ok = panel_auth.verify_password(password, a.password_hash if a is not None and not locked else None)     # None: gasta o mesmo tempo
        step: int | None = None
        code_ok = False
        if a is not None and not locked and pw_ok:
            secret = panel_auth.decrypt_secret(a.totp_secret_enc) if a.totp_secret_enc else None
            if secret is not None:
                step = panel_auth.verify_totp(secret, code, last_step=a.last_totp_step)
                code_ok = step is not None
            else:
                code_ok = not settings.panel_require_totp            # sem segredo cadastrado: só vale se o código não for exigido (desenvolvimento)
        ok = a is not None and not locked and pw_ok and code_ok
        if a is not None and not locked:
            if ok:
                a.failed_logins, a.locked_until, a.last_login_at = 0, None, now
                if step is not None:
                    a.last_totp_step = step
                cookie, csrf = panel_auth.make_session(str(a.id), a.password_version)
                service.audit(s, a.email, "admin.login", None, ip=ip)
            else:
                a.failed_logins += 1
                if a.failed_logins >= settings.login_max_failures:
                    a.failed_logins, a.locked_until = 0, now + timedelta(minutes=settings.login_lock_minutes)
                service.audit(s, "painel", "admin.login_failed", None, ip=ip, admin=str(a.id))
        else:
            service.audit(s, "painel", "admin.login_failed", None, ip=ip, admin=None)
    if not ok:
        return _render(request, "login.html", None, 401, error=LOGIN_ERROR, totp_required=settings.panel_require_totp)
    r = RedirectResponse("/painel/visao-geral", 303)
    r.set_cookie(SESSION_COOKIE, cookie, **_cookie_kw(settings.panel_session_hours * 3600))
    return r


@router.post("/sair")
def logout(request: Request, csrf: str = Form("")) -> Response:
    auth = _auth(request)
    _check(request, auth, csrf)
    r = RedirectResponse("/painel/entrar", 303)
    r.delete_cookie(SESSION_COOKIE, path="/painel")
    return r


@router.get("/senha", response_class=HTMLResponse)
def password_form(request: Request) -> Response:
    return _render(request, "password.html", _auth(request), min_length=panel_auth.MIN_LENGTH)


@router.post("/senha")
def password_change(request: Request, csrf: str = Form(""), current: str = Form(""), new: str = Form(""), again: str = Form("")) -> Response:
    auth = _auth(request)
    _check(request, auth, csrf)
    err = None
    with session_scope() as s:
        a = s.get(Admin, auth.admin_id)
        assert a is not None
        if not panel_auth.verify_password(current, a.password_hash):
            err = "A senha atual está incorreta."
        elif new != again:
            err = "A confirmação não é igual à nova senha."
        elif panel_auth.policy_errors(new):
            err = "A nova senha precisa ter: " + "; ".join(panel_auth.policy_errors(new)) + "."
        elif panel_auth.verify_password(new, a.password_hash):
            err = "A nova senha precisa ser diferente da atual."
        else:
            a.password_hash, a.password_version = panel_auth.hash_password(new), a.password_version + 1
            service.audit(s, a.email, "admin.password_change", None)
            cookie, _ = panel_auth.make_session(str(a.id), a.password_version)
    if err:
        return _flash(RedirectResponse("/painel/senha", 303), err, False)
    r = _flash(RedirectResponse("/painel/visao-geral", 303), "Senha alterada. As outras sessões foram encerradas.")
    r.set_cookie(SESSION_COOKIE, cookie, **_cookie_kw(settings.panel_session_hours * 3600))
    return r


# ---------------------------------------------------------------- visão geral
@router.get("/visao-geral", response_class=HTMLResponse)
def dashboard(request: Request) -> Response:
    auth = _auth(request)
    now = service.utcnow()
    with session_scope() as s:
        rows = service.overview(s, now)
        refusals = service.recent_refusals(s, now)
    summary = {"total": len(rows), "alert": sum(1 for r in rows if r["level"] >= service.LEVEL_WARN), "suspended": sum(1 for r in rows if r["silence"] == "suspended"),
               "warned": sum(1 for r in rows if r["silence"] == "client_warned"), "active": sum(1 for r in rows if r["status"] == "ativo")}
    return _render(request, "dashboard.html", auth, rows=rows, refusals=refusals, summary=summary, nav="visao")


@router.get("/clientes/novo", response_class=HTMLResponse)
def new_form(request: Request) -> Response:
    return _render(request, "new.html", _auth(request), nav="novo", d=service)


@router.post("/clientes")
def new_create(request: Request, csrf: str = Form(""), customer: str = Form(""), contact_email: str = Form(""), devices: str = Form("50"), months: str = Form("12"),
               tolerance_days: str = Form("15"), on_end: str = Form("stop_inspection"), note: str = Form("")) -> Response:
    auth = _auth(request)
    _check(request, auth, csrf)
    try:
        if not customer.strip():
            raise service.ServiceError("name_required", "informe o nome do cliente")
        with session_scope() as s:
            c = service.create_customer(s, customer.strip()[:200], contact_email.strip()[:320] or None, actor=auth.email)
            k = service.create_weekly_contract(s, c, _int(devices, "máquinas"), _int(months, "meses"), tolerance_days=_int(tolerance_days, "tolerância"),
                                               on_end=on_end if on_end in ("stop_inspection", "keep_inspection") else "stop_inspection", note=note.strip()[:2000] or None, actor=auth.email)
            cid = str(k.id)
    except service.ServiceError as exc:
        return _flash(RedirectResponse("/painel/clientes/novo", 303), exc.detail, False)
    return _back(cid, "Cliente e contrato criados com a política semanal recomendada. Gere o código de ativação abaixo.")


# ---------------------------------------------------------------- um contrato
def _contract_page(request: Request, auth: Auth, cid: str, new_code: str | None = None, status_code: int = 200) -> Response:
    now = service.utcnow()
    with session_scope() as s:
        k = _contract(s, cid)
        customer = s.get(Customer, k.customer_id)
        inst = s.execute(select(Installation).where(Installation.contract_id == k.id, Installation.unbound_at.is_(None))).scalar()
        codes = list(s.execute(select(ActivationCode).where(ActivationCode.contract_id == k.id).order_by(ActivationCode.created_at.desc()).limit(5)).scalars())
        last = s.execute(select(IssuedAuthorization).where(IssuedAuthorization.contract_id == k.id).order_by(IssuedAuthorization.serial.desc()).limit(1)).scalar()
        log = list(s.execute(select(AuditEntry).where(AuditEntry.contract_id == k.id).order_by(AuditEntry.id.desc()).limit(30)).scalars())
        row = next(r for r in service.overview(s, now) if r["id"] == k.id)
        for o in (k, customer, inst, last, *codes, *log):
            if o is not None:
                s.expunge(o)
    return _render(request, "contract.html", auth, status_code, k=k, customer=customer, inst=inst, codes=codes, last=last, log=log, row=row, new_code=new_code,
                   nav="visao", weekly=dict(renew=service.DEFAULT_RENEW_HOURS // 24, validity=service.DEFAULT_VALIDITY_DAYS, warn=service.DEFAULT_WARN_DAYS, suspend=service.DEFAULT_SUSPEND_DAYS))


@router.get("/contratos/{cid}", response_class=HTMLResponse)
def contract_page(request: Request, cid: str) -> Response:
    return _contract_page(request, _auth(request), cid)


def _action(request: Request, cid: str, csrf: str, fn, ok_msg: str) -> Response:
    """Roda uma alteração no contrato; erro vira aviso (nada é gravado) e sucesso é registrado com o e-mail de quem fez."""
    auth = _auth(request)
    _check(request, auth, csrf)
    try:
        with session_scope() as s:
            fn(s, _contract(s, cid), service.utcnow(), auth.email)
    except service.ServiceError as exc:
        return _back(cid, exc.detail, False)
    return _back(cid, ok_msg)


@router.post("/contratos/{cid}/prazo")
def edit_deadline(request: Request, cid: str, csrf: str = Form(""), action: str = Form(""), end: str = Form(""), days: str = Form(""), months: str = Form(""), reason: str = Form("")) -> Response:
    def go(s, k, now, actor):
        if action == "set":
            try:
                day = date.fromisoformat(end.strip())
            except ValueError as exc:
                raise service.ServiceError("bad_date", "informe a nova data de fim") from exc
            service.set_end_date(s, k, datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=BRT).astimezone(timezone.utc), reason, now, actor=actor)
        elif action == "add":
            service.add_days(s, k, _int(days, "dias"), reason, now, actor=actor)
        elif action == "months":
            service.set_term_months(s, k, _int(months, "meses"), actor=actor)
        else:
            raise service.ServiceError("bad_action", "ação desconhecida")
    return _action(request, cid, csrf, go, "Prazo atualizado. A instalação vê o novo prazo na próxima validação.")


@router.post("/contratos/{cid}/condicoes")
def edit_terms(request: Request, cid: str, csrf: str = Form(""), preset: str = Form(""), devices: str = Form("0"), tolerance_days: str = Form("15"), on_end: str = Form("stop_inspection"),
               renew_days: str = Form("7"), validity_days: str = Form("28"), warn_days: str = Form(""), suspend_days: str = Form(""), note: str = Form("")) -> Response:
    def go(s, k, now, actor):
        common = dict(devices=_int(devices, "máquinas"), tolerance_days=_int(tolerance_days, "tolerância"), on_end=on_end, note=note.strip()[:2000] or None, actor=actor)
        if preset == "weekly":
            service.update_terms(s, k, renew_after_hours=service.DEFAULT_RENEW_HOURS, auth_validity_days=service.DEFAULT_VALIDITY_DAYS,
                                 warn_after_days=service.DEFAULT_WARN_DAYS, suspend_after_days=service.DEFAULT_SUSPEND_DAYS, **common)
        else:
            try:
                warn, suspend = _opt_int(warn_days), _opt_int(suspend_days)
            except ValueError as exc:
                raise service.ServiceError("bad_number", "avisar e suspender: informe números inteiros ou deixe em branco") from exc
            service.update_terms(s, k, renew_after_hours=_int(renew_days, "validar a cada") * 24, auth_validity_days=_int(validity_days, "validade"),
                                 warn_after_days=warn, suspend_after_days=suspend, **common)
    return _action(request, cid, csrf, go, "Condições atualizadas. Valem na próxima validação da instalação.")


@router.post("/contratos/{cid}/codigo")
def issue_code(request: Request, cid: str, csrf: str = Form(""), valid_days: str = Form("7")) -> Response:
    auth = _auth(request)
    _check(request, auth, csrf)
    try:
        with session_scope() as s:
            code = service.issue_code(s, _contract(s, cid), service.utcnow(), _int(valid_days, "validade do código"), actor=auth.email)
    except service.ServiceError as exc:
        return _back(cid, exc.detail, False)
    return _contract_page(request, auth, cid, new_code=code)       # o código aparece SÓ aqui (no banco fica o hash); não há redirecionamento de propósito


def _danger(request: Request, cid: str, csrf: str, confirm: str, fn, ok_msg: str) -> Response:
    if confirm != "sim":
        auth = _auth(request)
        _check(request, auth, csrf)
        return _back(cid, "Marque a caixa de confirmação para continuar.", False)
    return _action(request, cid, csrf, fn, ok_msg)


@router.post("/contratos/{cid}/encerrar")
def close(request: Request, cid: str, csrf: str = Form(""), reason: str = Form(""), confirm: str = Form("")) -> Response:
    def go(s, k, now, actor):
        if len(reason.strip()) < 3:
            raise service.ServiceError("reason_required", "informe o motivo do encerramento")
        service.close_contract(s, k, reason.strip(), now, actor=actor)
    return _danger(request, cid, csrf, confirm, go, "Contrato encerrado. A instalação fica sabendo na próxima validação.")


@router.post("/contratos/{cid}/reabrir")
def reopen(request: Request, cid: str, csrf: str = Form("")) -> Response:
    return _action(request, cid, csrf, lambda s, k, now, actor: service.reopen_contract(s, k, now, actor=actor), "Contrato reaberto.")


@router.post("/contratos/{cid}/desvincular")
def unbind(request: Request, cid: str, csrf: str = Form(""), confirm: str = Form("")) -> Response:
    return _danger(request, cid, csrf, confirm, lambda s, k, now, actor: service.unbind(s, k, now, actor=actor), "Instalação desvinculada. Gere um código novo para vincular de novo.")


# ---------------------------------------------------------------- pacotes e auditoria
@router.get("/downloads", response_class=HTMLResponse)
def downloads(request: Request) -> Response:
    auth = _auth(request)
    return _render(request, "downloads.html", auth, nav="downloads", pkgs=packages.list_packages(), dir=str(packages.packages_dir()), signing_ready=packages._public_key() is not None)


@router.get("/downloads/{name}")
def download_file(request: Request, name: str) -> Response:
    auth = _auth(request)
    pkg = packages.find(name)
    if pkg is None:
        raise HTTPException(404, "pacote não encontrado")
    if not pkg.trusted:
        return _flash(RedirectResponse("/painel/downloads", 303), "Download recusado: o arquivo não confere com o manifesto assinado (foi trocado ou a assinatura falha).", False)
    with session_scope() as s:
        service.audit(s, auth.email, "package.download", None, file=pkg.name, sha256=pkg.sha256)
    return FileResponse(packages.file_path(pkg), media_type="application/zip", filename=pkg.name, headers={"Cache-Control": "no-store"})


@router.get("/downloads/{name}/leia-me", response_class=HTMLResponse)
def download_readme(request: Request, name: str) -> Response:
    auth = _auth(request)
    pkg = packages.find(name)
    text = packages.readme_text(pkg) if pkg else None
    if pkg is None or text is None:
        raise HTTPException(404, "leia-me não encontrado")
    return _render(request, "readme.html", auth, nav="downloads", pkg=pkg, text=text)


@router.get("/auditoria", response_class=HTMLResponse)
def audit_page(request: Request, contrato: str = "") -> Response:
    auth = _auth(request)
    with session_scope() as s:
        q = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(200)
        if contrato:
            try:
                q = q.where(AuditEntry.contract_id == uuid.UUID(contrato))
            except ValueError as exc:
                raise HTTPException(404) from exc
        entries = list(s.execute(q).scalars())
        for e in entries:
            s.expunge(e)
    return _render(request, "audit.html", auth, nav="auditoria", entries=entries, contrato=contrato)


# ---------------------------------------------------------------- versões publicadas (aplicação e pacotes de regras)
@router.get("/versoes", response_class=HTMLResponse)
def versions_page(request: Request) -> Response:
    auth = _auth(request)
    now = service.utcnow()
    with session_scope() as s:
        rels = {(r.kind, r.version): r for r in s.execute(select(Release)).scalars()}
        for r in rels.values():
            s.expunge(r)
        latest = {k: service.latest_release(s, k) for k in ("app", "rules")}
        latest_ver = {k: (v.version if v else None) for k, v in latest.items()}
        rows = service.overview(s, now)
    groups = []
    for kind, title in (("app", "Aplicação (pacote de instalação)"), ("rules", "Pacotes de regras de detecção")):
        items = []
        for p in packages.list_packages(kind):
            items.append({"pkg": p, "rel": rels.get((kind, p.version))})
        published_only = [r for (k, _), r in rels.items() if k == kind and not any(i["pkg"].version == r.version for i in items)]
        groups.append({"kind": kind, "title": title, "items": items, "orphans": published_only, "latest": latest_ver[kind]})
    installs = [{"customer": r["customer"], "id": r["id"], "version": r["version"], "rules_version": r["rules_version"], "update_state": r["update_state"], "outdated": r["outdated"]} for r in rows if r["has_installation"]]
    return _render(request, "versions.html", auth, nav="versoes", groups=groups, installs=installs, signing_ready=packages._public_key() is not None)


@router.post("/versoes/publicar")
def versions_publish(request: Request, csrf: str = Form(""), kind: str = Form(""), file: str = Form(""), notes: str = Form(""), security: str = Form(""), confirm: str = Form("")) -> Response:
    auth = _auth(request)
    _check(request, auth, csrf)
    if confirm != "sim":
        return _flash(RedirectResponse("/painel/versoes", 303), "Marque a caixa de confirmação para publicar.", False)
    try:
        with session_scope() as s:
            rel = service.publish_release(s, kind, file, notes, security == "sim", service.utcnow(), actor=auth.email)
            version = rel.version
    except service.ServiceError as exc:
        return _flash(RedirectResponse("/painel/versoes", 303), exc.detail, False)
    return _flash(RedirectResponse("/painel/versoes", 303), f"Versão {version} publicada. Cada instalação é avisada na próxima validação (até 7 dias, na política semanal).")


@router.post("/versoes/{rid}/retirar")
def versions_withdraw(request: Request, rid: str, csrf: str = Form(""), reason: str = Form("")) -> Response:
    auth = _auth(request)
    _check(request, auth, csrf)
    try:
        with session_scope() as s:
            try:
                rel = s.get(Release, uuid.UUID(rid))
            except ValueError:
                rel = None
            if rel is None:
                raise HTTPException(404, "versão não encontrada")
            service.withdraw_release(s, rel, reason, service.utcnow(), actor=auth.email)
    except service.ServiceError as exc:
        return _flash(RedirectResponse("/painel/versoes", 303), exc.detail, False)
    return _flash(RedirectResponse("/painel/versoes", 303), "Versão retirada: os clientes deixam de ser avisados dela. Quem já baixou não perde nada.")
