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
   * Tastaturbedienung: `[Tab]` zum Wechseln zwischen Räumen, Verlauf und Eingabezeile; `[R]` zum sofortigen Synchronisieren; `[N]` für neuen Chat
   * **Automatischer Nachrichtenempfang:** Neue Nachrichten werden standardmäßig alle 5 Sekunden im Hintergrund abgerufen, ohne die Eingabe zu blockieren
   * **Lokale Nachrichtenverwaltung:** Im Verlaufsfokus mit `[↑/↓]` eine Nachricht auswählen, `[Entf/X]` löscht nur diese Nachricht und `[L]` den kompletten lokalen Raumverlauf. In der Raumliste entfernt `[Entf/X]` den ausgewählten Chat samt komplettem lokalem Verlauf; Kontakt oder Kanal auf dem Companion bleiben unverändert.
   * Persistenter Speicher: Chatverläufe bleiben in `chat_history.json` lokal gespeichert
4. **📻 Kanal- & Scope-Verwaltung:**
   * Anzeige und Einrichtung von Kanälen 1–7 (`get_channels`, `set_channel`)
   * Kanäle 1–7 mit `[8]` löschen (`remove_channel`); entfernt nach Bestätigung auch den lokalen Kanalverlauf
   * Flood-Scope Konfiguration (`scope`)
5. **👥 Gehörte Nodes & Kontaktliste (Dual-Tab Ansicht):**
   * **Tab 1: 📡 Gehörte Nodes:**
     * Interaktive Liste aller über Funk empfangener Knoten (`node_discover`, `pending_contacts`) mit SNR, RSSI, Knotentyp und Timestamp.
     * **Sofort gefüllt:** Gespeicherte Kontakte erscheinen mit dem Zeitpunkt ihres letzten Adverts, den der Companion auch dann speichert, wenn der Client nicht läuft. Die Liste ist nach dem letzten Advert sortiert (neueste zuerst).
     * **Automatische Aktualisierung ohne Ladebildschirm:** Die Ansicht öffnet sofort; Pending-Nodes und Kontakte werden im Hintergrund im konfigurierten Intervall aktualisiert. Eine Discovery läuft direkt nach dem Öffnen und anschließend höchstens alle 30 Sekunden, ebenfalls im Hintergrund – auch der manuelle Scan mit `[R]`. Adverts werden durch die gemeinsame `meshcli`-Sitzung auch zwischen den Aktualisierungen erfasst – sowohl von neuen (Pending-)Nodes als auch von bereits gespeicherten Kontakten. Gespeicherte Nodes sind in der Liste mit `✓` markiert; `[Enter]` öffnet für sie direkt den Chat.
     * **Übernahme in Kontakte (`[S]`):** Speichert einen gehörten Knoten direkt in das feste Adressbuch des MeshCore-Nodes (`add_pending` / `add_contact`).
     * Scan aktualisieren (`[R]`) und Liste leeren (`[F]`).
   * **Auto-Speichern ein/aus (`[M]`, in beiden Tabs):** Schaltet die Companion-Einstellung `manual_add_contacts` um. Ist Auto-Speichern **an** (Firmware-Standard), speichert der Companion jeden gehörten Node sofort als Kontakt. Ist es **aus**, erscheinen neue Nodes nur unter „Gehörte Nodes“ und werden erst mit `[S]` gespeichert. Der aktuelle Zustand steht in der Statusleiste. Die Einstellung wird im Companion gespeichert und gilt auch für andere Apps. Hinweis: Ist `autoadd_config` auf dem Companion gesetzt, speichert er die dort gewählten Node-Typen trotzdem automatisch; der Client weist darauf hin.
   * **Tab 2: 👥 Gespeicherte Kontakte:**
     * Übersicht aller gespeicherten Kontakte mit Signalwerten, Pfad, Hops und Rollen (`contacts`).
     * Direkte Aktionen: Chat starten (`[C/Enter]`), Kontaktdetails (`[D]`), Pfad-Erkennung (`[P]`), Telemetrie (`[T]`), URI-Export (`[E]`), Löschen (`[L / Entf / X]`) und manuell Hinzufügen (`[+]`).
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

Beim ersten Start erstellt das Skript die virtuelle Umgebung und installiert automatisch alle Abhängigkeiten aus `requirements.txt` (einschließlich `pyserial` und `meshcore-cli`). Dafür wird eine Internetverbindung benötigt. Bei späteren Starts werden die Abhängigkeiten nur bei Änderungen oder fehlenden Modulen erneut installiert.

Falls antiX/Debian beim Erstellen der Umgebung einen `venv`- oder `pip`-Fehler meldet, zuerst die benötigten Systempakete installieren:

```bash
sudo apt update
sudo apt install python3-venv python3-pip
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
* **Verbindung `[6]`**: Auto-Refresh-Intervall zwischen 2, 5, 10, 30 und 60 Sekunden wechseln
* **Chat, Raumlistenfokus**: `[Entf/X]` ausgewählten Chat samt komplettem lokalem Verlauf löschen, `[L]` nur den Verlauf leeren und den Eintrag behalten
* **Chat, Verlaufsfokus**: `[↑/↓]` Nachricht auswählen, `[Entf/X]` einzelne lokale Nachricht löschen, `[L]` lokalen Raumverlauf leeren
* **Kanalverwaltung `[8]`**: Kanal 1–7 auf dem Companion und seinen lokalen Verlauf löschen

Das Refresh-Intervall wird in `~/.config/meshcore/tui_config.json` als `refresh_interval` gespeichert. Im Hardwarebetrieb verwendet der Client eine einzige dauerhaft laufende `meshcli`-Sitzung. Alle Befehle werden darin serialisiert; es gibt keine parallelen USB-Zugriffe. Neue Nachrichten werden weiterhin regelmäßig mit `sync_msgs` abgerufen, während Advert- und Nachrichtenereignisse zwischen den Befehlen automatisch zwischengespeichert werden. Noch nicht übernommene Ereignisse werden in `~/.config/meshcore/event_spool.json` gesichert und überstehen dadurch Timeouts, Prozessneustarts und das Beenden des Clients.

---

## 📄 Lizenz

Dieses Projekt steht unter der [MIT-Lizenz](LICENSE).
