"""Forwarded addresses are accepted only from explicitly configured ingress peers."""
import ipaddress
import os


def client_ip(request):
    peer = request.client.host if request.client else 'unknown'
    try:
        address = ipaddress.ip_address(peer)
        networks = [ipaddress.ip_network(x.strip()) for x in os.getenv('TRUSTED_PROXY_CIDRS', '').split(',') if x.strip()]
        if not networks or any(n.prefixlen == 0 for n in networks) or not any(address in n for n in networks):
            return peer
        forwarded = request.headers.get('x-forwarded-for', '').split(',', 1)[0].strip()
        return str(ipaddress.ip_address(forwarded)) if forwarded else peer
    except ValueError:
        return peer
