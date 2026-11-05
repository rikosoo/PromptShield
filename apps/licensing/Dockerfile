# Contexto de build: raiz do repositório (ver docker-compose.yml, perfil "vendor"). Serviço do FORNECEDOR, não vai para o servidor do cliente.
FROM python:3.12-slim
WORKDIR /srv
COPY packages/licensing ./packages/licensing
COPY apps/licensing ./apps/licensing
RUN pip install --no-cache-dir -e packages/licensing -e apps/licensing
WORKDIR /srv/apps/licensing
EXPOSE 8100
# o banco do serviço é o dono: migra e serve com a mesma conexão (não há papel restrito/RLS aqui: é um serviço interno do fornecedor)
CMD ["sh", "-c", "alembic upgrade head && uvicorn lic_service.main:app --host 0.0.0.0 --port 8100"]
