from __future__ import annotations

import socket
import ssl
import time
from contextlib import contextmanager
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager


@contextmanager
def force_ipv4_resolution() -> Any:
    """Temporarily force DNS resolution to return only IPv4 addresses.

    Some government sites reset IPv6 connections from certain networks.
    Using this context manager makes requests/urllib3 use AF_INET only.
    """

    original_getaddrinfo = socket.getaddrinfo

    def ipv4_only_getaddrinfo(host: str, port: str | int, family: int = 0, type: int = 0, proto: int = 0, flags: int = 0):  # type: ignore[override]
        results = original_getaddrinfo(host, port, family, type, proto, flags)
        ipv4_results = [ai for ai in results if ai and ai[0] == socket.AF_INET]
        return ipv4_results or results

    socket.getaddrinfo = ipv4_only_getaddrinfo  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]


def robust_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    verify: bool = True,
    stream: bool = False,
    allow_redirects: bool = True,
    max_attempts: int = 10,
    sleep_seconds: float = 0.8,
) -> requests.Response:
    """GET with a best-effort IPv4 fallback and small retries."""

    class _TLSv12HttpAdapter(HTTPAdapter):
        def __init__(self, *, verify: bool = True):
            # NOTE: HTTPAdapter.__init__ calls init_poolmanager(), which needs _verify.
            self._verify = bool(verify)
            super().__init__()

        def _build_ssl_context(self) -> ssl.SSLContext:
            ctx = ssl.create_default_context()
            # Some servers reset TLSv1.3 handshakes. Force TLS 1.2 as a fallback.
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.maximum_version = ssl.TLSVersion.TLSv1_2
            if not self._verify:
                # When we provide a custom SSLContext, urllib3 can't safely override
                # check_hostname/verify_mode for verify=False. Configure it explicitly.
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            return ctx

        def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any):
            pool_kwargs["ssl_context"] = self._build_ssl_context()
            self.poolmanager = PoolManager(
                num_pools=connections,
                maxsize=maxsize,
                block=block,
                **pool_kwargs,
            )

        def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any):
            proxy_kwargs["ssl_context"] = self._build_ssl_context()
            return super().proxy_manager_for(proxy, **proxy_kwargs)

    tls12_session = requests.Session()
    tls12_session.mount("https://", _TLSv12HttpAdapter(verify=verify))

    last_exc: Exception | None = None
    try:
        # Strategy sequence (increasingly opinionated):
        # 1) default
        # 2) IPv4-only DNS
        # 3) TLSv1.2-only
        # 4) TLSv1.2-only + IPv4-only DNS
        # 5+) repeat last strategy
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt == 1:
                    return requests.get(
                        url,
                        headers=headers,
                        timeout=timeout,
                        verify=verify,
                        stream=stream,
                        allow_redirects=allow_redirects,
                    )

                if attempt == 2:
                    with force_ipv4_resolution():
                        return requests.get(
                            url,
                            headers=headers,
                            timeout=timeout,
                            verify=verify,
                            stream=stream,
                            allow_redirects=allow_redirects,
                        )

                if attempt == 3:
                    return tls12_session.get(
                        url,
                        headers=headers,
                        timeout=timeout,
                        verify=verify,
                        stream=stream,
                        allow_redirects=allow_redirects,
                    )

                with force_ipv4_resolution():
                    return tls12_session.get(
                        url,
                        headers=headers,
                        timeout=timeout,
                        verify=verify,
                        stream=stream,
                        allow_redirects=allow_redirects,
                    )
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    raise
                time.sleep(min(6.0, sleep_seconds * float(attempt)))
    finally:
        tls12_session.close()

    # Defensive; the loop should always return or raise.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("robust_get failed without exception")
