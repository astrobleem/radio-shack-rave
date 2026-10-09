"""Turn a /RENDER or /TOUR capture into a video with sound.

In render mode the game runs on a virtual clock: every presented frame is
saved as Fnnnnn.RAW (160 bytes x 200 rows, Tandy mode 9 nibbles) and the
clock advances exactly half a BIOS tick; every SN76496 write goes to PSG.LOG
as "<time in 1/256 tick> <byte>". This script re-synthesizes the PSG and
muxes it with the frames through ffmpeg, so the video is frame-exact and
independent of emulator speed.

    python tools/tour_video.py CAPTURE_DIR rave.mp4

Needs numpy and an ffmpeg executable. The PSG model is a plain SN76496
(3.579545 MHz, 2 dB attenuation steps, 15-bit noise); it is a preview, not a
recording of a real Tandy.
"""
import argparse,subprocess,wave
from pathlib import Path
import numpy as np

PAL=[(0,0,0),(0,0,170),(0,170,0),(0,170,170),(170,0,0),(170,0,170),(170,85,0),(170,170,170),
     (85,85,85),(85,85,255),(85,255,85),(85,255,255),(255,85,85),(255,85,255),(255,255,85),(255,255,255)]
PIT=1193182;CLOCK=3579545;RATE=44100
FINE_SECONDS=65536/PIT/256          # one 1/256-tick unit
FPS=PIT/65536*2                      # half a tick per frame, about 36.41

def synth(log,seconds):
    events=[]
    for line in Path(log).read_text().split('\n'):
        if line.strip():
            t,b=line.split();events.append((int(t)*FINE_SECONDS,int(b)))
    n=int(seconds*RATE);out=np.zeros(n)
    div=[1,1,1];att=[15,15,15,15];noise_ctl=0;latch=0
    vol=[0 if a==15 else 10**(-a/10) for a in range(16)]
    phase=[0.0,0.0,0.0];lfsr=0x4000;nphase=0.0;nout=1
    bounds=[int(t*RATE) for t,_ in events]+[n]
    pos=0
    for i in range(len(events)+1):
        end=min(bounds[i],n)
        if end>pos:
            seg=np.arange(end-pos)
            for ch in range(3):
                if att[ch]<15 and div[ch]>1:
                    f=CLOCK/(32*div[ch])
                    ph=phase[ch]+seg*f/RATE
                    out[pos:end]+=np.where((ph%1.0)<0.5,1.0,-1.0)*vol[att[ch]]*0.25
                    phase[ch]=(phase[ch]+(end-pos)*f/RATE)%1.0
            if att[3]<15:
                rate=[CLOCK/512,CLOCK/1024,CLOCK/2048,CLOCK/(32*max(div[2],1))][noise_ctl&3]
                white=noise_ctl&4;buf=np.empty(end-pos)
                for k in range(end-pos):
                    nphase+=rate/RATE
                    while nphase>=1.0:
                        nphase-=1.0
                        bit=((lfsr&1)^((lfsr>>1)&1)) if white else (lfsr&1)
                        lfsr=(lfsr>>1)|(bit<<14);nout=lfsr&1
                    buf[k]=1.0 if nout else -1.0
                out[pos:end]+=buf*vol[att[3]]*0.25
            pos=end
        if i==len(events):break
        b=events[i][1]
        if b&0x80:
            latch=(b>>5)&3
            if b&0x10:att[latch]=b&15
            elif latch==3:noise_ctl=b&7;lfsr=0x4000
            else:div[latch]=(div[latch]&0x3f0)|(b&15)
        elif latch<3:div[latch]=(div[latch]&15)|((b&63)<<4)
    return np.clip(out,-1,1)

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('capture',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--scale',type=int,default=3,help='width multiple; height keeps 4:3')
    a=p.parse_args()
    frames=sorted(a.capture.glob('F*.RAW'))
    if not frames:raise SystemExit('no F*.RAW frames')
    seconds=len(frames)/FPS
    audio=synth(a.capture/'PSG.LOG',seconds)
    wav=a.output.with_suffix('.wav')
    with wave.open(str(wav),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(RATE)
        w.writeframes((audio*32000).astype('<i2').tobytes())
    lut=np.array(PAL,dtype=np.uint8)
    W,H=320*a.scale,240*a.scale
    cmd=['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s','320x200',
         '-framerate',f'{FPS:.6f}','-i','-','-i',str(wav),
         '-vf',f'scale={W}:{H}:flags=neighbor,fps=60','-c:v','libx264','-pix_fmt','yuv420p',
         '-crf','16','-c:a','aac','-b:a','192k','-shortest',str(a.output)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    for f in frames:
        b=np.frombuffer(f.read_bytes(),dtype=np.uint8)
        idx=np.empty(b.size*2,dtype=np.uint8);idx[0::2]=b>>4;idx[1::2]=b&15
        proc.stdin.write(lut[idx].tobytes())
    proc.stdin.close();proc.wait()
    wav.unlink()
    print(f'{a.output}: {len(frames)} frames, {seconds:.1f} s')
if __name__=='__main__':main()
