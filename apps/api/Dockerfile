# Contexto de build: raiz do repositório (ver docker-compose.yml)
# 1) extensão do navegador (build sideload, distribuída pelo sensor)
FROM node:22-slim AS extension
WORKDIR /ext
COPY apps/extension/package*.json ./
RUN npm ci
COPY apps/extension ./
RUN node build.mjs --sideload

FROM python:3.12-slim
WORKDIR /srv
COPY packages ./packages
COPY apps/api ./apps/api
COPY --from=extension /ext/dist/sideload /srv/extension
RUN pip install --no-cache-dir -e packages/detection -e packages/adapters/inference_hooks -e packages/adapters/claude_code_hook -e packages/licensing -e apps/api
WORKDIR /srv/apps/api
EXPOSE 8000
# migra com o dono do banco (ADMIN_DATABASE_URL) e serve com o papel restrito (DATABASE_URL)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
