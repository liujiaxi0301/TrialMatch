FROM mcr.microsoft.com/playwright:v1.56.1-noble AS test
WORKDIR /tests
COPY docker/frontend/package.json docker/frontend/package-lock.json ./
RUN npm ci
COPY services/frontend/e2e/ ./
CMD ["npm", "test"]

FROM nginx:1.28.0-alpine AS runtime
COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY services/frontend/static/ /usr/share/nginx/html/
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=5s --retries=18 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz
