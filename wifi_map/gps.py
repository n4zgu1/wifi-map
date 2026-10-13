from __future__ import annotations

import json
import math
import socket
import threading
import time


class GPS:
    def __init__(self, host="127.0.0.1", port=2947):
        self.host, self.port = host, port
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def update(self, report: dict, received: float | None = None):
        if report.get("class") != "TPV":
            return
        with self.lock:
            self.latest = None
            try:
                if int(report.get("mode", 0)) < 2:
                    return
                lat, lon = float(report["lat"]), float(report["lon"])
                if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    return
                errors = [float(report[k]) for k in ("epx", "epy") if k in report]
                accuracy = max(errors) if errors and all(math.isfinite(v) and v >= 0 for v in errors) else None
                self.latest = {"lat": lat, "lon": lon, "accuracy": accuracy,
                               "received": time.monotonic() if received is None else received}
            except (ValueError, TypeError, KeyError):
                return

    def fix(self, max_age=3.0) -> dict | None:
        with self.lock:
            if self.latest and time.monotonic() - self.latest["received"] <= max_age:
                return dict(self.latest)
        return None

    def _run(self):
        while not self.stop.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=2) as sock:
                    sock.settimeout(2)
                    sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    pending = b""
                    while not self.stop.is_set():
                        try:
                            chunk = sock.recv(8192)
                        except socket.timeout:
                            continue
                        if not chunk:
                            break
                        pending += chunk
                        if len(pending) > 262144:
                            raise ValueError("GPS report too large")
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            try:
                                report = json.loads(line)
                                if isinstance(report, dict):
                                    self.update(report)
                            except (ValueError, UnicodeDecodeError):
                                continue
            except (OSError, ValueError):
                pass
            with self.lock:
                self.latest = None
            self.stop.wait(2)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
