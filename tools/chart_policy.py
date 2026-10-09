"""Offline metrical thinning. Select source onsets; never shift or erase audio."""
from bisect import bisect_right
from fractions import Fraction as F

def seconds_to_beat(tempo_map,seconds):
    prev=F(0);elapsed=F(0);bpm=tempo_map[0][1]
    for beat,value in tempo_map:
        end=elapsed+(beat-prev)*60/bpm
        if seconds<end:return prev+(seconds-elapsed)*bpm/60
        prev=beat;elapsed=end;bpm=value
    return prev+(seconds-elapsed)*bpm/60

def select_required(notes,tempo_map,gap_ms,eligible=None):
    if gap_ms==0:return set(range(len(notes)))
    starts=[n['start'] for n in notes];gap=F(gap_ms,1000)
    # Maximum-weight independent set with explicit elapsed-time density bound.
    # Quarter onsets outrank nearby offbeats; duration is only a tie-break bonus.
    weights=[]
    for i,n in enumerate(notes):
        beat=seconds_to_beat(tempo_map,n['start'])
        strength=8 if beat.denominator==1 else 3 if (beat*2).denominator==1 else 1
        sustain=min(F(1),n['end']-n['start'])
        weights.append(F(strength)+sustain if eligible is None or eligible[i] else F(0))
    best=[F(0)];take=[];pre=[]
    for i,n in enumerate(notes):
        j=bisect_right(starts,n['start']-gap,0,i)
        score=best[j]+weights[i]
        yes=score>best[-1]  # equality keeps earlier stable selection
        best.append(score if yes else best[-1]);take.append(yes);pre.append(j)
    result=set();i=len(notes)
    while i:
        if take[i-1]:result.add(i-1);i=pre[i-1]
        else:i-=1
    return result


def separate_lane_windows(notes, selected, tempo_map, clock, rounded, window=3):
    """Thin required inputs only; disjoint same-lane windows prevent stealing.
    Keep metrical priority within the already elapsed-density-bounded subset.
    """
    result=set()
    for lane in range(3):
        indices=sorted(i for i in selected if (notes[i]['note']-45)%3==lane)
        ticks=[rounded(notes[i]['start']*clock) for i in indices]
        best=[F(0)];take=[];pre=[]
        for pos,i in enumerate(indices):
            n=notes[i];beat=seconds_to_beat(tempo_map,n['start'])
            weight=F(8 if beat.denominator==1 else 3 if (beat*2).denominator==1 else 1)+min(F(1),n['end']-n['start'])
            j=bisect_right(ticks,ticks[pos]-2*window-1,0,pos)
            value=best[j]+weight;yes=value>best[-1]
            best.append(value if yes else best[-1]);take.append(yes);pre.append(j)
        pos=len(indices)
        while pos:
            if take[pos-1]:result.add(indices[pos-1]);pos=pre[pos-1]
            else:pos-=1
    return result
