"""Find direct `call rel32` sites targeting a VA. Usage: callers.py <pe> <target_va hex>"""
import sys, re, pefile

pe = pefile.PE(sys.argv[1], fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
target = int(sys.argv[2], 16)
text = pe.sections[0]
data = text.get_data()
va0 = base + text.VirtualAddress
for m in re.finditer(b"\xe8", data):
    i = m.start()
    if i + 5 > len(data):
        break
    rel = int.from_bytes(data[i + 1:i + 5], "little", signed=True)
    if va0 + i + 5 + rel == target:
        print(f"{va0 + i:08x}")
