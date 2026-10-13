from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .capture import collect, demo
from .core import Store, default_db, geojson, write_export
from .web import serve


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Passive WLAN-Karte mit GPS; keine SSIDs, keine Client-Daten.")
    parser.add_argument("--db", type=Path, default=default_db())
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture", help="Passiver Messlauf auf vorhandener Monitor-Schnittstelle")
    capture.add_argument("--interface", required=True)
    capture.add_argument("--channels", default="", help="Explizite erlaubte Kanäle, z.B. 1,6,11; leer = aktueller Kanal")
    capture.add_argument("--dwell", type=float, default=0.5)
    capture.add_argument("--gps-host", default="127.0.0.1")
    capture.add_argument("--gps-port", type=int, default=2947)
    capture.add_argument("--retention-days", type=int, default=7)
    web = sub.add_parser("serve", help="Lokale, zugriffsgeschützte Kartenoberfläche")
    web.add_argument("--port", type=int, default=8080)
    sub.add_parser("demo", help="Synthetischen Messlauf ohne Hardware erzeugen")
    sub.add_parser("sessions", help="Messläufe auflisten")
    export = sub.add_parser("export", help="GeoJSON exportieren, standardmäßig vergröbert")
    export.add_argument("--session", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--exact", action="store_true", help="ACHTUNG: genaue Empfangsorte exportieren")
    prune = sub.add_parser("prune", help="Alte Messläufe löschen (kein sicheres Löschen auf Flash)")
    prune.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    store = None
    try:
        if args.command == "serve":
            if not 1 <= args.port <= 65535:
                raise ValueError("Port muss zwischen 1 und 65535 liegen")
            serve(args.db, args.port)
            return
        store = Store(args.db)
        if args.command == "capture":
            channels = [int(c.strip()) for c in args.channels.split(",") if c.strip()]
            if any(not 1 <= c <= 233 for c in channels) or not 0.1 <= args.dwell <= 10:
                raise ValueError("Ungültige Kanäle oder Verweildauer (0,1–10 s)")
            if args.retention_days < 1:
                raise ValueError("Aufbewahrungsfrist muss mindestens einen Tag betragen")
            store.prune(args.retention_days)
            collect(store, args.interface, channels, args.dwell, args.gps_host, args.gps_port)
        elif args.command == "demo":
            print(demo(store))
        elif args.command == "sessions":
            for s in store.sessions():
                print(f"{s['id']}  {s['mode']}  {s['observations']} Beobachtungen  {s['access_points']} APs")
        elif args.command == "export":
            points = store.points(args.session, limit=1000000)
            if not points:
                raise ValueError("Messlauf nicht vorhanden oder leer")
            write_export(args.output, geojson(points, exact=args.exact))
            print(args.output)
        elif args.command == "prune":
            if args.days < 1:
                raise ValueError("Aufbewahrungsfrist muss mindestens einen Tag betragen")
            store.prune(args.days)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    main()
