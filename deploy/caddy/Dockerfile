ARG CADDY_BASE_IMAGE=caddy:2.11-alpine@sha256:78bd35025c7ba85961dd149ae670315129954e77abe2383ac47c89106b35ade9
FROM ${CADDY_BASE_IMAGE}
# The upstream executable has CAP_NET_BIND_SERVICE. With cap_drop: ALL this
# file capability makes exec fail with EPERM. Ports are enabled by the
# container's ip_unprivileged_port_start sysctl; no capability is needed.
# v28.123.0: the base image is pinned by digest, so the package fixes published since are installed here.
RUN apk upgrade --no-cache && apk add --no-cache libcap && setcap -r /usr/bin/caddy
USER 10001:10001
