"""MHF-Z model (.pac -> 'fmod' chunk file) parser prototype.  Spec: spec/model-format.md
Usage:  python -I tools/mhfmodel.py <file.pac> [--obj outdir] [--png outdir]
(-I ignores PYTHONPATH/cwd, so this file inserts its own dir into sys.path.)
Everything here is re-derived from decomp/*.c; see spec for evidence addresses. Engine-neutral output only.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhfpac

# ---- generic chunk walker: header = u32 type, u32 count, u32 size(bytes incl. 12-byte header) ----
def chunks(x, o, end):
    while o + 12 <= end:
        t, c, s = struct.unpack_from('<III', x, o)
        if s < 12 or o + s > end:
            return
        yield o, t, c, s
        o += s

def f32s(x, o, n):
    return struct.unpack_from('<%df' % n, x, o)

def parse_fmod(x):
    """returns dict(meshes=[...], materials=[...], texdesc=[...], header=...)"""
    t, c, s = struct.unpack_from('<III', x, 0)
    assert t == 1 and s == len(x), (t, c, s, len(x))
    out = dict(meshes=[], materials=[], texdesc=[], hdr=None)
    for o, t, c, s in chunks(x, 12, len(x)):
        if t == 0x20000:
            out['hdr'] = struct.unpack_from('<I', x, o + 12)[0]
        elif t == 2:
            for mo, mt, mc, ms in chunks(x, o + 12, o + s):
                assert mt == 4
                out['meshes'].append(parse_mesh(x, mo, ms))
        elif t == 9:
            for co, ct, cc, cs in chunks(x, o + 12, o + s):
                p = o_ = co + 12
                n = (cs - 12) // 4
                d = struct.unpack_from('<%dI' % n, x, p)
                out['materials'].append(dict(
                    specular=f32s(x, p, 4), diffuse=f32s(x, p + 16, 4), ambient=f32s(x, p + 32, 4),
                    power=f32s(x, p + 48, 1)[0], ntex=d[13], tex_desc_index=[d[n - 1]] if n > 64 else [],
                    raw=d))
        elif t == 0xa:
            for co, ct, cc, cs in chunks(x, o + 12, o + s):
                a, w, h = struct.unpack_from('<III', x, co + 12)
                out['texdesc'].append(dict(image_index=a, width=w, height=h))
    return out

def parse_mesh(x, mo, ms):
    m = dict(groups=[], mat_list=[], strip_mat=[], pos=[], nrm=[], uv=[], col=[], skin=[], tan=None, bones=None, extra={})
    for co, ct, cc, cs in chunks(x, mo + 12, mo + ms):
        p = co + 12
        if ct == 5:  # strip groups
            for go, gt, gc, gs in chunks(x, p, co + cs):
                q = go + 12
                strips = []
                for _ in range(gc):
                    n = struct.unpack_from('<I', x, q)[0]
                    flag = n >> 31
                    n &= 0x7fffffff
                    strips.append((flag, list(struct.unpack_from('<%dI' % n, x, q + 4))))
                    q += 4 + 4 * n
                m['groups'].append((gt, strips))
        elif ct == 0x50000:
            m['mat_list'] = list(struct.unpack_from('<%dI' % cc, x, p))
        elif ct == 0x60000:
            m['strip_mat'] = list(struct.unpack_from('<%dI' % cc, x, p))
        elif ct == 0x70000:
            m['pos'] = [f32s(x, p + 12 * i, 3) for i in range(cc)]
        elif ct == 0x80000:
            m['nrm'] = [f32s(x, p + 12 * i, 3) for i in range(cc)]
        elif ct == 0xa0000:
            m['uv'] = [f32s(x, p + 8 * i, 2) for i in range(cc)]
        elif ct == 0xb0000:
            m['col'] = [f32s(x, p + 16 * i, 4) for i in range(cc)]
        elif ct == 0xc0000:  # per-vertex variable record: u32 n, n * (u32 bone, f32 weight%)
            q = p
            for _ in range(cc):
                n = struct.unpack_from('<I', x, q)[0]
                m['skin'].append([(struct.unpack_from('<I', x, q + 4 + 8 * k)[0], f32s(x, q + 8 + 8 * k, 1)[0]) for k in range(n)])
                q += 4 + 8 * n
        elif ct == 0x120000:
            m['tan'] = [f32s(x, p + 16 * i, 4) for i in range(cc)]
        elif ct == 0x100000:
            m['bones'] = list(struct.unpack_from('<%dI' % cc, x, p))
        else:
            m['extra'][hex(ct)] = (cc, cs)
    return m

def triangles(mesh):
    """flatten all strips to a triangle list (index triples), honouring the per-strip flag bit as winding hint.
    returns list of (material_local_index, group_type, (a,b,c))"""
    tris = []
    si = 0
    for gt, strips in mesh['groups']:
        for flag, idx in strips:
            mat = mesh['strip_mat'][si] if si < len(mesh['strip_mat']) else 0
            si += 1
            for k in range(len(idx) - 2):
                a, b, c = idx[k], idx[k + 1], idx[k + 2]
                if a == b or b == c or a == c:
                    continue
                if (k & 1) ^ flag:
                    a, b = b, a
                tris.append((mat, gt, (a, b, c)))
    return tris

def parse_fskl(x):
    t, c, s = struct.unpack_from('<III', x, 0)
    bones = []
    for o, t, c, s in chunks(x, 12, len(x)):
        if t & 0x3fffffff == 1:
            d = struct.unpack_from('<%dI' % ((s - 12) // 4), x, o + 12)
            f = struct.unpack_from('<%df' % ((s - 12) // 4), x, o + 12)
            bones.append(dict(id=d[0], parent=struct.unpack('<i', struct.pack('<I', d[1]))[0], child=struct.unpack('<i', struct.pack('<I', d[2]))[0],
                              sibling=struct.unpack('<i', struct.pack('<I', d[3]))[0], scale=f[4:8], rot_xyzw=f[8:12], pos=f[12:15], raw=d))
    return bones

def load_pac_models(path):
    """returns (fmod_bytes, fskl_bytes, textures:list[bytes]) for entry 0/1 of an em*.pac"""
    b = mhfpac.load_any(path)
    ent = mhfpac.pac_entries(b)
    o, s = ent[0]
    sub = mhfpac.pac_entries(b[o:o + s])
    def un(i):
        it = b[o + sub[i][0]: o + sub[i][0] + sub[i][1]]
        return mhfpac.jkr_decompress(it) if it[:4] == b'JKR\x1a' else it
    fmod, fskl = un(0), un(1)
    tex = []
    if len(ent) > 1 and ent[1][1]:
        o1, s1 = ent[1]
        for so, ss in mhfpac.pac_entries(b[o1:o1 + s1]):
            tex.append(b[o1 + so: o1 + so + ss])
    return fmod, fskl, tex

def write_obj(path, mesh):
    with open(path, 'w') as f:
        for v in mesh['pos']: f.write('v %f %f %f\n' % v)
        for t in mesh['uv']: f.write('vt %f %f\n' % (t[0], 1 - t[1]))
        for v in mesh['nrm']: f.write('vn %f %f %f\n' % v)
        for mat, gt, (a, b, c) in triangles(mesh):
            f.write('f %d/%d/%d %d/%d/%d %d/%d/%d\n' % (a+1,a+1,a+1,b+1,b+1,b+1,c+1,c+1,c+1))

if __name__ == '__main__':
    path = sys.argv[1]
    fmod, fskl, tex = load_pac_models(path)
    m = parse_fmod(fmod)
    print('fmod', len(fmod), 'bytes; header word', hex(m['hdr'] or 0), '; meshes', len(m['meshes']), '; materials', len(m['materials']), '; texdesc', len(m['texdesc']), '; textures in pac', len(tex))
    for i, me in enumerate(m['meshes']):
        tr = triangles(me)
        nv = len(me['pos'])
        mx = max((max(t[2]) for t in tr), default=-1)
        print(' mesh %d: verts %d strips %s tris %d maxidx %d mats %s skin=%s tan=%s extra=%s' % (
            i, nv, [len(g[1]) for g in me['groups']], len(tr), mx, me['mat_list'], bool(me['skin']), me['tan'] is not None, me['extra']))
        assert mx < nv
    bones = parse_fskl(fskl)
    print('skeleton bones', len(bones))
    if '--obj' in sys.argv:
        d = sys.argv[sys.argv.index('--obj') + 1]; os.makedirs(d, exist_ok=True)
        for i, me in enumerate(m['meshes']): write_obj(os.path.join(d, 'mesh%d.obj' % i), me)
    if '--png' in sys.argv:
        d = sys.argv[sys.argv.index('--png') + 1]; os.makedirs(d, exist_ok=True)
        for i, t in enumerate(tex): open(os.path.join(d, 'tex%d.png' % i), 'wb').write(t)
