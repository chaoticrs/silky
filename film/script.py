"""The launch film's script: what is said and shown, in order. make_audio.py turns it into a soundtrack and
a timeline; film.html draws each scene by its id.

Two kinds of scene:
  narrated  "lines": (voice, pause before it in seconds, text). Voices are the kit's TTS ("narrator") and Chimera.
  footage   "shots": names of proof shots cut from the recorded take (cut.py). They bring their own sound:
            the command as it went into the microphone slot and what the assistant answered. "lead" is the
            time the scene's title card holds before the footage starts.
`min` is the shortest a scene may be. Every number spoken or shown was measured on the laptop it was made on.
"""
SCENES = [
    {"id": "hook", "min": 5.0, "lines": [
        ("narrator", 0.35, "This is Silky. A voice assistant that runs on your laptop."),
        ("narrator", 0.15, "Only on your laptop. Watch.")]},
    {"id": "grammar", "shots": ["grammar"], "lead": 1.0, "title": "Fix what I selected", "colour": "violet"},
    {"id": "files", "shots": ["files"], "lead": 1.0, "title": "Find files by meaning", "colour": "amber"},
    {"id": "watch", "shots": ["watch"], "lead": 1.0, "title": "Watch my screen", "colour": "green"},
    {"id": "chimera", "shots": ["chimera"], "lead": 1.0, "title": "A second voice", "colour": "blue"},
    {"id": "also", "shots": ["recall", "open"], "lead": 0.0, "title": "And it remembers. And it opens things.", "colour": "pink",
     "lines": [("narrator", 0.2, "It remembers what you tell it. It opens what you ask for.")]},
    {"id": "speed", "min": 6.5, "lines": [
        ("narrator", 0.3, "A command it knows takes under a tenth of a second. Choosing a tool, under half a second."),
        ("narrator", 0.15, "On a four gigabyte laptop graphics card.")]},
    {"id": "freedom", "min": 6.5, "lines": [
        ("narrator", 0.3, "No account. No subscription. Nobody listening."),
        ("narrator", 0.25, "Your computer. Your models. Your rules.")]},
    {"id": "end", "min": 5.0, "lines": [
        ("narrator", 0.5, "Silky. Private, because there's nowhere else for it to go.")]},
]
TAIL = 0.7  # seconds a scene holds after its last line
