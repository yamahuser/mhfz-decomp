import struct,sys
sys.path.insert(0,'tools')
from jkr import jkr_decode
def sarch(d):
    if len(d)<12: return None
    n=struct.unpack_from('<I',d,0)[0]
    if n==0 or n>4096 or 4+8*n>len(d): return None
    ents=[struct.unpack_from('<II',d,4+8*i) for i in range(n)]
    for o,s in ents:
        if o+s>len(d) or o<4+8*n: return None
    return ents
def walk(d,name,depth=0,dump=None):
    pad='  '*depth
    if d[:4]==b'JKR\x1a':
        u=jkr_decode(d); print(pad+f'{name}: JKR -> {len(u)}'); walk(u,name+'*',depth+1,dump); return
    e=sarch(d)
    if e:
        print(pad+f'{name}: archive n={len(e)} {[(hex(o),s) for o,s in e]}')
        for i,(o,s) in enumerate(e):
            if s: walk(d[o:o+s],f'{name}/{i}',depth+1,dump)
        return
    print(pad+f'{name}: raw {len(d)} head={d[:24].hex(" ")}')
    if dump is not None: dump[name]=d
if __name__=='__main__':
    walk(open(sys.argv[1],'rb').read(),sys.argv[1].split('/')[-1])
