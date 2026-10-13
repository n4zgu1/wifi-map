from __future__ import annotations

import random
import os
import re
import selectors
import shutil
import signal
import subprocess
import threading
import time

from .core import Anonymizer, Store, parse_beacon
from .gps import GPS


def capture_command(interface: str) -> list[str]:
    return ["tshark", "-n", "-l", "-i", interface,
            "-f", "type mgt subtype beacon", "-Y", "wlan.fc.type_subtype == 0x08",
            "-T", "fields", "-E", "occurrence=f", "-E", "separator=/t",
            "-e", "wlan.bssid", "-e", "radiotap.dbm_antsignal", "-e", "radiotap.channel.freq",
            "-e", "wlan.rsn.version", "-e", "wlan.fixed.capabilities.privacy"]


def verify_interface(interface: str):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", interface):
        raise ValueError("Ungültiger Schnittstellenname")
    for program in ("tshark", "iw"):
        if not shutil.which(program):
            raise ValueError(f"{program} fehlt; siehe README")
    result = subprocess.run(["iw", "dev", interface, "info"], capture_output=True, text=True)
    if result.returncode or not re.search(r"\btype monitor\b", result.stdout):
        raise ValueError("Die Schnittstelle muss bereits im Monitor-Modus sein; siehe README")


class Hopper:
    def __init__(self, interface: str, channels: list[int], dwell: float, stop: threading.Event):
        self.interface, self.channels, self.dwell, self.stop = interface, channels, dwell, stop
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            for channel in self.channels:
                try:
                    result = subprocess.run(["iw", "dev", self.interface, "set", "channel", str(channel)],
                                            capture_output=True, timeout=3)
                    if result.returncode:
                        self.error = f"Kanal {channel} konnte nicht gesetzt werden (Berechtigungen/Regdomain prüfen)."
                        self.stop.set()
                        return
                except (OSError, subprocess.TimeoutExpired):
                    self.error = "Kanalwechsel fehlgeschlagen."
                    self.stop.set()
                    return
                if self.stop.wait(self.dwell):
                    return


def collect(store: Store, interface: str, channels: list[int], dwell: float, host: str, port: int):
    verify_interface(interface)
    stop = threading.Event()
    previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    gps = GPS(host, port)
    hopper = Hopper(interface, channels, dwell, stop) if channels else None
    process = None
    selector = selectors.DefaultSelector()
    sid = store.start("passive")
    anonymizer = Anonymizer()
    count = 0
    try:
        gps.start()
        process = subprocess.Popen(capture_command(interface), stdout=subprocess.PIPE, bufsize=0)
        selector.register(process.stdout, selectors.EVENT_READ)
        if hopper:
            hopper.thread.start()
        print(f"Messlauf {sid}. Abbruch mit Strg+C. Ohne frischen GPS-Fix wird nichts gespeichert.", flush=True)
        last_status = 0.0
        pending = b""
        while not stop.is_set():
            if time.monotonic() - last_status >= 5:
                print(f"GPS: {'OK' if gps.fix() else 'kein frischer Fix'} | gespeicherte Beobachtungen: {count}", flush=True)
                last_status = time.monotonic()
            for key, _ in selector.select(timeout=0.5):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    raise RuntimeError("tshark beendet; Adapter/Berechtigungen prüfen. Details siehe stderr.")
                pending += chunk
                if len(pending) > 1048576:
                    raise RuntimeError("Unerwartet große Ausgabe von tshark")
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    parsed, fix = parse_beacon(line.decode("utf-8", errors="replace")), gps.fix()
                    if parsed and fix:
                        bssid, rssi, freq, security = parsed
                        before = store.db.total_changes
                        store.add(sid, anonymizer.identify(bssid), time.time(), fix, rssi, freq, security)
                        count += store.db.total_changes - before
        if hopper and hopper.error:
            raise RuntimeError(hopper.error)
    finally:
        stop.set()
        selector.close()
        if process:
            if process.stdout:
                process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if hopper and hopper.thread.ident is not None:
            hopper.thread.join(timeout=4)
        gps.close()
        store.finish(sid)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def demo(store: Store) -> str:
    sid = store.start("demo")
    rng = random.Random(42)
    aps = [f"demo-{i:02d}" for i in range(4)]
    for i in range(240):
        for j, ap in enumerate(aps):
            store.add(sid, ap, time.time() - 240 + i,
                      {"lat": 52.52 + i * 0.000005, "lon": 13.405 + i * 0.00001, "accuracy": 4},
                      max(-95, min(-30, int(-40 - abs(i - j * 65) / 4 + rng.gauss(0, 3)))),
                      (2412, 2437, 2462, 5180)[j], "RSN")
    store.finish(sid)
    return sid
