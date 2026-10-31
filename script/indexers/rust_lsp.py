"""Small, bounded JSON-RPC transport for the pinned rust-analyzer LSP server."""

from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
from typing import Any


class RustProtocolError(RuntimeError):
    """The engine did not complete the required protocol operation."""


class RustLanguageServer:
    """Run one analyzer per project and reap it on success, failure or timeout.

    All requests are serialized. Reader threads drain stdout and stderr while
    the main thread handles server requests and notifications. This prevents a
    full diagnostic pipe from deadlocking a supposedly bounded request.
    """

    def __init__(self, executable: Path, root: Path, environment: dict[str, str],
                 configuration: dict[str, Any], timeout: float = 120) -> None:
        self.timeout = timeout
        self.configuration = configuration
        self.events: queue.Queue[dict | BaseException] = queue.Queue()
        self.stderr: deque[str] = deque(maxlen=100)
        self.process = subprocess.Popen(
            [str(executable)], cwd=root, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
        self.sequence = 0
        self.status: dict | None = None
        self.notifications: list[dict] = []
        self._threads = [
            threading.Thread(target=self._read_messages, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        try:
            initialized = self.request("initialize", {
                "processId": os.getpid(), "rootUri": root.as_uri(),
                "clientInfo": {"name": "Sourcetrail", "version": "modern-1"},
                "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
                "capabilities": {
                    "general": {"positionEncodings": ["utf-8"]},
                    "workspace": {"configuration": True},
                    "experimental": {"serverStatusNotification": True},
                    "textDocument": {
                        "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                        "definition": {"linkSupport": True},
                        "implementation": {"linkSupport": True},
                    },
                },
                "initializationOptions": configuration,
            })
            self.capabilities = initialized["capabilities"]
            if self.capabilities.get("positionEncoding") != "utf-8":
                raise RustProtocolError("rust-analyzer did not negotiate UTF-8 byte positions")
            for capability in ("definitionProvider", "referencesProvider", "documentSymbolProvider",
                               "callHierarchyProvider", "implementationProvider"):
                if not self.capabilities.get(capability):
                    raise RustProtocolError(f"rust-analyzer lacks {capability}")
            self.notify("initialized", {})
            self.wait_until_ready()
        except BaseException:
            self.close(graceful=False)
            raise

    def _read_messages(self) -> None:
        try:
            assert self.process.stdout is not None
            while True:
                headers: dict[bytes, bytes] = {}
                total_header = 0
                while True:
                    line = self.process.stdout.readline(8193)
                    if not line:
                        raise RustProtocolError("rust-analyzer closed its output pipe")
                    total_header += len(line)
                    if total_header > 8192:
                        raise RustProtocolError("Oversized LSP header")
                    if line in (b"\r\n", b"\n"):
                        break
                    key, value = line.split(b":", 1)
                    key = key.strip().lower()
                    if key in headers:
                        raise RustProtocolError("Duplicate LSP header")
                    headers[key] = value.strip()
                length = int(headers[b"content-length"])
                if not 0 < length <= 64 * 1024 * 1024:
                    raise RustProtocolError("Invalid LSP message size")
                data = self.process.stdout.read(length)
                if len(data) != length:
                    raise RustProtocolError("Truncated LSP message")
                value = json.loads(data)
                if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
                    raise RustProtocolError("Malformed JSON-RPC response")
                self.events.put(value)
        except BaseException as error:
            self.events.put(error)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in iter(self.process.stderr.readline, b""):
            self.stderr.append(line.decode("utf-8", errors="replace").rstrip())

    def _send(self, value: dict) -> None:
        assert self.process.stdin is not None
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        try:
            self.process.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
            self.process.stdin.write(payload)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise RustProtocolError("Cannot send a request to rust-analyzer") from error

    def notify(self, method: str, parameters: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": parameters})

    def _next(self, deadline: float) -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RustProtocolError("rust-analyzer request timed out")
        try:
            event = self.events.get(timeout=remaining)
        except queue.Empty as error:
            raise RustProtocolError("rust-analyzer request timed out") from error
        if isinstance(event, BaseException):
            tail = "\n".join(self.stderr)
            raise RustProtocolError(f"rust-analyzer transport failed: {event}\n{tail}") from event
        return event

    def _server_event(self, event: dict) -> None:
        method = event.get("method")
        if "id" in event:
            if method == "workspace/configuration":
                result = []
                for item in event.get("params", {}).get("items", []):
                    section = item.get("section", "")
                    value: Any = self.configuration
                    if section == "rust-analyzer":
                        section = ""
                    elif section.startswith("rust-analyzer."):
                        section = section[len("rust-analyzer."):]
                    for part in filter(None, section.split(".")):
                        value = value.get(part) if isinstance(value, dict) else None
                    result.append(value)
            elif method in ("window/workDoneProgress/create", "client/registerCapability",
                            "client/unregisterCapability", "workspace/semanticTokens/refresh",
                            "workspace/inlayHint/refresh", "workspace/diagnostic/refresh"):
                result = None
            else:
                self._send({"jsonrpc": "2.0", "id": event["id"], "error": {
                    "code": -32601, "message": f"Unsupported server request: {method}",
                }})
                return
            self._send({"jsonrpc": "2.0", "id": event["id"], "result": result})
        elif method == "experimental/serverStatus":
            self.status = event.get("params", {})
        elif method in ("textDocument/publishDiagnostics", "window/showMessage"):
            self.notifications.append(event)

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.timeout
        while not (self.status and self.status.get("quiescent")):
            self._server_event(self._next(deadline))
        if self.status.get("health") == "error":
            raise RustProtocolError(f"rust-analyzer could not load the workspace: {self.status}")

    def request(self, method: str, parameters: Any) -> Any:
        self.sequence += 1
        request_id = self.sequence
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": parameters})
        deadline = time.monotonic() + self.timeout
        while True:
            event = self._next(deadline)
            if "method" in event:
                self._server_event(event)
                continue
            if event.get("id") != request_id:
                raise RustProtocolError("Unexpected JSON-RPC response identifier")
            if "error" in event:
                raise RustProtocolError(f"{method} failed: {event['error']}")
            if "result" not in event:
                raise RustProtocolError(f"{method} returned no result")
            return event["result"]

    def close(self, *, graceful: bool = True) -> None:
        if self.process.poll() is None and graceful:
            try:
                original_timeout = self.timeout
                self.timeout = min(self.timeout, 5)
                self.request("shutdown", None)
                self.notify("exit", None)
                self.process.wait(timeout=5)
            except (RustProtocolError, subprocess.TimeoutExpired):
                pass
            finally:
                self.timeout = original_timeout
        if self.process.poll() is None:
            if os.name == "posix":
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                self.process.kill()
            self.process.wait(timeout=5)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe:
                pipe.close()
        for thread in self._threads:
            thread.join(timeout=1)

    def __enter__(self) -> RustLanguageServer:
        return self

    def __exit__(self, exception_type: Any, exception: Any, traceback: Any) -> None:
        self.close(graceful=exception_type is None)
