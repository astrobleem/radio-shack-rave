"""Convert an image you own (or have rights to use) into an RSPL splash bitmap.

The game shows LOGO.BIN, if it is present beside RSRAVE.EXE, before the
attract sequence. Nothing is bundled: run this on your own artwork.

    python tools/make_splash.py logo.png runtime/LOGO.BIN --key-white --preview logo_preview.png

RSPL: 'RSPL', u16 width, height, x, y, then height rows of width/2 bytes,
two Tandy 16-color pixels per byte, left pixel in the high nibble.
Requires Pillow.
"""
import argparse,struct
from pathlib import Path
from PIL import Image

PAL=[(0,0,0),(0,0,170),(0,170,0),(0,170,170),(170,0,0),(170,0,170),(170,85,0),(170,170,170),
     (85,85,85),(85,85,255),(85,255,85),(85,255,255),(255,85,85),(255,85,255),(255,255,85),(255,255,255)]
# Tandy 320x200 pixels are about 1.2 times taller than wide on a 4:3 screen.
PIXEL_ASPECT=1.2
BAYER=[[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]]

def key_white(rgb):
    """Treat the image as ink on white paper and lift it onto black."""
    r,g,b=rgb;a=1-min(r,g,b)/255
    if a<=0.02:return (0,0,0)
    un=[(c-(1-a)*255)/a for c in rgb]
    return tuple(max(0,min(255,round(c*a))) for c in un)

def nearest(rgb):
    return min(range(16),key=lambda i:sum((p-q)**2 for p,q in zip(PAL[i],rgb)))

def convert(img,max_w=304,max_h=180,x=None,y=None,keyed=False,dither=False,trim=True):
    img=img.convert('RGB')
    if trim:
        from PIL import ImageChops
        bg=Image.new('RGB',img.size,img.getpixel((0,0)))
        box=ImageChops.difference(img,bg).convert('L').point(lambda v:255 if v>12 else 0).getbbox()
        if box:img=img.crop(box)
    w,h=img.size
    scale=min(max_w/w,max_h*PIXEL_ASPECT/h)
    tw=max(2,int(w*scale)//2*2);th=max(1,min(max_h,round(h*scale/PIXEL_ASPECT)))
    img=img.resize((tw,th),Image.LANCZOS)
    if x is None:x=(320-tw)//2//2*2
    if y is None:y=(200-th)//2
    if x%2 or tw%2 or x+tw>320 or y+th>200:raise SystemExit('placement outside the 320x200 screen or not even')
    px=img.load();idx=[]
    for j in range(th):
        for i in range(tw):
            c=px[i,j]
            if keyed:c=key_white(c)
            if dither:
                t=(BAYER[j%4][i%4]/16-0.5)*48
                c=tuple(max(0,min(255,round(v+t))) for v in c)
            idx.append(nearest(c))
    rows=bytearray()
    for j in range(th):
        r=idx[j*tw:(j+1)*tw]
        rows+=bytes((r[i]<<4)|r[i+1] for i in range(0,tw,2))
    return struct.pack('<4sHHHH',b'RSPL',tw,th,x,y)+bytes(rows),(tw,th,x,y,idx)

def preview(info,path,scale=3):
    tw,th,x,y,idx=info
    im=Image.new('P',(320,200),0);im.putpalette([v for c in PAL for v in c])
    for j in range(th):
        for i in range(tw):im.putpixel((x+i,y+j),idx[j*tw+i])
    im.resize((320*scale,int(200*scale*PIXEL_ASPECT)),Image.NEAREST).save(path)

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('image',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--max-width',type=int,default=304);p.add_argument('--max-height',type=int,default=180)
    p.add_argument('--x',type=int);p.add_argument('--y',type=int)
    p.add_argument('--key-white',action='store_true',help='artwork on white: make white the black background')
    p.add_argument('--dither',action='store_true',help='ordered dither for photos and gradients')
    p.add_argument('--no-trim',action='store_true',help='keep blank margins')
    p.add_argument('--preview',type=Path,help='also write an aspect-corrected PNG preview')
    a=p.parse_args()
    blob,info=convert(Image.open(a.image),a.max_width,a.max_height,a.x,a.y,a.key_white,a.dither,not a.no_trim)
    a.output.write_bytes(blob)
    if a.preview:preview(info,a.preview)
    print(f'{a.output}: {info[0]}x{info[1]} at ({info[2]},{info[3]}), {len(blob)} bytes')
if __name__=='__main__':main()
