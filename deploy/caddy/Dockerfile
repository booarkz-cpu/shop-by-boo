ARG CADDY_BASE_IMAGE=caddy:2.11-alpine@sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5
FROM ${CADDY_BASE_IMAGE}
# The upstream executable has CAP_NET_BIND_SERVICE. With cap_drop: ALL this
# file capability makes exec fail with EPERM. Ports are enabled by the
# container's ip_unprivileged_port_start sysctl; no capability is needed.
RUN apk add --no-cache libcap && setcap -r /usr/bin/caddy
USER 10001:10001
