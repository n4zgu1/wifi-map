import json
from pathlib import Path
import re
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request


class WebTests(unittest.TestCase):
    def test_auth_host_static_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "survey.sqlite3")
            subprocess.run([sys.executable, "-m", "wifi_map.cli", "--db", db, "demo"], check=True, capture_output=True)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            proc = subprocess.Popen([sys.executable, "-m", "wifi_map.cli", "--db", db, "serve", "--port", str(port)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(timeout=10), "Server startup timed out")
                line = proc.stdout.readline()
                token = re.search(r"#token=(\S+)", line).group(1)
                base = f"http://127.0.0.1:{port}"
                with urllib.request.urlopen(base) as response:
                    self.assertIn(b"wifi-map", response.read())
                    self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + "/api/sessions")
                self.assertEqual(error.exception.code, 401)
                error.exception.close()
                req = urllib.request.Request(base + "/api/sessions", headers={"Authorization": "Bearer " + token})
                with urllib.request.urlopen(req) as response:
                    sessions = json.load(response)
                self.assertEqual(sessions[0]["observations"], 960)
                req = urllib.request.Request(base + "/api/export?session=" + sessions[0]["id"], headers={"Authorization": "Bearer " + token})
                with urllib.request.urlopen(req) as response:
                    self.assertEqual(len(json.load(response)["features"]), 960)
                req = urllib.request.Request(base + "/", headers={"Host": "evil.example"})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(req)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            finally:
                proc.send_signal(signal.SIGINT)
                proc.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
