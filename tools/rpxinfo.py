"""Inspect a Wii U .rpx/.rpl: list sections (inflating RPL_ZLIB ones) and dump symbols.

usage: python -I rpxinfo.py <file.rpx> [outdir]
Writes <outdir>/sections/*.bin (decompressed) and <outdir>/symbols.tsv if a symtab exists.
"""
import os, struct, sys, zlib

SHF_RPL_ZLIB = 0x08000000

def main():
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    data = open(path, 'rb').read()
    assert data[1:4] == b'ELF', 'not ELF'  # some dumps carry 0x7E instead of 0x7F
    (e_shoff,) = struct.unpack_from('>I', data, 0x20)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('>HHH', data, 0x2E)
    secs = []
    for i in range(e_shnum):
        name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from(
            '>IIIIIIIIII', data, e_shoff + i * e_shentsize)
        raw = data[off:off + size] if typ != 8 else b''  # 8 = NOBITS
        if flags & SHF_RPL_ZLIB and raw:
            raw = zlib.decompress(raw[4:])
        secs.append(dict(i=i, name=name, type=typ, flags=flags, addr=addr, size=size,
                         link=link, entsize=entsize, raw=raw))
    shstr = secs[e_shstrndx]['raw']
    def cstr(buf, o):
        e = buf.find(b'\0', o)
        return buf[o:e].decode('latin1')
    for s in secs:
        s['nm'] = cstr(shstr, s['name']) if shstr else ''
        print(f"{s['i']:3} {s['nm']:<20} type={s['type']:#010x} addr={s['addr']:#010x} "
              f"size={len(s['raw']):>9}")
    if out:
        os.makedirs(os.path.join(out, 'sections'), exist_ok=True)
        for s in secs:
            if s['raw']:
                fn = f"{s['i']:02}_{s['nm'].strip('.') or 'noname'}.bin"
                open(os.path.join(out, 'sections', fn), 'wb').write(s['raw'])
    for s in secs:
        if s['type'] != 2:  # SHT_SYMTAB
            continue
        strtab = secs[s['link']]['raw']
        syms = []
        for o in range(0, len(s['raw']), 16):
            st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from(
                '>IIIBBH', s['raw'], o)
            if st_name:
                syms.append((st_value, st_size, st_info & 0xF, cstr(strtab, st_name)))
        funcs = [x for x in syms if x[2] == 2]
        objs = [x for x in syms if x[2] == 1]
        print(f"\nsymtab '{s['nm']}': {len(syms)} named symbols, {len(funcs)} FUNC, {len(objs)} OBJECT")
        for x in funcs[:15]:
            print(f"  {x[0]:#010x} {x[1]:>6} {x[3]}")
        if out:
            with open(os.path.join(out, 'symbols.tsv'), 'w', encoding='utf-8') as f:
                f.write('addr\tsize\ttype\tname\n')
                for x in syms:
                    f.write(f"{x[0]:08x}\t{x[1]}\t{x[2]}\t{x[3]}\n")

if __name__ == '__main__':
    main()
