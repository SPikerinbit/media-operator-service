"""Short-lived loopback proxy for public media requests and extractor redirects."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import ipaddress
from functools import lru_cache
import secrets
import select
import socket
import threading
import time
from urllib.parse import unquote, urlsplit

import httpx


@lru_cache(maxsize=128)
def proxy_dns(host, proxy, period):
    """Resolve a hostname when the system proxy installs a synthetic DNS address."""
    with httpx.Client(proxy=proxy, timeout=5, trust_env=False) as client:
        response = client.get("https://1.1.1.1/dns-query", params={"name": host, "type": "A"},
                              headers={"Accept": "application/dns-json"})
        response.raise_for_status()
        return tuple(record["data"] for record in response.json().get("Answer", []) if record.get("type") == 1)


def public_target(value, upstream=None):
    parsed = urlsplit(value)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username is not None
            or parsed.port not in {None, 80, 443} or any(char.isspace() or char == chr(92) for char in value)):
        raise ValueError("请输入公开的 HTTP(S) 媒体链接")
    host = parsed.hostname.rstrip(".")
    if ("." not in host and ":" not in host or host.endswith((".localhost", ".local", ".internal", ".test"))):
        raise ValueError("链接必须指向公网")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    synthetic = ipaddress.ip_network("198.18.0.0/15")
    if upstream and addresses and all(ipaddress.ip_address(address).is_loopback
                                     or ipaddress.ip_address(address) in synthetic for address in addresses):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            proxy = upstream if "://" in upstream else "http://" + upstream
            try:
                addresses = proxy_dns(host, proxy, int(time.monotonic() // 60))
            except (httpx.HTTPError, ValueError):
                raise ValueError("链接必须指向可访问的公网地址") from None
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise ValueError("链接必须指向公网")
    if not addresses:
        raise ValueError("未找到公网地址")
    return parsed, port, addresses


def connect(addresses, port, upstream):
    if upstream:
        proxy = urlsplit(upstream if "://" in upstream else "http://" + upstream)
        if proxy.scheme != "http" or not proxy.hostname:
            raise ValueError("请使用 Windows HTTP 代理")
        for address in addresses:
            authority = f"[{address}]:{port}" if ":" in address else f"{address}:{port}"
            peer = socket.create_connection((proxy.hostname, proxy.port or 80), timeout=10)
            try:
                headers = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
                if proxy.username is not None:
                    credential = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}".encode()
                    headers += "Proxy-Authorization: Basic " + base64.b64encode(credential).decode() + "\r\n"
                peer.sendall((headers + "\r\n").encode("ascii"))
                with peer.makefile("rb", buffering=0) as response:
                    status = response.readline(4096).split()
                    for _ in range(100):
                        if response.readline(4096) in {b"\r\n", b""}:
                            break
                    else:
                        raise OSError("Invalid proxy response")
                if len(status) > 1 and status[1] == b"200":
                    return peer
            except OSError:
                pass
            peer.close()
        raise OSError("Windows proxy could not connect")
    for address in addresses:
        try:
            return socket.create_connection((address, port), timeout=8)
        except OSError:
            pass
    raise OSError("Media host could not be reached")


@contextmanager
def public_proxy(upstream_for):
    password = secrets.token_urlsafe(18)
    credential = "Basic " + base64.b64encode(f"media:{password}".encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def handle_request(self):
            if self.headers.get("Proxy-Authorization") != credential:
                self.send_error(407)
                return
            tunnel = self.command == "CONNECT"
            target = "https://" + self.path if tunnel else self.path
            try:
                upstream = upstream_for(target)
                parsed, port, addresses = public_target(target, upstream)
                if (tunnel and (parsed.path or parsed.query or parsed.fragment)
                        or not tunnel and parsed.scheme != "http"):
                    raise ValueError("Invalid proxy request")
                peer = connect(addresses, port, upstream)
            except (OSError, ValueError):
                self.send_error(502, "Public media target unavailable")
                return
            try:
                with peer:
                    if tunnel:
                        self.send_response_only(200)
                        self.end_headers()
                        self.wfile.flush()
                        while True:
                            readable, _, _ = select.select([peer, self.connection], [], [], 45)
                            if not readable:
                                break
                            for origin in readable:
                                chunk = origin.recv(65536)
                                if not chunk:
                                    return
                                (peer if origin is self.connection else self.connection).sendall(chunk)
                    else:
                        path = parsed.path or "/"
                        if parsed.query:
                            path += "?" + parsed.query
                        skip = {"host", "connection", "proxy-connection", "proxy-authorization"}
                        headers = f"{self.command} {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nConnection: close\r\n"
                        headers += "".join(f"{key}: {value}\r\n" for key, value in self.headers.items() if key.lower() not in skip)
                        peer.sendall((headers + "\r\n").encode("latin-1"))
                        for chunk in iter(lambda: peer.recv(65536), b""):
                            self.wfile.write(chunk)
            except OSError:
                pass

        do_CONNECT = do_GET = do_HEAD = handle_request

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        try:
            yield f"http://media:{password}@127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join()
