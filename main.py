import os
import sys
import json
import shutil
import threading

import webview

from player import MpvPlayer, find_mpv

APP_NAME = "Media X Classic"
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "ui")
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else BASE_DIR

AUDIO_EXT = {"mp3", "flac", "wav", "aac", "m4a", "ogg", "opus", "wma", "aiff", "ape"}
VIDEO_EXT = {"mp4", "mkv", "webm", "mov", "avi", "wmv", "m4v", "mpg", "mpeg", "ts", "3gp"}
EQ_FREQS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
SKINS = ("graphite", "steel", "amber")


def kind_of(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return None


def dialog(kind):
    fd = getattr(webview, "FileDialog", None)
    if fd is not None:
        return {"open": fd.OPEN, "folder": fd.FOLDER}[kind]
    return {"open": webview.OPEN_DIALOG, "folder": webview.FOLDER_DIALOG}[kind]


class Api:
    def __init__(self):
        self.window = None
        self.windows = {}
        self.items = []  # [{"path", "title", "kind"}]
        self.index = -1
        self.player = None
        self.gains = [0.0] * len(EQ_FREQS)
        self.preamp = 0.0
        self.volume = 80
        self.skin = "graphite"
        self.last_load = 0.0
        self.lock = threading.Lock()

    # ----- player -----
    def _mpv(self):
        if self.player is not None and self.player.alive():
            return self.player
        exe = find_mpv(APP_DIR) or find_mpv(BASE_DIR)
        if not exe:
            return None
        self.player = MpvPlayer(exe)
        self.player.set("volume", self.volume)
        self._apply_eq()
        return self.player

    def _apply_eq(self):
        if not self.player or not self.player.alive():
            return
        active = any(g for g in self.gains) or self.preamp
        bands = [f"equalizer=f={f}:width_type=o:width=2:g={max(-12, min(12, g + self.preamp)):.1f}"
                 for f, g in zip(EQ_FREQS, self.gains)]
        self.player.set("af", "lavfi=[" + ",".join(bands) + "]" if active else "")

    def _load(self, i):
        m = self._mpv()
        if m is None:
            return {"ok": False, "error": "mpv not found"}
        self.index = i
        self.last_load = __import__("time").time()
        m.command("loadfile", self.items[i]["path"], "replace")
        return {"ok": True}

    def play(self, i=None):
        if not self.items:
            return {"ok": False}
        if i is None:
            i = self.index if self.index >= 0 else 0
        return self._load(i)

    def toggle(self):
        m = self._mpv()
        if m is None:
            return
        if self.index < 0 and self.items:
            self._load(0)
            return
        m.command("cycle", "pause")

    def next(self):
        if self.index + 1 < len(self.items):
            self._load(self.index + 1)

    def prev(self):
        m = self._mpv()
        if m and (m.get("time-pos", 0) or 0) > 3:
            m.command("seek", 0, "absolute")
        elif self.index > 0:
            self._load(self.index - 1)

    def stop(self):
        if self.player and self.player.alive():
            self.player.command("stop")
        self.index = -1

    def seek(self, seconds):
        if self.player and self.player.alive():
            self.player.command("seek", float(seconds), "absolute")

    def set_volume(self, value):
        self.volume = max(0, min(130, int(value)))
        if self.player and self.player.alive():
            self.player.set("volume", self.volume)

    def set_eq(self, gains, preamp=None):
        self.gains = [max(-12.0, min(12.0, float(g))) for g in gains][:len(EQ_FREQS)]
        if preamp is not None:
            self.preamp = max(-12.0, min(12.0, float(preamp)))
        self._apply_eq()
        return True

    def state(self):
        m = self.player if self.player and self.player.alive() else None
        now = self.items[self.index] if 0 <= self.index < len(self.items) else None
        s = {"playing": bool(m and self.index >= 0), "index": self.index, "count": len(self.items),
             "title": now["title"] if now else "Media X Classic", "volume": self.volume, "skin": self.skin,
             "time": 0, "duration": 0, "paused": True}
        if m and self.index >= 0:
            s["time"] = m.get("time-pos", 0) or 0
            s["duration"] = m.get("duration", 0) or 0
            s["paused"] = bool(m.get("pause", True))
            eof = bool(m.get("eof-reached", False))
            if eof and self.index + 1 < len(self.items) and __import__("time").time() - self.last_load > 1.5:
                self._load(self.index + 1)
        return s

    # ----- playlist -----
    def _add(self, path):
        kind = kind_of(path)
        if kind and path not in [i["path"] for i in self.items]:
            self.items.append({"path": path, "title": os.path.splitext(os.path.basename(path))[0], "kind": kind})

    def add_files(self):
        if self.window is None:
            return 0
        paths = self.window.create_file_dialog(dialog("open"), allow_multiple=True, file_types=(
            "Media files (*.mp3;*.flac;*.wav;*.m4a;*.ogg;*.mp4;*.mkv;*.webm;*.avi)",))
        for p in paths or []:
            self._add(p)
        return len(self.items)

    def add_folder(self):
        if self.window is None:
            return 0
        paths = self.window.create_file_dialog(dialog("folder"))
        if paths:
            for root, dirs, files in os.walk(paths[0]):
                for name in files:
                    self._add(os.path.join(root, name))
        return len(self.items)

    def playlist(self):
        return {"items": self.items, "index": self.index}

    def remove(self, i):
        if 0 <= i < len(self.items):
            if i == self.index:
                self.stop()
            del self.items[i]
            if i < self.index:
                self.index -= 1
        return True

    def clear(self):
        self.stop()
        self.items = []
        return True

    def save_m3u(self):
        if self.window is None or not self.items:
            return False
        paths = self.window.create_file_dialog(dialog("open"), save_filename="playlist.m3u") if False else None
        target = os.path.join(APP_DIR, "playlist.m3u")
        with open(target, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for it in self.items:
                f.write(it["path"] + "\n")
        return target

    # ----- skins and windows -----
    def set_skin(self, name):
        if name in SKINS:
            self.skin = name
        return self.skin

    def open_window(self, name):
        titles = {"playlist": ("Playlist", 360, 480), "eq": ("Equalizer", 520, 260)}
        if name not in titles:
            return False
        win = self.windows.get(name)
        if win is not None:
            try:
                win.show()
                return True
            except Exception:
                pass
        title, w, h = titles[name]
        self.windows[name] = webview.create_window(
            f"{APP_NAME} - {title}", url=os.path.join(UI_DIR, f"{name}.html"),
            js_api=self, width=w, height=h, frameless=True, background_color="#1B1D22",
        )
        return True

    def hide_window(self, name):
        win = self.windows.get(name)
        if win is not None:
            win.hide()
        return True

    def minimize(self, name="main"):
        win = self.window if name == "main" else self.windows.get(name)
        if win is not None:
            win.minimize()
        return True

    def close_window(self, name="main"):
        if name == "main":
            self.shutdown()
            if self.window is not None:
                self.window.destroy()
        else:
            self.hide_window(name)
        return True

    def shutdown(self):
        if self.player:
            self.player.close()


def main():
    api = Api()
    api.window = webview.create_window(
        APP_NAME, url=os.path.join(UI_DIR, "main.html"), js_api=api,
        width=420, height=170, resizable=False, frameless=True, background_color="#1B1D22",
    )
    api.window.events.closed += api.shutdown
    webview.start(debug=False)


if __name__ == "__main__":
    main()
