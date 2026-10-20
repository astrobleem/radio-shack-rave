/* Prepared output from the frozen shared MIDI producer. No parser or synth
   runs during playback. Serialized bytes, not compiler-native struct layout. */
#define RV_BLOCK_FRAMES 900U
#define RV_FRAME_BYTES 18U
#define RV_BLOCKS 20U
static unsigned char far *rvBlocks[RV_BLOCKS];
static unsigned rvBlockCount,rvBlock,rvIndex,rvCount,rvDone,rvPrepared;
static unsigned rvP[3],rvVolume,rvNoise,rvFlags,rvPit,rvMessages;
static unsigned rvNoiseValid,rvNoiseMode;
static unsigned long rvAt,rvFrames,rvPosition,rvLastPoll,rvSum;
static unsigned rvPollSeen;
static unsigned char rvPsgBytes[11];
static unsigned rv16(const unsigned char far *p)
{return (unsigned)p[0]|((unsigned)p[1]<<8);}
static unsigned long rv32(const unsigned char far *p)
{return (unsigned long)rv16(p)|((unsigned long)rv16(p+2)<<16);}
static void rv_free(void)
{
    unsigned i;
    for(i=0;i<rvBlockCount;i++){_ffree(rvBlocks[i]);rvBlocks[i]=0;}
    rvBlockCount=rvPrepared=0;
}
static void rv_decode(void)
{
    const unsigned char far *p=rvBlocks[rvBlock]+rvIndex*RV_FRAME_BYTES;
    rvAt=rv32(p);rvP[0]=rv16(p+4);rvP[1]=rv16(p+6);
    rvP[2]=rv16(p+8);rvVolume=rv16(p+10);rvNoise=p[12];
    rvFlags=p[13];rvPit=rv16(p+14);rvMessages=rv16(p+16);
}
static int rv_load(const char *path)
{
    FILE *f;unsigned char h[32];static unsigned char bounce[512];
    unsigned b,n,k,offset,bytes;unsigned long remain,sum=0,previous=0,total=0;
    long size;int valid=1;
    f=fopen(path,"rb");if(!f)return 0;
    if(fread(h,1,32,f)!=32 || memcmp(h,"RWS1",4) || rv16(h+4)!=32 ||
       rv16(h+6)!=RV_FRAME_BYTES || rv16(h+18)!=3 || rv16(h+20)!=1 ||
       rv16(h+22) || rv32(h+28)!=0x3954504fUL){fclose(f);return 0;}
    rvFrames=rv32(h+8);openedDuration=rv32(h+12);openedEvents=rv16(h+16);
    if(!rvFrames || rvFrames>RV_BLOCK_FRAMES*RV_BLOCKS || !openedEvents ||
       openedEvents>32768U || !openedDuration || openedDuration>3600000UL) {
        fclose(f);return 0;
    }
    if(fseek(f,0,SEEK_END)){fclose(f);return 0;}size=ftell(f);
    if(size!=(long)(32UL+rvFrames*RV_FRAME_BYTES) || fseek(f,32,SEEK_SET)) {
        fclose(f);return 0;
    }
    remain=rvFrames;
    while(remain) {
        n=remain>RV_BLOCK_FRAMES?RV_BLOCK_FRAMES:(unsigned)remain;
        bytes=n*RV_FRAME_BYTES;
        rvBlocks[rvBlockCount]=(unsigned char far *)_fmalloc(bytes);
        if(!rvBlocks[rvBlockCount]){fclose(f);rv_free();return 0;}
        b=rvBlockCount++;offset=0;
        while(offset<bytes) {
            k=bytes-offset;if(k>sizeof(bounce))k=sizeof(bounce);
            if(fread(bounce,1,k,f)!=k){fclose(f);rv_free();return 0;}
            _fmemcpy(rvBlocks[b]+offset,(void far *)bounce,k);
            for(n=0;n<k;n++)sum+=bounce[n];
            offset+=k;
        }
        remain-=bytes/RV_FRAME_BYTES;
    }
    fclose(f);
    if(sum!=rv32(h+24)){rv_free();return 0;}
    rvBlock=rvIndex=0;
    for(rvPosition=0;rvPosition<rvFrames;rvPosition++) {
        rv_decode();
        if(rvAt<previous || rvP[0]>1023 || rvP[1]>1023 || rvP[2]>1023 ||
           rvNoise>7 || rvFlags>1 || (rvPit && rvPit<152))valid=0;
        if((!rvP[0] && (rvVolume&15)!=15) ||
           (!rvP[1] && ((rvVolume>>4)&15)!=15) ||
           (!rvP[2] && ((rvVolume>>8)&15)!=15))valid=0;
        previous=rvAt;total+=rvMessages;
        if(++rvIndex==RV_BLOCK_FRAMES){rvIndex=0;rvBlock++;}
    }
    if(total!=openedEvents || rvVolume!=65535U || rvPit ||
       rvAt>(openedDuration/1000UL)*4661UL+
            ((openedDuration%1000UL)*4661UL)/1000UL+50UL)valid=0;
    if(!valid){rv_free();return 0;}
    rvBlock=rvIndex=0;rvPosition=0;rvDone=0;rvNoiseValid=0;
    rvLastPoll=0;rvPollSeen=0;rvPrepared=1;rv_decode();return 1;
}
static void rv_rewind(void)
{
    rvBlock=rvIndex=0;rvPosition=0;rvDone=0;rvNoiseValid=0;
    rvLastPoll=0;rvPollSeen=0;rv_decode();
}
static void rv_poll(unsigned long fine)
{
    unsigned i,n;unsigned long late,gap;
    if(rvPollSeen && fine>=rvLastPoll) {
        gap=fine-rvLastPoll;
        gap=(gap*55UL+255UL)>>8;
        if(gap>maxPollGap)maxPollGap=gap>65535UL?65535U:(unsigned)gap;
    }
    rvPollSeen=1;rvLastPoll=fine;
    while(!rvDone && rvAt<=fine) {
        n=0;
        for(i=0;i<3;i++) {
            rvPsgBytes[n++]=(unsigned char)(0x80|(i<<5)|(rvP[i]&15));
            rvPsgBytes[n++]=(unsigned char)((rvP[i]>>4)&63);
            rvPsgBytes[n++]=(unsigned char)(0x90|(i<<5)|((rvVolume>>(i*4))&15));
        }
        if(!rvNoiseValid || rvNoiseMode!=rvNoise || rvFlags) {
            rvPsgBytes[n++]=(unsigned char)(0xe0|rvNoise);
        }
        rvPsgBytes[n++]=(unsigned char)(0xf0|(rvVolume>>12));
        if(DosSoundPsgBytes(rvPsgBytes,n))errors++;
        else {rvNoiseMode=rvNoise;rvNoiseValid=1;emittedPackedVolume=rvVolume;}
        if(DosSoundPitDivisor(rvPit,0))errors++;
        else emittedPitGate=rvPit!=0;
        delivered+=rvMessages;
        late=((fine-rvAt)*55UL+255UL)>>8;
        if(late>maxLateness)maxLateness=late>65535UL?65535U:(unsigned)late;
        rvPosition++;
        if(rvPosition==rvFrames){rvDone=ended=1;break;}
        if(++rvIndex==RV_BLOCK_FRAMES){rvIndex=0;rvBlock++;}
        rv_decode();
    }
}
