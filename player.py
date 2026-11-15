import os
import json
import time
import uuid
import threading
import subprocess


def find_mpv(base_dir):
    for p in (os.path.join(base_dir, "mpv", "mpv.exe"), os.path.join(base_dir, "mpv", "mpv")):
        if os.path.isfile(p):
            return p
    import shutil
    return shutil.which("mpv")


class MpvPlayer:
    """Plays audio and video through mpv, controlled over its JSON IPC pipe."""

    def __init__(self, exe):
        self.pipe = r"\\.\pipe\mediaxclassic-" + uuid.uuid4().hex[:10]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            [exe, "--idle=yes", "--keep-open=yes", "--force-window=no", "--no-terminal",
             f"--input-ipc-server={self.pipe}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
        )
        self.f = self._connect()
        self.lock = threading.Lock()
        self.next_id = 1
        self.waiters = {}
        self.results = {}
        threading.Thread(target=self._reader, daemon=True).start()

    def _connect(self):
        for _ in range(100):
            try:
                return open(self.pipe, "r+b", buffering=0)
            except OSError:
                if self.proc.poll() is not None:
                    raise RuntimeError("mpv exited")
                time.sleep(0.1)
        raise RuntimeError("could not reach mpv")

    def _reader(self):
        buf = b""
        while True:
            try:
                chunk = self.f.read(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                rid = msg.get("request_id")
                if rid in self.waiters:
                    self.results[rid] = msg
                    self.waiters.pop(rid).set()

    def command(self, *args):
        with self.lock:
            self.f.write((json.dumps({"command": list(args)}) + "\n").encode("utf-8"))

    def set(self, prop, value):
        self.command("set_property", prop, value)

    def get(self, prop, default=None):
        with self.lock:
            rid = self.next_id
            self.next_id += 1
            ev = threading.Event()
            self.waiters[rid] = ev
            self.f.write((json.dumps({"command": ["get_property", prop], "request_id": rid}) + "\n").encode("utf-8"))
        if not ev.wait(1.0):
            self.waiters.pop(rid, None)
            return default
        msg = self.results.pop(rid, {})
        return msg.get("data", default) if msg.get("error") == "success" else default

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        try:
            self.proc.kill()
        except OSError:
            pass
