"""Atualizações ASSISTIDAS, lado do cliente: o fornecedor AVISA (junto com a validação semanal), o administrador APROVA, o servidor BAIXA e CONFERE.

Nada aqui instala nem executa o que foi baixado. Cada etapa tem uma porta que o administrador abre:
- aplicação (`app`): aviso -> o administrador aprova o download -> o worker baixa e confere (assinatura do fornecedor, SHA-256, tamanho, versão maior que a instalada)
  -> fica `ready` -> o administrador roda `atualizar.sh` no servidor (backup, imagens novas, subida). A API não tem acesso ao Docker de propósito.
- regras (`rules`): aviso -> o worker baixa, confere e GUARDA (`staged`, sem efeito) -> o administrador ativa em modo sombra e, vendo o efeito, promove.

Tudo que chega é conferido com a chave do fornecedor FIXADA na instalação. Qualquer aviso ou arquivo que não confere é ignorado e vira um erro visível ao administrador."""
from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from promptshield_licensing import RULES_PRODUCT as _RULES  # noqa: F401  (documenta o domínio de assinatura usado pelo aviso)
from promptshield_licensing import ReleaseError, ReleaseNotice, build_request, is_newer, verify_notice
from sqlalchemy import select

from app import rulepacks
from app.config import settings
from app.db import anonymous_session
from app.models import UpdateState

log = logging.getLogger("promptshield.updates")
KINDS = ("app", "rules")
MAX_APP_BYTES = 6 * 1024**3
MAX_RULES_BYTES = 2 * 1024 * 1024
FREE_SPACE_MARGIN = 1.25


class UpdateError(Exception):
    def __init__(self, detail: str, http: int = 409) -> None:
        super().__init__(detail)
        self.detail, self.http = detail, http


def _now() -> datetime:
    return datetime.now(timezone.utc)


def updates_dir() -> Path:
    return Path(settings.license_state_dir) / "updates"


def _pub():
    from app import license_client

    return license_client._pinned()


def installed_version(kind: str) -> str | None:
    return settings.version if kind == "app" else rulepacks.installed_version()


# ---------------------------------------------------------------- avisos que chegam com a validação
def record_notices(tokens: dict[str, str | None] | None, now: datetime | None = None) -> list[str]:
    """Guarda (ou apaga) o aviso de cada tipo. Aviso com assinatura inválida, de versão que não é maior que a instalada ou de outro tipo é IGNORADO.
    Nunca levanta: um problema aqui jamais pode atrapalhar a validação da licença."""
    now = now or _now()
    done: list[str] = []
    try:
        pub = _pub()
    except Exception:  # noqa: BLE001
        return done
    for kind in KINDS:
        tok = (tokens or {}).get(kind)
        try:
            notice = verify_notice(tok, pub) if tok else None
            if notice is not None and (notice.kind != kind or not is_newer(notice.version, installed_version(kind))):
                notice = None
        except ReleaseError as exc:
            log.warning("aviso de %s ignorado: %s", kind, exc)
            notice = None
        with anonymous_session() as s:
            row = s.get(UpdateState, kind)
            if notice is None:
                if row is not None and row.status in ("available", "failed"):
                    s.delete(row)                                       # retirada pelo fornecedor, ou já instalada: some
                    done.append(f"{kind}:removido")
                continue
            if row is not None and row.version == notice.version:
                row.notice, row.notes, row.security = tok, notice.notes, notice.security
                continue
            if row is not None:
                s.delete(row)
                s.flush()
            s.add(UpdateState(kind=kind, notice=tok, version=notice.version, security=notice.security, notes=notice.notes, size=notice.size, sha256=notice.sha256,
                              file=notice.file, status="available", updated_at=now))
            done.append(f"{kind}:{notice.version}")
    return done


def report_fields() -> dict[str, str]:
    """O que a instalação conta ao fornecedor na validação: versão das regras e o estado das atualizações (texto curto)."""
    with anonymous_session() as s:
        parts = [f"{r.kind}:{r.status}({r.version})" for r in s.execute(select(UpdateState).order_by(UpdateState.kind)).scalars()]
    out = {"update_state": "; ".join(parts)[:300]}
    live = rulepacks.live_version()
    if live:
        out["rules_version"] = live
    return out


# ---------------------------------------------------------------- estado para a API e o console
def _row_view(r: UpdateState) -> dict[str, Any]:
    return {"version": r.version, "security": r.security, "notes": r.notes, "size": int(r.size), "sha256": r.sha256, "file": r.file, "status": r.status,
            "error": r.error, "approved_by": r.approved_by, "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "ready_at": r.ready_at.isoformat() if r.ready_at else None}


def summary() -> dict[str, Any]:
    with anonymous_session() as s:
        rows = {r.kind: _row_view(r) for r in s.execute(select(UpdateState)).scalars()}
    return {"app": {"installed": settings.version, "notice": rows.get("app"), "ready_path": str(ready_file()) if (rows.get("app") or {}).get("status") == "ready" else None},
            "rules": {"installed": rulepacks.installed_version(), "live": rulepacks.live_version(), "notice": rows.get("rules")}}


def ready_file() -> Path | None:
    with anonymous_session() as s:
        r = s.get(UpdateState, "app")
        if r is None or r.status != "ready":
            return None
        p = updates_dir() / r.file
        return p if p.is_file() else None


def ready_info() -> dict[str, Any] | None:
    """Para o `atualizar.sh`: arquivo pronto, versão e o SHA-256 que o servidor conferiu."""
    with anonymous_session() as s:
        r = s.get(UpdateState, "app")
        if r is None or r.status != "ready" or not (updates_dir() / r.file).is_file():
            return None
        return {"version": r.version, "file": r.file, "sha256": r.sha256, "size": int(r.size), "path": str(updates_dir() / r.file)}


# ---------------------------------------------------------------- ações do administrador
def approve_app(version: str, actor: str, now: datetime | None = None) -> None:
    """O administrador autoriza BAIXAR esta versão (e só ela). Não instala nada."""
    now = now or _now()
    with anonymous_session() as s:
        r = s.execute(select(UpdateState).where(UpdateState.kind == "app").with_for_update()).scalar()
        if r is None or r.version != version:
            raise UpdateError("esta versão não está disponível (o aviso mudou ou foi retirado); recarregue a página", 404)
        if r.status in ("approved", "ready"):
            raise UpdateError(f"esta versão já está «{r.status}»")
        if not is_newer(r.version, settings.version):
            raise UpdateError("só se aceita uma versão MAIOR que a instalada")
        r.status, r.error, r.approved_by, r.approved_at = "approved", None, actor, now


def retry(kind: str) -> None:
    """Tenta de novo um download ou pacote que falhou (aplicação volta a «approved»; regras voltam a «available»)."""
    with anonymous_session() as s:
        r = s.execute(select(UpdateState).where(UpdateState.kind == kind).with_for_update()).scalar()
        if r is None or r.status != "failed":
            raise UpdateError("nada para tentar de novo", 404)
        r.status, r.error = ("approved" if kind == "app" else "available"), None


# ---------------------------------------------------------------- o worker baixa e confere
def _fail(kind: str, detail: str) -> None:
    with anonymous_session() as s:
        r = s.get(UpdateState, kind)
        if r is not None:
            r.status, r.error = "failed", detail[:300]
    log.warning("atualização %s falhou: %s", kind, detail)


def _download(notice: ReleaseNotice, dest: Path, limit: int, now: datetime) -> str:
    """Baixa para `dest.part`, conferindo tamanho e SHA-256 enquanto grava; só renomeia se tudo confere. Devolve o SHA-256."""
    from app import license_client

    inst = license_client.installation(create=False)
    if inst is None:
        raise UpdateError("identidade da instalação não encontrada (LICENSE_STATE_DIR)")
    if notice.size > limit:
        raise UpdateError(f"arquivo grande demais ({notice.size} bytes)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dest.parent).free
    if free < notice.size * FREE_SPACE_MARGIN:
        raise UpdateError(f"pouco espaço em disco: preciso de {int(notice.size * FREE_SPACE_MARGIN) // 1_048_576} MB e há {free // 1_048_576} MB livres")
    req = build_request(inst, "download", now, kind=notice.kind, version=notice.version)
    part = dest.with_suffix(dest.suffix + ".part")
    digest, got = hashlib.sha256(), 0
    try:
        with license_client.http_factory() as c, c.stream("POST", license_client._server_url() + "/v1/releases/download", json={"request": req}) as r:
            if r.status_code != 200:
                r.read()
                try:
                    code = str(r.json().get("code", ""))
                except ValueError:
                    code = ""
                raise UpdateError(f"o fornecedor recusou o download ({r.status_code} {code})".strip())
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    got += len(chunk)
                    if got > notice.size:
                        raise UpdateError("o arquivo recebido é maior que o anunciado")
                    digest.update(chunk)
                    f.write(chunk)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - rede, disco...
        part.unlink(missing_ok=True)
        raise UpdateError(f"falha no download: {type(exc).__name__}") from exc
    if got != notice.size or digest.hexdigest() != notice.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("o arquivo baixado NÃO confere com o SHA-256 assinado pelo fornecedor: descartado")
    part.replace(dest)
    return digest.hexdigest()


def _pending(status: str, kind: str) -> UpdateState | None:
    with anonymous_session() as s:
        r = s.get(UpdateState, kind)
        if r is not None and r.status == status:
            s.expunge(r)
            return r
    return None


def _app_step(now: datetime) -> str | None:
    r = _pending("approved", "app")
    if r is None:
        return None
    try:
        notice = verify_notice(r.notice, _pub())
        if notice.version != r.version or not is_newer(notice.version, settings.version):
            raise UpdateError("o aviso guardado não vale mais (versão)")
        _download(notice, updates_dir() / notice.file, MAX_APP_BYTES, now)
    except (UpdateError, ReleaseError) as exc:
        _fail("app", str(getattr(exc, "detail", exc)))
        return "app:falhou"
    with anonymous_session() as s:
        row = s.get(UpdateState, "app")
        if row is not None:
            row.status, row.error, row.ready_at = "ready", None, now
    return f"app:pronto({r.version})"


def _rules_step(now: datetime) -> str | None:
    r = _pending("available", "rules")
    if r is None:
        return None
    path = updates_dir() / f"{r.file}.tmp"
    try:
        notice = verify_notice(r.notice, _pub())
        if not is_newer(notice.version, rulepacks.installed_version()):
            raise UpdateError("o pacote de regras não é mais novo que o já recebido")
        _download(notice, path, MAX_RULES_BYTES, now)
        rulepacks.stage(path.read_text(encoding="utf-8"), notice.version, now)
    except UpdateError as exc:
        _fail("rules", exc.detail)
        return "rules:falhou"
    except ReleaseError as exc:
        _fail("rules", f"pacote recusado: {exc}")
        return "rules:falhou"
    except Exception as exc:  # noqa: BLE001 - PackError e afins: mostra os motivos
        errs = getattr(exc, "errors", None)
        _fail("rules", "pacote recusado: " + ("; ".join(errs[:3]) if errs else type(exc).__name__))
        return "rules:falhou"
    finally:
        path.unlink(missing_ok=True)
    with anonymous_session() as s:
        row = s.get(UpdateState, "rules")
        if row is not None:
            row.status, row.error, row.ready_at = "staged", None, now
    return f"rules:guardado({r.version})"


def tick(now: datetime | None = None) -> list[str]:
    """Uma passada do worker. Devolve o que fez (para o log; só nomes e versões)."""
    now = now or _now()
    out = [x for x in (_app_step(now), _rules_step(now)) if x]
    return out
