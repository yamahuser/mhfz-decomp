import struct
def jkr_hfi(d, hfbits=False):
    magic,ver,typ,off,size=struct.unpack_from('<IHHII',d,0)
    tl=struct.unpack_from('<H',d,off)[0]
    tab=[struct.unpack_from('<H',d,off+2+2*i)[0] for i in range((tl-0x100+1)*2)]
    p=off+2+(tl-0x100+1)*4
    st={'p':p,'mask':0,'flag':0,'hm':0,'hb':0}
    def rawbyte():
        b=d[st['p']]; st['p']+=1; return b
    def bit():
        if st['mask']==0:
            st['flag']=rawbyte(); st['mask']=0x80
        b=1 if st['flag']&st['mask'] else 0; st['mask']>>=1; return b
    def hbit():
        if st['hm']==0:
            st['hb']=rawbyte(); st['hm']=0x80
        b=1 if st['hb']&st['hm'] else 0; st['hm']>>=1; return b
    def hbyte():
        n=tl
        while n>=0x100:
            n=tab[(n-0x100)*2+hbit()]
        return n&0xff
    out=bytearray()
    while len(out)<size:
        if not bit():
            out.append(hbyte()); continue
        if not bit():
            ln=(bit()<<1|bit())+3; o=hbyte()+1
        else:
            hi=hbyte(); lo=hbyte()
            ln=hi>>5; o=((hi&0x1f)<<8|lo)+1
            if ln==0:
                if not bit(): ln=(bit()<<3|bit()<<2|bit()<<1|bit())+0x0a
                else: ln=hbyte()+0x1a
            else: ln+=2
        for _ in range(ln): out.append(out[-o])
    return bytes(out)
