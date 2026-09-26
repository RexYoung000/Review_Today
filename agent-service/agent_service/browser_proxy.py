"""An ephemeral, authenticated public-network proxy for the isolated renderer.

Every CONNECT and plain HTTP request resolves once, validates every address,
and connects to the validated IP. TLS remains end-to-end in the browser.
This module must not import model configuration or load any .env file.
"""
import base64
import hmac
import ipaddress
import secrets
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
from agent_service.certs import ssl_context
from agent_service.web_privacy import public_service_url

FAKE_IP = ipaddress.ip_network('198.18.0.0/15')
MAX_BYTES = 24_000_000
MAX_CONNECTIONS = 96


def public_addresses(values):
    addresses = list(dict.fromkeys(str(ipaddress.ip_address(v)) for v in values))
    if not addresses or any(not ipaddress.ip_address(v).is_global or ipaddress.ip_address(v).is_reserved
                            for v in addresses):
        raise ValueError('RT.WEB.BROWSER_ADDRESS_BLOCKED')
    return addresses


def resolve_public(host, deadline):
    public_service_url('https://' + host + '/')
    values = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    # Only a system-wide Fake-IP mapping may use the public DNS fallback.
    # A private, loopback, mixed or empty answer is never retried elsewhere.
    if values and all(ipaddress.ip_address(v).version == 4 and ipaddress.ip_address(v) in FAKE_IP for v in values):
        timeout = min(4, deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError()
        with httpx.Client(verify=ssl_context(), trust_env=False, follow_redirects=False, timeout=timeout) as client:
            response = client.get('https://cloudflare-dns.com/dns-query',
                                  params={'name': host, 'type': 'A'}, headers={'Accept': 'application/dns-json'})
            response.raise_for_status()
            if len(response.content) > 32_000:
                raise ValueError('RT.WEB.BROWSER_DNS_FAILED')
            data = response.json()
            if data.get('Status') != 0 or data.get('TC') or not isinstance(data.get('Answer'), list):
                raise ValueError('RT.WEB.BROWSER_DNS_FAILED')
            values = [v['data'] for v in data['Answer'] if v.get('type') == 1 and isinstance(v.get('data'), str)]
    return public_addresses(values)


class PublicProxy:
    def __init__(self, seconds, *, resolver=resolve_public):
        self.deadline = time.monotonic() + seconds
        self.resolver = resolver
        self.password = secrets.token_urlsafe(24)
        self.authorization = 'Basic ' + base64.b64encode(('review:' + self.password).encode()).decode()
        self.lock = threading.Lock()
        self.sockets = set()
        self.cache = {}
        self.connections = self.bytes = self.blocked = 0
        self.stopped = threading.Event()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ProxyHandler)
        self.server.daemon_threads = True
        self.server.owner = self
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .05}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    @property
    def configuration(self):
        return dict(server=f'http://127.0.0.1:{self.server.server_port}', username='review', password=self.password,
                    bypass='<-loopback>')

    def check(self):
        if self.stopped.is_set() or time.monotonic() >= self.deadline:
            raise TimeoutError()

    def connect(self, host, port):
        self.check()
        public_service_url(f'https://{host}:{port}/')
        with self.lock:
            if self.connections >= MAX_CONNECTIONS:
                raise ValueError('RT.WEB.BROWSER_RESOURCE_LIMIT')
            self.connections += 1
            cached = self.cache.get(host)
        addresses = public_addresses(cached if cached is not None else self.resolver(host, self.deadline))
        with self.lock:
            self.cache[host] = addresses
        for address in addresses[:3]:
            self.check()
            family = socket.AF_INET6 if ':' in address else socket.AF_INET
            connection = socket.socket(family, socket.SOCK_STREAM)
            try:
                connection.settimeout(min(3, max(.01, self.deadline - time.monotonic())))
                # No second hostname resolution is permitted here.
                connection.connect((address, port))
                peer = str(ipaddress.ip_address(connection.getpeername()[0]))
                public_addresses([peer])
                if peer != address:
                    raise ValueError('RT.WEB.BROWSER_ADDRESS_BLOCKED')
                with self.lock:
                    self.sockets.add(connection)
                return connection
            except OSError:
                connection.close()
            except Exception:
                connection.close()
                raise
        raise OSError('RT.WEB.BROWSER_CONNECTION')

    def relay(self, client, upstream):
        client.settimeout(1)
        with self.lock:
            self.sockets.add(client)
        try:
            while True:
                self.check()
                readable, _, _ = select.select([client, upstream], [], [], .1)
                for source in readable:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    with self.lock:
                        self.bytes += len(chunk)
                        if self.bytes > MAX_BYTES:
                            raise ValueError('RT.WEB.BROWSER_RESOURCE_LIMIT')
                    target = upstream if source is client else client
                    target.sendall(chunk)
        finally:
            with self.lock:
                self.sockets.discard(client)
                self.sockets.discard(upstream)
            upstream.close()

    def __exit__(self, *_):
        self.stopped.set()
        with self.lock:
            sockets = list(self.sockets)
        for connection in sockets:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=.2)


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    rbufsize = 0

    def log_message(self, *_):
        pass  # Request URLs and headers never enter application logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(2)

    def authenticated(self):
        if hmac.compare_digest(self.headers.get('Proxy-Authorization', ''), self.server.owner.authorization):
            return True
        self.send_response(407)
        self.send_header('Proxy-Authenticate', 'Basic realm="ReviewToday"')
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        return False

    def do_CONNECT(self):
        if not self.authenticated():
            return
        upstream = None
        try:
            target = urlsplit('https://' + self.path)
            if target.path or target.query or target.fragment or target.username or target.password:
                raise ValueError()
            upstream = self.server.owner.connect(target.hostname or '', target.port or 443)
            self.send_response(200)
            self.end_headers()
            self.server.owner.relay(self.connection, upstream)
        except (ValueError, OSError, httpx.HTTPError, TimeoutError):
            with self.server.owner.lock:
                self.server.owner.blocked += 1
            if upstream is None:
                self.send_error(403, 'Public destination required')
        finally:
            if upstream:
                upstream.close()
            self.close_connection = True

    def do_GET(self):
        if not self.authenticated():
            return
        upstream = None
        try:
            target = urlsplit(self.path)
            if target.scheme != 'http' or target.username or target.password or target.fragment:
                raise ValueError()
            upstream = self.server.owner.connect(target.hostname or '', target.port or 80)
            path = (target.path or '/') + ('?' + target.query if target.query else '')
            headers = {k: v for k, v in self.headers.items() if k.lower() not in
                       {'proxy-authorization', 'proxy-connection', 'connection', 'host', 'content-length', 'transfer-encoding'}}
            headers.update(Host=target.netloc, Connection='close')
            raw = f'{self.command} {path} HTTP/1.1\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in headers.items()) + '\r\n'
            upstream.sendall(raw.encode('iso-8859-1'))
            self.server.owner.relay(self.connection, upstream)
        except (ValueError, OSError, httpx.HTTPError, TimeoutError):
            with self.server.owner.lock:
                self.server.owner.blocked += 1
            if upstream is None:
                self.send_error(403, 'Public destination required')
        finally:
            if upstream:
                upstream.close()
            self.close_connection = True

    do_HEAD = do_GET
