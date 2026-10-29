"""EXF ("exf\\x1a") .mus decryptor + MOMO (.snd/.snp) bank splitter.  Run with python -I.
Spec: spec/subsystems/audio.md.  Derived from game fns 114d9bd0 (key), 114d9e30 (decrypt-read callback), 114d9c70 (open).
  python -I tools/mhf_exf.py exf  in.mus out.ogg      # decrypt (plain OggS .mus are copied)
  python -I tools/mhf_exf.py momo in.snd              # print section table / JKR-decode Head
"""
import struct, sys
TAB = {0: (0x4a4b522e, 1), 1: (0x10dcd, 1), 2: (0x10dcd, 1), 3: (0x10dcd, 1), 4: (0x2e90edd, 3)}  # VA 0x115fccb8
M = 0xFFFFFFFF

def exf_key(h):
    ver, = struct.unpack_from('<H', h, 4); seed, = struct.unpack_from('<I', h, 12)
    mul, inc = TAB[ver]; s = seed; ws = []
    for _ in range(4):
        s = (mul * s + inc) & M; ws.append(s ^ seed)
    return struct.pack('<4I', *ws)

def exf_decrypt(d):
    if d[:4] != b'exf\x1a': return d
    K = exf_key(d); out = bytearray(len(d) - 16)
    for i in range(len(out)):          # i = payload index (file offset - 0x10)
        x = (d[16 + i] ^ i) & 0xff; hi = x >> 4; lo = x & 15
        out[i] = (((K[i & 15] ^ hi) & 15) << 4) | (((K[hi] >> 4) ^ lo) & 15)
    return bytes(out)

def momo_sections(d):
    assert d[:4] == b'MOMO'
    ver, hsz, head_sz, head_pad, wave_sz, third_off, third_sz = struct.unpack_from('<7I', d, 4)
    return dict(version=ver, header=hsz, head_jkr=(hsz, head_sz), wave=(hsz + head_pad, wave_sz),
                third_jkr=(third_off, third_sz))

if __name__ == '__main__':
    c = sys.argv[1]
    if c == 'exf':
        open(sys.argv[3], 'wb').write(exf_decrypt(open(sys.argv[2], 'rb').read()))
    elif c == 'momo':
        d = open(sys.argv[2], 'rb').read(); print(momo_sections(d))
