"""Loss-audited MIDI arrangement sidecar -> RBG4/5. Standard library only.

MML is a tone editing companion. This sidecar is authoritative for measured
MIDI timing and percussion; importing the MML alone cannot preserve drums.
"""
import argparse, hashlib, json, struct
from fractions import Fraction as F
from pathlib import Path
from import_score import (MAX_LEAD, MAX_STATES, MAX_DRUMS, DIFFICULTIES,
                          DIFFICULTY_CODE, DRUM_KINDS, gm_drum, clean_title,
                          stable_json, beat_segments)
from mml import CLOCK, PITCH, ScoreError, rounded

SCHEMA='rave-midi-arrangement-v1'
# Cue skill priority, separately declared from the legacy MML drum importer.
PRIORITY=['kick','snare','crash','low_tom','high_tom','open_hat','closed_hat']

def integer(value, lo, hi, label):
    if type(value) is not int or not lo<=value<=hi:
        raise ScoreError(f'{label} must be an integer {lo}..{hi}')
    return value

def clock_seconds(tick, ppq, tempos):
    """Exact SMF tempo integration; default 500000 us/QN before first event."""
    tick=F(tick);prev=F(0);us=500000;seconds=F(0)
    for at,value in tempos:
        if at>tick:break
        seconds+=(F(at)-prev)*us/(ppq*1000000)
        prev=F(at);us=value
    return seconds+(tick-prev)*us/(ppq*1000000)

def validate(a):
    if not isinstance(a,dict) or a.get('schema')!=SCHEMA:raise ScoreError('unknown MIDI arrangement schema')
    ppq=integer(a.get('ppq'),1,32767,'PPQ')
    start=integer(a.get('start_tick'),0,0x7fffffff,'excerpt start')
    end=integer(a.get('end_tick'),start+1,0x7fffffff,'excerpt end')
    tempos=a.get('tempos');voices=a.get('voices');drums=a.get('drums')
    if not isinstance(tempos,list) or len(tempos)>4096:raise ScoreError('tempo map must contain at most 4096 events')
    last=-1
    for event in tempos:
        if not isinstance(event,list) or len(event)!=2:raise ScoreError('malformed tempo event')
        at=integer(event[0],0,0x7fffffff,'tempo tick');integer(event[1],1,0xffffff,'tempo microseconds')
        if at<=last:raise ScoreError('tempo ticks must increase strictly')
        last=at
    if not isinstance(voices,list) or not 1<=len(voices)<=3:raise ScoreError('requires 1..3 tone voices')
    for vi,voice in enumerate(voices):
        if not isinstance(voice,dict):raise ScoreError('malformed tone voice')
        integer(voice.get('volume'),0,127,'tone volume')
        integer(voice.get('shift'),-48,48,'tone transpose')
        runs=voice.get('runs')
        if not isinstance(runs,list) or len(runs)>50000:raise ScoreError('too many tone runs')
        prev=F(0)
        for run in runs:
            if not isinstance(run,list) or len(run)!=4:raise ScoreError('malformed tone run')
            _,pitch,cell,cells=run
            integer(cell,0,50000,'tone start cell');integer(cells,1,50000,'tone cells')
            if F(cell)<prev:raise ScoreError('overlapping tone runs')
            prev=F(cell+cells)
            if pitch is not None:
                integer(pitch,0,127,'source tone pitch')
                integer(pitch+voice['shift'],45,96,'transposed tone pitch')
    grid=integer(a.get('grid'),1,16,'grid')
    if grid not in (1,2,4,8,16):raise ScoreError('unsupported grid')
    if not isinstance(drums,list) or len(drums)>100000:raise ScoreError('drums must be a bounded event list')
    for i,d in enumerate(drums):
        if not isinstance(d,dict):raise ScoreError(f'malformed drum {i}')
        integer(d.get('tick'),start,end-1,f'drum {i} tick')
        integer(d.get('velocity'),1,127,f'drum {i} velocity')
        integer(d.get('key'),0,127,f'drum {i} key')
        integer(d.get('track'),0,255,f'drum {i} track')
        if gm_drum(d['key']) is None:raise ScoreError(f'drum {i}: unmapped GM key {d["key"]}; explicit mapping required')
    if a.get('difficulty') not in DIFFICULTIES:raise ScoreError('unknown difficulty')
    if not isinstance(a.get('title'),str) or clean_title(a['title'])!=a['title']:raise ScoreError('invalid title')
    override=a.get('tempo_override')
    if override is not None:integer(override,32,255,'tempo override')
    return ppq,start,end

def convert_arrangement(a):
    ppq,start,end=validate(a)
    tempos=a['tempos'];grid=a['grid'];override=a.get('tempo_override')
    origin=clock_seconds(start,ppq,tempos)
    def seconds(tick):
        if override is not None:return (F(tick)-start)*60/(ppq*override)
        return clock_seconds(tick,ppq,tempos)-origin
    duration=seconds(end)
    if not 0<duration<=600:raise ScoreError('MIDI excerpt exceeds 600 seconds')
    total=rounded(duration*CLOCK)
    notes=[]
    for vi,voice in enumerate(a['voices']):
        level=rounded(F(voice['volume']*15,127));ns=[]
        for _,p,cell,cells in voice['runs']:
            if p is None or not level:continue
            s=F(start)+F(cell*ppq,grid);e=s+F(cells*ppq,grid)
            if e>end:raise ScoreError('tone run extends beyond excerpt')
            ns.append(dict(start=seconds(s),end=seconds(e),note=p+voice['shift'],level=level))
        notes.append(ns)
    tempo_map=[(F(0),F(60_000_000,500000))]
    if override is not None:tempo_map=[(F(0),override)]
    else:
        for at,us in tempos:
            if at<=start:tempo_map[0]=(F(0),F(60_000_000,us))
            elif at<end:tempo_map.append((F(at-start,ppq),F(60_000_000,us)))
    policy=a.get('chart_policy','elapsed')
    if policy not in ('elapsed','metrical'):raise ScoreError('unknown chart policy')
    selected=None
    if policy=='metrical':
        from chart_policy import select_required,separate_lane_windows
        eligible=[rounded(n['end']*CLOCK)-rounded(n['start']*CLOCK)>3 for n in notes[0]] if a['difficulty'] in ('easy','normal') else None
        selected=select_required(notes[0],tempo_map,DIFFICULTIES[a['difficulty']],eligible)
        if eligible is not None:selected=separate_lane_windows(notes[0],selected,tempo_map,CLOCK,rounded)
        if not selected:raise ScoreError('no lead onset survives forgiving input windows; choose another lead or slower tempo')
    lead=[];last=None;required=0;gap=F(DIFFICULTIES[a['difficulty']],1000)
    for index,n in enumerate(notes[0]):
        tick=rounded(n['start']*CLOCK);off=rounded(n['end']*CLOCK)
        if off<=tick:raise ScoreError('lead interval collapses at BIOS resolution')
        auto=(index not in selected) if selected is not None else (last is not None and n['start']-last<gap)
        if not auto:last=n['start'];required+=1
        lead.append((tick,off,rounded(F(3579545,32*PITCH[n['note']-45])),
                     (n['note']-45)%3,15-n['level'],n['note'],int(auto)))
    if not 1<=len(lead)<=MAX_LEAD:raise ScoreError('lead count outside 1..2048; shorten excerpt, never drop it silently')
    if any(b[0]<a[1] for a,b in zip(lead,lead[1:])):raise ScoreError('lead overlaps after BIOS quantization')
    events={F(0):[],duration:[]};collapsed=[]
    for vi,ns in enumerate(notes[1:],1):
        for n in ns:
            events.setdefault(n['start'],[]).append((1,vi,n['note'],n['level']))
            events.setdefault(n['end'],[]).append((0,vi,0,0))
            if rounded(n['end']*CLOCK)<=rounded(n['start']*CLOCK):collapsed.append(dict(voice=vi+1,start=str(n['start'])))
    ds=[0,0,0];ats=[15,15,15];states=[];back_collisions=[]
    for at,ev in sorted(events.items()):
        for on,k,n,v in sorted(ev):
            ds[k]=rounded(F(3579545,32*PITCH[n-45])) if n and v else 0
            ats[k]=15-v if ds[k] else 15
        row=(rounded(at*CLOCK),*ds,*ats)
        if states and states[-1][0]==row[0]:back_collisions.append(dict(tick=row[0],kept_seconds=str(at)));states[-1]=row
        else:states.append(row)
    if not 2<=len(states)<=MAX_STATES:raise ScoreError('backing states outside 2..4096')
    segments=beat_segments(tempo_map,duration)
    grouped={};source=[]
    for i,d in enumerate(a['drums']):
        measured=clock_seconds(d['tick'],ppq,tempos)-origin
        at=seconds(d['tick']);tick=rounded(at*CLOCK)
        kind=gm_drum(d['key']);att=15-rounded(F(d['velocity']*15,127))
        row=dict(d,source_index=i,source_seconds=str(measured),playback_seconds=str(at),
                 native_tick=tick,kind=kind,attenuation=att,
                 quantization_seconds=str(F(tick)/CLOCK-at))
        source.append(row);grouped.setdefault(tick,[]).append(row)
    winners=[];collisions=[]
    for tick,rows in sorted(grouped.items()):
        win=min(rows,key=lambda r:(PRIORITY.index(r['kind']),r['attenuation'],r['track'],r['source_index']))
        winners.append(win)
        for row in rows:
            if row is not win:collisions.append(dict(tick=tick,kept_source=win['source_index'],dropped_source=row['source_index'],
                                                    kept=win['kind'],dropped=row['kind']))
    if len(winners)>MAX_DRUMS:raise ScoreError('more than 4096 noise hits; shorten excerpt')
    old_total=total
    if winners and winners[-1]['native_tick']>=total:
        total=winners[-1]['native_tick']+1
        if total>10924:raise ScoreError('drum tail exceeds native duration limit')
        states.append((total,0,0,0,15,15,15))
        if len(states)>MAX_STATES:raise ScoreError('drum tail exceeds state bound')
    version=5 if winners else 4
    blob=struct.pack('<4sHHHHHBx24s',b'RBG%d'%version,version,total,len(states),len(lead),
                     len(segments),DIFFICULTY_CODE[a['difficulty']],a['title'].encode('ascii'))
    if winners:blob+=struct.pack('<HH',len(winners),0)
    blob+=b''.join(struct.pack('<4H3Bx',*s) for s in states)
    blob+=b''.join(struct.pack('<3H4B',*n) for n in lead)
    blob+=b''.join(struct.pack('<LLHH',start,period,first,count) for first,start,period,count in segments)
    blob+=b''.join(struct.pack('<HBB',w['native_tick'],DRUM_KINDS.index(w['kind']),w['attenuation']) for w in winners)
    report=dict(schema='rave-midi-import-report-v1',title=a['title'],score_sha256=hashlib.sha256(blob).hexdigest(),
                lead_events=len(lead),chart_taps=required,automatic_lead_events=len(lead)-required,
                states=len(states),seconds=str(duration),duration_ticks=total,beat_segments=len(segments),
                native_tail_extension_ticks=total-old_total,
                source=a.get('source'),tone_reductions=a.get('tone_reductions'),
                ignored_midi_events=a.get('ignored_midi_events'),
                tone_velocity_policy='Chosen fixed per-voice volume; original tone velocities not synthesized',
                chart_policy=policy,tempo_override=override,collapsed_backing_intervals=collapsed,same_tick_backing_states=back_collisions,
                drums=dict(source_hits=len(source),hits=len(winners),priority=PRIORITY,
                           same_tick_collisions=collisions,events=source,kept_source_indices=[w['source_index'] for w in winners],
                           mapping='Existing RBG5 seven-kind noise kit; velocity 1..127 -> attenuation 15..0',
                           unmapped_policy='Reject; no silent loss'))
    normalized=dict(schema='normalized-midi-arrangement-v1',duration_seconds=str(F(total)/CLOCK),source_duration_seconds=str(duration),
                    voices=[[dict(n,start=str(n['start']),end=str(n['end'])) for n in ns] for ns in notes],
                    drums=source)
    return blob,stable_json(report),stable_json(normalized)

def decode_score(blob):
    """Inspect the actual delivered bytes, including the complete drum payload."""
    if len(blob)<40:raise ScoreError('truncated native header')
    magic,version,total,ns,nl,nb,difficulty,title=struct.unpack_from('<4sHHHHHBx24s',blob)
    if version not in (4,5) or magic!=b'RBG%d'%version:raise ScoreError('unsupported native format')
    offset=40;nd=0
    if version==5:
        if len(blob)<44:raise ScoreError('truncated drum header')
        nd,reserved=struct.unpack_from('<HH',blob,offset);offset+=4
        if reserved:raise ScoreError('reserved native drum header must be zero')
    if len(blob)!=offset+ns*12+nl*10+nb*12+nd*4:raise ScoreError('native payload length mismatch')
    def rows(count,fmt):
        nonlocal offset
        size=struct.calcsize(fmt);result=[struct.unpack_from(fmt,blob,offset+i*size) for i in range(count)]
        offset+=count*size;return result
    result=dict(version=version,total=total,states=rows(ns,'<4H3Bx'),lead=rows(nl,'<3H4B'),
                beats=rows(nb,'<LLHH'),drums=rows(nd,'<HBB'))
    if not 2<=ns<=MAX_STATES or not 1<=nl<=MAX_LEAD or nd>MAX_DRUMS:raise ScoreError('native counts outside bounds')
    if any(t>=total or k>=len(DRUM_KINDS) or v>15 for t,k,v in result['drums']):raise ScoreError('invalid native drum event')
    if any(b[0]<=a[0] for a,b in zip(result['drums'],result['drums'][1:])):raise ScoreError('native drums must increase')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args()
    try:
        if a.source.resolve()==a.output.resolve():raise ScoreError('input and output must differ')
        if a.source.stat().st_size>16*1024*1024:raise ScoreError('sidecar exceeds 16 MiB')
        blob,report,events=convert_arrangement(json.loads(a.source.read_text()))
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_bytes(blob);a.output.with_suffix('.json').write_bytes(report);a.output.with_suffix('.events.json').write_bytes(events)
        print('PASS: measured tones and percussion imported; '+hashlib.sha256(blob).hexdigest())
    except (OSError,ValueError,TypeError,KeyError,ScoreError) as exc:p.exit(2,f'Import rejected: {exc}\n')
if __name__=='__main__':main()
