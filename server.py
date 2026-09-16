"""Server TCP e dashboard web per AntiCopy.

Il protocollo TCP sulla porta 5000 resta identico a quello atteso da main.py.
La dashboard FastAPI e disponibile localmente su http://127.0.0.1:8080.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import threading
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse


HOST = os.getenv("ANTICOPY_TCP_HOST", "0.0.0.0")
TCP_PORT = int(os.getenv("ANTICOPY_TCP_PORT", "5000"))
WEB_HOST = "127.0.0.1"
WEB_PORT = int(os.getenv("ANTICOPY_WEB_PORT", "8080"))
HEARTBEAT_TIMEOUT_SECONDS = 10
MAX_EVENTS = 300
BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("anticopy.server")


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_exclusions() -> list[str]:
    """Carica le app da escludere senza cambiare il protocollo del client.

    Esempio PowerShell:
    $env:ANTICOPY_EXCLUDED_APPS = 'explorer.exe,Teams.exe'
    """
    configured = os.getenv("ANTICOPY_EXCLUDED_APPS", "")
    return [item.strip() for item in configured.split(",") if item.strip()]


@dataclass
class Client:
    id: str
    username: str
    address: str
    connected_at: str
    last_seen: str
    last_activity_at: str | None = None
    active_process: str | None = None
    active_window: str | None = None


class MonitorState:
    """Stato condiviso in sicurezza fra listener TCP e richieste HTTP."""

    def __init__(self, exclusions: list[str]) -> None:
        self._lock = threading.RLock()
        self._clients: dict[str, Client] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self.exclusions = exclusions
        self.started_at = iso_now()

    def add_client(self, username: str, address: str) -> str:
        client_id = uuid.uuid4().hex
        now = iso_now()
        client = Client(
            id=client_id,
            username=username,
            address=address,
            connected_at=now,
            last_seen=now,
        )
        with self._lock:
            self._clients[client_id] = client
            self._add_event("connected", client, message="Client connesso")
        logger.info("Client connesso: %s (%s)", username, address)
        return client_id

    def record_ping(self, client_id: str) -> None:
        with self._lock:
            client = self._clients.get(client_id)
            if client:
                client.last_seen = iso_now()

    def record_activity(self, client_id: str, message: str) -> None:
        """Registra il formato prodotto dal client: ora - utente - app - titolo."""
        with self._lock:
            client = self._clients.get(client_id)
            if not client:
                return

            client.last_seen = iso_now()
            client_time, process, title = parse_activity(message)
            client.last_activity_at = client_time or client.last_seen
            client.active_process = process or "Applicazione non identificata"
            client.active_window = title or message
            self._add_event(
                "activity",
                client,
                client_time=client_time,
                process=client.active_process,
                window_title=client.active_window,
            )

    def remove_client(self, client_id: str, reason: str) -> None:
        with self._lock:
            client = self._clients.pop(client_id, None)
            if client:
                self._add_event("disconnected", client, message=reason)
        if client:
            logger.info("Client disconnesso: %s (%s)", client.username, reason)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            clients = [asdict(client) for client in self._clients.values()]
            clients.sort(key=lambda client: client["username"].lower())
            return {
                "generated_at": iso_now(),
                "started_at": self.started_at,
                "online_count": len(clients),
                "exclusions": list(self.exclusions),
                "clients": clients,
                "events": list(reversed(self._events)),
            }

    def _add_event(self, kind: str, client: Client, **details: str | None) -> None:
        self._events.append(
            {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "received_at": iso_now(),
                "client_id": client.id,
                "username": client.username,
                "address": client.address,
                **details,
            }
        )


def parse_activity(message: str) -> tuple[str | None, str | None, str | None]:
    parts = message.split(" - ", 3)
    if len(parts) != 4:
        return None, None, None
    client_time, _username, process, title = parts
    return client_time.strip() or None, process.strip() or None, title.strip() or None


def send_list(sock: socket.socket, values: list[str]) -> None:
    payload = json.dumps(values).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)))
    sock.sendall(payload)


class TcpMonitor:
    def __init__(self, state: MonitorState, host: str, port: int) -> None:
        self.state = state
        self.host = host
        self.port = port
        self._socket: socket.socket | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve, name="tcp-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=3)

    def _serve(self) -> None:
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen()
            listener.settimeout(1)
            self._socket = listener
            logger.info("Listener client attivo su %s:%s", self.host, self.port)

            while not self._stop_event.is_set():
                try:
                    conn, address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(
                    target=self._handle_client,
                    args=(conn, address),
                    name=f"client-{address[0]}:{address[1]}",
                    daemon=True,
                ).start()
        except OSError as error:
            logger.exception("Impossibile avviare il listener TCP: %s", error)
        finally:
            if self._socket:
                try:
                    self._socket.close()
                except OSError:
                    pass
            self._socket = None

    def _handle_client(self, conn: socket.socket, address: tuple[str, int]) -> None:
        client_id: str | None = None
        reason = "Connessione chiusa"
        buffer = ""
        address_text = f"{address[0]}:{address[1]}"
        try:
            conn.settimeout(1)
            username, buffer = receive_line(conn, buffer)
            if not username:
                reason = "Nome utente non ricevuto"
                return

            send_list(conn, self.state.exclusions)
            client_id = self.state.add_client(username, address_text)
            last_heartbeat = datetime.now().timestamp()

            while not self._stop_event.is_set():
                try:
                    data = conn.recv(1024)
                except socket.timeout:
                    if datetime.now().timestamp() - last_heartbeat > HEARTBEAT_TIMEOUT_SECONDS:
                        reason = "Timeout heartbeat"
                        break
                    continue

                if not data:
                    reason = "Client disconnesso"
                    break

                last_heartbeat = datetime.now().timestamp()
                buffer += data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    message, buffer = buffer.split("\n", 1)
                    message = message.strip()
                    if not message:
                        continue
                    if message.replace("\r", "") == "PING":
                        self.state.record_ping(client_id)
                    else:
                        self.state.record_activity(client_id, message)
                        logger.info("Attivita %s: %s", username, message)
        except (ConnectionError, OSError) as error:
            reason = f"Errore di connessione: {error}"
        except Exception:
            reason = "Errore inatteso"
            logger.exception("Errore con il client %s", address_text)
        finally:
            if client_id:
                self.state.remove_client(client_id, reason)
            try:
                conn.close()
            except OSError:
                pass


def receive_line(sock: socket.socket, buffer: str) -> tuple[str | None, str]:
    while "\n" not in buffer:
        data = sock.recv(1024)
        if not data:
            return None, buffer
        buffer += data.decode("utf-8", errors="replace")
    line, buffer = buffer.split("\n", 1)
    return line.strip(), buffer


state = MonitorState(load_exclusions())
monitor = TcpMonitor(state, HOST, TCP_PORT)


@asynccontextmanager
async def lifespan(_: FastAPI):
    monitor.start()
    logger.info("Dashboard disponibile su http://%s:%s", WEB_HOST, WEB_PORT)
    try:
        yield
    finally:
        monitor.stop()


app = FastAPI(title="AntiCopy Monitor", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(BASE_DIR / "web" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/dashboard")
def dashboard_data() -> JSONResponse:
    return JSONResponse(state.snapshot(), headers={"Cache-Control": "no-store"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)
