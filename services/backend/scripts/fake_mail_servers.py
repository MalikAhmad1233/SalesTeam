"""Local IMAP and SMTP servers for the dashboard's end-to-end test (never used in a deployment).

    uv run python scripts/fake_mail_servers.py

IMAP on 127.0.0.1:8143 and SMTP on 127.0.0.1:8025 (no TLS: only allowed in local/test), plus a
control endpoint on 127.0.0.1:8144: ``POST /inbox`` adds a raw email to the mailbox, ``GET /sent``
lists what was sent, ``GET /health`` answers when ready.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from email import message_from_bytes, policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mail_servers import FakeImap, FakeSmtp

IMAP_PORT, SMTP_PORT, CONTROL_PORT = 8143, 8025, 8144


def main() -> None:
    imap, smtp = FakeImap(IMAP_PORT), FakeSmtp(SMTP_PORT)

    class Control(BaseHTTPRequestHandler):
        def _json(self, status: int, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json(200, {"ok": True})
            elif self.path == "/sent":
                sent = []
                for envelope in smtp.handler.received:
                    msg = message_from_bytes(envelope.original_content or b"", policy=policy.default)
                    sent.append(
                        {"to": envelope.rcpt_tos, "subject": str(msg["Subject"]), "in_reply_to": msg["In-Reply-To"]}
                    )
                self._json(200, sent)
            else:
                self._json(404, {})

        def do_POST(self) -> None:
            if self.path != "/inbox":
                self._json(404, {})
                return
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self._json(200, {"uid": imap.mailbox.add(raw)})

        def log_message(self, *_args: object) -> None:
            pass

    control = ThreadingHTTPServer(("127.0.0.1", CONTROL_PORT), Control)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    threading.Thread(target=control.serve_forever, daemon=True).start()
    print(f"fake mail servers: IMAP {IMAP_PORT}, SMTP {SMTP_PORT}, control {CONTROL_PORT}", flush=True)
    stop.wait()
    control.shutdown()
    imap.stop()
    smtp.stop()


if __name__ == "__main__":
    main()
