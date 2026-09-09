import re

def syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    # numbers handled by caller
    vowels = "aeiouy"
    count, prev = 0, False
    for ch in w:
        isv = ch in vowels
        if isv and not prev:
            count += 1
        prev = isv
    if w.endswith("e") and count > 1 and not w.endswith(("le", "ee", "ye")):
        count -= 1
    return max(count, 1)

NUMWORDS = {"0":"zero","1":"one","2":"two","3":"three","4":"four","5":"five",
            "6":"six","7":"seven","8":"eight","9":"nine","10":"ten","12":"twelve",
            "0.5":"zero point five","1000":"one thousand"}

def expand(text):
    text = text.replace("dB", "decibels").replace("kHz", "kilohertz").replace("EQ", "E Q")
    def rep(m):
        return NUMWORDS.get(m.group(0), m.group(0))
    return re.sub(r"\d+\.\d+|\d+", rep, text)

def fk(text):
    t = expand(text)
    sentences = [s for s in re.split(r"[.!?:;]+", t) if s.strip()]
    words = re.findall(r"[A-Za-z']+", t)
    syl = sum(syllables(w) for w in words)
    S, W = len(sentences), len(words)
    grade = 0.39 * (W / S) + 11.8 * (syl / W) - 15.59
    return round(grade, 2), W, S, syl

texts = {
 "c1": "Sets how far the EQ moves your track toward the Tone Target. It shapes tone only: it does not change loudness or dynamics.",
 "c2": "Tilts the curve up to 2 dB, hinged at 1 kHz: one end lifts as the other drops. From 5 to 12 kHz it can add no more than 0.5 dB, so fizz cannot come back.",
 "c3": "The Tone Target is the tone shape Shimmer aims at: the middle of hundreds of finished masters, band by band. The Target Range is the normal spread around it, so a track already inside the range needs little or no EQ.",
}
tot = 0
for k, v in texts.items():
    g, W, S, syl = fk(v)
    tot += g
    print(k, "FK grade", g, "| words", W, "| sentences", S, "| syllables", syl)
print("mean", round(tot/3, 2))

# also without colon as a sentence break (colon-inclusive vs period-only)
def fk_periods(text):
    t = expand(text)
    sentences = [s for s in re.split(r"[.!?]+", t) if s.strip()]
    words = re.findall(r"[A-Za-z']+", t)
    syl = sum(syllables(w) for w in words)
    return round(0.39*(len(words)/len(sentences)) + 11.8*(syl/len(words)) - 15.59, 2)
print("period-only:", {k: fk_periods(v) for k, v in texts.items()})
