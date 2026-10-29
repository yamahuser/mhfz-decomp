"""MHF-Z container helpers (prototype; engine-neutral spec in spec/model-format.md).
 - pac: u32 count, then count*(u32 offset,u32 size); entries may be nested sub-archives
 - JKR: 'JKR\x1a' u16 ver, u16 type(0 raw,2 huff+raw?,3 LZ,4 Huffman+LZ), u32 dataoff, u32 outsize
Algorithm re-derived from decomp 1158f240 (header), 1158efe0 (LZ), 1158eec0 (huffman byte getter).
"""
import struct, sys

def jkr_decompress(b, base=0):
    assert b[base:base+4] == b'JKR\x1a'
    ver, typ, off, outsz = struct.unpack_from('<HHII', b, base+4)
    p = base + off
    out = bytearray()
    if typ == 0:
        return bytes(b[p:p+outsz])
    if typ == 4:
        L = struct.unpack_from('<H', b, p)[0]
        tab = p + 2
        # table: (L-256) nodes * 2 ushort children; data stream starts after table
        datap = p + 4*L - 0x3f9   # decomp: ptr = hdr + 4*L - 0x3f9 ; initial bit byte = ptr[-1]
        state = {'p': datap, 'bits': 0, 'cur': b[datap-1]}
        def getb():
            n = L
            while True:
                bit = (state['cur'] >> (7 - state['bits'])) & 1
                state['bits'] += 1
                if state['bits'] == 8:
                    state['cur'] = b[state['p']]; state['p'] += 1; state['bits'] = 0
                n = struct.unpack_from('<H', b, tab + ((n - 256)*2 + bit)*2)[0]
                if n < 256: return n
    else:
        st = {'p': p}
        def getb():
            v = b[st['p']]; st['p'] += 1; return v
    fl = {'n': 0, 'v': 0}
    def bit():
        fl['n'] -= 1
        if fl['n'] < 0:
            fl['v'] = getb(); fl['n'] = 7
        return (fl['v'] >> fl['n']) & 1
    def cpy(dist, ln):
        for _ in range(ln):
            out.append(out[-dist - 1])
    while len(out) < outsz:
        if bit() == 0:
            out.append(getb()); continue
        if bit() == 0:
            ln = (bit() << 1 | bit()) + 3
            cpy(getb(), ln)
        else:
            h = getb(); l = getb()
            off_ = ((h & 0x1f) << 8) | l
            ln = h >> 5
            if ln == 0:
                if bit() == 0:
                    ln = (bit() << 3 | bit() << 2 | bit() << 1 | bit()) + 0x0a
                else:
                    c = getb()
                    if c == 0xff:
                        for _ in range(off_ + 0x1b): out.append(getb())
                        continue
                    ln = c + 0x1a
            else:
                ln += 2
            cpy(off_, ln)
    return bytes(out[:outsz])

def pac_entries(b, base=0, size=None):
    n = struct.unpack_from('<I', b, base)[0]
    return [struct.unpack_from('<II', b, base+4+8*i) for i in range(n)]

if __name__ == '__main__':
    d = open(sys.argv[1], 'rb').read()
    for i, (o, s) in enumerate(pac_entries(d)):
        print(i, hex(o), hex(s), d[o:o+8].hex(' '))


# --- ECD ('ecd\x1a') decryption; re-derived from decomp 1158f460 / 1158f510 (key table @ 0x115df198) ---
ECD_KEYS = [(1246450222, 1), (69069, 1), (69069, 1), (69069, 1), (1664525, 3), (2100005341, 1)]

def ecd_decrypt(b, limit=None):
    assert b[:4] == b'ecd\x1a'
    idx, chk, size, crc = struct.unpack_from('<HHII', b, 4)
    mul, add = ECD_KEYS[idx]
    M = 0xffffffff
    st = ((((crc | 0x10000) >> 16) | (crc << 16)) & M)
    st = (st * mul + add) & M
    dl = st & 0xff
    out = bytearray()
    for i in range(size if limit is None else min(size, limit)):
        st = (mul * st + add) & M
        t = b[0x10 + i] ^ dl
        al = t >> 4
        cp = st
        for _ in range(8):
            d2 = al
            al = (al ^ (cp & 0xff) ^ t) & 0xff
            cp >>= 4
            t = d2
        dl = ((d2 << 4) & 0xff) | (al & 0xf)
        out.append(dl)
    return bytes(out)

def load_any(path):
    """read file; ecd-decrypt if needed (JKR left for caller)"""
    b = open(path, 'rb').read()
    if b[:4] == b'ecd\x1a':
        b = ecd_decrypt(b)
    return b

