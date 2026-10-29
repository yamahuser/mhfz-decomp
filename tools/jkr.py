"""JKR (JPK) decoder, types 2(none?),3 (LZ), 4 (Huffman+LZ) - written from the game's own decoder 1158f240/1158efe0/1158eec0."""
import struct
def jkr_decode(d, l4=10):
    assert d[:4]==b'JKR\x1a'
    ver,typ,off,size=struct.unpack_from('<HHII',d,4)
    if typ==0: return d[off:off+size]
    p=off
    hf=None
    if typ==4:
        tl=struct.unpack_from('<H',d,off)[0]
        tab=struct.unpack_from('<%dH'%((tl-0x100+1)*2),d,off+2)
        p=off+tl*4-0x3f9+0   # src pointer after table
        hb=d[p-1]; hn=0
        hf=(tl,tab)
    st=[p,0,0,hb if typ==4 else 0,0]  # src, flagidx, flag, hbyte, hbitcount
    def raw():
        b=d[st[0]]; st[0]+=1; return b
    def hbyte():
        tl,tab=hf; n=tl
        while True:
            k=st[4]; bit=(st[3]>>(7-k))&1; k+=1; st[4]=k
            if k==8:
                st[3]=d[st[0]]; st[0]+=1; st[4]=0
            n=tab[(n-0x100)*2+bit]
            if n<0x100: return n
    gb=hbyte if typ==4 else raw
    def bit():
        st[1]-=1
        if st[1]<0:
            st[2]=gb(); st[1]=7
        return (st[2]>>st[1])&1
    out=bytearray()
    while len(out)<size:
        if not bit():
            out.append(gb()); continue
        if not bit():
            ln=(bit()<<1|bit())+3; o=gb()+1
        else:
            hi=gb(); lo=gb(); o=((hi&0x1f)<<8|lo)+1
            if hi&0xe0: ln=(hi>>5)+2
            elif not bit():
                ln=(bit()<<3|bit()<<2|bit()<<1|bit())+l4
            else:
                b=gb()
                if b==0xff:
                    n=o-1+0x1b
                    for _ in range(n): out.append(gb())
                    continue
                ln=b+0x1a
        for _ in range(ln): out.append(out[-o])
    return bytes(out[:size])

