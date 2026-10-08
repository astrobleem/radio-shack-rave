"""Bounded offline ArcheAge MML -> PSG states and selected onset chart.

Python 3 only; no runtime parser or copyrighted song is shipped in the DOS kit.
"""
import argparse
from fractions import Fraction as F
import json
from pathlib import Path
import re
import struct

PPQN = 96
CLOCK = F(1193182, 65536)
PITCH = [110,117,123,131,139,147,156,165,175,185,196,208,220,233,
         247,262,277,294,311,330,349,370,392,415,440,466,494,523,
         554,587,622,659,698,740,784,831,880,932,988,1047,1109,
         1175,1245,1319,1397,1480,1568,1661,1760,1865,1976,2093]

class ScoreError(ValueError):
    pass

def rounded(value):
    return (value.numerator * 2 + value.denominator) // (2 * value.denominator)

def parse(text, octave=4, length=4, tempo=120, volume=100, transpose=0,
          max_voices=3, parts_only=False):
    if len(text.encode('ascii', errors='replace')) > 8192:
        raise ScoreError('source exceeds 8192 bytes')
    if not text.isascii():
        raise ScoreError('ASCII source required')
    original = text
    # Keep positions stable for diagnostics, including optional wrapper.
    m = re.match(r'\s*MML@', text, re.I)
    if m:
        text = ' ' * m.end() + text[m.end():]
        end = text.rstrip()
        if not end.endswith(';'):
            raise ScoreError('MML@ wrapper needs final semicolon')
        pos = len(end)-1
        text = text[:pos]+' '+text[pos+1:]
    if not 0 <= octave <= 8 or length not in (1,2,4,8,16,32,64):
        raise ScoreError('invalid explicit default octave/length')
    if not 32 <= tempo <= 255 or not 0 <= volume <= 127:
        raise ScoreError('invalid explicit default tempo/volume')
    voices, tempos = [], []
    offset = 0
    for vi, part in enumerate(text.split(',')):
        if vi >= max_voices:
            raise ScoreError(f'at most {max_voices} comma voices in this profile')
        beat = F(0)
        o, l, v, i = octave, length, volume, 0
        notes, tm, tie = [], {}, False
        def fail(msg, at=None):
            p = offset + (i if at is None else at)
            line = original.count('\n',0,p)+1
            col = p-original.rfind('\n',0,p)
            raise ScoreError(f'voice {vi+1}, line {line}, column {col}: {msg}')
        def number(required=False):
            nonlocal i
            start=i
            while i<len(part) and part[i].isdigit(): i+=1
            if required and i==start: fail('integer required')
            if i-start>6:fail('integer token exceeds six digits',start)
            return int(part[start:i]) if i>start else None
        while i < len(part):
            ch=part[i].lower()
            if ch.isspace(): i+=1; continue
            start=i; i+=1
            if ch in 'oltv':
                if tie: fail('command inside tie',start)
                n=number(True)
                if ch=='o':
                    if not 0<=n<=8: fail('octave outside 0..8',start)
                    o=n
                elif ch=='l':
                    if n not in (1,2,4,8,16,32,64): fail('length must be power of two 1..64',start)
                    l=n
                elif ch=='v':
                    if not 0<=n<=127: fail('volume outside 0..127',start)
                    v=n
                else:
                    if not 32<=n<=255: fail('tempo outside 32..255',start)
                    if beat in tm and tm[beat]!=n: fail('conflicting tempo at same beat',start)
                    tm[beat]=n
            elif ch in '<>':
                if tie: fail('octave command inside tie',start)
                o += 1 if ch=='>' else -1
                if not 0<=o<=8: fail('octave shift outside 0..8',start)
            elif ch=='&':
                if tie or not notes or notes[-1]['note']==0: fail('tie needs preceding sounding note',start)
                tie=True
            elif ch in 'abcdefgr':
                note=0 if ch=='r' else (o+1)*12+{'c':0,'d':2,'e':4,'f':5,'g':7,'a':9,'b':11}[ch]
                if i<len(part) and part[i] in '+#-':
                    if not note: fail('rest accidental',start)
                    note += -1 if part[i]=='-' else 1; i+=1
                n=number()
                if n is None: n=l
                if n not in (1,2,4,8,16,32,64): fail('unsupported duration',start)
                duration=F(4,n); extra=duration
                dots=0
                while i<len(part) and part[i]=='.':
                    i+=1; dots+=1; extra/=2; duration+=extra
                    if dots>3: fail('at most three dots',start)
                if note:
                    before=note; note+=transpose
                    if parts_only:
                        if not 1<=note<=127: fail('normalized pitch outside MIDI1..127',start)
                    elif not 45<=note<=96: fail(f'pitch {before} -> {note} outside MIDI45..96; choose transposition, never clamped',start)
                level=rounded(F(v*15,127)) if note else 0
                if tie:
                    prior=notes[-1]
                    if prior['note']!=note or prior['volume']!=level: fail('tie must keep pitch and level',start)
                    prior['end']+=duration; tie=False
                else:
                    notes.append(dict(start=beat,end=beat+duration,note=note,volume=level))
                beat+=duration
                if len(notes)>4096: fail('voice exceeds 4096 notes/rests',start)
            else:
                fail(f'unsupported syntax {part[start]!r}',start)
        if tie: fail('unfinished tie')
        voices.append(notes); tempos.append(tm); offset+=len(part)+1
    # Declared tempo maps must agree. Omitted maps inherit the common map.
    declared=[t for t in tempos if t]
    if declared and any(t!=declared[0] for t in declared):
        raise ScoreError('conflicting voice tempo maps; align all explicit tempo changes')
    common=dict(declared[0]) if declared else {}
    common.setdefault(F(0),tempo)
    def seconds(beat):
        total=F(0); prev=F(0); bpm=tempo
        for at,value in sorted(common.items()):
            if at>beat: break
            total+=(at-prev)*60/bpm; prev=at; bpm=value
        return total+(beat-prev)*60/bpm
    endbeat=max((n['end'] for ns in voices for n in ns),default=F(0))
    duration=seconds(endbeat)
    if not 0<duration<=600: raise ScoreError('score duration must be 0..600 seconds')
    if parts_only:
        normalized=[]
        for ns in voices:
            normalized.append([dict(start=seconds(n['start']),end=seconds(n['end']),
                note=n['note'],volume=n['volume']) for n in ns])
        event_times={F(0),duration}
        for ns in normalized:
            for n in ns:event_times.update((n['start'],n['end']))
        if len(event_times)>10000:raise ScoreError('more than 10000 normalized event times')
        return normalized,sorted(common.items()),duration
    events={F(0):[],duration:[]}
    attacks=[]
    for vi,ns in enumerate(voices):
        for n in ns:
            a,b=seconds(n['start']),seconds(n['end'])
            events.setdefault(a,[]).append((1,vi,n['note'] if n['volume'] else 0,n['volume']))
            events.setdefault(b,[]).append((0,vi,0,0))
            if n['note'] and n['volume']: attacks.append((a,vi,n['note']))
    state=[0]*3; vols=[0]*3; states=[]
    for at,ev in sorted(events.items()):
        mask=0
        for on,vi,note,vol in sorted(ev):
            state[vi]=note; vols[vi]=vol
            if on and note and vol: mask|=1<<vi
        states.append((at,tuple(state),tuple(vols),mask))
    if len(states)>10000: raise ScoreError('more than 10000 interchange states')
    return states, sorted(attacks), duration


