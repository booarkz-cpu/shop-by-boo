ARG NODE_BASE_IMAGE=node:26-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94
ARG NGINX_BASE_IMAGE=nginx:1.30-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949
FROM ${NODE_BASE_IMAGE} AS build
# VITE_API_URL is the historical Compose build argument; Next.js reads NEXT_PUBLIC_API_URL.
ARG VITE_API_URL=""
ENV NEXT_PUBLIC_API_URL=$VITE_API_URL \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /src/apps/lucy-admin/web
COPY apps/lucy-admin/web/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --ignore-scripts --no-audit --no-fund; else npm install --package-lock=false --ignore-scripts --no-audit --no-fund; fi
COPY apps/lucy-admin/web/ .
COPY apps/user-cabinet/src/support-attachments.tsx /src/apps/user-cabinet/src/support-attachments.tsx
COPY apps/user-cabinet/src/public-pages.tsx /src/apps/user-cabinet/src/public-pages.tsx
COPY apps/user-cabinet/src/button-tree.tsx /src/apps/user-cabinet/src/button-tree.tsx
COPY apps/user-cabinet/src/http-json.ts /src/apps/user-cabinet/src/http-json.ts
COPY apps/user-cabinet/scripts/csp-externalize.mjs /src/apps/user-cabinet/scripts/csp-externalize.mjs
RUN ln -s /src/admin/node_modules /src/apps/user-cabinet/node_modules
RUN npm run build
FROM ${NGINX_BASE_IMAGE}
# The base image is pinned by digest: the package fixes published since are installed here (v28.123.0).
RUN apk upgrade --no-cache
COPY --from=build /src/apps/lucy-admin/web/dist /usr/share/nginx/html
COPY apps/lucy-admin/web/nginx.conf /etc/nginx/nginx.conf
COPY apps/lucy-admin/web/default.conf /etc/nginx/conf.d/default.conf
USER 101:101
EXPOSE 80
CMD ["/bin/sh", "-c", "mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && chmod 1777 /tmp/nginx /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && exec nginx -g 'daemon off;'"]
