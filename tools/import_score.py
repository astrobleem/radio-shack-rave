"""Deterministic offline MML -> normalized events -> RBG4 agency chart."""
import argparse,hashlib,json,struct
from fractions import Fraction as F
from pathlib import Path
from mml import parse,ScoreError,rounded,CLOCK,PITCH
from chart_policy import select_required,separate_lane_windows

DIFFICULTIES={'easy':500,'normal':280,'hard':200,'full':0}
# Runtime bounds (src/BEAT.C, src/CORE.H): far tables sized per song.
MAX_LEAD=2048
MAX_STATES=4096
MAX_DRUMS=4096
# Drum kinds played on the noise channel, in collision priority order when
# two hits land on the same BIOS tick (earlier in this list wins).
DRUM_KINDS=['kick','snare','closed_hat','open_hat','crash','low_tom','high_tom']
DRUM_PRIORITY=['crash','snare','kick','low_tom','high_tom','open_hat','closed_hat']
def gm_drum(note):
    """General MIDI percussion key -> drum kind, or None if unmapped."""
    if note in (35,36):return 'kick'
    if note in (37,38,39,40):return 'snare'
    if note in (42,44,54,56,69,70,73,74,75,76,77,78,79,80,81):return 'closed_hat'
    if note==46:return 'open_hat'
    if note in (49,51,52,53,55,57,58,59):return 'crash'
    if note in (41,43,45,61,63,64,66,68):return 'low_tom'
    if note in (47,48,50,60,62,65,67,71,72):return 'high_tom'
    return None
DIFFICULTY_CODE={'easy':0,'normal':1,'hard':2,'full':3}
TITLE_CHARS=set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !?'.,-:&/+")
TITLE_MAX=24
MAX_BEAT_SEGMENTS=64
def clean_title(text):
    """Uppercase, map characters the DOS font lacks to spaces, collapse, truncate."""
    out=''.join(c if c in TITLE_CHARS else ' ' for c in str(text).upper())
    return ' '.join(out.split())[:TITLE_MAX].rstrip()
def beat_seconds(tempo_map,beat):
    total=F(0);prev=F(0);bpm=tempo_map[0][1]
    for at,value in tempo_map:
        if at>beat:break
        total+=(at-prev)*60/bpm;prev=at;bpm=value
    return total+(beat-prev)*60/bpm
def beat_segments(tempo_map,duration):
    """Integer quarter-note beats as runs of equal spacing, in 16.16 BIOS ticks."""
    times=[];k=0
    while True:
        t=beat_seconds(tempo_map,F(k))*CLOCK
        if t>=duration*CLOCK:break
        times.append(t);k+=1
    segs=[]
    for k,t in enumerate(times):
        if segs:
            first,start,period,count=segs[-1]
            if count==1 or t==start+period*count:
                if count==1:period=t-start
                segs[-1]=(first,start,period,count+1);continue
        segs.append((k,t,F(0),1))
    if len(segs)>MAX_BEAT_SEGMENTS:
        raise ScoreError(f'{len(segs)} distinct tempo runs exceed the {MAX_BEAT_SEGMENTS}-segment beat grid; simplify tempo changes')
    return [(first,rounded(start*65536),rounded(period*65536),count) for first,start,period,count in segs]
def rational(x):return f'{x.numerator}/{x.denominator}'
def stable_json(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode('utf8')
def audible(ns):return [n for n in ns if n['note'] and n['volume']]
def ranking(ns,index):
    notes=audible(ns);pitches=sorted(n['note'] for n in notes)
    median=pitches[(len(pitches)-1)//2] if pitches else 0
    return (len(notes),median,-index)

def convert(text,*,lead='auto',lead_policy='activity',parts=None,difficulty='normal',gap_ms=None,
            octave=4,length=4,tempo=120,volume=100,transpose=0,voice_transpose=None,title='',chart_policy='elapsed',
            drums=None):
    """Return exact byte artifacts; does not touch network or filesystem."""
    if difficulty not in DIFFICULTIES:raise ScoreError('difficulty must be easy/normal/hard/full')
    if gap_ms is None:gap_ms=DIFFICULTIES[difficulty]
    if not isinstance(gap_ms,int) or not (200<=gap_ms<=2000 or (difficulty=='full' and gap_ms==0)):
        raise ScoreError('gap_ms must be an integer 200..2000, or 0 only for explicit full melody')
    if not isinstance(transpose,int) or not -48<=transpose<=48:raise ScoreError('transpose must be integer -48..48')
    if not isinstance(title,str) or clean_title(title)!=title:
        raise ScoreError(f'title must be at most {TITLE_MAX} characters of A-Z 0-9 space and !?\'.,-:&/+')
    voice_transpose=voice_transpose or {}
    if any(not isinstance(k,int) or not isinstance(v,int) or not -48<=v<=48 for k,v in voice_transpose.items()):
        raise ScoreError('voice transpositions need 1-based voice numbers and integer -48..48 shifts')
    voices,tempo_map,duration=parse(text,octave=octave,length=length,tempo=tempo,
        volume=volume,max_voices=8,parts_only=True)
    if any(not 1<=k<=len(voices) for k in voice_transpose):raise ScoreError('transpose voice does not exist')
    if lead_policy not in ('activity','melody'):raise ScoreError('lead_policy must be activity or melody')
    max_attacks=max(len(audible(ns)) for ns in voices)
    def rank_key(i):
        count,median,order=ranking(voices[i],i)
        if lead_policy=='melody':return (count*2>=max_attacks and count>0,median,count,order)
        return (count,median,order)
    ranks=sorted(range(len(voices)),key=rank_key,reverse=True)
    drum_index=None
    if drums is not None:
        if not isinstance(drums,int) or not 1<=drums<=len(voices):raise ScoreError('drums must be an existing 1-based voice number')
        drum_index=drums-1
        if not audible(voices[drum_index]):raise ScoreError(f'drum voice {drums} has no audible notes')
        if drums in voice_transpose:raise ScoreError('the drum voice keys General MIDI percussion; it cannot be transposed')
        # The drum voice never competes for the lead or a tone channel.
        ranks=[i for i in ranks if i!=drum_index]
    if lead=='auto':lead_index=ranks[0]
    else:
        try:lead_index=int(lead)-1
        except (ValueError,TypeError):raise ScoreError('lead must be auto or a 1-based voice number')
        if not 0<=lead_index<len(voices):raise ScoreError('lead voice does not exist')
    if lead_index==drum_index:raise ScoreError('the drum voice cannot also be the lead')
    if not audible(voices[lead_index]):raise ScoreError('selected lead has no audible notes')
    if parts is None:
        selected=[lead_index]+[i for i in ranks if i!=lead_index and audible(voices[i])][:2]
    else:
        if not 1<=len(parts)<=3 or len(set(parts))!=len(parts):raise ScoreError('parts needs 1..3 distinct voice numbers')
        if any(not isinstance(i,int) or not 1<=i<=len(voices) for i in parts):raise ScoreError('selected part does not exist')
        if lead_index+1 not in parts:raise ScoreError('parts must include selected lead')
        if drums is not None and drums in parts:raise ScoreError('the drum voice plays on the noise channel; leave it out of parts')
        selected=[lead_index]+[i-1 for i in parts if i!=lead_index+1]
    transformed={};transpositions=[]
    for vi in selected:
        shift=transpose+voice_transpose.get(vi+1,0);out=[]
        for n in voices[vi]:
            target=n['note']+shift if n['note'] else 0
            if n['note'] and n['volume'] and not 45<=target<=96:
                raise ScoreError(f'voice {vi+1} at {rational(n["start"])}s pitch {n["note"]} -> {target} outside MIDI45..96; explicit transpose needed; never clamped')
            out.append(dict(n,note=target))
        transformed[vi]=out
        pitches=[n['note'] for n in audible(voices[vi])]
        transpositions.append(dict(voice=vi+1,semitones=shift,
            input_range=[min(pitches),max(pitches)] if pitches else None,
            output_range=[min(pitches)+shift,max(pitches)+shift] if pitches else None))
    source_lead=audible(transformed[lead_index]);chosen=[];dropped=[];last=None;required=0
    if chart_policy not in ('metrical','elapsed'):raise ScoreError('chart_policy must be metrical or elapsed')
    eligible=[rounded(n['end']*CLOCK)-rounded(n['start']*CLOCK)>3 for n in source_lead] if difficulty in ('easy','normal') else None
    selected_required=select_required(source_lead,tempo_map,gap_ms,eligible) if chart_policy=='metrical' else None
    if selected_required is not None and difficulty in ('easy','normal'):
        selected_required=separate_lane_windows(source_lead,selected_required,tempo_map,CLOCK,rounded)
    if selected_required is not None and not selected_required:raise ScoreError('no lead onset survives the easy/normal audible late-window requirement; choose another lead, slower tempo, or explicit hard/full')
    for index,n in enumerate(source_lead):
        automatic=(index not in selected_required) if selected_required is not None else (last is not None and n['start']-last<F(gap_ms,1000))
        if automatic:
            dropped.append(dict(onset=index,start=rational(n['start']),reason='not a required input; retained automatic lead'))
        tick,off=rounded(n['start']*CLOCK),rounded(n['end']*CLOCK)
        if off<=tick:raise ScoreError(f'lead voice {lead_index+1} at {rational(n["start"])}s collapses at BIOS resolution')
        d=rounded(F(3579545,32*PITCH[n['note']-45]));lane=(n['note']-45)%3
        chosen.append((tick,off,d,lane,15-n['volume'],n['note'],int(automatic)))
        if not automatic:last=n['start'];required+=1
    if not chosen or len(chosen)>MAX_LEAD:raise ScoreError(f'native score requires 1..{MAX_LEAD} total lead events; source must fit, never discard melody to meet storage bounds')
    if any(b[0]<a[1] for a,b in zip(chosen,chosen[1:])):raise ScoreError('selected lead intervals overlap after tick quantization')
    total=rounded(duration*CLOCK)
    if not 1<=total<=10924 or chosen[-1][0]>=total:raise ScoreError('native score duration/onset invalid')
    # Selected backing parts retain all their intervals, including same-pitch attacks.
    events={F(0):[],duration:[]}
    collapsed=[]
    for native,vi in enumerate(selected[1:],1):
        for index,n in enumerate(transformed[vi]):
            events.setdefault(n['start'],[]).append((1,native,n['note'] if n['volume'] else 0,n['volume']))
            events.setdefault(n['end'],[]).append((0,native,0,0))
            if n['note'] and n['volume'] and rounded(n['end']*CLOCK)<=rounded(n['start']*CLOCK):
                collapsed.append(dict(voice=vi+1,onset=index,start=rational(n['start']),reason='backing interval below BIOS resolution'))
    ds=[0,0,0];ats=[15,15,15];packed=[];collisions=[]
    for at,ev in sorted(events.items()):
        for on,k,n,v in sorted(ev):
            ds[k]=rounded(F(3579545,32*PITCH[n-45])) if n and v else 0
            ats[k]=15-v if ds[k] else 15
        row=(rounded(at*CLOCK),tuple(ds),tuple(ats))
        if packed and packed[-1][0]==row[0]:
            collisions.append(dict(tick=row[0],kept_seconds=rational(at)))
            packed[-1]=row
        else:packed.append(row)
    if not 2<=len(packed)<=MAX_STATES:raise ScoreError(f'native stream requires 2..{MAX_STATES} states')
    segments=beat_segments(tempo_map,duration)
    # Drum voice -> noise-channel hits, one per BIOS tick (priority wins).
    drum_events={};drum_collisions=[];by_kind={k:0 for k in DRUM_KINDS}
    if drum_index is not None:
        for n in voices[drum_index]:
            if not (n['note'] and n['volume']):continue
            kind=gm_drum(n['note'])
            if kind is None:raise ScoreError(f'drum voice {drums} at {rational(n["start"])}s: note {n["note"]} is not a mapped General MIDI percussion key (35..81)')
            tick=rounded(n['start']*CLOCK)
            if tick>=total:raise ScoreError(f'drum voice {drums} at {rational(n["start"])}s: hit at or after the song end')
            ev=(DRUM_KINDS.index(kind),15-n['volume'])
            if tick in drum_events:
                old=drum_events[tick]
                win=min(old,ev,key=lambda e:(DRUM_PRIORITY.index(DRUM_KINDS[e[0]]),e[1]))
                drum_collisions.append(dict(tick=tick,kept=DRUM_KINDS[win[0]],dropped=DRUM_KINDS[(ev if win==old else old)[0]]))
                drum_events[tick]=win
            else:drum_events[tick]=ev
        if not drum_events:raise ScoreError(f'drum voice {drums} has no hits inside the song')
        if len(drum_events)>MAX_DRUMS:raise ScoreError(f'{len(drum_events)} drum hits exceed {MAX_DRUMS}; simplify the drum part')
        for k,_ in drum_events.values():by_kind[DRUM_KINDS[k]]+=1
    version=5 if drum_events else 4
    blob=struct.pack('<4sHHHH',b'RBG%d'%version,version,total,len(packed),len(chosen))
    blob+=struct.pack('<HBx24s',len(segments),DIFFICULTY_CODE[difficulty],title.encode('ascii'))
    if drum_events:blob+=struct.pack('<HH',len(drum_events),0)
    blob+=b''.join(struct.pack('<4H3Bx',tick,*d,*a) for tick,d,a in packed)
    blob+=b''.join(struct.pack('<3H4B',*n) for n in chosen)
    blob+=b''.join(struct.pack('<LLHH',start,period,first,count) for first,start,period,count in segments)
    blob+=b''.join(struct.pack('<HBB',t,k,lv) for t,(k,lv) in sorted(drum_events.items()))
    normalized=dict(schema='normalized-mml-v2',tempo_map=[dict(beat=rational(t),bpm=b) for t,b in tempo_map],
        duration_seconds=rational(duration),voices=[[dict(start=rational(n['start']),end=rational(n['end']),
            note=n['note'],level=n['volume']) for n in ns] for ns in voices])
    settings=dict(title=title,lead=lead,lead_policy=lead_policy,parts=parts,difficulty=difficulty,gap_ms=gap_ms,octave=octave,
        length=length,tempo=tempo,volume=volume,transpose=transpose,
        voice_transpose={str(k):v for k,v in sorted(voice_transpose.items())})
    if drums is not None:settings.update(drums=drums)
    if chart_policy!='elapsed':
        settings.update(chart_policy=chart_policy,audible_late_window_ticks=3,
            minimum_same_lane_required_spacing_ticks=7 if difficulty in ('easy','normal') else 0,
            minimum_required_duration_ticks=4 if difficulty in ('easy','normal') else 1)
    report=dict(schema='deterministic-rbg4-v4' if version==4 else 'deterministic-rbg5-v1',title=title,
        beat_grid=dict(segments=len(segments),beats=sum(c for *_,c in segments),units='16.16 BIOS ticks; integer quarter-note beats'),source_sha256=hashlib.sha256(text.encode('ascii')).hexdigest(),
        score_sha256=hashlib.sha256(blob).hexdigest(),settings=settings,
        lead_voice=lead_index+1,psg_voices=[i+1 for i in selected],
        ranking=[dict(voice=i+1,attacks=ranking(voices[i],i)[0],lower_median_pitch=ranking(voices[i],i)[1]) for i in ranks],
        auto_policy=('voices with at least half the busiest part attacks first, then higher lower-median pitch, then attack count, then lower voice number' if lead_policy=='melody' else 'most audible attacks, then higher lower-median pitch, then lower source voice number'),
        dropped_voices=[i+1 for i in range(len(voices)) if i not in selected],
        transpositions=transpositions,source_lead_onsets=len(source_lead),lead_events=len(chosen),chart_taps=required,automatic_lead_events=len(chosen)-required,
        input_density=dict(required=required,seconds=rational(duration),required_per_second=rational(F(required)/duration)),
        audible_retention=dict(source_onsets=len(source_lead),retained_onsets=len(chosen),fraction=rational(F(len(chosen),len(source_lead)))),
        thinned_onsets=dropped,states=len(packed),duration_ticks=total,seconds=rational(duration),
        native_quantization='rational half-up BIOS ticks; later backing state wins same tick',
        same_tick_backing_states=collisions,collapsed_backing_intervals=collapsed,
        volume_quantization='input 0..127 -> half-up 0..15 PSG level',
        lead_policy='required notes hit-owned; misses silent; uncharted notes automatically play on the elapsed clock; no source lead onsets dropped',
        lane_policy='(transposed MIDI pitch - 45) modulo 3',
        unsupported_policy='reject with location; no automatic repair or pitch clamping')
    if drum_index is not None:
        report.update(drums=dict(voice=drums,hits=len(drum_events),by_kind=by_kind,same_tick_collisions=drum_collisions,
            mapping='General MIDI percussion keys -> kick, snare, closed/open hat, crash, low/high tom on the noise channel',
            level='15 - quantized MML volume, added to each kit attenuation'))
        report['dropped_voices']=[v for v in report['dropped_voices'] if v!=drums]
    return blob,stable_json(report),stable_json(normalized)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--chart-policy',choices=('metrical','elapsed'),default='elapsed')
    p.add_argument('--lead',default='auto');p.add_argument('--parts',help='1-based comma voices, lead plus up to two backing')
    p.add_argument('--lead-policy',choices=('activity','melody'),default='activity')
    p.add_argument('--difficulty',choices=DIFFICULTIES,default='normal');p.add_argument('--gap-ms',type=int)
    p.add_argument('--octave',type=int,default=4);p.add_argument('--length',type=int,default=4)
    p.add_argument('--tempo',type=int,default=120);p.add_argument('--volume',type=int,default=100)
    p.add_argument('--title',help=f'song title shown in game (default: source file name), up to {TITLE_MAX} chars')
    p.add_argument('--drums',type=int,metavar='VOICE',help='1-based voice keyed as General MIDI percussion; plays on the noise channel (writes RBG5)')
    p.add_argument('--transpose',type=int,default=0);p.add_argument('--voice-transpose',action='append',default=[],metavar='VOICE:SEMITONES')
    args=p.parse_args();opts=vars(args).copy();source=opts.pop('source');out=opts.pop('output')
    try:
        opts['parts']=[int(x) for x in args.parts.split(',')] if args.parts else None
        shifts={}
        for value in args.voice_transpose:
            k,v=map(int,value.split(':'))
            if k in shifts:raise ScoreError('duplicate voice transpose setting')
            shifts[k]=v
        opts['voice_transpose']=shifts
        opts['title']=clean_title(args.title if args.title is not None else source.stem)
        if args.title is not None and opts['title']!=args.title.upper():
            print(f'Title normalized to {opts["title"]!r}')
        blob,report,normalized=convert(source.read_text(encoding='ascii'),**opts)
        # Validate everything before writing any output.
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(blob);out.with_suffix('.json').write_bytes(report)
        out.with_suffix('.events.json').write_bytes(normalized)
        info=json.loads(report);print(f'Lead source voice{info["lead_voice"]}; PSG parts{info["psg_voices"]}; {info["chart_taps"]} taps; dropped voices{info["dropped_voices"]}; SHA256 {info["score_sha256"]}')
    except (ScoreError,ValueError,UnicodeError) as exc:p.exit(2,f'Import rejected: {exc}\n')
if __name__=='__main__':main()
