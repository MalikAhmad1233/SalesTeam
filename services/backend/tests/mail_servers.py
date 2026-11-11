"""Local mail servers for tests: a small IMAP server (the commands Mixt uses) and a real SMTP
server (aiosmtpd). Both run on 127.0.0.1 without TLS ("none" security is allowed only in tests)."""

from __future__ import annotations

import shlex
import socket
import socketserver
import threading
from dataclasses import dataclass, field
from typing import Any

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, Envelope, LoginPassword, Session

USER, PASSWORD = "sales@mixt.example", "app-password-1234"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Mailbox:
    uidvalidity: int = 1001
    messages: list[tuple[int, bytes]] = field(default_factory=list)
    password: str = PASSWORD
    commands: list[str] = field(default_factory=list)

    def add(self, raw: bytes) -> int:
        uid = (self.messages[-1][0] + 1) if self.messages else 1
        self.messages.append((uid, raw))
        return uid

    def uidnext(self) -> int:
        return (self.messages[-1][0] + 1) if self.messages else 1


class _ImapHandler(socketserver.StreamRequestHandler):
    server: _ImapServer

    def _send(self, line: str | bytes) -> None:
        self.wfile.write((line.encode() if isinstance(line, str) else line) + b"\r\n")

    def handle(self) -> None:
        box = self.server.mailbox
        self._send("* OK [CAPABILITY IMAP4rev1] fake IMAP ready")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode().rstrip("\r\n")
            tag, _, rest = line.partition(" ")
            command, _, args = rest.partition(" ")
            command = command.upper()
            box.commands.append(f"{command} {args}".strip())
            if command == "CAPABILITY":
                self._send("* CAPABILITY IMAP4rev1")
                self._send(f"{tag} OK CAPABILITY completed")
            elif command == "LOGIN":
                user, password = shlex.split(args)
                if user == USER and password == box.password:
                    self._send(f"{tag} OK LOGIN completed")
                else:
                    self._send(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials")
            elif command in ("SELECT", "EXAMINE"):
                self._send(f"* {len(box.messages)} EXISTS")
                self._send(f"* OK [UIDVALIDITY {box.uidvalidity}] UIDs valid")
                self._send(f"* OK [UIDNEXT {box.uidnext()}] Predicted next UID")
                self._send(f"{tag} OK [READ-ONLY] {command} completed")
            elif command == "UID":
                self._uid(tag, args, box)
            elif command == "LOGOUT":
                self._send("* BYE logging out")
                self._send(f"{tag} OK LOGOUT completed")
                return
            else:
                self._send(f"{tag} OK {command} completed" if command == "NOOP" else f"{tag} BAD unknown command")

    def _uid(self, tag: str, args: str, box: Mailbox) -> None:
        sub, _, rest = args.partition(" ")
        sub = sub.upper()
        uids = [u for u, _ in box.messages]
        if sub == "SEARCH":
            parts = rest.split()
            if parts and parts[0].upper() == "UID":
                start = int(parts[1].split(":")[0])
                found = [u for u in uids if u >= start] or uids[-1:]  # "n:*" always matches the newest
            else:
                found = uids  # ALL, SINCE <date>: every message is recent enough here
            self._send("* SEARCH " + " ".join(str(u) for u in found))
            self._send(f"{tag} OK SEARCH completed")
        elif sub == "FETCH":
            uid = int(rest.split()[0])
            for seq, (u, body) in enumerate(box.messages, start=1):
                if u == uid:
                    self.wfile.write(f"* {seq} FETCH (UID {u} BODY[] {{{len(body)}}}\r\n".encode() + body + b")\r\n")
            self._send(f"{tag} OK FETCH completed")
        else:
            self._send(f"{tag} BAD unsupported")


class _ImapServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, mailbox: Mailbox, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), _ImapHandler)
        self.mailbox = mailbox


class FakeImap:
    def __init__(self, port: int = 0) -> None:
        self.mailbox = Mailbox()
        self.server = _ImapServer(self.mailbox, port)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@dataclass
class _SmtpHandler:
    received: list[Envelope] = field(default_factory=list)
    refuse: set[str] = field(default_factory=set)
    temporary_failure: bool = False

    async def handle_RCPT(  # noqa: N802 (aiosmtpd hook name)
        self, server: Any, session: Session, envelope: Envelope, address: str, rcpt_options: list[str]
    ) -> str:
        if self.temporary_failure:
            return "451 4.3.0 Try again later"
        if address in self.refuse:
            return "550 5.1.1 No such user"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: Any, session: Session, envelope: Envelope) -> str:  # noqa: N802
        self.received.append(envelope)
        return "250 Message accepted"


def _authenticator(server: Any, session: Session, envelope: Envelope, mechanism: str, auth_data: Any) -> AuthResult:
    ok = (
        isinstance(auth_data, LoginPassword)
        and auth_data.login == USER.encode()
        and auth_data.password == (PASSWORD.encode())
    )
    return AuthResult(success=ok, handled=False)  # handled=False: the server answers 535 itself on failure


class FakeSmtp:
    def __init__(self, port: int | None = None) -> None:
        self.handler = _SmtpHandler()
        self.port = port or free_port()
        self.controller = Controller(
            self.handler,
            hostname="127.0.0.1",
            port=self.port,
            authenticator=_authenticator,
            auth_require_tls=False,
            auth_required=True,
        )
        self.controller.start()

    def stop(self) -> None:
        self.controller.stop()
