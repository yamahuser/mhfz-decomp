"""Disassemble a VA range of a 32-bit PE. Usage: disasm.py <pe> <start_va hex> <end_va hex>"""
import sys, pefile, capstone

pe = pefile.PE(sys.argv[1], fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
base = pe.OPTIONAL_HEADER.ImageBase
start, end = int(sys.argv[2], 16), int(sys.argv[3], 16)
iat = {imp.address: (imp.name or b"?").decode()
       for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) for imp in e.imports}
code = pe.get_data(start - base, end - start)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
for ins in md.disasm(code, start):
    note = ""
    for a, n in iat.items():
        if f"0x{a:x}" in ins.op_str:
            note = f"  ; {n}"
    print(f"{ins.address:08x}  {ins.bytes.hex():<20} {ins.mnemonic} {ins.op_str}{note}")
