# wifi-map

Passive WLAN-Funkkarte für Raspberry Pi, Alfa-WLAN-Adapter und USB-GPS. Python 3.11+; keine Python-Laufzeitabhängigkeiten.

**Eine Karte von Empfangsbeobachtungen, nicht von Routerstandorten oder internen Netzwerken.** Nur WLAN-Beacons werden ausgewertet. Kein Verbinden mit fremden Netzen, keine Probe-Anfragen, keine Deauthentication, kein Passworttest, kein Mitschnitt von Nutzdaten.

## Schnellstart ohne Hardware

```bash
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/wifi-map demo
.venv/bin/wifi-map serve
```

Den vollständigen Link aus dem Terminal öffnen. Die Demo erzeugt 960 **synthetische** Beobachtungen in Berlin und vier fiktive Zugangspunkte. Keine Funkerfassung. Die Karte hat standardmäßig einen Offline-Rasterhintergrund, ermöglicht Verschieben/Zoomen, Messlauf- und AP-Auswahl sowie GeoJSON-Export. Online-OpenStreetMap-Kacheln sind optional; dabei werden IP-Adresse und Kartenausschnitt an den Kartenanbieter übertragen. Kein Offline-Kacheldownload.

## Raspberry Pi vorbereiten

1. Raspberry Pi OS mit Python 3.11 oder neuer verwenden. Für den konkreten **Alfa-Chipsatz** Linux-Treiber, Monitor-Modus und Radiotap-Signalwerte prüfen. Unterstützung ist nicht allein vom Markennamen abhängig.
2. Benötigte Systempakete installieren:

   ```bash
   sudo apt update
   sudo apt install python3-venv tshark iw gpsd gpsd-clients
   ```

   Bei der Wireshark-Paketkonfiguration dürfen bei Bedarf Mitglieder der Gruppe `wireshark` Pakete erfassen. Nur vertrauenswürdige Benutzer hinzufügen; neu anmelden:

   ```bash
   sudo dpkg-reconfigure wireshark-common
   sudo usermod -aG wireshark "$USER"
   ```

3. USB-GPS in der gpsd-Konfiguration des Systems eintragen, Dienst aktivieren und mit `cgps -s` einen Fix prüfen. Der Gerätename ist häufig `/dev/ttyACM0`, aber muss geprüft werden. gpsd sollte nur lokal erreichbar sein. Ohne frische Position speichert wifi-map **keine** Funkbeobachtungen.
4. Dedizierten Alfa-Adapter auswählen:

   ```bash
   iw dev
   iw list
   iw reg get
   ```

   Die regulatorische Region muss zum tatsächlichen Standort passen. Keine gesperrten Kanäle freischalten. Beispiele verwenden ausschließlich 2,4-GHz-Kanäle; zusätzliche Bänder nur nach Prüfung von Hardware und örtlichen Regeln.
5. Monitor-Schnittstelle vorbereiten. **`wlan1`/`phy1` sind Platzhalter** für den Alfa-Adapter. Der Adapter darf nicht gleichzeitig als normales WLAN verwaltet werden. Beispielsweise bei NetworkManager:

   ```bash
   sudo nmcli device set wlan1 managed no
   sudo ip link set wlan1 down
   sudo iw phy phy1 interface add mon0 type monitor
   sudo ip link set mon0 up
   sudo iw dev mon0 set channel 6
   ```

   Das interne Pi-WLAN nicht abschalten. Bei Systemen ohne NetworkManager muss der tatsächlich zuständige Netzwerkdienst entsprechend konfiguriert werden. Der Messdienst verändert den Monitor-Modus nicht selbst und sendet keine WLAN-Pakete.

## Messlauf

Auf einem fest eingestellten Kanal kann die Erfassung ohne Root laufen, wenn `dumpcap` über die Paketkonfiguration die nötigen Rechte hat:

```bash
.venv/bin/wifi-map capture --interface mon0
```

Mehrere Kanäle erfordern zusätzlich Rechte zum Kanalwechsel. Die einfache Variante für einen vertrauenswürdigen, dedizierten Pi:

```bash
sudo .venv/bin/wifi-map --db "$HOME/.local/share/wifi-map/survey.sqlite3" capture \
  --interface mon0 --channels 1,6,11 --dwell 0.5
```

Dabei werden Dateien zunächst Eigentum von root. Nach dem Messlauf für die unprivilegierte Kartenansicht zurückgeben:

```bash
sudo chown -R "$USER":"$(id -gn)" "$HOME/.local/share/wifi-map"
.venv/bin/wifi-map serve
```

Für Dauerbetrieb stattdessen Benutzerrechte und Diensthärtung gezielt einrichten. Nicht pauschal `sudo` ohne Passwort freigeben. Karte **nicht** als root starten. Adapterabbrüche und nicht erlaubte Kanalwechsel beenden den Messlauf kontrolliert; ein automatischer Hardware-Wiederanlauf ist in dieser Version nicht enthalten.

Statusausgabe alle fünf Sekunden; Strg+C oder SIGTERM beendet den Messlauf. GPS-Daten älter als drei Sekunden oder ohne 2D-Fix werden verworfen. GPS-Genauigkeit wird gespeichert, sofern gpsd sie liefert; sie ist keine garantierte Fehlergrenze. Nach abruptem Stromverlust kann ein Messlauf als unvollendet erscheinen. Frühere Transaktionen bleiben erhalten.

Monitor-Schnittstelle nach dem Einsatz entfernen und normale Verwaltung bei Bedarf wieder aktivieren:

```bash
sudo iw dev mon0 del
sudo nmcli device set wlan1 managed yes
```

## Kartenoberfläche und Fernzugriff

`serve` lauscht ausschließlich auf `127.0.0.1:8080`. Die Daten-API verlangt einen zufälligen Zugriffsschlüssel pro Serverstart. Der Link enthält diesen im URL-Fragment; die Oberfläche entfernt ihn nach dem Laden und hält ihn im Browser-Sitzungsspeicher. Den Link nicht veröffentlichen.

Vom Laptop über eine bereits erlaubte Verbindung zum eigenen Pi:

```bash
ssh -L 8080:127.0.0.1:8080 pi@raspberrypi.local
```

Dann den vom Pi ausgegebenen Link am Laptop öffnen. Ein Smartphone kann einen geeigneten SSH-Tunnel-Client verwenden. Diese Version richtet keinen Hotspot ein und veröffentlicht keinen unverschlüsselten Webdienst im LAN.

Die Karte zeigt genaue Empfangsorte aus der lokalen Datenbank. Maximal 50.000 Punkte pro Messlauf werden geladen; die Oberfläche weist auf diese Grenze hin. Die Online-Kacheln werden nur nach Aktivierung geladen und entsprechend der [OSM-Tile-Nutzungsrichtlinie](https://operations.osmfoundation.org/policies/tiles/) ohne Bulk-Download genutzt. Für größere Einsätze eigenen/geeigneten Kartenanbieter verwenden.

## Daten, Export und Aufbewahrung

Gespeichert: Messlauf-ID, Zeit, GPS-Position/Genauigkeit, Signalstärke, Frequenz, grobe Schutzklasse und eine HMAC-pseudonymisierte BSSID. Der zufällige HMAC-Schlüssel existiert nur im Arbeitsspeicher und wechselt pro Messlauf. Wiedererkennung ist innerhalb eines Messlaufs möglich, nicht absichtlich zwischen Läufen.

**Nicht gespeichert:** SSID, originale BSSID, Client-Adressen, Rohpakete, Nutzdaten. tshark erhält einen Beacon-Capture-Filter und gibt nur fünf ausgewählte Felder aus. Fremde Daten werden nicht als Paketdateien geschrieben. `RSN` unterscheidet nicht WPA2/WPA3; `protected-unknown` ist kein Nachweis einer bestimmten Verschlüsselung. Manche Adapter liefern keine auswertbaren Signalwerte; solche Beobachtungen werden verworfen.

```bash
.venv/bin/wifi-map sessions
.venv/bin/wifi-map export --session MESSLAUF_ID --output karte.geojson
.venv/bin/wifi-map prune --days 7
```

GeoJSON enthält standardmäßig Positionen in einem **100-m-Web-Mercator-Raster** (keine konstanten 100 m Bodenabstand in allen Breitengraden), keine Zeitstempel und keine explizite Laufroute. Reihenfolge, Punktverteilung und Zusatzwissen können trotzdem Rückschlüsse erlauben: **keine Anonymitätsgarantie**, nicht ungeprüft veröffentlichen. `--exact` exportiert präzise Empfangsorte für ausdrücklich private Nutzung. CLI-Exporte überschreiben keine bestehenden Dateien; maximal eine Million Beobachtungen werden exportiert. Web-Exporte verwenden das 50.000-Punkte-Limit.

Alte Messläufe werden beim Start einer Erfassung nach sieben Tagen gelöscht (`--retention-days` konfigurierbar). Für regelmäßiges Löschen ohne neue Erfassung `prune` per Timer ausführen. Löschen aus SQLite ist **keine sichere Löschung auf Flash**; für sensible Nutzung verschlüsselten Speicher einsetzen und Backups berücksichtigen.

Daten liegen unter `$XDG_DATA_HOME/wifi-map` oder `~/.local/share/wifi-map`, Dateirechte `0600`. Mit `--db PFAD` vor dem Unterbefehl lässt sich ein anderer Ort wählen. Messdaten und Exporte sind über `.gitignore` vom Repository ausgeschlossen. Vor jeder Veröffentlichung dennoch prüfen.

## Grenzen und verantwortliche Nutzung

- Nur dort verwenden, wo die Erfassung und Verarbeitung nach den örtlichen Regeln zulässig ist; Speicherung und Veröffentlichung gesondert prüfen.
- Keine vollständige Bestandsaufnahme: Kanalwechsel, Abschattung, Antennenausrichtung und Gehgeschwindigkeit beeinflussen Ergebnisse.
- Keine Router-Ortung, keine Heatmap-Interpolation und keine automatische Einstufung fremder Netze als „unsicher“.
- MVP: keine Status-LEDs/Taster, CSV-Ausgabe, automatische Adapterreparatur oder fertige systemd-Installation.
- Vor einer Tour mit eigenen Zugangspunkten prüfen, ob ausschließlich Beacons erfasst werden, GPS und Frequenzen stimmen und die Stromversorgung stabil ist.

## Entwicklung

```bash
python3 -m unittest discover -s tests -v
node --check wifi_map/static/app.js
```

Tests prüfen Parser, Pseudonymisierung, GPS-Alter/Validierung, Datenbank/Deduplizierung/Löschung, Export sowie HTTP-Zugriffsschutz. Die CI testet Python 3.11–3.14. Echte Adapter, gpsd und Funkmessungen müssen zusätzlich auf dem Pi getestet werden.

MIT-Lizenz, siehe `LICENSE`.
