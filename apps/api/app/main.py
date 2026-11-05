import hmac
import logging
import time
import uuid as _uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import logging_config, metrics, services
from app.config import settings
from app.routers import (
    admin,
    alerts,
    analytics,
    enrollment,
    events,
    exports,
    feedback,
    incidents,
    inference_hook,
    license_status,
    pilot,
    policies,
    privacy,
    reports,
    sensor,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    services.init_ner()
    yield


logging_config.configure(settings.log_json)
access_log = logging.getLogger("promptshield.access")

app = FastAPI(title="PromptShield API", version=settings.version, lifespan=lifespan,
              description="Ingestão de eventos, políticas e incidentes. Autenticação: `X-API-Key` (coletores) ou "
                          "`Authorization: Bearer <token OIDC>` (console).")


@app.middleware("http")
async def observe(request: Request, call_next):
    """Log de acesso estruturado e métricas. Só modelo da rota, método, status e duração: nunca corpo, query string ou valores."""
    started = time.perf_counter()
    rid = request.headers.get("x-request-id", "")
    rid = rid if 0 < len(rid) <= 64 and rid.replace("-", "").isalnum() else _uuid.uuid4().hex
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "(sem rota)")
    elapsed = time.perf_counter() - started
    response.headers["X-Request-ID"] = rid
    if request.url.path.startswith("/v1"):  # a API não deve ser guardada em cache de navegador ou proxy; sem adivinhar tipo de conteúdo
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
    metrics.inc("ps_http_requests_total", route=route, method=request.method, status=str(response.status_code))
    metrics.observe_request(route, request.method, elapsed)
    if route != "/health":
        access_log.info("request", extra={"request_id": rid, "tenant_id": getattr(request.state, "tenant_id", None), "route": route,
                                          "method": request.method, "status": response.status_code, "duration_ms": round(elapsed * 1000, 1)})
    return response


@app.get("/metrics", include_in_schema=False)
def prometheus(request: Request) -> PlainTextResponse:
    token = settings.metrics_token
    given = request.headers.get("authorization", "")
    if not token or not hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
        return PlainTextResponse("not found", status_code=404)  # desligada sem token; com token errado não revela que existe
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version", tags=["infra"])
def version() -> dict[str, str]:
    return {"version": settings.version}


_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
if settings.sideload_extension_origin and settings.sideload_extension_origin not in _origins:
    _origins.append(settings.sideload_extension_origin)  # a extensão instalada pelo sensor (ID fixo); precisa de chave válida para qualquer coisa
if _origins:  # nenhum outro site pode chamar a API pelo navegador
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST"],
                       allow_headers=["X-API-Key", "Content-Type", "Authorization"], max_age=600,
                       expose_headers=["X-PromptShield-Inspection", "X-PromptShield-Suspended"])   # a extensão mostra "inspeção parada"

app.include_router(events.router)
app.include_router(feedback.router)
app.include_router(incidents.router)
app.include_router(policies.router)
app.include_router(admin.router)
app.include_router(analytics.router)
app.include_router(alerts.router)
app.include_router(exports.router)
app.include_router(reports.router)
app.include_router(inference_hook.router)
app.include_router(privacy.router)
app.include_router(pilot.router)
app.include_router(enrollment.router)
app.include_router(sensor.router)
app.include_router(license_status.router)

if settings.oidc_mode == "mock":  # só desenvolvimento: nunca registrado em outro modo
    from app.security import issue_mock_token

    class _Email(BaseModel):
        email: str

    @app.post("/dev/token", tags=["desenvolvimento"], summary="Token de login simulado (OIDC_MODE=mock)")
    def dev_token(body: _Email) -> dict[str, str]:
        return {"access_token": issue_mock_token(body.email), "token_type": "bearer"}
