"""Tools that are one function in front of a brick the app built: the file index and the Chimera voice.
Each install(...) takes the brick (by its methods, nothing is imported from it) and registers the tool.
"""
from .files import listing
from .registry import tool


def install_search(index) -> None:
    """index: anything with search(text) -> [(score, path, passage)] (the FileIndex brick)."""
    @tool("Find files by what they are about (topic or content), when the user describes a file rather "
          "than naming it, e.g. 'my notes on op-amps', 'the internship offer letter'.")
    def search_files_by_meaning(about: str) -> str:
        return listing([path for _, path, _ in index.search(about)]) or "the file index is empty"


def install_voice(voice) -> None:
    """voice: anything with adjust(preset, **settings) -> str (the ChimeraVoice brick)."""
    @tool("Change how the Chimera voice sounds, only when the user asks for that. Pass only what should change. "
          "preset: default, male, female, child. female, child, breathiness, tension, roughness, fry, brightness: "
          "0 to 1. pitch_hz: 60-400 (0 = natural; deeper is about 85, higher about 220). rate: 0.5 slow to 2 fast. "
          "vibrato: 0-100.")
    def set_chimera_voice(preset: str = "", female: float = None, child: float = None, pitch_hz: float = None,
                          rate: float = None, breathiness: float = None, tension: float = None,
                          roughness: float = None, fry: float = None, brightness: float = None,
                          vibrato: float = None) -> str:
        return voice.adjust(preset, female=female, child=child, pitch_hz=pitch_hz, rate=rate,
                            breathiness=breathiness, tension=tension, roughness=roughness, fry=fry,
                            brightness=brightness, vibrato=vibrato)
