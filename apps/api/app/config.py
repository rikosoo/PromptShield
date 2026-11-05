from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # papel da aplicação (sem BYPASSRLS); usado pela API em runtime
    database_url: str = "postgresql+psycopg://promptshield_app:promptshield_app@localhost:5432/promptshield"
    # dono/superuser: só para migrações e CLI (Alembic e `python -m app.cli`)
    admin_database_url: str | None = None
    version: str = "0.3.0"

    # origens com permissão de CORS, separadas por vírgula (ex.: chrome-extension://<id>,https://console.empresa.com). Padrão: nenhuma.
    cors_allowed_origins: str = ""
    # ID FIXO da extensão distribuída pelo sensor (derivado da chave pública em apps/extension/sideload-public-key.txt; conferido em teste)
    sideload_extension_origin: str = "chrome-extension://ddbppnhmehihdablhhdmoiedblkelmji"
    # pasta da extensão construída com `node build.mjs --sideload` (no Docker: /srv/extension); vazio = o servidor não distribui a extensão
    extension_dist: str = "/srv/extension"

    # licenciamento on-premise (docs/licenciamento.md). off = SaaS/desenvolvimento: nada muda. onprem = esta instalação precisa de uma autorização
    # assinada pelo fornecedor (ativação por código, renovação periódica); as regras dos estados são públicas e testadas.
    license_mode: str = "off"
    license_server_url: str | None = None
    # chave PÚBLICA do fornecedor, fixada na instalação (32 bytes em base64 urlsafe, ou PEM). Nunca baixe essa chave do serviço de licenças.
    license_public_key: str | None = None
    license_state_dir: str = "/var/lib/promptshield"     # guarda a chave PRIVADA da instalação (arquivo 0600); precisa de volume persistente
    license_allow_http: bool = False                      # só desenvolvimento/teste; em produção o serviço de licenças é https
    license_retry_minutes: int = 15                       # intervalo entre tentativas quando a renovação falha

    max_text_chars: int = 2_000_000
    enable_ner: bool = False

    # texto original (opcional por tenant). Chave mestra em base64 de 32 bytes. Interino até o KMS por tenant (Etapa 9).
    original_text_master_key: str | None = None

    # login do console: off | mock (só desenvolvimento) | oidc
    oidc_mode: str = "off"
    oidc_mock_secret: str | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    # notificações (Etapa 7). Webhooks exigem https e destino público, salvo estas válvulas de desenvolvimento/teste.
    allow_insecure_webhooks: bool = False
    allow_private_webhook_targets: bool = False
    webhook_timeout_seconds: float = 5.0
    outbox_max_attempts: int = 5
    # e-mail: sem smtp_host o envio por e-mail falha com mensagem clara (nada é fingido)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "promptshield@localhost"
    smtp_starttls: bool = True
    # endereço do console, usado nos links das notificações (opcional)
    console_url: str | None = None

    # inference hooks do Claude Enterprise (Etapa 8). O orçamento fica abaixo do tempo limite padrão da Anthropic (5.000 ms).
    inference_hook_budget_ms: int = 3000
    inference_hook_max_body_bytes: int = 64 * 1024 * 1024  # o protocolo permite até 64 MiB
    inference_hook_previous_secret_minutes: int = 10  # a troca de segredo é imediata do lado da Anthropic; aceitamos o anterior por um tempo

    # limites de requisição por credencial por minuto, por processo (0 desliga). Coletores de uma empresa inteira usam UMA chave.
    rate_limit_key_per_minute: int = 6000
    rate_limit_user_per_minute: int = 600
    rate_limit_enroll_per_minute: int = 120   # por IP de origem; uma empresa inteira costuma sair por um IP só (NAT): o sensor espera e tenta de novo no 429
    # /metrics só existe se houver token (Authorization: Bearer ...); sem token a rota responde 404
    metrics_token: str | None = None
    log_json: bool = True


settings = Settings()
