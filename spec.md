# Spezifikation: Terminalclient für MeshCore (TUI)

* **Projekt:** MeshCore Terminal Client (TUI)
* **Autor / Ersteller:** Christian Fojtzik
* **Stand:** November 2026

---

## 1. Zielsetzung

Es soll ein interaktiver, menügesteuerter MeshCore-Client als leichtgewichtige Terminalanwendung (TUI) bereitgestellt werden.
* **Vollständiger Funktionsumfang:** Der Client soll den gesamten Funktionsumfang von MeshCore abdecken (Messaging, Kanäle, Adressbuch, Repeater, Telemetrie, Node-Konfiguration und freie Befehlsausführung).
* **Menüsteuerung (TUI):** Intuitive Bedienung über Tastatur und Menüs mit der Python-Standardbibliothek `curses` anstelle rein statischer CLI-Befehle.
* **USB-Kommunikation:** Direkte Verbindung mit dem MeshCore-Companion über USB (virtuelle serielle Schnittstelle / UART über `/dev/ttyUSB*` bzw. `/dev/ttyACM*`).

---

## 2. Bedingungen & Plattformanforderungen

* **Hardware- & OS-Kompatibilität:**
  * Volle Unterstützung für ältere **32-Bit x86-Systeme (i386 / i686)** sowie 64-Bit Linux-Systeme.
  * Läuft direkt auf leichtgewichtigen Linux-Installationen (z. B. Debian 12 Bookworm i386, Alpine Linux).
* **Ressourceneffizienz:**
  * Extrem geringer Speicher- und CPU-Bedarf (~25–35 MB RAM).
  * Verzicht auf ressourcenhungrige Web- oder Schwere-Frameworks (kein Electron, kein Textual, keine JavaScript-Runtimes).
* **Upstream-Integrität & Verlässlichkeit:**
  * Nutzung des offiziellen, geprüften GitHub-Projekts **`meshcore-cli`** (≥ v1.6.9).
  * **Wichtige Vorgabe:** Das bestehende `meshcore-cli` darf nicht modifiziert werden. Es wird als stabiles, unverändertes Backend eingebunden.
* **Hardwareunabhängiges Testen:**
  * Integrierter Simulationsmodus (`--simulate`), um das Interface, Menüs und Chatverläufe auch ohne physisch angeschlossenen USB-Companion vollumfänglich bedienen und testen zu können.

---

## 3. Technologie & Architektur

* **Programmiersprache:** **Python 3** (≥ 3.10)
* **Benutzeroberfläche:** **`curses`** (Python-Standardbibliothek)
  * Farb- und Monochromunterstützung mit automatischer Fallback-Erkennung.
  * Dynamische Anpassung an beliebige Fenstergrößen (`KEY_RESIZE`).
  * Absturzsichere Textausgabe (`safe_addstr`) mit Boundary-Clipping.
* **Backend-Integration:**
  * Das bestehende Tool `meshcore-cli` (`meshcli`) wird als Subprozess über die serielle Schnittstelle angesteuert.
  * Strukturierte Datenerfassung (JSON-Modus `-j` wo verfügbar, Text-Parsing für Rückmeldungen).
  * Vollständige Entkopplung der UI vom seriellen I/O-Stack.

### Projektstruktur
```
meshcore_cli_client/
├── run.sh                  # Ausführbares Startskript mit venv-Erkennung
├── requirements.txt        # Externe Abhängigkeiten (meshcore-cli, pyserial)
├── spec.md                 # Projektspezifikation
├── README.md               # Benutzerdokumentation & Bedienungsanleitung
├── src/
│   ├── config.py           # Konfigurationsmanager & Pfadverwaltung
│   ├── main.py             # Startpunkt mit Argument-Parser (-s, -b, --simulate)
│   ├── backend/
│   │   ├── executor.py     # Subprozess-Wrapper um meshcli mit Simulation
│   │   ├── chat_store.py   # Persistenter Chatverlauf & Nachrichtenrouting
│   │   ├── contact_store.py# Verwaltung von gehörten Nodes & gespeicherten Kontakten
│   │   └── mock_data.py    # Realistische Simulationsdaten für alle Bereiche
│   └── ui/
│       ├── colors.py       # Curses-Farbschema & Palettenverwaltung
│       ├── widgets.py      # Dialoge, Eingabemasken, Scrollfenster & Boxen
│       ├── async_task.py   # Nicht blockierende Backend-Hintergrundaufgaben
│       ├── app.py          # Hauptmenü-Controller & Event-Loop
│       └── views/
│           ├── connection.py  # USB-Port-Scan, Baudrate & Verbindungstest
│           ├── node_info.py   # Status, Telemetrie, Uhrzeit & Reboot
│           ├── chat_view.py   # Dual-Pane Chatfenster mit Verlauf & Live-Eingabe
│           ├── messaging.py   # Kanalverwaltung (0–7) & Flood-Scope
│           ├── contacts.py    # Gehörte Nodes & Kontaktliste (Dual-Tab)
│           ├── repeaters.py   # Repeater-Login, Remote-Befehle & Traceroute
│           ├── settings.py    # Radio-Parameter (get/set) & Advertisements
│           └── raw_cli.py     # Unbeschränkte MeshCore-Konsole (100% CLI)
└── tests/
    ├── test_client.py      # Basis- & Konfigurationstests
    ├── test_chat.py        # Tests für Chat-Speicher, Routing & DMs
    ├── test_contacts.py    # Tests für Gehört-Liste, Speichern & Löschen
    ├── test_ui.py          # Curses-, Chat-, Lösch- und Scheduler-Tests
    └── test_auto_refresh.py# Tests für automatische Aktualisierung & Intervalle
```

---

## 4. Funktionsumfang & Menüstruktur

### 1. Verbindungsmanagement (USB / Serial)
* Automatische Erkennung und Priorisierung von USB-Seriell-Geräten (`/dev/ttyUSB*`, `/dev/ttyACM*`) via `pyserial`.
* Konfiguration von Baudrate (115200 Standard, 9600 bis 921600 Baud) und manueller Pfadeingabe.
* Verbindungstest mit direkter Statusrückmeldung des Knotens.
* Umschaltung zwischen echtem USB-Betrieb und Simulationsmodus.

### 2. Node-Informationen & Telemetrie
* Vollständige Abfrage der Geräteinfos (`infos`): Name, MAC-Adresse, Hardware-Typ, LoRa-Frequenz, Bandbreite, Spreading Factor, Sendeleistung und Akkustand.
* Firmware-Versionsabfrage (`ver`).
* Eigene Node-Telemetrie mit Kanalauslastung, Airtime, Sende-/Empfangszählern und Temperatur (`self_telemetry`).
* Hostzeit-Synchronisation (`clock sync`) und kontrollierter Neustart (`reboot`).

### 3. Chatfenster & Verlauf (Kanäle & Direktnachrichten)
* **Dual-Pane-Interface:**
  * **Linke Seitenleiste:** Alle Kanäle (`#Public (0)`, `#Emergency (1)`, etc.) und Direktkontakte (`@Kontaktname`) mit Zählern für empfangene Nachrichten.
  * **Rechter Hauptbereich:** Scrollbarer Chatverlauf mit Zeitstempel (`[HH:MM]`), Absender, Sende-/Empfangsstatus (`[ACK]`, `[RX]`) und Farbkodierung.
  * **Untere Live-Eingabezeile:** Sofortiges Tippen und Absenden ohne blockierende Popup-Dialoge.
* **Zielgerichteter Chat-Start:** Wird ein Kontakt aus der Kontaktliste per `[C]` oder `[Enter]` ausgewählt, öffnet sich das Chatfenster sofort für diesen spezifischen Kontakt.
* **Unterstützung für Namen mit Leerzeichen:** Saubere Adressierung von Kontakten mit komplexen Namen (z. B. `CF T-Deck`).
* **Persistenter Verlauf:** Speicherung des Chatverlaufs in `~/.config/meshcore/chat_history.json`.
* **Sync-Funktion (`[R]`):** Direkter Abruf neuer ungelesener Nachrichten über `sync_msgs`.
* **Automatischer Empfang:** Ungelesene Nachrichten werden zusätzlich im konfigurierbaren `refresh_interval` (standardmäßig 5 Sekunden) nicht blockierend im Hintergrund abgerufen.
* **Nachrichten löschen:** Im Verlaufsfokus kann eine ausgewählte lokale Nachricht mit `[Entf]` / `[X]` oder der komplette lokale Raumverlauf mit `[L]` gelöscht werden. In der Raumliste entfernt `[Entf]` / `[X]` den ausgewählten Chat einschließlich des kompletten lokalen Verlaufs, ohne den Kontakt oder Kanal auf dem Companion zu löschen.

### 4. Kanal- & Scope-Verwaltung
* Konfiguration von bis zu 8 Kanälen (Kanal 0 Public, Kanäle 1–7 für Teams/Gruppen).
* Anzeige konfigurierter Kanäle (`get_channels`) und Zuweisung von Kanalnamen und PSK-Schlüsseln (`set_channel`).
* Löschen der Kanäle 1–7 auf dem Companion (`remove_channel`) einschließlich des zugehörigen lokalen Kanalverlaufs nach Bestätigung.
* Regionale Begrenzung von Paketen über den Flood-Scope (`scope <region>`).

### 5. Gehörte Nodes & Kontaktverwaltung (Dual-Tab)
* **Tab 1: 📡 Gehörte Nodes (Discovered / Pending):**
  * Interaktive Liste über Funk empfangener Knoten (`pending_contacts`, `node_discover`) mit Signalwerten (SNR, RSSI), Knotentyp, Public Key und Zeitstempel.
  * Automatische Aktualisierung der Pending-Liste im konfigurierten Refresh-Intervall; vollständige Discovery beim Öffnen und höchstens alle 30 Sekunden.
  * **Übernahme in Kontakte (`[S]` oder `[Enter]`):** Ausgewählte gehörte Knoten werden mit anpassbarem Namen und Typ direkt in das feste Adressbuch des Nodes übernommen (`add_pending` / `add_contact`).
  * Einzelne gehörte Knoten löschen (`[L]` / `[Entf]`) oder gesamte Liste leeren (`[F]`).
* **Tab 2: 👥 Gespeicherte Kontakte (Contacts):**
  * Übersicht aller gespeicherten Knoten mit Signalwerten, Pfad, Hops und Rollen (`contacts`).
  * Direktsprung in den Chat (`[C]` oder `[Enter]`).
  * Kontaktdetails (`contact_info`), Pfadsuche (`disc_path`), Telemetrieabfrage (`req_telemetry`) und Kontakt-Export als URI (`export_contact`).
  * **Zuverlässiges Löschen (`[L]`, `[Entf]`, `[X]`):** Mehrstufige Löschung über Kontaktnamen mit automatischem Fallback auf den Public-Key-Präfix bei Sonderzeichen.
  * Manuelles Hinzufügen von Kontakten (`[+]`).

### 6. Repeater & Fernverwaltung
* Authentifizierung an Repeatern mit Passwort (`login`, `logout`).
* Senden von Remote-Befehlen an Repeater (`cmd`).
* Abfrage von Betriebsstatus, Solar-/Batteriewerten und Laufzeit (`req_status`).
* Abfrage binärer Nachbarschaftstabellen (`req_neighbours`).
* Multi-Hop Traceroute durch das Mesh-Netzwerk (`trace <pfad>`).

### 7. Node-Einstellungen & Wartung
* Auslesen und Setzen sämtlicher MeshCore-Parameter (`get <param>`, `set <param> <wert>`).
* Vollständige Parameter-Hilfeliste (`get help`).
* Lokales Advertisement (`advert`) und netzsweites Flood-Advertisement (`floodadv`).
* Export der eigenen Node-Card / URI (`card`).

### 8. Direkte MeshCore-Konsole (100% CLI)
* Integrierter Terminal-Runner für ungefilterten Zugriff auf jeden existierenden und zukünftigen `meshcli`-Befehl.
* Eingebettete Befehlshistorie mit Scroll- und Löschfunktion.
* Aufruf der internen `meshcli`-Hilfe (`-h`).

---

## 5. Bedienkonzept & Shortcuts

| Bereich | Tasten | Aktion |
| :--- | :--- | :--- |
| **Allgemein** | `[↑ / ↓]` bzw. `[k / j]` | Navigation durch Menüs und Listen |
| | `[Enter]` / `[Leertaste]` | Auswählen / Bestätigen / Senden |
| | `[1 – 9]` | Direktauswahl von Menüpunkten |
| | `[Esc]` / `[q]` | Zurück zum vorherigen Menü / Beenden |
| **Chatfenster** | `[Tab]` | Fokus wechseln: **Eingabezeile** ⇄ **Raumliste** ⇄ **Verlauf** |
| | `[Enter]` *(in Eingabe)* | Nachricht an aktuellen Raum/Kontakt absenden |
| | `[Enter]` *(in Raumliste)*| Raum/Kontakt aktivieren und Fokus in Eingabezeile setzen |
| | `[R]` | Ungelesene Nachrichten abrufen (`sync_msgs`) |
| | `[N]` | Neuen Chat starten (`@Kontakt` oder `#Kanal`) |
| | `[Entf]` / `[X]` *(in Raumliste)* | Chat und kompletten lokalen Verlauf löschen |
| | `[Entf]` / `[X]` *(im Verlauf)* | Ausgewählte lokale Nachricht löschen |
| | `[L]` | Lokalen Verlauf des aktiven Chats leeren, Chat-Eintrag behalten |
| **Verbindung** | `[6]` | Auto-Refresh-Intervall (2/5/10/30/60 Sekunden) wechseln |
| **Kanalverwaltung** | `[8]` | Kanal 1–7 auf Companion und lokal löschen |
| **Knoten-Verwaltung** | `[Tab]` / `[← / →]` | Umschalten: **Gehörte Nodes** ⇄ **Gespeicherte Kontakte** |
| *(Tab 1: Gehört)* | `[S]` / `[Enter]` | **Ausgewählten Knoten in Kontaktliste speichern** |
| | `[L]` / `[Entf]` / `[X]` | Ausgewählten gehörten Knoten entfernen |
| | `[R]` | Nach neuen Nodes scannen (`node_discover`) |
| | `[F]` | Gesamte Gehört-Liste leeren (`flush_pending`) |
| *(Tab 2: Gespeichert)*| `[C]` / `[Enter]` | **Chat mit dem ausgewählten Kontakt öffnen** |
| | `[L]` / `[Entf]` / `[X]` | **Kontakt sicher löschen** (`remove_contact`) |
| | `[D]` | Kontaktdetails anzeigen (`contact_info`) |
| | `[P]` | Pfad zum Knoten ermitteln (`disc_path`) |
| | `[+]` / `[A]` | Kontakt manuell per Public Key anlegen |
