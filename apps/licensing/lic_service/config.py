from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # banco PRÓPRIO do serviço de licenças (do fornecedor); nunca o banco de um cliente
    database_url: str = "postgresql+psycopg://licensing:licensing@localhost:5432/licensing"
    # chave privada Ed25519 do fornecedor (PEM, ou o PEM em base64). Gere com: python -m lic_service.cli gen-key. Sem ela nada é assinado.
    license_signing_key: str | None = None
    version: str = "0.1.0"
    # limite de pedidos por IP por minuto em /v1/activate e /v1/renew (compartilhado entre processos, no banco)
    rate_limit_per_minute: int = 30
    # painel web do fornecedor (/painel). Desligado por padrão. Só você deve alcançá-lo: ponha atrás de VPN/lista de IPs e HTTPS (docs/painel-fornecedor.md).
    panel_enabled: bool = False
    panel_secret: str | None = None                # assina as sessões e cifra os segredos do código de 6 dígitos; 32+ caracteres; trocar derruba todas as sessões
    panel_cookie_secure: bool = True               # false só para teste local sem HTTPS
    panel_require_totp: bool = True                # exige o código de 6 dígitos no login (desligue só em desenvolvimento)
    panel_session_hours: int = 8
    packages_dir: str = "/srv/packages"            # onde ficam os pacotes (.zip) que o painel entrega ao cliente
    trusted_proxy_hops: int = 0                    # quantos proxies de confiança há à frente deste serviço; 0 = ignora X-Forwarded-For (padrão seguro)
    login_max_failures: int = 5
    login_lock_minutes: int = 15


    @model_validator(mode="after")
    def _panel_needs_a_strong_secret(self) -> "Settings":
        if self.panel_enabled and len(self.panel_secret or "") < 32:
            raise ValueError("PANEL_ENABLED=true exige PANEL_SECRET com pelo menos 32 caracteres (gere com: openssl rand -hex 32)")
        return self


settings = Settings()
