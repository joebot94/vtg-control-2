# VTG rate record: what the official software stores

Source: `C:\ProgramData\VTG400\1.2.0.0\Data\hi.vtg` from Extron's VTG400 software 1.2.0.0.
It's an XML file headed "created for emulation purposes only", i.e. the software's offline
stand-in for a VTG 400 (PartNumber 60-564-01, FW 2.00.0001). A local copy is in `research/`,
which git ignores because it's Extron's file.

It contains 8 `GROUP`s holding 113 `RATE`s. Group 8 is **Custom Rates** (`GroupIDc="99"`)
and is empty in this file. Each `RATE` element's text is an **80-byte record** written as
`$XX` hex bytes:

| offset | size | content |
|---|---|---|
| 0  | 40 | ASCII display text: name (12), resolution, then `31.50kHz  60.00Hz` |
| 40 | 2  | H active (big-endian u16) |
| 42 | 2  | V active |
| 44 | 2  | H total |
| 46 | 2  | V total |
| 48 | 2  | H sync width |
| 50 | 2  | V sync width |
| 52 | 2  | H back porch |
| 54 | 2  | V back porch |
| 56 | 2  | H front porch |
| 58 | 2  | V front porch |
| 60 | 20 | **unknown** (see below) |

The field order was checked against all 113 records: in 107 of them the totals equal
active + sync + back + front exactly. The other 6 are 1080-line rates at 50/25/24 Hz where
the stored **H front porch is wrong but H total is right** (e.g. 2640 total, fp stored 308,
should be 528). So the VTG probably works from the totals and ignores the stored front porch.
Confirm on hardware.

## Unknown 20 bytes: first observations

VGA 640x480@60 is `0C D1 08 8D 00 42 08 00 00 00 08 E8 0A BC 80 02 25 1B 11 00`.

- Bytes 60–65 and 70–73 are identical for every rate with the same H active
  (640 → `0C D1 08 8D 00 42` … `08 E8 0A BC`), so they're probably scaling constants for
  drawing patterns, derived from H active.
- Byte 66 (`08`/`04`/`10`) and bytes 67–69 vary with sync type, interlace or stereo, and
  polarity. Candidates for the flag fields.
- Byte 74 (`80`/`00`) is a flag.
- Bytes 75–78 change with the clock (e.g. VGA 60 Hz `02 25 1B 11` vs 72 Hz `02 22 03 01`).
  Most likely pixel-clock synthesiser settings (a divider range plus the synthesiser's
  multiplier/divider values).

## What this means for custom timing

This is probably the same record the software uploads when programming a custom rate. It
still has to be confirmed with a serial capture. To do that: create a custom rate in the
official software (it should then appear under GROUP_99 in this file), capture the upload
with the Lab, and compare the bytes on the wire with the stored record.
