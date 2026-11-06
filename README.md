# MeshCore Terminal Client (TUI)

Ein ressourcenschonender, menügesteuerter Terminal-Client für **MeshCore**, optimiert für Linux-Systeme inklusive älterer **32-Bit x86**-Hardware (i386 / i686).

* **Autor:** Christian Fojtzik
* **Technologie:** Python 3 (≥ 3.10) mit Python-Standardbibliothek `curses`
* **Backend:** Basiert auf dem geprüften und unveränderten `meshcore-cli` (v1.6.9+)

---

## 🎯 Highlights

* **100% Funktionsumfang:** Greift auf das offizielle, geprüfte `meshcore-cli` zu, ohne dessen Code zu modifizieren.
* **Menügesteuertes Curses-Interface:** Klare Menüführung mit Zifferntasten (1–8) und Pfeiltasten, kein manuelles Tippen komplexer Parameterketten nötig.
* **Extrem ressourcenschonend:** Minimaler Speicherverbrauch (~25–35 MB RAM) durch Verzicht auf schwere TUI-Frameworks (kein Electron, kein Textual).
* **32-Bit x86 & 64-Bit Linux:** Läuft direkt auf leichtgewichtigen Linux-Installationen (z. B. Debian 12 i386, Alpine Linux).
* **Integrierter Simulationsmodus:** Ermöglicht das Testen und Erkunden aller Menüs, Dialoge und Features auch ohne angeschlossenen physischen USB-Companion.

---

## 📋 Funktionsübersicht

1. **🔌 Verbindung & USB-Ports:**
   * Automatische Erkennung und Auflistung von USB-Seriell-Geräten (`/dev/ttyUSB*`, `/dev/ttyACM*`)
   * Konfiguration von Baudrate (Standard: 115200) und manueller Port-Eingabe
   * Verbindungstest mit Rückmeldung
2. **ℹ️ Node-Status & Telemetrie:**
   * Abfrage von Gerätename, Hardware, Frequenz, Sendeleistung und Akkustand (`infos`)
   * Firmware-Version (`ver`) und detaillierte Telemetrie (`self_telemetry`)
   * Uhrzeitsynchronisation mit dem Hostsystem (`clock sync`) und Neustart (`reboot`)
3. **💬 Chatfenster & Verlauf (Kanäle & Direktnachrichten):**
   * Vollwertiges, interaktives Chatfenster mit geteiltem Terminal-Bildschirm (Dual-Pane)
   * Linke Leiste: Räume (`#Public (0)`, `#Emergency (1)`, `#Local-Team (2)`) und Kontakte (`@BaseStation-1`, `@Mobile-Bravo`) mit Nachrichten-Zählern
   * Rechter Verlauf: Scrollbare Historie mit Zeitstempeln (`[12:01]`), Absendern, Sendestatus (`[ACK]`, `[RX]`) und Farbkennzeichnung
   * Untere Live-Eingabe: Sofortiges Tippen und Absenden mit `[Enter]`
   * Tastaturbedienung: `[Tab]` zum Wechseln zwischen Räumen, Verlauf und Eingabezeile; `[R]` zum Synchronisieren unread Messages; `[N]` für neuen Chat
   * Persistenter Speicher: Chatverläufe bleiben in `chat_history.json` lokal gespeichert
4. **📻 Kanal- & Scope-Verwaltung:**
   * Anzeige und Einrichtung von Kanälen 1–7 (`get_channels`, `set_channel`)
   * Flood-Scope Konfiguration (`scope`)
5. **👥 Kontakte & Pfadverwaltung:**
   * Übersicht aller bekannten Knoten mit RSSI-, SNR- und Hop-Zahlen (`contacts`)
   * Pfadsuche / Path Discovery (`disc_path`) und Pfad-Reset (`reset_path`)
   * Direktsprung in den Chat mit Kontakten (`[C]`)
   * Telemetrieabfrage entfernter Knoten (`req_telemetry`)
   * Kontakt-Export und -Import über URIs (`export_contact`, `import_contact`)
6. **📡 Repeater & Fernverwaltung:**
   * Authentifizierung an Repeatern (`login`, `logout`)
   * Ausführung entfernter Befehle (`cmd`)
   * Status- und Nachbarschaftsabfrage (`req_status`, `req_neighbours`)
   * Traceroute durch das Mesh-Netzwerk (`trace`)
7. **⚙️ Node-Einstellungen & Advert:**
   * Auslesen und Anpassen von Radio- und Node-Parametern (`get`, `set`)
   * Lokales Advertisement (`advert`) und Flood-Advertisement (`floodadv`)
   * Export der eigenen Node-Card (`card`)
8. **💻 Direkte MeshCore Konsole:**
   * 100% ungefilterter Zugriff auf jeden beliebigen `meshcli`-Befehl und erweiterte Skripte direkt aus dem Terminal.

---

## 🚀 Installation & Start

### Voraussetzungen
* Python 3.10 oder neuer
* USB-Verbindung zum MeshCore Companion-Radio (z. B. Heltec LoRa 32, LilyGO T-Beam, ESP32-S3)

### Schnelle Einrichtung
```bash
# Repository-Verzeichnis betreten
cd meshcore_cli_client

# Starten (erstellt oder nutzt automatisch die virtuelle Umgebung .venv)
./run.sh
```

### Starten im Simulationsmodus (ohne USB-Hardware)
```bash
./run.sh --simulate
```

### Manueller Start mit bestimmtem Port
```bash
./run.sh -s /dev/ttyUSB0 -b 115200
```

---

## ⌨️ Tastatursteuerung

* **Pfeiltasten [↑ / ↓]** oder **[j / k]**: Menüelemente auswählen
* **[Enter]** oder **[Leertaste]**: Menüpunkt aufrufen / Aktion bestätigen
* **Zifferntasten [1–8]**: Direktanwahl von Menüoptionen
* **[Esc]** oder **[q]**: Zurück zum vorherigen Menü / Beenden
* **[PgUp / PgDn]**: Scrollen in langen Textanzeigen
