"""Temporary webhook-only loopback relay; standard library only (Python 3.8+).

Run on Windows: python -m accounts.webhook_relay
ONLY tunnel 127.0.0.1:8765, never the Django development server on port 8000.
No credentials, payloads, cookies, or debug responses are logged or stored here.
This module does not create a public tunnel, call Paystack, or process payments.
"""

import argparse
import http.client
import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


RELAY_ADDRESS = ("127.0.0.1", 8765)
PREVIEW_ADDRESS = ("127.0.0.1", 8000)
PUBLIC_PATH = "/payments/paystack/test/webhook/"
PREVIEW_PATH = "/payments/paystack/test/local-relay/"
MAX_BODY = 256 * 1024
MAX_ACK = 4096
IO_TIMEOUT = 10
MAX_CLIENTS = 8


def _preview_request(method, body=None, signature=None):
    # HTTPConnection uses this fixed loopback address directly: no DNS, proxy
    # environment variables, user-supplied target, or automatic redirect follow.
    connection = http.client.HTTPConnection(*PREVIEW_ADDRESS, timeout=IO_TIMEOUT)
    headers = {"Accept": "application/json"}
    if body is not None:
        headers.update({
            "Content-Type": "application/json", "Content-Length": str(len(body)),
            "x-paystack-signature": signature,
        })
    try:
        connection.request(method, PREVIEW_PATH, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(MAX_ACK + 1)
        if len(raw) > MAX_ACK:
            return 503, None
        status = response.status
        if status != 200:
            # Never forward HTML, error text, redirects, cookies or other headers.
            return (status if status in {400, 403, 413, 415, 429} else 503), None
        if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return 503, None
        try:
            return status, json.loads(raw)
        except (ValueError, UnicodeError):
            return 503, None
    except (OSError, http.client.HTTPException):
        return 503, None
    finally:
        connection.close()


def preview_ready():
    status, data = _preview_request("GET")
    return bool(
        status == 200 and isinstance(data, dict)
        and data.get("disposable_paystack_preview") is True
        and type(data.get("relay_protocol")) is int and data["relay_protocol"] == 1
    )


class WebhookRelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # One request per connection; no keep-alive.
    server_version = "StudiGarden-WebhookRelay"
    sys_version = ""

    def log_message(self, *_args):
        # Request paths/headers/bodies/signatures may contain private material.
        pass

    def send_error(self, code, message=None, explain=None):
        self._reply(code)  # Never echo a malformed request or exception.

    def _reply(self, status, body=b""):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if body and getattr(self, "command", None) != "HEAD":
            self.wfile.write(body)

    def do_POST(self):
        # Check the raw request target too: the standard parser normalizes //.
        parts = self.raw_requestline.rstrip(b"\r\n").split(b" ")
        if len(parts) != 3:
            return self._reply(400)
        target = parts[1]
        if self.path != PUBLIC_PATH or target != PUBLIC_PATH.encode("ascii"):
            return self._reply(404)
        for field in ("Content-Length", "Content-Type", "x-paystack-signature"):
            if len(self.headers.get_all(field, [])) > 1:
                return self._reply(400)
        if self.headers.get("Transfer-Encoding") is not None:
            return self._reply(400)
        if self.headers.get("Content-Encoding") is not None:
            return self._reply(415)
        if self.headers.get("Expect") is not None:
            return self._reply(417)
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self._reply(415)
        length = self.headers.get("Content-Length", "")
        if not re.fullmatch(r"[0-9]{1,10}", length):
            return self._reply(411)
        size = int(length)
        if size > MAX_BODY:
            return self._reply(413)
        signature = self.headers.get("x-paystack-signature", "")
        if not re.fullmatch(r"[a-fA-F0-9]{128}", signature):
            return self._reply(403)
        try:
            body = self.rfile.read(size)
        except OSError:
            return self._reply(400)
        if len(body) != size:
            return self._reply(400)
        status, data = _preview_request("POST", body, signature)
        if status == 200:
            if not (
                isinstance(data, dict) and data.get("received") is True
                and data.get("membership_updates") is False
            ):
                return self._reply(503)
            # Acknowledgement only, never an unfiltered backend response body.
            return self._reply(200, b'{"received":true}')
        return self._reply(status)

    def _deny(self):
        return self._reply(404)

    do_GET = _deny
    do_HEAD = _deny
    do_PUT = _deny
    do_DELETE = _deny
    do_PATCH = _deny
    do_OPTIONS = _deny
    do_TRACE = _deny
    do_CONNECT = _deny


class WebhookRelayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = MAX_CLIENTS

    def __init__(self, address, handler=WebhookRelayHandler):
        if address[0] != "127.0.0.1":
            raise ValueError("The webhook relay must listen on loopback only.")
        self._slots = threading.BoundedSemaphore(MAX_CLIENTS)
        super().__init__(address, handler)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def process_request(self, request, client_address):
        request.settimeout(IO_TIMEOUT)
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # Never print debug traces or captured request values to a tunnel log.
        pass


def _minutes(value):
    minutes = int(value)
    if not 1 <= minutes <= 120:
        raise argparse.ArgumentTypeError("Choose between 1 and 120 minutes.")
    return minutes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Paystack TEST webhook-only relay. No public tunnel is started.")
    parser.add_argument("--minutes", type=_minutes, default=60)
    args = parser.parse_args(argv)
    if not preview_ready():
        print("Stopped: the disposable Paystack preview is not ready on 127.0.0.1:8000. No relay was opened.")
        return 1
    try:
        server = WebhookRelayServer(RELAY_ADDRESS)
    except OSError:
        print("Stopped: local relay port 8765 is unavailable. No public connection was opened.")
        return 1
    with server:
        timer = threading.Timer(args.minutes * 60, server.shutdown)
        timer.daemon = True
        timer.start()
        print("Webhook-only relay ready at http://127.0.0.1:8765")
        print("Only POST " + PUBLIC_PATH + " is forwarded to the guarded disposable preview.")
        print("No tunnel is running yet. Never tunnel the development server's port 8000.")
        print("Press Ctrl+C to stop; automatic stop after " + str(args.minutes) + " minutes.")
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        finally:
            timer.cancel()
    print("Relay stopped. Stop any separate tunnel too, and remove its URL from Paystack TEST settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
