from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # banco PRÓPRIO do serviço de licenças (do fornecedor); nunca o banco de um cliente
    database_url: str = "postgresql+psycopg://licensing:licensing@localhost:5432/licensing"
    # chave privada Ed25519 do fornecedor (PEM, ou o PEM em base64). Gere com: python -m lic_service.cli gen-key. Sem ela nada é assinado.
    license_signing_key: str | None = None
    version: str = "0.1.0"
    # limite de pedidos por IP por minuto em /v1/activate e /v1/renew (por processo)
    rate_limit_per_minute: int = 30


settings = Settings()
