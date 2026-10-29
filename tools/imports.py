"""List timing/D3D-related imports of a PE and the code sites that call them."""
import sys, re, pefile

INTERESTING = re.compile(r"Sleep|Perf|Tick|timeGetTime|timeBeginPeriod|Wait|Timer|Direct3DCreate|Present", re.I)

pe = pefile.PE(sys.argv[1], fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
base = pe.OPTIONAL_HEADER.ImageBase
iat = {}
for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
    for imp in entry.imports:
        name = imp.name.decode() if imp.name else f"ord{imp.ordinal}"
        iat[imp.address] = f"{entry.dll.decode()}!{name}"
        if INTERESTING.search(name):
            print(f"{imp.address:08x}  {entry.dll.decode()}!{name}")
print(f"total imports: {len(iat)}")

# Find `call dword ptr [iat]` (FF 15 xx xx xx xx) and `mov reg,[iat]` refs in .text
text = pe.sections[0]
data = text.get_data()
va0 = base + text.VirtualAddress
targets = {a: n for a, n in iat.items() if INTERESTING.search(n)}
for addr, name in sorted(targets.items()):
    needle = addr.to_bytes(4, "little")
    hits = [m.start() for m in re.finditer(re.escape(needle), data)]
    print(f"{name}: {len(hits)} refs -> " + " ".join(f"{va0 + h - 2:08x}" for h in hits[:12]))
