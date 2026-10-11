"""Bounded offline reference/PSG-noise previews; approximations, not hardware audio.

Reference retains MIDI polyphony/pitches/velocities and measured tempo; it uses
simple oscillators, not the MIDI author's instrument patches or a recording.
"""
import array,json,math,sys,wave
from fractions import Fraction as F
from midi_arrangement import clock_seconds,convert_arrangement,decode_score
from import_score import gm_drum,DRUM_KINDS
from mml import CLOCK,PITCH,rounded

KIT_CTL=(2,5,4,4,4,1,0)
KIT_ATT=(0,1,5,4,2,1,1)
KIT_LEN=(560,840,230,1400,4200,1160,930)

def tone(mix,pitch,start,end,amp,rate,chip=False,divisor=None):
    a=max(0,int(start*rate));b=min(len(mix),int(end*rate))
    if a>=b:return
    freq=440*2**((pitch-69)/12)
    if chip:
        div=divisor or rounded(F(3579545,32*PITCH[pitch-45]));freq=3579545/(32*div)
    step=freq/rate
    for i in range(a,b):
        phase=((i-a)*step)%1
        # Reference is a sine oscillator, the chip path a square wave.
        value=(1 if phase<0.5 else -1) if chip else math.sin(2*math.pi*phase)
        mix[i]+=int(value*amp)

def noise(mix,kind,start,att,rate,stop=None):
    k=DRUM_KINDS.index(kind);a=max(0,int(start*rate))
    seconds=float(F(KIT_LEN[k],256)/CLOCK)
    b=min(len(mix),int((start+seconds)*rate),int(stop*rate) if stop is not None else len(mix))
    shift=0x4000;phase=0.0;ctl=KIT_CTL[k]
    step=(3579545/(512*(1<<(ctl&3))))/rate
    for i in range(a,b):
        phase+=step
        while phase>=1:
            feedback=((shift&1)^((shift>>1)&1)) if ctl&4 else shift&1
            shift=(shift>>1)|(feedback<<14);phase-=1
        age=(i-a)/rate*float(CLOCK)*256
        level=min(15,KIT_ATT[k]+att+int((15-KIT_ATT[k])*age/KIT_LEN[k]))
        amp=6500*10**(-level/10) if level<15 else 0
        mix[i]+=int(amp if shift&1 else -amp)

def game_samples(result,rate,max_seconds):
    blob,_,_=convert_arrangement(result['arrangement']);score=decode_score(blob)
    total=min(float(F(score['total'])/CLOCK),max_seconds);mix=[0]*(int(total*rate)+1)
    for tick,end,div,lane,att,pitch,auto in score['lead']:
        tone(mix,pitch,float(F(tick)/CLOCK),float(F(end)/CLOCK),int(7000*10**(-att/10)),rate,True,div)
    for state,nxt in zip(score['states'],score['states'][1:]):
        tick,d0,d1,d2,a0,a1,a2=state
        for div,att in [(d1,a1),(d2,a2)]:
            if div:tone(mix,69,float(F(tick)/CLOCK),float(F(nxt[0])/CLOCK),int(7000*10**(-att/10)),rate,True,div)
    hits=score['drums']
    for i,(tick,kind,att) in enumerate(hits):
        start=float(F(tick)/CLOCK)
        stop=float(F(hits[i+1][0])/CLOCK) if i+1<len(hits) else total
        noise(mix,DRUM_KINDS[kind],start,att,rate,stop)
    return mix,total

def write_wav(path,channels,rate):
    n=max(map(len,channels));samples=array.array('h')
    for i in range(n):
        for ch in channels:samples.append(max(-32000,min(32000,ch[i] if i<len(ch) else 0)))
    if sys.byteorder=='big':samples.byteswap()
    with wave.open(str(path),'wb') as w:
        w.setnchannels(len(channels));w.setsampwidth(2);w.setframerate(rate);w.writeframes(samples.tobytes())

def render_game(result,path,rate=22050,max_seconds=120):
    if not 8000<=rate<=48000 or not 0<max_seconds<=120:raise ValueError('preview limits: rate 8000..48000, length <=120s')
    mix,total=game_samples(result,rate,max_seconds);write_wav(path,[mix],rate);return total

def render_comparison(smf,result,path,rate=22050,max_seconds=30):
    if not 8000<=rate<=48000 or not 0<max_seconds<=120:raise ValueError('preview limits exceeded')
    game,total=game_samples(result,rate,max_seconds);source=[0]*len(game)
    a=result['arrangement'];ppq,tracks,tempos,_=smf
    start=a['start_tick'];end=a['end_tick'];origin=clock_seconds(start,ppq,tempos)
    for tr in tracks:
        attacks={(d['tick'],d['pitch'],d['channel']):d['velocity'] for d in tr.get('attacks',[])}
        for s,e,p,ch in tr['notes']:
            if ch==9 or e<=start or s>=end:continue
            on=float(clock_seconds(max(start,s),ppq,tempos)-origin)
            off=float(clock_seconds(min(end,e),ppq,tempos)-origin)
            tone(source,p,on,off,3000*attacks.get((s,p,ch),90)/127,rate)
        for d in tr.get('attacks',[]):
            if d['channel']!=9 or not start<=d['tick']<end:continue
            kind=gm_drum(d['pitch'])
            if kind is None:raise ValueError('unmapped source percussion cannot be previewed faithfully')
            at=float(clock_seconds(d['tick'],ppq,tempos)-origin)
            noise(source,kind,at,15-rounded(F(d['velocity']*15,127)),rate)
    write_wav(path,[source,game],rate)
    return dict(seconds=total,left='Source MIDI oscillator approximation: full polyphony and measured drums',
                right='Reduced PSG square + one noise channel approximation: native drum quantization/priority',
                caveat='No original recording, General MIDI patch synthesis, or physical Tandy audio claim')
