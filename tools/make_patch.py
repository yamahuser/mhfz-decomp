"""Write a copy of mhfo-hd.dll with the frame limiter's 33 ms frame time changed.

Usage: make_patch.py <original dll> <output dll> [frame_ms=16]
The original is never modified. Each patch site is byte-verified before writing.
"""
import sys, shutil, pefile

src, dst = sys.argv[1], sys.argv[2]
ms = int(sys.argv[3]) if len(sys.argv) > 3 else 16
assert 1 <= ms <= 0x7f

# (VA, expected bytes, replacement bytes)  -- frame limiter fn @ 0x1000a2f0
SITES = [
    (0x1000a2fd, bytes.fromhex("be21000000"), bytes([0xbe, ms, 0, 0, 0])),  # mov esi, 33
    (0x1000a31b, bytes.fromhex("83c621"),     bytes([0x83, 0xc6, ms])),     # add esi, 33 (alt path)
]

pe = pefile.PE(src, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
data = bytearray(open(src, "rb").read())
for va, old, new in SITES:
    off = pe.get_offset_from_rva(va - base)
    cur = bytes(data[off:off + len(old)])
    if cur != old:
        sys.exit(f"ABORT: {va:08x} has {cur.hex()}, expected {old.hex()} (different client build?)")
    data[off:off + len(new)] = new
    print(f"{va:08x} @file {off:08x}: {old.hex()} -> {new.hex()}")
open(dst, "wb").write(data)
print(f"wrote {dst} (frame time {ms} ms = ~{1000 // ms} fps cap)")
