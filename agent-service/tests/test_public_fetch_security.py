import socket
import time
import unittest
from unittest.mock import MagicMock, patch

from agent_service.capture.fetch import _public_addresses, _read_public, fetch_public_url


class PublicFetchSecurityTests(unittest.TestCase):
    def addresses(self, ip="93.184.216.34"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]

    def test_private_dns_and_numeric_urls_rejected(self):
        for address in ["127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "192.0.2.1"]:
            with patch("socket.getaddrinfo", return_value=self.addresses(address)):
                with self.assertRaisesRegex(ValueError, "SSRF"):
                    _public_addresses("http://source.example/doc")
        with self.assertRaisesRegex(ValueError, "SSRF"):
            _public_addresses("http://2130706433/doc")

    def test_all_dns_answers_must_be_public(self):
        with patch("socket.getaddrinfo", return_value=self.addresses() + self.addresses("10.1.2.3")):
            with self.assertRaisesRegex(ValueError, "SSRF"):
                _public_addresses("https://source.example")

    def transport(self, response):
        sock = MagicMock()
        sock.getpeername.return_value = ("93.184.216.34", 80)
        conn = MagicMock()
        conn.getresponse.return_value = response
        return sock, conn

    def test_redirect_to_localhost_is_checked_before_next_connection(self):
        response = MagicMock(status=302)
        response.getheader.return_value = "http://localhost/private"
        sock, conn = self.transport(response)
        with patch("socket.getaddrinfo", return_value=self.addresses()), patch("socket.socket", return_value=sock), patch("http.client.HTTPConnection", return_value=conn):
            with self.assertRaisesRegex(ValueError, "SSRF"):
                fetch_public_url("http://source.example")
        self.assertEqual(sock.connect.call_count, 1)

    def test_connect_uses_approved_address_without_second_dns(self):
        response = MagicMock(status=200)
        response.getheader.return_value = "identity"
        response.read1.side_effect = [b"a" * 100, b""]
        sock, conn = self.transport(response)
        with patch("socket.getaddrinfo", side_effect=[self.addresses(), self.addresses("127.0.0.1")]) as dns, patch("socket.socket", return_value=sock), patch("http.client.HTTPConnection", return_value=conn):
            _read_public("http://source.example", time.monotonic() + 10)
        dns.assert_called_once()
        sock.connect.assert_called_once_with(("93.184.216.34", 80))
        self.assertIs(conn.sock, sock)

    def test_actual_peer_is_checked(self):
        sock, conn = self.transport(MagicMock(status=200))
        sock.getpeername.return_value = ("127.0.0.1", 80)
        with patch("socket.getaddrinfo", return_value=self.addresses()), patch("socket.socket", return_value=sock), patch("http.client.HTTPConnection", return_value=conn):
            with self.assertRaisesRegex(ValueError, "SSRF"):
                _read_public("http://source.example", time.monotonic() + 10)
        conn.request.assert_not_called()

    def test_response_size_and_deadline_are_bounded(self):
        response = MagicMock(status=200)
        response.getheader.return_value = "identity"
        response.read1.return_value = b"a" * 64_000
        sock, conn = self.transport(response)
        with patch("socket.getaddrinfo", return_value=self.addresses()), patch("socket.socket", return_value=sock), patch("http.client.HTTPConnection", return_value=conn):
            with self.assertRaisesRegex(ValueError, "RESPONSE_TOO_LARGE"):
                _read_public("http://source.example", time.monotonic() + 10)
            with self.assertRaises(TimeoutError):
                _read_public("http://source.example", time.monotonic() - 1)

    def test_redirect_limit(self):
        with patch("agent_service.capture.fetch._read_public", return_value=("https://example.com/again", b"")) as read:
            with self.assertRaisesRegex(ValueError, "TOO_MANY_REDIRECTS"):
                fetch_public_url("https://example.com")
        self.assertEqual(read.call_count, 6)
