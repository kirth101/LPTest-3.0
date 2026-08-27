"""
bgm.py -- optional background music, one loop per screen (Android/Kivy
port of the desktop app's bgm.py).

Drop audio files into the bgm/ folder using the screen names below and
they'll loop automatically while that screen is showing, stopping (or
switching) when you move to a screen whose track differs. Nothing is
required -- a missing file just means that screen stays quiet, same
philosophy as sound_effects.py.

Uses kivy.core.audio.SoundLoader with looping instead of the desktop
version's dedicated pygame mixer channel -- each Kivy Sound already plays
independently of every other Sound (including sound_effects.py's one-shot
effects and _AndroidTTS's Read Aloud playback in main.py), so nothing here
needs a manually reserved channel to avoid fighting over playback.

There is no separate "loading" SCREEN in this Kivy rebuild the way the
desktop app has one -- the landing screen just shows a busy/status message
while a file is being read/processed. main.py calls set_screen("loading")
for that busy state and set_screen("landing") once it's idle again, so the
"loading" track still gets used exactly when the desktop version's does.
"""

from __future__ import annotations
import os

from kivy.core.audio import SoundLoader

# Screen name -> file this BGM loop uses, if present. Matches the
# ScreenManager screen names in main.py (plus the synthetic "loading"
# state described above).
BGM_FILES = {
    "landing": "landing",
    "loading": "loading",
    "count_select": "count_select",
    "quiz": "quiz",
    "summary": "summary",
}
_EXTENSIONS = (".wav", ".ogg", ".mp3")


def _bgm_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "bgm")


class BGMPlayer:
    def __init__(self):
        self.music_enabled = True  # master on/off (Settings > Sound Effects)
        self.screen_enabled: dict[str, bool] = {name: True for name in BGM_FILES}
        self._tracks: dict[str, object] = {}
        self._current_screen: str | None = None
        self._current_sound = None

        folder = _bgm_dir()
        for name, stem in BGM_FILES.items():
            for ext in _EXTENSIONS:
                path = os.path.join(folder, stem + ext)
                if os.path.isfile(path):
                    try:
                        sound = SoundLoader.load(path)
                    except Exception:
                        sound = None
                    if sound is not None:
                        sound.loop = True
                        self._tracks[name] = sound
                    break

    def set_screen(self, screen_name: str):
        """Called whenever the visible screen changes (or the app enters/
        leaves its busy "loading" state). Loops whichever track matches
        screen_name; stops cleanly if there isn't one, if music is off
        globally, or if that specific screen's toggle is off. Re-calling
        with the SAME screen_name (e.g. a re-render) is a no-op so the
        track doesn't restart from zero every time."""
        if screen_name == self._current_screen:
            return
        self._current_screen = screen_name
        if self._current_sound is not None:
            try:
                self._current_sound.stop()
            except Exception:
                pass
            self._current_sound = None

        if not self.music_enabled or not self.screen_enabled.get(screen_name, True):
            return
        track = self._tracks.get(screen_name)
        if track is not None:
            try:
                track.play()
            except Exception:
                pass
            else:
                self._current_sound = track

    def set_enabled(self, enabled: bool):
        """Master on/off toggle (Settings)."""
        self.music_enabled = enabled
        self._replay_current()

    def set_screen_enabled(self, screen_name: str, enabled: bool):
        """Per-screen toggle -- e.g. music on for the quiz screen but off
        on the landing screen."""
        self.screen_enabled[screen_name] = enabled
        self._replay_current()

    def _replay_current(self):
        """Re-evaluates whatever screen is currently showing against the
        latest enabled/disabled state, without restarting a track that's
        already correctly playing (or correctly silent)."""
        screen = self._current_screen
        self._current_screen = None  # force set_screen to actually re-evaluate
        if screen:
            self.set_screen(screen)

    @property
    def has_any_tracks(self) -> bool:
        return bool(self._tracks)
