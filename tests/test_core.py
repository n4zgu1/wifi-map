import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from wifi_map.capture import capture_command, demo
from wifi_map.core import Anonymizer, Store, coarse_position, geojson, parse_beacon, write_export
from wifi_map.gps import GPS


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "survey.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_deduplication_and_finish(self):
        sid = self.store.start("passive")
        for _ in range(2):
            self.store.add(sid, "ap", 1000.5, {"lat": 52.5, "lon": 13.4}, -55, 2412, "RSN")
        self.store.finish(sid)
        self.assertEqual(self.store.sessions()[0]["observations"], 1)
        self.assertIsNotNone(self.store.sessions()[0]["ended"])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_session_local_pseudonyms(self):
        a, b = Anonymizer(), Anonymizer()
        mac = "aa:bb:cc:dd:ee:ff"
        self.assertEqual(a.identify(mac), a.identify(mac.upper()))
        self.assertNotEqual(a.identify(mac), b.identify(mac))
        self.assertNotIn(mac, a.identify(mac))
        with self.assertRaises(ValueError):
            a.identify("invalid")

    def test_beacon_parser(self):
        self.assertEqual(parse_beacon("aa:bb:cc:dd:ee:ff\t-55\t2412\t1\t1\n"),
                         ("aa:bb:cc:dd:ee:ff", -55, 2412, "RSN"))
        self.assertEqual(parse_beacon("aa:bb:cc:dd:ee:ff\t-80\t\t\t0\n")[-1], "open")
        self.assertEqual(parse_beacon("aa:bb:cc:dd:ee:ff\t-80\t2412\t\t1\n")[-1], "protected-unknown")
        for bad in ("", "invalid\t-55\t2412\t1\t1", "aa:bb:cc:dd:ee:ff\t\t2412\t1\t1",
                    "aa:bb:cc:dd:ee:ff\t20\t2412\t1\t1"):
            self.assertIsNone(parse_beacon(bad))

    def test_capture_is_beacons_only(self):
        command = capture_command("mon0")
        self.assertEqual(command[command.index("-f") + 1], "type mgt subtype beacon")
        self.assertNotIn("-w", command)
        self.assertNotIn("wlan.ssid", command)
        self.assertNotIn("-I", command)

    def test_gps_validation_and_expiry(self):
        gps = GPS()
        gps.update({"class": "TPV", "mode": 3, "lat": 52.5, "lon": 13.4, "epx": 4, "epy": 5})
        self.assertEqual(gps.fix()["accuracy"], 5)
        gps.update({"class": "TPV", "mode": 3, "lat": 52.5, "lon": 13.4}, received=time.monotonic() - 10)
        self.assertIsNone(gps.fix())
        for report in ({"mode": 1}, {"mode": 3, "lat": float("nan"), "lon": 1}, {"mode": 3, "lat": 100, "lon": 1}):
            gps.update({"class": "TPV", **report})
            self.assertIsNone(gps.fix())

    def test_pruning_cascades(self):
        sid = self.store.start("passive")
        self.store.add(sid, "ap", 1, {"lat": 0, "lon": 0}, -55, None, "open")
        self.store.db.execute("UPDATE sessions SET started=0 WHERE id=?", (sid,))
        self.store.db.commit()
        self.store.prune(7)
        self.assertEqual(self.store.sessions(), [])
        self.assertEqual(self.store.points(sid), [])

    def test_export_is_coarse_and_has_no_timestamps(self):
        sid = demo(self.store)
        points = self.store.points(sid)
        self.assertEqual(len(points), 960)
        exported = geojson(points)
        p = exported["features"][0]
        self.assertEqual(p["geometry"]["coordinates"], list(reversed(coarse_position(points[0]["lat"], points[0]["lon"]))))
        self.assertNotIn("second", p["properties"])
        self.assertNotIn("session_id", p["properties"])
        exact = geojson(points, exact=True)
        self.assertEqual(exact["features"][0]["geometry"]["coordinates"], [points[0]["lon"], points[0]["lat"]])
        target = Path(self.tmp.name) / "export.geojson"
        write_export(target, exported)
        self.assertEqual(json.loads(target.read_text())["type"], "FeatureCollection")
        with self.assertRaises(FileExistsError):
            write_export(target, exported)


if __name__ == "__main__":
    unittest.main()
