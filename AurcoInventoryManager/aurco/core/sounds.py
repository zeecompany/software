"""Alert sounds for AURCO — task reminders, alarms and UI feedback.

Windows gets real beeps through winsound (no extra dependency). Other platforms
fall back to Qt's system beep. Sounds can be muted, and a custom .wav can be
used instead of the built-in tones.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

# name -> list of (frequency Hz, duration ms)
TONES: dict[str, list[tuple[int, int]]] = {
    "reminder":  [(880, 150), (1175, 220)],
    "alarm":     [(988, 180), (784, 180), (988, 180), (1319, 380)],
    "urgent":    [(1319, 120), (0, 60), (1319, 120), (0, 60), (1319, 260)],
    "success":   [(784, 110), (1047, 180)],
    "warning":   [(600, 200), (450, 260)],
    "error":     [(400, 260), (300, 340)],
    "tick":      [(1200, 45)],
}

SOUND_NAMES = list(TONES)


def _winsound_play(seq: list[tuple[int, int]]) -> bool:
    try:
        import winsound
    except ImportError:
        return False
    for freq, dur in seq:
        try:
            if freq <= 0:
                import time
                time.sleep(dur / 1000.0)
            else:
                winsound.Beep(int(freq), int(dur))
        except Exception:
            return False
    return True


def _wav_play(path: str) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    try:
        import winsound
        winsound.PlaySound(str(p), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True
    except ImportError:
        pass
    try:
        from PySide6.QtMultimedia import QSoundEffect
        from PySide6.QtCore import QUrl
        eff = QSoundEffect()
        eff.setSource(QUrl.fromLocalFile(str(p)))
        eff.setVolume(0.9)
        eff.play()
        globals().setdefault("_keep", []).append(eff)  # keep a reference alive
        return True
    except Exception:
        return False


def _qt_beep() -> bool:
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            QApplication.beep()
            return True
    except Exception:
        pass
    return False


def play(name: str = "reminder", db=None, wav: str = "", blocking: bool = False) -> bool:
    """Play an alert. Returns True when something was actually sounded."""
    if db is not None:
        try:
            if not db.get_bool("sound_enabled", True):
                return False
            wav = wav or (db.get_setting(f"sound_file_{name}", "") or "")
        except Exception:
            pass

    def _run() -> bool:
        if wav and _wav_play(wav):
            return True
        seq = TONES.get(name, TONES["reminder"])
        if _winsound_play(seq):
            return True
        # non-Windows: a single system beep per tone keeps it audible
        done = False
        for _ in seq[:2]:
            done = _qt_beep() or done
        if not done:
            try:
                sys.stdout.write("\a")
                sys.stdout.flush()
                done = True
            except Exception:
                pass
        return done

    if blocking:
        return _run()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return True


def play_for_task(task: dict, db=None) -> bool:
    """Choose a tone based on how urgent the task is."""
    pr = (task or {}).get("priority", "Normal")
    if pr == "Urgent":
        return play("urgent", db)
    if pr == "High":
        return play("alarm", db)
    return play("reminder", db)


def test(name: str, db=None) -> bool:
    return play(name, db, blocking=False)
