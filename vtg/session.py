"""One live connection: transport + worker + protocol, opened and closed together."""

from __future__ import annotations

from .capture import CaptureLog
from .protocol import VTGProtocol
from .transport import MockTransport, SerialTransport, Transport
from .worker import SerialWorker

MOCK_PORT = "MOCK"


class Session:
    def __init__(self, transport: Transport):
        self.transport = transport
        transport.connect()
        self.worker = SerialWorker(transport)
        self.vtg = VTGProtocol(self.worker)

    @property
    def is_mock(self) -> bool:
        return self.transport.is_mock

    @property
    def label(self) -> str:
        return self.transport.label

    def close(self) -> None:
        self.worker.shutdown()
        self.transport.disconnect()


def open_session(port: str, baud: int, log: CaptureLog) -> Session:
    if port == MOCK_PORT:
        return Session(MockTransport(log))
    return Session(SerialTransport(log, port, baud))
