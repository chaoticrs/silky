"""The 60-second explainer: five beats, the voiceover cut into phrases, and the moments the sound effects land.

Each phrase is synthesized on its own, so every phrase starts at a known instant and the kinetic type can follow
it. `at` is when a phrase should start. make_audio.py moves a phrase later only if the one before it is still
speaking. explainer.html draws each shot against the phrase times it is given, so the picture follows the
voice, not the other way round.
Every number spoken or shown here was measured on the laptop the product runs on (see ../README.md).
"""
LENGTH = 60.0

BEATS = [  # (id, start, end, label)
    ("problem", 0.0, 10.0, "The problem"),
    ("meet", 10.0, 20.0, "Meet Silky"),
    ("does", 20.0, 38.0, "What it does"),
    ("fast", 38.0, 50.0, "Fast and private"),
    ("promise", 50.0, 60.0, "The promise"),
]

# (id, at, text). The ids are what explainer.html refers to.
PHRASES = [
    ("p1", 0.45, "Every time you talk to an assistant,"),
    ("p2", 2.7, "your voice leaves the room."),
    ("p3", 6.6, "What if it didn't have to?"),
    ("p4", 10.35, "Meet Silky."),
    ("p5", 12.4, "Say its name. Say what you want."),
    ("p6", 15.9, "And models on your own laptop do it."),
    ("p7", 20.3, "Fix the grammar of what you've selected."),
    ("p8", 24.1, "Find files by what they're about,"),
    ("p9", 26.5, "not what they're called."),
    ("p10", 30.1, "Ask it to watch the screen,"),
    ("p11", 32.0, "and tell you when the download's done."),
    ("p12", 35.0, "It even remembers your bike lock code."),
    ("p13", 38.4, "A command it knows runs in under a tenth of a second."),
    ("p14", 43.1, "Picking the right tool? Under half."),
    ("p15", 46.9, "All on a four gig laptop graphics card."),
    ("p16", 50.35, "No account."),
    ("p17", 51.55, "No subscription."),
    ("p18", 52.85, "Nobody listening."),
    ("p19", 54.5, "Silky. Private, because there's nowhere else for it to go."),
]
GAP = 0.12  # the least silence between two phrases

# Sound effects that are not tied to a phrase: (seconds, kind). Kinds: click, swoosh, rswoosh, pop, ding, tick, ping, thump.
# Effects tied to a phrase are written as ("p5", offset, kind) and land `offset` seconds after that phrase starts.
SFX = [
    ("p1", 0.9, "swoosh"),       # the waveform leaves the laptop
    ("p2", 0.55, "click"),       # the lock opens
    ("p3", -0.35, "rswoosh"),    # the line snaps back
    ("p4", 0.05, "click"),       # the wordmark lands, the ring pulses
    ("p5", 0.0, "click"),        # speech bubble
    ("p5", 1.6, "click"),        # open_app chip
    ("p5", 2.0, "pop"),          # calculator window
    ("p6", 1.2, "swoosh"),       # the laptop outline closes
    ("p7", -0.3, "swoosh"),      # into the editor
    ("p7", 1.0, "click"),
    ("p7", 1.12, "click"),
    ("p7", 1.24, "click"),
    ("p7", 1.9, "ding"),         # the sentence is fixed
    ("p8", 0.1, "swoosh"),       # documents sort
    ("p9", 1.3, "click"),        # one is opened
    ("p10", -0.3, "swoosh"),
    ("p11", 1.8, "ping"),        # download done
    ("p12", 0.6, "click"),       # memory chip
    ("p12", 1.3, "tick"),        # four dials click into place
    ("p12", 1.55, "tick"),
    ("p12", 1.8, "tick"),
    ("p12", 2.05, "tick"),
    ("p13", -0.3, "swoosh"),     # into the pipeline
    ("p13", 1.6, "roll"),        # counter rolls
    ("p13", 2.7, "click"),       # and stops
    ("p14", 0.4, "roll"),
    ("p14", 1.6, "click"),
    ("p15", 0.6, "thump"),       # 4 GB
    ("p16", 0.0, "click"),
    ("p17", 0.0, "click"),
    ("p18", 0.0, "click"),
    ("p19", -0.25, "swoosh"),
    (58.1, 0.0, "click"),        # end card
]
