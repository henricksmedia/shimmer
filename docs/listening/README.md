# Listening records

What people actually heard, kept apart from the tool they heard it on.

The bench in `listening-test/ab/` is equipment. It is built fresh by
`scripts/make_bench_set.py`, it holds audio and the answer keys that hide
which arm is which, and none of it is in git. This folder holds the part
that has to outlive the equipment: what was preferred, under what
conditions, and how far it can be trusted.

Rebuild a record with `scripts/listening_report.py`. Do not hand-edit the
JSON.

## Two rules for these records

**Record what won, never which letter won it.** The letter is the blindfold.
Publishing letters would make the sets on disk useless to anyone who read
this repo. Publishing what won does not, because letters are shuffled again
every time a set is built.

**Never drop a round quietly.** One verdict in the 2026-09-09 round is a test
entry written while the interface was being checked. It is marked as excluded
with the reason attached, not deleted. A record that throws rows away without
saying so cannot be checked by anyone.

## Read the limits before the numbers

### 2026-09-09 bench round

Read these first. They are not small print.

**One listener, and that listener built the tool.** He could not see which arm
was which. He did know what each result would mean for the project. That is
the first thing a fair critic will raise, and they are right to. It is the
weakest point in this round, more than the number of people is.

**Everything was heard on one system: the computer speakers he uses for
everyday music.** This cuts two ways, and both ways are real.

It helps more than it looks. Most people who make AI music listen on laptop
speakers, phones and earbuds. Mastering engineers have always checked their
work on small speakers for exactly this reason. A tone choice that holds up
on the system the music will really be played on is worth something, and it
is a check this project had never done.

But it was the only system. So the round cannot tell the difference between
"this curve sounds better" and "this curve suits these speakers." Small
speakers have their own bumps and dips through the presence range, and the
change being judged sits in that same range.

**One part of the tone change was probably never heard at all.** The change
adds about 0.6 dB above 12.5 kHz. Small computer speakers usually give up
somewhere below that. So the preference was most likely carried by the 2 to
8 kHz lift and the 1.2 dB cut in the low mids, not by the air. Any story
about "more air" should be treated as unproven.

**No audibility test.** Not one round required the listener to prove he could
tell the two arms apart before his preference was counted. Without that, a
preference between two things that sound the same is still recorded as a
preference.

**One pick per round, no ranking.** In the four-arm sets we know which arm
won. We do not know whether our chain came second or last.

**Short listens in the tone sets.** The median is 8.3 seconds. That is enough
to judge a broad tone change and too short for much else.

**The sets are now spent.** The listener has read the results, so he knows
what won. These 36 sets cannot give an independent second opinion any more.
Anything that needs confirming needs new material.

## What this round does and does not show

It shows that one listener, blind to the arms, on a consumer playback system,
chose the same direction over and over. The direction was one-sided in every
group. That is real evidence and it is why the tone target was put back.

It does not show that the question is settled. A single invested listener on
a single system is a starting point, not a verdict.

**The test that would settle the tone result** is to judge three of the same
songs again on a different system, such as headphones. If the direction
holds, the result is about the music and the target is right. If it flips or
goes flat, the target is bending to fit one pair of speakers. This is about
ten minutes of work and it is worth more than another eight songs on the same
speakers.

## Rules for the next round

Three things should change before the next round is run.

1. **Make audibility a gate.** A preference should not count until the
   listener has shown he can tell the arms apart.
2. **Write down the gear and the level every time.** This round nearly lost
   that, and it turned out to matter.
3. **Get a second listener for anything that changes a default.** One person
   is fine for finding things worth checking. It is thin for changing what
   every user gets.

## What may be said in public

Say what happened. One listener, who wrote the tool, blind to the arms, on
his own computer speakers, in one session, on eight AI-generated songs.

Do not say the tone is "validated by listening tests." That wording suggests
a panel and a protocol, and neither exists yet. `GOALS.md` already gets this
right by saying "judged by the author," which is the honest phrasing and
should stay.
