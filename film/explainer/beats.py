"""The explainer, in order: voiceover phrases and two real recordings of Silky at work, in five beats.

SEQ runs back to back. Each item starts `gap` seconds after the one before it ends (a negative gap overlaps).
  phrase   (id, gap, text)            synthesized by the kit's TTS, one clip per phrase
  footage  (id, gap, {shot, from, to}) a stretch of a proof shot cut from the launch film's recorded take
                                       (../out/frames/<shot>/, ../out/cut_<shot>.npy, ../out/cut.json): the real
                                       daemon answering a spoken command. Its own sound plays; nobody narrates over it.
explainer.html draws each scene against these ids, so the picture follows the voice and the footage.
Every number spoken or shown was measured on the laptop the product runs on (see ../README.md).
"""
SEQ = [
    # 1 · the problem
    ("p1", 0.30, "Every time you talk to an assistant,"),
    ("p2", 0.10, "your voice leaves the room."),
    ("p3", 0.45, "What if it didn't have to?"),
    # 2 · meet Silky
    ("p4", 0.55, "Meet Silky."),
    ("p5", 0.30, "Say its name. Say what you want."),
    ("p6", 0.20, "Models on your own laptop do the rest."),
    # 3 · what it does: two real takes, then a quick run through more
    ("p7", 0.45, "Here it is, for real."),
    ("F1", 0.10, {"shot": "grammar", "from": 0.25, "to": 9.7, "title": "Fix the grammar of what I selected"}),
    ("p8", 0.15, "It finds files by what they're about."),
    ("F2", 0.05, {"shot": "files", "from": 0.25, "to": 10.43, "title": "Find files by meaning"}),
    ("p9", 0.25, "It watches the screen for you,"),
    ("p10", 0.10, "and remembers what you tell it."),
    # 4 · fast and local
    ("p11", 0.40, "A command it knows: under a tenth of a second."),
    ("p12", 0.20, "Picking the right tool? Under half."),
    ("p13", 0.20, "All on a four gig laptop graphics card."),
    # 5 · the promise
    ("p14", 0.40, "No account."),
    ("p15", 0.12, "No subscription."),
    ("p16", 0.12, "Nobody listening."),
    ("p17", 0.30, "Silky. Private, because there's nowhere else for it to go."),
]
END_CARD = 2.6   # seconds the end card holds after the last phrase

BEATS = [  # (label, the item that opens it, seconds before that item the beat starts)
    ("The problem", "p1", 0.3),
    ("Meet Silky", "p4", 0.45),
    ("What it does", "p7", 0.35),
    ("Fast and local", "p11", 0.3),
    ("Private", "p14", 0.3),
]

# Sound effects: (item id, seconds after that item starts, kind). Kinds: click, swoosh, rswoosh, pop, ding, tick, roll, ping, thump.
# A negative offset lands before the item. ("end", x, kind) is x seconds after the end card appears.
SFX = [
    ("p1", 0.7, "swoosh"),       # the waveform leaves the laptop
    ("p2", 0.45, "click"),       # the lock opens
    ("p3", -0.3, "rswoosh"),     # the line snaps back
    ("p4", 0.05, "click"),       # the wordmark lands
    ("p5", 0.0, "click"),        # speech bubble
    ("p5", 1.4, "click"),        # open_app chip
    ("p5", 1.7, "pop"),          # calculator window
    ("p6", 1.0, "swoosh"),       # the laptop outline closes
    ("p7", -0.2, "swoosh"),      # into the recording
    ("F1", 0.0, "click"),
    ("p8", -0.1, "swoosh"),
    ("p9", -0.2, "swoosh"),
    ("p9", 1.5, "ping"),         # download done
    ("p10", -0.15, "swoosh"),
    ("p10", 0.5, "click"),       # memory chip
    ("p10", 0.9, "tick"),        # the dials click into place
    ("p10", 1.1, "tick"),
    ("p10", 1.3, "tick"),
    ("p10", 1.5, "tick"),
    ("p11", -0.25, "swoosh"),    # into the pipeline
    ("p11", 1.3, "roll"),        # counter rolls
    ("p11", 2.3, "click"),       # and stops
    ("p12", 0.3, "roll"),
    ("p12", 1.4, "click"),
    ("p13", 0.5, "thump"),       # 4 GB
    ("p14", 0.0, "click"),
    ("p15", 0.0, "click"),
    ("p16", 0.0, "click"),
    ("p17", -0.2, "swoosh"),
    ("end", 0.0, "click"),
]
