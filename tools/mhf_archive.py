"""MHF-Z archive/container toolkit (spec: spec/archive-format.md).  Run with: python -I tools/mhf_archive.py ...

Layers (outermost first):  ECD ("ecd\\x1a") encryption  ->  JKR ("JKR\\x1a") compression  ->  pack table
(u32 count, count*(u32 off,u32 size)).  Also EXF ("exf\\x1a") xor-obfuscation for .mus.
Commands:
  info    <file>                 identify layers, print table
  unwrap  <file> <out>           strip ECD/JKR/EXF layers
  list    <file>                 list entries of a pack table (after unwrapping)
  extract <file> <outdir>        write every entry (unwrapped recursively one level) to outdir
"""
import struct, sys, os, zlib

# ECD key table: index -> (multiplier, increment) of a 32-bit LCG   (mhfo-hd.dll VA 0x115df198)
ECD_KEYS = [(0x4a4b522e, 1), (0x10dcd, 1), (0x10dcd, 1), (0x10dcd, 1), (0x19660d, 3), (0x7d2b89dd, 1)]
M32 = 0xFFFFFFFF
LEN4 = 0x12


def ecd_decrypt(buf):
    assert buf[:4] == b'ecd\x1a'
    key, chk, size, seed = struct.unpack_from('<HHII', buf, 4)
    mul, inc = ECD_KEYS[key]
    st = (((seed | 0x10000) >> 16) | (seed << 16)) & M32
    st = (st * mul + inc) & M32
    prev = st & 0xff
    out = bytearray(size)
    src = buf[16:16 + size]
    for i in range(len(src)):
        st = (st * mul + inc) & M32
        t = src[i] ^ prev
        b3 = t >> 4
        loc = st
        for _ in range(8):
            b2 = b3
            b3 = ((b2 ^ loc) & 0xff) ^ t
            loc >>= 4
            t = b2
        prev = ((b2 << 4) | (b3 & 0xf)) & 0xff
        out[i] = prev
    return bytes(out), dict(key=key, name_hash=chk, size=size, seed=seed)


def jkr_decompress(buf):
    """JKR: u32 magic, u16 version, u16 type, u32 data_off, u32 out_size.  type 0 raw, 3 LZ, 4 Huffman-bytes+LZ."""
    ver, typ, off, osz = struct.unpack_from('<HHII', buf, 4)
    if typ == 0:
        return bytes(buf[off:off + osz])
    if typ not in (3, 4):
        raise NotImplementedError('JKR type %d' % typ)
    pos = off
    if typ == 4:
        root = struct.unpack_from('<H', buf, pos)[0]
        tbl = struct.unpack_from('<%dH' % ((root - 0xff) * 2), buf, pos + 2)
        st = {'pos': pos + root * 4 - 0x3fa, 'n': 8}   # first bitstream byte (right after node table)
        cur = [0]

        def rd():
            node = root
            while node > 0xff:
                if st['n'] == 8:
                    cur[0] = buf[st['pos']]
                    st['pos'] += 1
                    st['n'] = 0
                bit_ = (cur[0] >> (7 - st['n'])) & 1
                st['n'] += 1
                node = tbl[(node - 0x100) * 2 + bit_]
            return node
    else:
        st = {'pos': pos}

        def rd():
            b = buf[st['pos']]
            st['pos'] += 1
            return b
    out = bytearray()
    fl = [0, -1]   # flag byte, bit index

    def bit():
        fl[1] -= 1
        if fl[1] < 0:
            fl[0] = rd()
            fl[1] = 7
        return (fl[0] >> fl[1]) & 1

    def copy(n, d):
        for _ in range(n):
            out.append(out[-d - 1])
    while len(out) < osz:
        if bit() == 0:
            out.append(rd())
            continue
        if bit() == 0:
            n = (bit() << 1 | bit()) + 3
            copy(n, rd())
            continue
        a = rd()
        b = rd()
        d = (a & 0x1f) << 8 | b
        if a & 0xe0:
            copy((a >> 5) + 2, d)
            continue
        if bit() == 0:
            n = (bit() << 3 | bit() << 2 | bit() << 1 | bit()) + LEN4
            copy(n, d)
        else:
            c = rd()
            if c == 0xff:
                for _ in range(d + 0x1b):
                    out.append(rd())
            else:
                copy(c + 0x1b, d)
    return bytes(out[:osz])


def unwrap(buf, trace=None):
    while True:
        m = buf[:4]
        if m == b'ecd\x1a':
            buf, h = ecd_decrypt(buf)
            if trace is not None: trace.append(('ecd', h))
        elif m == b'JKR\x1a':
            buf = jkr_decompress(buf)
            if trace is not None: trace.append(('jkr', {}))
        else:
            return buf


def pack_table(buf):
    """Return [(off,size)] if buf looks like a pack table, else None."""
    if len(buf) < 12: return None
    n = struct.unpack_from('<I', buf, 0)[0]
    if n == 0 or n > 100000 or 4 + 8 * n > len(buf): return None
    ents = [struct.unpack_from('<II', buf, 4 + 8 * i) for i in range(n)]
    if ents[0][0] < 4 + 8 * n: return None
    for o, s in ents:
        if o + s > len(buf): return None
    return ents


def pack_build(blobs):
    """Build a pack table (u32 count, count*(off,size), then entries back-to-back, no padding)."""
    hdr = 4 + 8 * len(blobs)
    out = bytearray(struct.pack('<I', len(blobs)))
    off = hdr
    for b in blobs:
        out += struct.pack('<II', off, len(b))
        off += len(b)
    for b in blobs:
        out += b
    return bytes(out)


def tree(b, ind=0, depth=4, name=''):
    u = unwrap(b)
    t = pack_table(u)
    if t is None or depth == 0:
        print(' ' * ind + name, len(b), '->', len(u), u[:8].hex(' '))
        return
    print(' ' * ind + name, 'PACK x%d' % len(t), len(u), 'bytes', '(was wrapped)' if u is not b else '')
    for i, (o, s) in enumerate(t):
        tree(u[o:o + s], ind + 2, depth - 1, '[%d]' % i)


if __name__ == '__main__':
    cmd = sys.argv[1]
    data = open(sys.argv[2], 'rb').read()
    tr = []
    u = unwrap(data, tr)
    if cmd == 'info':
        print(tr, 'unwrapped', len(u), u[:16].hex(' '))
        t = pack_table(u)
        print('pack table:', None if t is None else len(t))
    elif cmd == 'unwrap':
        open(sys.argv[3], 'wb').write(u)
    elif cmd == 'list':
        for i, (o, s) in enumerate(pack_table(u) or []):
            print(i, hex(o), s, u[o:o + 4].hex(' '))
    elif cmd == 'tree':
        tree(data)
    elif cmd == 'repack-test':   # unwrap + rebuild the top-level table; must be byte-identical
        t = pack_table(u)
        print('roundtrip identical:', pack_build([u[o:o + s] for o, s in t]) == u)
    elif cmd == 'extract':
        os.makedirs(sys.argv[3], exist_ok=True)
        for i, (o, s) in enumerate(pack_table(u) or []):
            open(os.path.join(sys.argv[3], '%04d.bin' % i), 'wb').write(u[o:o + s])
