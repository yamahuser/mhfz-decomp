"""Build test variants of a Monster Hunter Frontier monster pack's texture container.

Entry 2 of an emXXX(-hd).pac is a simple container: u32 count, count * (u32 offset, u32 size), then
the blobs, which are plain 8-bit indexed PNGs. This script rewrites that container with modified PNGs
(same data re-encoded, or integer-upscaled) so ReFrontier can repack it. No third-party deps (numpy only).

usage: python -I mhf_texpack.py <in_container.bin> <out_container.bin> <mode> [index]
  modes: reencode        decode + re-encode every PNG (same size)
         up2             nearest-neighbour 2x upscale of every PNG (indexed colour kept)
         up2_one <idx>   upscale only texture <idx>, leave the rest untouched
"""
import struct, sys, zlib
import numpy as np


def read_png(b):
    assert b[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat, plte, trns, hdr = 8, b'', None, None, None
    while pos < len(b):
        ln, typ = struct.unpack('>I4s', b[pos:pos + 8])
        data = b[pos + 8:pos + 8 + ln]
        if typ == b'IHDR': hdr = struct.unpack('>IIBBBBB', data)
        elif typ == b'PLTE': plte = data
        elif typ == b'tRNS': trns = data
        elif typ == b'IDAT': idat += data
        pos += 12 + ln
    w, h, bd, ct, _, _, il = hdr
    if not (bd == 8 and ct == 3 and il == 0): raise NotImplementedError(f'png {hdr}')
    raw = zlib.decompress(idat)
    stride = w
    img = np.zeros((h, w), np.uint8)
    prev = np.zeros(w, np.int32)
    p = 0
    for y in range(h):
        f = raw[p]; line = np.frombuffer(raw, np.uint8, stride, p + 1).astype(np.int32); p += 1 + stride
        if f == 0: cur = line
        elif f == 1:
            cur = line.copy()
            for x in range(1, w): cur[x] = (cur[x] + cur[x - 1]) & 255
        elif f == 2: cur = (line + prev) & 255
        elif f == 3:
            cur = line.copy()
            for x in range(w): cur[x] = (cur[x] + (((cur[x - 1] if x else 0) + prev[x]) >> 1)) & 255
        elif f == 4:
            cur = line.copy()
            for x in range(w):
                a = cur[x - 1] if x else 0; bb = prev[x]; c = prev[x - 1] if x else 0
                pa, pb, pc = abs(bb - c), abs(a - c), abs(a + bb - 2 * c)
                pr = a if pa <= pb and pa <= pc else (bb if pb <= pc else c)
                cur[x] = (cur[x] + pr) & 255
        else: raise ValueError(f)
        img[y] = cur; prev = cur
    return img, plte, trns


def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)


def write_png(img, plte, trns):
    h, w = img.shape
    raw = b''.join(b'\x00' + img[y].tobytes() for y in range(h))
    out = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 3, 0, 0, 0)) + chunk(b'PLTE', plte)
    if trns: out += chunk(b'tRNS', trns)
    return out + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')


def main():
    src, dst, mode = sys.argv[1:4]
    only = int(sys.argv[4]) if len(sys.argv) > 4 else None
    b = open(src, 'rb').read()
    n = struct.unpack_from('<I', b, 0)[0]
    blobs = []
    for i in range(n):
        o, s = struct.unpack_from('<II', b, 4 + 8 * i)
        blob = b[o:o + s]
        if mode == 'reencode' or (mode == 'up2') or (mode == 'up2_one' and i == only):
            try:
                img, plte, trns = read_png(blob)
                if mode != 'reencode':
                    img = img.repeat(2, axis=0).repeat(2, axis=1)
                blob = write_png(img, plte, trns)
            except NotImplementedError as e:
                print(f'  texture {i}: skipped ({e})')
        blobs.append(blob)
    off = 4 + 8 * n
    head, body = b'', b''
    head += struct.pack('<I', n)
    for bl in blobs:
        head += struct.pack('<II', off + len(body), len(bl)); body += bl
    open(dst, 'wb').write(head + body)
    print(f'{mode}: {n} textures, {len(b)} -> {len(head + body)} bytes')


if __name__ == '__main__':
    main()

