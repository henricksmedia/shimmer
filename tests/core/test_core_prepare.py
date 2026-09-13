"""core.prepare() and the plan cache.

A fix that must read the whole song first (Shimmer's spectral de-noise,
about 50 s for a 3-minute song) does it once per song, says how far it has
got, and can be stopped with nothing half done kept. Two requests that ask
at once (a preview and an export) share the work.
"""
import threading
import time

import numpy as np
import pytest

from shimmer.core import Cancelled, Progress, Settings, Source, plans_pending, prepare, render
from shimmer.core.repair import hash_remover

SR = 48000

needs_weights = pytest.mark.skipif(not hash_remover.available(),
                                   reason="the network's weights are not here")


def _song(seconds=8.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    x = 0.3 * np.sin(2 * np.pi * 220.0 * t)[:, None] + 0.02 * rng.standard_normal((t.size, 2))
    return x.astype(np.float32)


def test_two_threads_asking_for_the_same_thing_work_it_out_once():
    src = Source.from_array(_song(1.0), SR)
    calls = []

    def make():
        calls.append(1)
        time.sleep(0.2)
        return 42
    out = []
    threads = [threading.Thread(target=lambda: out.append(src._remember("k", make)))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert out == [42, 42, 42] and len(calls) == 1


def test_work_that_failed_is_done_by_the_next_to_ask():
    src = Source.from_array(_song(1.0), SR)

    def stopped():
        raise Cancelled()
    with pytest.raises(Cancelled):
        src._remember("k", stopped)
    assert src._remember("k", lambda: 7) == 7


def test_only_a_slow_fix_needs_getting_ready():
    src = Source.from_array(_song(), SR)
    assert plans_pending(src, Settings(fixes={"sibilance": 0.5})) == []
    if hash_remover.available():
        assert plans_pending(src, Settings(fixes={"shimmer": 0.5, "sibilance": 0.5})) == ["shimmer"]


@needs_weights
def test_prepare_says_how_far_it_has_got_then_nothing_is_left():
    src = Source.from_array(_song(), SR)
    s = Settings(fixes={"shimmer": 1.0}, auto=False, mastering=False)
    said = []
    prepare(src, s, Progress(on_stage=lambda key, label, detail: said.append((key, label, detail))))
    assert said and {k for k, _, _ in said} == {"fixes"}
    assert said[0][1] == "Shimmer: Spectral de-noise"
    assert said[-1][2] == "reading the whole song once, 100%"
    assert plans_pending(src, s) == []


@needs_weights
def test_prepare_can_be_cancelled_and_keeps_nothing_half_done():
    src = Source.from_array(_song(), SR)
    s = Settings(fixes={"shimmer": 1.0}, auto=False, mastering=False)
    prog = Progress(on_stage=lambda *a: prog.cancel())
    with pytest.raises(Cancelled):
        prepare(src, s, prog)
    assert plans_pending(src, s) == ["shimmer"]


@needs_weights
def test_an_export_says_it_is_reading_the_song_the_first_time_only():
    src = Source.from_array(_song(), SR)
    s = Settings(fixes={"shimmer": 1.0}, auto=False, mastering=False, preserve_volume=False)
    said = []
    render(src, s, progress=Progress(on_stage=lambda k, label, detail: said.append(detail)))
    assert any(d.startswith("reading the whole song once") for d in said)
    said.clear()
    render(src, s, progress=Progress(on_stage=lambda k, label, detail: said.append(detail)))
    assert not any(d.startswith("reading the whole song once") for d in said)
