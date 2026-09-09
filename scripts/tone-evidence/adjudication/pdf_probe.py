"""Is Figure 2 a vector plot? If so its data points are in the file.

The dispute is entirely about what the mean LTAS does above 4.5 kHz, and all
we have is a quadratic fitted over seven octaves. If the figures were saved
as vector graphics, the plotted curve is a path in the content stream and the
real data can be read out instead of approximated.
"""
import re
import zlib

raw = open(r"C:\Users\jerem\Downloads\Elowsson-Long-termAverageSpectruminPopularMusic.pdf",
           "rb").read()
print(f"{len(raw)} bytes")

streams = []
for m in re.finditer(rb"stream\r?\n", raw):
    s = m.end()
    e = raw.find(b"endstream", s)
    if e < 0:
        continue
    data = raw[s:e]
    try:
        data = zlib.decompress(data)
    except Exception:
        pass
    streams.append((s, data))

print(f"{len(streams)} streams")
for i, (off, d) in enumerate(streams):
    if not d[:1].isascii():
        continue
    # a plotted curve shows up as a long run of lineto operators
    lt = len(re.findall(rb"[\d.]+ [\d.]+ l\b", d))
    mv = len(re.findall(rb"[\d.]+ [\d.]+ m\b", d))
    if lt > 50:
        print(f"  stream {i:3d} @{off:8d}  {len(d):8d} bytes  "
              f"moveto {mv:5d}  lineto {lt:6d}")
