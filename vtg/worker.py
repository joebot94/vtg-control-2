"""Single-queue serial worker.

Copied from joebot-display-lab/generators/serial_worker.py and adapted:
it now drives a Transport (bytes in, lines out, everything logged) instead
of a bare pyserial port.

All traffic to the device flows through one worker thread and one queue —
nothing else may touch the port. Each command carries its own timeout,
retry count and parser; callers get a Future. Before each write the
worker drains the input buffer, so a late reply to an earlier command can
never be mistaken for the answer to this one (the May 2025 app's bug).
"""

from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable

from .transport import Transport

log = logging.getLogger("vtg.worker")


class SerialCommandError(Exception):
    pass


class SerialTimeout(SerialCommandError):
    pass


class WorkerStopped(SerialCommandError):
    pass


@dataclass
class SerialCommand:
    data: bytes
    timeout: float = 1.0
    retries: int = 0
    # Parser turns the decoded, stripped reply line into the Future's result;
    # raising inside it fails the command (and consumes a retry).
    parser: Callable[[str], object] = lambda line: line
    expect_response: bool = True
    # When True a missing reply resolves the Future with None instead of
    # failing. Used for set-commands until we know which ones the VTG acks.
    response_optional: bool = False
    future: Future = field(default_factory=Future)


class SerialWorker:
    def __init__(self, transport: Transport):
        self._transport = transport
        self._queue: queue.Queue[SerialCommand | None] = queue.Queue()
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="vtg-serial")
        self._thread.start()

    def submit(self, command: SerialCommand) -> Future:
        if self._stopped:
            command.future.set_exception(WorkerStopped("worker stopped"))
        else:
            self._queue.put(command)
        return command.future

    def send(self, data: bytes | str, timeout: float = 1.0, retries: int = 0,
             parser: Callable[[str], object] | None = None,
             expect_response: bool = True, response_optional: bool = False) -> Future:
        if isinstance(data, str):
            data = data.encode("ascii")
        return self.submit(SerialCommand(
            data=data, timeout=timeout, retries=retries,
            parser=parser or (lambda line: line),
            expect_response=expect_response, response_optional=response_optional,
        ))

    def pending(self) -> int:
        return self._queue.qsize()

    def shutdown(self) -> None:
        """Stop after the command in flight; fail everything still queued."""
        self._stopped = True
        while True:
            try:
                cmd = self._queue.get_nowait()
            except queue.Empty:
                break
            if cmd is not None:
                cmd.future.set_exception(WorkerStopped("worker stopped"))
        self._queue.put(None)
        self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            cmd = self._queue.get()
            if cmd is None:
                return
            self._execute(cmd)

    def _execute(self, cmd: SerialCommand) -> None:
        attempts = cmd.retries + 1
        last_error: Exception | None = None
        shown = cmd.data.decode("ascii", errors="replace")
        for attempt in range(attempts):
            try:
                self._transport.drain()
                self._transport.write(cmd.data)
                if not cmd.expect_response:
                    cmd.future.set_result(None)
                    return
                raw = self._transport.readline(cmd.timeout)
                if not raw:
                    if cmd.response_optional:
                        cmd.future.set_result(None)
                        return
                    raise SerialTimeout(f"no response to {shown!r}")
                line = raw.decode("ascii", errors="replace").strip()
                cmd.future.set_result(cmd.parser(line))
                return
            except Exception as exc:  # noqa: BLE001 — retried, then surfaced
                last_error = exc
                log.warning("command %r attempt %d failed: %s", shown, attempt + 1, exc)
        self._transport.log.error(f"{shown!r}: {last_error}")
        cmd.future.set_exception(
            last_error if last_error is not None else SerialCommandError(shown)
        )
