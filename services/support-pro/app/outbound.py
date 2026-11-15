"""Connect only to validated literal public IPs; preserve TLS hostname."""
import ipaddress
import socket

class _PinnedPublicDNSBackend:
    """httpcore backend that resolves hostnames immediately before each new TCP connection.

    The resolved IP is then passed as a literal to the underlying socket connector while
    httpcore keeps the original hostname for TLS SNI/certificate verification. This closes
    the validation-vs-use DNS rebinding window: the connection cannot perform a second DNS
    lookup after the public-IP check.
    """
    def __init__(self):
        import httpcore
        self._backend=httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        import httpcore
        try:
            literal=ipaddress.ip_address(host)
            if literal.is_private or not literal.is_global:
                raise OSError("destination is not a globally routable IP")
            target=str(literal)
        except ValueError:
            try:
                infos=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
            except OSError as exc:
                raise OSError(f"DNS resolution failed: {exc}") from exc
            addresses=[]
            for info in infos:
                addr=info[4][0].split("%",1)[0]
                try: ip=ipaddress.ip_address(addr)
                except ValueError: continue
                if ip.is_private or not ip.is_global:
                    raise OSError("hostname resolved to a non-public address")
                if str(ip) not in addresses:
                    addresses.append(str(ip))
            if not addresses:
                raise OSError("hostname has no globally routable address")
            target=addresses[0]
        return await self._backend.connect_tcp(target,port,timeout,local_address,socket_options)


def _pinned_public_http_client(timeout_seconds:int):
    import httpx
    transport=httpx.AsyncHTTPTransport(retries=0,trust_env=False)
    # httpx exposes the httpcore pool internally; using its documented network-backend
    # abstraction avoids a second DNS lookup while retaining the original TLS hostname.
    transport._pool._network_backend=_PinnedPublicDNSBackend()
    return httpx.AsyncClient(timeout=timeout_seconds,transport=transport,follow_redirects=False)

