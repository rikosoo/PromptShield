FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# limita o heap do Node no build: cabe em VM de 2 GB
RUN NODE_OPTIONS=--max-old-space-size=1024 npm run build
EXPOSE 3000
CMD ["npm", "run", "start"]
