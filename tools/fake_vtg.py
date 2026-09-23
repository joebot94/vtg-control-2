"""Fake VTG 400 on a Parallels serial socket, for capturing the official software.

Parallels exposes the Windows VM's COM port as a Unix socket on the Mac
(serial port "socket" mode, server). This script connects to it, answers
like a VTG 400, and logs every byte both ways to a JSONL capture that the
LAB tab can open.

    python3 tools/fake_vtg.py                      # default socket /tmp/vtg-fake.sock
    python3 tools/fake_vtg.py --socket /tmp/x.sock --gap 0.08

Framing: SIS commands have no terminator, so bytes are grouped into one
command when the line goes quiet for --gap seconds.

Replies, in order:
  1. tools/fake_vtg_replies.json  {"exact command": "reply"}  (edit while running;
     reloaded per command)  "" means stay silent
  2. identity answers taken from the official software's hi.vtg
  3. the app's MockTransport VTG (N, P, J, *10#, *15#, =, 20S …)
  4. anything else: printable -> "E10", binary -> silent (logged as UNKNOWN)
Every reply gets \\r\\n appended.

Directions in the capture: TX = software -> VTG, RX = VTG -> software
(the same point of view as the LAB).
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vtg.capture import CaptureLog, Event, to_ascii  # noqa: E402
from vtg.paths import data_dir  # noqa: E402
from vtg.transport import _FakeVTG  # noqa: E402

REPLIES_FILE = Path(__file__).with_name("fake_vtg_replies.json")

# From hi.vtg <Misc PartNumber="60-564-01" FW1="2.00.0001" ...>. Formats are guesses.
IDENTITY = {
    "N": "60-564-01",
    "Q": "2.00",
    "*Q": "2.00.0001",
    "I": "VTG 400",
}

COLOR = {"TX": "\033[38;5;208m", "RX": "\033[32m", "INFO": "\033[90m", "ERR": "\033[31m"}


def load_overrides() -> dict:
    try:
        return json.loads(REPLIES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as exc:
        print(f"!! {REPLIES_FILE.name} is not valid JSON ({exc}); ignoring it")
        return {}


def reply_for(cmd_bytes: bytes, vtg: _FakeVTG) -> tuple[str | None, str]:
    """(reply or None for silence, where the reply came from)."""
    text = cmd_bytes.decode("latin-1").strip("\r\n")
    overrides = load_overrides()
    if text in overrides:
        return overrides[text] or None, "override"
    if text in IDENTITY:
        return IDENTITY[text], "identity"
    printable = all(0x20 <= b < 0x7F or b in (0x0D, 0x0A) for b in cmd_bytes)
    if not printable:
        return None, "UNKNOWN binary"
    answer = vtg.handle(text)
    return answer, ("mock" if answer != "E10" else "UNKNOWN")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--socket", default="/tmp/vtg-fake.sock")
    ap.add_argument("--gap", type=float, default=0.05, help="idle seconds that end a command")
    ap.add_argument("--capture", default=None, help="JSONL path (default captures/fake_<time>.jsonl)")
    args = ap.parse_args()

    cap_path = Path(args.capture) if args.capture else \
        data_dir("captures") / time.strftime("fake_%Y%m%d_%H%M%S.jsonl")
    cap_file = open(cap_path, "a", encoding="utf-8", newline="\n")
    log = CaptureLog()

    def on_event(ev: Event) -> None:
        cap_file.write(ev.to_json() + "\n")
        cap_file.flush()
        body = to_ascii(ev.data) if ev.data else ""
        note = f"  [{ev.note}]" if ev.note else ""
        print(f"{COLOR.get(ev.dir, '')}{ev.clock()} {ev.dir:<4} {body}{note}\033[0m", flush=True)
    log.subscribe(on_event)
    log.info(f"fake VTG 400 → capture {cap_path}")

    vtg = _FakeVTG()
    while True:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(args.socket)
        except OSError as exc:
            print(f"waiting for Parallels socket {args.socket} ({exc.strerror}) …", end="\r", flush=True)
            time.sleep(1)
            continue
        log.info(f"connected to {args.socket}")
        try:
            serve(sock, log, vtg, args.gap)
        except KeyboardInterrupt:
            log.info("stopped")
            return 0
        except OSError as exc:
            log.error(f"socket error: {exc}")
        finally:
            sock.close()
        log.info("disconnected; reconnecting")
        time.sleep(1)


def serve(sock: socket.socket, log: CaptureLog, vtg: _FakeVTG, gap: float) -> None:
    buf = bytearray()
    sock.settimeout(gap)
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                return  # Parallels closed the socket (VM stopped / port disconnected)
            buf += chunk
            continue
        except socket.timeout:
            pass
        if not buf:
            continue
        cmd = bytes(buf)
        buf.clear()
        answer, source = reply_for(cmd, vtg)
        log.tx(cmd, note=source)
        if answer is not None:
            data = answer.encode("latin-1") + b"\r\n"
            sock.sendall(data)
            log.rx(data)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
