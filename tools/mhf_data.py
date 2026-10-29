"""MHF-Z game-data helpers (spec: spec/subsystems/game_data.md).  Run with python -I.
Provides a CORRECTED JKR decoder (tools/mhf_archive.py uses LEN4=0x12 / c+0x1b which is wrong: the DLL (1158f157 lea esi,[eax+0xa],
1158f11a lea esi,[eax+0x1a]) and ReFrontier use +0x0a and +0x1a) and loaders for the data files.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import mhf_archive as ma

DAT = r'C:\Users\Ayman\Desktop\MHFZ\dat'


def jkr_decompress(buf):
    ver, typ, off, osz = struct.unpack_from('<HHII', buf, 4)
    if typ == 0:
        return bytes(buf[off:off + osz])
    if typ == 4:
        root = struct.unpack_from('<H', buf, off)[0]
        tbl = struct.unpack_from('<%dH' % ((root - 0xff) * 2), buf, off + 2)
        st = {'pos': off + root * 4 - 0x3fa, 'n': 8, 'cur': 0}

        def rd():
            node = root
            while node > 0xff:
                if st['n'] == 8:
                    st['cur'] = buf[st['pos']]; st['pos'] += 1; st['n'] = 0
                b = (st['cur'] >> (7 - st['n'])) & 1
                st['n'] += 1
                node = tbl[(node - 0x100) * 2 + b]
            return node
    elif typ == 3:
        st = {'pos': off}

        def rd():
            v = buf[st['pos']]; st['pos'] += 1; return v
    else:
        raise NotImplementedError('JKR type %d' % typ)
    out = bytearray(); fl = [0, -1]

    def bit():
        fl[1] -= 1
        if fl[1] < 0:
            fl[0] = rd(); fl[1] = 7
        return (fl[0] >> fl[1]) & 1

    def copy(n, d):
        for _ in range(n):
            out.append(out[-d - 1])
    try:
        while len(out) < osz:
            if bit() == 0:
                out.append(rd()); continue
            if bit() == 0:
                n = (bit() << 1 | bit()) + 3; copy(n, rd()); continue
            a = rd(); b = rd(); d = (a & 0x1f) << 8 | b
            if a & 0xe0:
                copy((a >> 5) + 2, d); continue
            if bit() == 0:
                n = (bit() << 3 | bit() << 2 | bit() << 1 | bit()) + 0x0a; copy(n, d)
            else:
                c = rd()
                if c == 0xff:
                    for _ in range(d + 0x1b): out.append(rd())
                else:
                    copy(c + 0x1a, d)
    except IndexError:
        pass
    if len(out) < osz:
        out += bytes(osz - len(out))
    return bytes(out[:osz])


def unwrap(buf):
    while True:
        m = buf[:4]
        if m == b'ecd\x1a':
            buf, _ = ma.ecd_decrypt(buf)
        elif m == b'JKR\x1a':
            buf = jkr_decompress(buf)
        else:
            return buf


def load(name):
    return unwrap(open(os.path.join(DAT, name), 'rb').read())


if __name__ == '__main__':
    n = sys.argv[1]
    d = load(n)
    out = sys.argv[2] if len(sys.argv) > 2 else None
    print(n, len(d), d[:16].hex())
    if out:
        open(out, 'wb').write(d)
