"""
sound_effects.py -- optional UI sound effects (Android/Kivy port of the
desktop app's sound_effects.py).

Drop audio files into the sounds/ folder (see sounds/README.md for the
exact filenames this looks for) and they'll play automatically at the
matching moment in the app. Nothing is required -- any file that isn't
present is just silently skipped, so the app works identically with zero,
some, or all of the effects filled in.

Uses kivy.core.audio.SoundLoader (the same backend main.py already uses
for swipe.wav) instead of the desktop version's pygame.mixer.Sound --
pygame isn't part of this app's Android build, and Kivy's audio provider
already gives each Sound its own independent playback slot, so multiple
effects (and BGM, see bgm.py) can overlap without one cutting another off.
"""

from __future__ import annotations
import os

from kivy.core.audio import SoundLoader

# name -> the file this effect plays, if present. Extensions tried in
# order; first one found on disk wins. Add your own file using any of
# these names (any format Kivy's audio provider can read: .wav, .ogg, .mp3).
SOUND_FILES = {
    "correct": "correct",
    "incorrect": "incorrect",
    "select": "select",
    "next_question": "next_question",
    "quiz_complete": "quiz_complete",
    "upload_success": "upload_success",
    "generation_complete": "generation_complete",
    "error": "error",
    "timer_goal": "timer_goal",
    "timer_tick": "timer_tick",
}
_EXTENSIONS = (".wav", ".ogg", ".mp3")


def _sounds_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")


class SoundEffects:
    def __init__(self):
        self._sounds: dict[str, object] = {}
        self.effects_enabled = True  # user-facing on/off (Settings > Sound Effects)

        folder = _sounds_dir()
        for name, stem in SOUND_FILES.items():
            for ext in _EXTENSIONS:
                path = os.path.join(folder, stem + ext)
                if os.path.isfile(path):
                    try:
                        sound = SoundLoader.load(path)
                    except Exception:
                        sound = None
                    if sound is not None:
                        self._sounds[name] = sound
                    break

    def play(self, name: str):
        """No-op if sound effects are turned off in Settings, or this
        specific effect's file was never added. Safe to call rapidly --
        stops and restarts from the beginning so back-to-back triggers
        (e.g. quick answer taps) don't queue up or get skipped."""
        if not self.effects_enabled:
            return
        sound = self._sounds.get(name)
        if sound is None:
            return
        try:
            sound.stop()
            sound.play()
        except Exception:
            pass  # a playback hiccup should never interrupt the quiz itself

    def set_enabled(self, enabled: bool):
        self.effects_enabled = enabled

    @property
    def has_any(self) -> bool:
        return bool(self._sounds)
