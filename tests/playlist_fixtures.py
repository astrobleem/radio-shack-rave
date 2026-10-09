"""Original synthetic charts only; no imported song material."""
from pathlib import Path
import struct,shutil

def chart(title,version=4,end=240):
    taps=[struct.pack('<3H4B',t,t+5,200,t//10%3,3,69,0)
          for t in range(10,end-10,10)]
    if not taps:taps=[struct.pack('<3H4B',4,9,200,0,3,69,0)]
    states=[struct.pack('<4H4B',0,0,300,400,15,3,4,0),
            struct.pack('<4H4B',end,0,0,0,15,15,15,0)]
    header=struct.pack('<4s4H',f'RBG{version}'.encode(),version,end,2,len(taps))
    if version==4:header+=struct.pack('<HBB24s',0,1,0,title.encode())
    return header+b''.join(states)+b''.join(taps)

def populate(root,runtime):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    shutil.copy2(runtime,root/'RSRAVE.EXE')
    (root/'LONG.RBG').write_bytes(chart('LONG'))
    for folder in ['EMPTY','INVALID','MIX','MANY','DEMO']:
        songs=root/folder/'SONGS';songs.mkdir(parents=True,exist_ok=True)
        (songs.parent/'ORIGINAL.RBG').write_bytes(chart('ORIGINAL',end=18))
    for folder in ['MIX','DEMO']:
        songs=root/folder/'SONGS'
        for v in [2,3,4]:(songs/f'VER{v}.RBG').write_bytes(chart(f'VERSION {v}',v,18))
        for name,data in [('EMPTY',b''),('SHORT',b'RBG4'),('BAD',b'garbage')]:
            (songs/(name+'.RBG')).write_bytes(data)
        (songs/'DIR.RBG').mkdir()
    for name,data in [('EMPTY',b''),('SHORT',b'RBG4'),('BAD',b'garbage')]:
        (root/'INVALID/SONGS'/(name+'.RBG')).write_bytes(data)
    for i in range(70):(root/'MANY/SONGS'/f'S{i:04}.RBG').write_bytes(chart('MANY',end=18))
