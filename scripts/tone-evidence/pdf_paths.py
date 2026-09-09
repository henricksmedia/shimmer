"""Pull the plotted polylines and the axis tick labels out of a figure stream.

A minimal content-stream interpreter: enough of the graphics state to get
path points into page coordinates (q/Q/cm), plus text-showing operators with
their positions so the axis ticks can be located. Nothing here is a general
PDF reader; it only has to survive one MATLAB figure.
"""
import re
import sys
import zlib

import numpy as np

PDF = r"C:\Users\jerem\Downloads\Elowsson-Long-termAverageSpectruminPopularMusic.pdf"

TOKEN = re.compile(rb"""
      \( (?: \\. | [^()\\] )* \)     # literal string
    | < [0-9A-Fa-f\s]* >             # hex string
    | [/A-Za-z'"*]+                  # name or operator
    | [-+]?[0-9.]+                   # number
    | [\[\]{}]
""", re.VERBOSE | re.DOTALL)


def load_streams():
    raw = open(PDF, "rb").read()
    out = []
    for m in re.finditer(rb"stream\r?\n", raw):
        s = m.end()
        e = raw.find(b"endstream", s)
        if e < 0:
            continue
        d = raw[s:e]
        try:
            d = zlib.decompress(d)
        except Exception:
            pass
        out.append(d)
    return out


def mul(a, b):
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def app(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def parse(data):
    """Return (paths, texts). paths is [(colour, [(x, y), ...]), ...]."""
    ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    gstack = []
    nums = []
    colour = (0.0, 0.0, 0.0)
    cur = []
    paths = []
    texts = []
    tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    tline = tm[:]

    def flush():
        nonlocal cur
        if len(cur) > 1:
            paths.append((colour, cur))
        cur = []

    for m in TOKEN.finditer(data):
        t = m.group()
        head = t[:1]
        if head.isdigit() or head in b"-+.":
            try:
                nums.append(float(t))
                continue
            except ValueError:
                pass
        if head == b"(":
            s = re.sub(rb"\\(.)", rb"\1", t[1:-1]).decode("latin-1")
            if s.strip():
                texts.append((app(ctm, tm[4], tm[5]), s))
            nums = []
            continue
        op = t.decode("latin-1")
        n = nums
        if op == "q":
            gstack.append((ctm[:], colour))
        elif op == "Q":
            if gstack:
                ctm, colour = gstack.pop()
                ctm = ctm[:]
        elif op == "cm" and len(n) >= 6:
            ctm = mul(n[-6:], ctm)
        elif op in ("RG", "rg", "SC", "sc", "SCN", "scn") and len(n) >= 3:
            colour = tuple(round(v, 3) for v in n[-3:])
        elif op in ("G", "g") and len(n) >= 1:
            colour = (round(n[-1], 3),) * 3
        elif op == "m" and len(n) >= 2:
            flush()
            cur = [app(ctm, n[-2], n[-1])]
        elif op == "l" and len(n) >= 2:
            cur.append(app(ctm, n[-2], n[-1]))
        elif op == "c" and len(n) >= 6:
            cur.append(app(ctm, n[-2], n[-1]))
        elif op in ("S", "s", "f", "F", "f*", "B", "B*", "b", "n"):
            flush()
        elif op == "BT":
            tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            tline = tm[:]
        elif op == "Tm" and len(n) >= 6:
            tm = n[-6:]
            tline = tm[:]
        elif op in ("Td", "TD") and len(n) >= 2:
            tline = mul([1.0, 0.0, 0.0, 1.0, n[-2], n[-1]], tline)
            tm = tline[:]
        nums = []
    flush()
    return paths, texts


if __name__ == "__main__":
    streams = load_streams()
    for idx in [int(a) for a in sys.argv[1:]]:
        paths, texts = parse(streams[idx])
        paths.sort(key=lambda p: -len(p[1]))
        print(f"=== stream {idx}: {len(paths)} paths, {len(texts)} text runs")
        for c, p in paths[:6]:
            a = np.array(p)
            print(f"  n={len(p):5d} colour={c} "
                  f"x [{a[:, 0].min():8.2f},{a[:, 0].max():8.2f}] "
                  f"y [{a[:, 1].min():8.2f},{a[:, 1].max():8.2f}]")
        short = [(round(p[0], 1), round(p[1], 1), s) for p, s in texts]
        print(f"  text: {sorted(short)[:36]}")
