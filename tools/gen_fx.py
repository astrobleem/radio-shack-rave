"""Generate src/FXDATA.H: precomputed images for the left-panel effects.

The 8088 never evaluates a sine, a square root or an arctangent for these.
Each palette-cycled scene is a 96x100 map of cycle phases 0..3 (two bits a
pixel, ordered-dithered between phases so motion looks continuous) plus a
short list of static runs (solid or two-color dithered) drawn over it. The
game expands a map into the window when the scene starts, then animates it
by rewriting four Tandy palette registers.

Also generated: the 32x32 rotozoom texture, a 256-entry sine table and each
scene's eight-entry color gradient.

    python tools/gen_fx.py               # rewrite src/FXDATA.H
    python tools/gen_fx.py --check       # exit 1 if src/FXDATA.H is stale
    python tools/gen_fx.py --preview DIR # also write PNG previews (Pillow)
"""
import argparse, math, sys
from pathlib import Path

W, H = 96, 100
CX, CY = 48, 50
TAU = 2 * math.pi
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
FONT = {  # 5x7, same faces as the game font
    'R': [30, 17, 17, 30, 20, 18, 17], 'A': [14, 17, 17, 31, 17, 17, 17],
    'V': [17, 17, 17, 17, 17, 10, 4], 'E': [31, 16, 16, 30, 16, 16, 31],
    'D': [30, 17, 17, 17, 17, 17, 30], 'J': [7, 2, 2, 2, 2, 18, 12],
    'L': [16, 16, 16, 16, 16, 16, 31], 'F': [31, 16, 16, 30, 16, 16, 16],
    'O': [14, 17, 17, 17, 17, 17, 14], 'M': [17, 27, 21, 21, 17, 17, 17],
    'S': [15, 16, 16, 14, 1, 1, 30], 'B': [30, 17, 17, 30, 17, 17, 30], ' ': [0] * 7}


def q(v):
    """Round to a fixed grid first so platform libm differences in the last
    bits cannot move a threshold."""
    return round(v * 4096) / 4096


def phase_map(f):
    """f(x, y) -> continuous phase (any real) or None for 'covered by runs'."""
    m = [[0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            p = f(x, y)
            if p is None:
                continue
            p = q(p) + (BAYER[y & 3][x & 3] + 0.5) / 16.0
            m[y][x] = int(math.floor(p)) & 3
    return m


def polar(x, y):
    dx, dy = x - CX + 0.5, y - CY + 0.5
    return math.hypot(dx, dy), math.atan2(dy, dx)


class Runs:
    """Static overlay: (y, x, length, a, b); a==b solid, else (x+y)&1 dither."""
    def __init__(self):
        self.px = {}

    def set(self, x, y, c, c2=None):
        if 0 <= x < W and 0 <= y < H:
            self.px[(x, y)] = (c, c if c2 is None else c2)

    def rows(self):
        out = []
        for y in range(H):
            xs = sorted(x for (x, yy) in self.px if yy == y)
            i = 0
            while i < len(xs):
                x0 = xs[i]; ab = self.px[(x0, y)]; n = 1
                while i + n < len(xs) and xs[i + n] == x0 + n and self.px[(x0 + n, y)] == ab:
                    n += 1
                out.append((y, x0, n, ab[0], ab[1]))
                i += n
        return out


def text_runs(runs, s, x0, y0, scale, face, edge):
    pts = set()
    for i, ch in enumerate(s):
        for r, bits in enumerate(FONT[ch]):
            for c in range(5):
                if bits & (16 >> c):
                    for a in range(scale):
                        for b in range(scale):
                            pts.add((x0 + i * 6 * scale + c * scale + b, y0 + r * scale + a))
    for (x, y) in pts:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1, 2):
                if (x + dx, y + dy) not in pts:
                    runs.set(x + dx, y + dy, edge)
    for (x, y) in pts:
        band = (y - y0) * 4 // (7 * scale)
        runs.set(x, y, face[min(band, len(face) - 1)])


# ---------------------------------------------------------------- scenes
def plasma():
    def f(x, y):
        r = math.hypot(x - CX, y - CY)
        v = (math.sin(x / 9.0) + math.sin(y / 7.0 + 1.0) + math.sin((x + y) / 11.0)
             + math.sin(r / 6.0))
        return (v + 4) * 1.1
    return phase_map(f), Runs()


def starburst():
    def f(x, y):
        r, a = polar(x, y)
        return a / TAU * 8 * 4 + r / 7.0
    runs = Runs()
    for y in range(H):
        for x in range(W):
            r, _ = polar(x, y)
            if r < 4.5:
                runs.set(x, y, 15)
            elif r < 7:
                runs.set(x, y, 14, 15)
    return phase_map(f), runs


def tunnel():
    def f(x, y):
        r, a = polar(x, y)
        return 300.0 / (r + 2.0) + a / TAU * 4 * 2
    runs = Runs()
    for y in range(H):
        for x in range(W):
            r, _ = polar(x, y)
            if r < 6:
                runs.set(x, y, 0)
            elif r < 10:
                runs.set(x, y, 0, 1)
    return phase_map(f), runs


def copper():
    def f(x, y):
        return y / 6.0 + 1.5 * math.sin(x / 10.0 + y / 25.0)
    runs = Runs()
    text_runs(runs, 'RAVE', 14, 39, 3, [15, 15, 11, 11], 0)
    return phase_map(f), runs


FLAG_SKY = None


def flag_sky():
    def f(x, y):
        return y / 10.0 + 0.8 * math.sin(x / 15.0)
    runs = Runs()
    for y in range(18, H):
        runs.set(10, y, 15)
        runs.set(11, y, 8)
        runs.set(12, y, 8)
    for y in range(13, 19):
        for x in range(8, 15):
            if (x - 11) ** 2 + (y - 15.5) ** 2 <= 9:
                runs.set(x, y, 14 if y < 16 else 6)
    for y in range(92, H):
        for x in range(W):
            runs.set(x, y, 2, 0)
    return phase_map(f), runs


def floor_grid():
    hz = 38

    def f(x, y):
        # Above hz+12 one pixel row spans more than a quarter cell and the
        # moving lines would alias into noise; those rows are static fog.
        if y <= hz + 12:
            return None
        z = 380.0 / (y - hz)
        return 4 * (z / 12.0)
    runs = Runs()
    for y in range(hz):
        for x in range(W):
            t = y / hz
            if t > 0.7:
                runs.set(x, y, 1, 5)
            elif t > 0.4:
                runs.set(x, y, 1, 0)
            else:
                runs.set(x, y, 0)
    seed = 12345
    for _ in range(26):
        seed = (seed * 1103515245 + 12345) & 0x7fffffff
        sx = seed % W
        seed = (seed * 1103515245 + 12345) & 0x7fffffff
        sy = seed % 24
        runs.set(sx, sy, 15 if seed & 1 else 8)
    for y in range(hz - 22, hz):
        for x in range(W):
            d = math.hypot(x - CX + 0.5, (y - hz + 0.5) * 1.2)
            if d <= 22:
                k = hz - y
                if k < 12 and (k % 4) == 0:
                    continue
                runs.set(x, y, 14 if k > 15 else (12 if k > 7 else 13))
    for x in range(W):
        runs.set(x, hz, 13)
    for y in range(hz + 1, hz + 13):
        for x in range(W):
            if y < hz + 4:
                runs.set(x, y, 5, 0)
            elif y < hz + 8:
                runs.set(x, y, 5 if (x + y) % 4 == 0 else 0)
            else:
                runs.set(x, y, 0)
    for y in range(hz + 1, H):
        z = 380.0 / (y - hz)
        for x in range(W):
            a = math.floor((x - CX) * z / 40.0 / 12.0)
            b = math.floor((x + 1 - CX) * z / 40.0 / 12.0)
            if a != b:
                runs.set(x, y, 13 if y > hz + 12 else 5)
    return phase_map(f), runs


DJ_BOOTH = 70


def dj():
    """DJ Alfredo's club: sweeping spotlights, pulsing speaker cones and
    spinning platters are all cycle phases; the booth and lettering are
    static. Alfredo himself is drawn live by the game."""
    def f(x, y):
        for (sx, sy) in ((8, 60), (8, 80), (87, 60), (87, 80)):
            r = math.hypot(x - sx, y - sy)
            if r < 6.5:
                return r * 0.9
        for px_ in (30, 66):
            dx, dy = (x - px_) / 9.0, (y - 67) / 2.6
            if dx * dx + dy * dy <= 1.0:
                return math.atan2(dy, dx) / TAU * 4 * 3
        a = math.atan2(y + 10.0, x - 48.0)
        return a / math.pi * 7 * 4 + y / 30.0
    runs = Runs()
    for y in range(H):
        for x in range(W):
            if (x < 2 or x > 93 or y < 50 or y > 89) and (x < 15 or x > 80):
                continue
            if (2 <= x <= 13 or 82 <= x <= 93) and 50 <= y <= 89:
                cx = 8 if x < 48 else 87
                if all(math.hypot(x - cx, y - cy) >= 6.5 for cy in (60, 80)):
                    edge = x in (2, 13, 82, 93) or y in (50, 89)
                    runs.set(x, y, 8 if edge else 0, 8 if edge else 1)
    for y in range(DJ_BOOTH, 92):
        for x in range(16, 80):
            if any(((x - px_) / 9.0) ** 2 + ((y - 67) / 2.6) ** 2 <= 1.0 for px_ in (30, 66)):
                continue
            if y == DJ_BOOTH:
                runs.set(x, y, 15)
            elif x in (16, 79) or y == 91:
                runs.set(x, y, 8)
            else:
                runs.set(x, y, 1, 0)
    for px_ in (30, 66):
        for y in range(63, 72):
            for x in range(px_ - 10, px_ + 11):
                d = ((x - px_) / 9.0) ** 2 + ((y - 67) / 2.6) ** 2
                if 1.0 < d <= 1.45:
                    runs.set(x, y, 8)
                elif d <= 0.08:
                    runs.set(x, y, 15)
    text_runs(runs, 'MOS LABS', 25, 78, 1, [14, 14, 6, 6], 1)
    for y in range(92, H):
        for x in range(W):
            runs.set(x, y, 5, 0)
    text_runs(runs, 'DJ ALFREDO', 19, 2, 1, [15, 15, 11, 11], 0)
    return phase_map(f), runs


# name, builder, gradient (physical colors), cycle steps per beat, kind
SCENES = [
    ('DJ ALFREDO', dj, [0, 0, 1, 5, 13, 5, 1, 0], 8, 'alfredo'),
    ('PLASMA', plasma, [1, 9, 11, 15, 14, 12, 13, 5], 8, 'none'),
    ('STARBURST', starburst, [0, 4, 12, 14, 15, 14, 12, 4], 8, 'cube'),
    ('TUNNEL', tunnel, [0, 1, 9, 11, 15, 11, 9, 1], 8, 'stars'),
    ('ROTOZOOM', None, [5, 13, 15, 13, 5, 1, 0, 1], 4, 'rotozoom'),
    ('COPPER', copper, [0, 5, 13, 15, 13, 5, 0, 0], 8, 'none'),
    ('FLAG', flag_sky, [0, 1, 1, 9, 9, 1, 1, 0], 4, 'flag'),
    ('GRID', floor_grid, [13, 13, 0, 0, 0, 0, 0, 0], 8, 'none'),
]
KINDS = ['none', 'cube', 'stars', 'rotozoom', 'flag', 'alfredo']


def texture():
    """32x32 rotozoom tile; phase indices 0..3 are written as cycle colors
    by the game (stored here as 16..19), statics as 0..15."""
    t = []
    for y in range(32):
        for x in range(32):
            c = 16 if ((x >> 3) ^ (y >> 3)) & 1 else 18
            d = math.hypot(x - 15.5, y - 15.5)
            if 10.0 <= d < 13.0:
                c = 15
            elif 13.0 <= d < 14.5:
                c = 0
            elif d < 4.0:
                c = 14
            elif d < 6.0:
                c = 0
            t.append(c)
    return t


def pack(m):
    out = []
    for y in range(H):
        for x in range(0, W, 4):
            out.append((m[y][x] << 6) | (m[y][x + 1] << 4) | (m[y][x + 2] << 2) | m[y][x + 3])
    return out


def c_bytes(name, data, far=True, per=24):
    lines = [f'static const unsigned char {"far " if far else ""}{name}[{len(data)}]={{']
    for i in range(0, len(data), per):
        lines.append(','.join(str(v) for v in data[i:i + per]) + (',' if i + per < len(data) else ''))
    lines.append('};')
    return '\n'.join(lines)


def build():
    parts = ['/* Generated by tools/gen_fx.py. Do not edit; regenerate. */',
             '#define FX_W %d' % W, '#define FX_H %d' % H, '#define FX_SCENES %d' % len(SCENES)]
    for i, k in enumerate(KINDS):
        parts.append('#define FXK_%s %d' % (k.upper(), i))
    maps, runs_all, run_off = [], [], []
    for name, fn, grad, speed, kind in SCENES:
        if fn is None:
            maps.append(None); run_off.append(len(runs_all)); runs_all.append(255)
            continue
        m, runs = fn()
        maps.append(pack(m))
        run_off.append(len(runs_all))
        for (y, x, n, a, b) in runs.rows():
            runs_all += [y, x, n, (a << 4) | b]
        runs_all.append(255)
    for i, data in enumerate(maps):
        if data is not None:
            parts.append(c_bytes('fx_map%d' % i, data))
    parts.append(c_bytes('fx_runs', runs_all))
    parts.append('static const unsigned char far *const fx_maps[FX_SCENES]={%s};' %
                 ','.join('fx_map%d' % i if d is not None else '0' for i, d in enumerate(maps)))
    parts.append('static const unsigned fx_run_off[FX_SCENES]={%s};' % ','.join(map(str, run_off)))
    parts.append('static const unsigned char fx_grad[FX_SCENES][8]={%s};' %
                 ','.join('{%s}' % ','.join(map(str, g)) for _, _, g, _, _ in SCENES))
    parts.append('static const unsigned char fx_speed[FX_SCENES]={%s};' %
                 ','.join(str(s) for *_, s, _ in SCENES))
    parts.append('static const unsigned char fx_type[FX_SCENES]={%s};' %
                 ','.join('FXK_%s' % k.upper() for *_, k in SCENES))
    parts.append('/* Scenes: %s */' % ', '.join(n for n, *_ in SCENES))
    parts.append(c_bytes('fx_tex', texture(), far=False, per=32))
    sin = [max(-127, min(127, int(round(127 * math.sin(i * TAU / 256))))) for i in range(256)]
    parts.append('static const signed char fx_sin[256]={%s};' % ','.join(map(str, sin)))
    return '\n'.join(parts) + '\n', maps, runs_all, run_off


PAL = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170), (170, 85, 0),
       (170, 170, 170), (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255), (255, 85, 85),
       (255, 85, 255), (255, 255, 85), (255, 255, 255)]


def preview(outdir, maps, runs_all, run_off, steps=(0, 3)):
    from PIL import Image
    outdir.mkdir(parents=True, exist_ok=True)
    for s, (name, fn, grad, speed, kind) in enumerate(SCENES):
        for t in steps:
            im = Image.new('RGB', (W, H))
            cyc = [grad[(t + 2 * k) % 8] for k in range(4)]
            data = maps[s]
            for y in range(H):
                for x in range(W):
                    if data is None:
                        c = 0
                    else:
                        b = data[y * 24 + x // 4]
                        c = cyc[(b >> (6 - 2 * (x & 3))) & 3]
                    im.putpixel((x, y), PAL[c])
            i = run_off[s]
            while runs_all[i] != 255:
                y, x, n, ab = runs_all[i:i + 4]; i += 4
                for k in range(n):
                    c = (ab >> 4) if ((x + k + y) & 1) == 0 else (ab & 15)
                    im.putpixel((x + k, y), PAL[c])
            im.resize((W * 3, int(H * 3 * 1.2)), Image.NEAREST).save(outdir / f'{s}_{name}_t{t}.png')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--check', action='store_true')
    p.add_argument('--preview', type=Path)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    text, maps, runs_all, run_off = build()
    target = root / 'src/FXDATA.H'
    if a.check:
        ok = target.exists() and target.read_text() == text
        print('FXDATA.H up to date' if ok else 'FXDATA.H is stale: run tools/gen_fx.py')
        sys.exit(0 if ok else 1)
    target.write_text(text)
    print(f'wrote {target}: {len(text)} bytes, maps {sum(len(m) for m in maps if m)} bytes, runs {len(runs_all)} bytes')
    if a.preview:
        preview(a.preview, maps, runs_all, run_off)


if __name__ == '__main__':
    main()
