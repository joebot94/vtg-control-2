# VTG Control 2 (JOEBOT VTG)

A Tkinter controller for the Extron VTG 400 / 400D / 400DVI. It replaces the
May 2025 `VTG400+HCFR.py`.

```
python main.py                      # pick MOCK in the Port box to run without hardware
python -m unittest discover tests   # offline tests
```

The only dependency is `pyserial`.

**Windows exe:** every push to `main` builds `VTGControl2.exe` on a GitHub Actions Windows
runner. The runner also runs the tests and launches the exe with `--selftest`. Download it
from the run's *Artifacts* on the Actions tab. Pushing a `v*` tag also attaches it to a
release. `presets/` and `captures/` are created next to the exe.

HCFR follow mode also needs `pywinauto` and `pywin32` (bundled in the exe), plus `pytesseract` and `Pillow` for the OCR fallback. It only runs on
Windows.

## Layout

```
vtg/transport.py  bytes on the wire. SerialTransport (pyserial) and MockTransport (fake VTG)
vtg/worker.py     the ONLY reader/writer: one thread, one queue, Futures (from joebot-display-lab)
vtg/protocol.py   every Extron SIS string and reply parser; custom timing is stubbed
vtg/timing.py     Timing model; refresh / H freq / pixel clock can each be the authoritative input
vtg/presets.py    timing presets as readable JSON in presets/
vtg/capture.py    TX/RX event log; JSONL save/load; raw-entry escape parser
vtg/hcfr.py       HCFR cue -> colour/IRE rules and the Windows watcher thread
vtg/session.py    opens transport + worker + protocol together
ui/               main window and one module per tab
tools/snap.py     dev helper (macOS): screenshots the app window
```

## What is verified and what is not

* **Commands** (`N`, `0P/1P`, `n*15#`, `nJ`, `n*10#`, resolution `nnn*nn=`, `20S`) come from the
  working May 2025 app.
* **Reply formats have not been captured.** The mock's replies are guesses that fit the old
  parsers. The real parsers accept any reply and extract the number from it. Set commands
  treat a missing reply as OK until we know which commands the VTG acknowledges.
* **Custom timing upload is not implemented.** `VTGProtocol.encode_custom_timing()` raises
  `NotCaptured`, and PROGRAM VTG stays disabled.
* **Interlaced timing math is not implemented.** The interlaced flag is stored, but the math
  is done as progressive and the UI warns about it.
* The 320×240 preset is an **example**, not verified 240p.

## Tomorrow: capture plan

1. **Baseline control.** Connect at 9600 and work through the CONTROL page. Record the real
   replies in LAB, then update the parsers and the mock's `_FakeVTG` to match.
2. **Official software.** Turn off *Poll VTG status* in LAB (for our own traffic). Capture the
   Extron software uploading a baseline custom timing, then change **one** field (for example
   H front porch 16 → 17) and upload again. Keep both as `.jsonl`.
3. **Diff.** Line up the two byte streams to map the fields. Then write
   `encode_custom_timing()` and set `supports_custom_timing = True`.

### Passive tap safety (FT4232H)

Before connecting anything, confirm with a meter or the datasheet that each tapped
FT4232H channel is an **RS-232-level receive input** (through a line transceiver, not bare
3.3 V TTL). Only connect the tap channels' **RX and GND**. Never connect a tap channel's TX
to either data line. Two drivers on one line can damage both ends and will corrupt the
capture. Use one RX for PC→VTG (TXD) and another for VTG→PC (RXD), with a shared ground.
