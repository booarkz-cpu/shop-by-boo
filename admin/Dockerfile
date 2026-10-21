ARG NODE_BASE_IMAGE=node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402
ARG NGINX_BASE_IMAGE=nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
FROM ${NODE_BASE_IMAGE} AS build
# VITE_API_URL is the historical Compose build argument; Next.js reads NEXT_PUBLIC_API_URL.
ARG VITE_API_URL=""
ENV NEXT_PUBLIC_API_URL=$VITE_API_URL \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /src/admin
COPY admin/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --ignore-scripts --no-audit --no-fund; else npm install --package-lock=false --ignore-scripts --no-audit --no-fund; fi
COPY admin/ .
COPY cabinet/src/support-attachments.tsx /src/cabinet/src/support-attachments.tsx
COPY cabinet/src/public-pages.tsx /src/cabinet/src/public-pages.tsx
COPY cabinet/src/button-tree.tsx /src/cabinet/src/button-tree.tsx
COPY cabinet/scripts/csp-externalize.mjs /src/cabinet/scripts/csp-externalize.mjs
RUN ln -s /src/admin/node_modules /src/cabinet/node_modules
RUN npm run build
FROM ${NGINX_BASE_IMAGE}
COPY --from=build /src/admin/dist /usr/share/nginx/html
COPY admin/nginx.conf /etc/nginx/nginx.conf
COPY admin/default.conf /etc/nginx/conf.d/default.conf
USER 101:101
EXPOSE 80
CMD ["/bin/sh", "-c", "mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && chmod 1777 /tmp/nginx /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && exec nginx -g 'daemon off;'"]
