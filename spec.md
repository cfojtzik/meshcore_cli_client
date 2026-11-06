# Terminalclient für Meshcore

## 1. Zielsetzung

Es soll ein interaktiver, menügesteuerter Meshcore-Client als Terminalanwendung (TUI) erstellt werden.
* **Vollständiger Funktionsumfang:** Der Client soll den gesamten Funktionsumfang von Meshcore unterstützen (Messaging, Kanäle, Kontakte, Repeater, Telemetrie, Node-Konfiguration).
* **Menüsteuerung (TUI):** Intuitive Bedienung über Tastatur/Menüs (Curses-Interface) statt reiner manueller Shell-Befehle.
* **USB-Kommunikation:** Direkte Kommunikation mit dem Meshcore-Companion über USB (virtuelle serielle Schnittstelle / UART über `/dev/ttyUSB*` bzw. `/dev/ttyACM*`).

## 2. Bedingungen & Plattformanforderungen

* **Architektur:** Volle Unterstützung für ältere 32-Bit x86-Systeme (i386 / i686) unter Linux.
* **Ressourceneffizienz:** Extrem ressourcenschonender Betrieb (geringer RAM- und CPU-Bedarf, keine schweren Web- oder GUI-Frameworks).
* **Verlässlichkeit:** Nutzung des bewährten und geprüften Projekts `meshcore-cli`.

## 3. Gewählte Technologie & Architektur

* **Programmiersprache:** **Python 3** (≥ 3.10)
* **Oberflächenbibliothek:** **`curses`** (Standardbibliothek von Python)
  * Garantiert minimalen Speicherbedarf (~25–35 MB RAM) ohne externe TUI-Schwergewichte (wie Textual oder Electron).
  * Funktioniert auf jedem gängigen Terminal und x86 32-Bit-Linux (z. B. Debian 12 Bookworm i386, Alpine Linux).
* **Backend-Integration:**
  * Das bestehende Projekt **`meshcore-cli`** wird **unverändert** als Backend eingebunden (über dessen CLI/Python-Schnittstelle).
  * Sämtliche Protokoll- und Kommunikationslogiken verbleiben im geprüften `meshcore-cli`.
  * Der neue Client fungiert als komfortables Menü- und Kontrollzentrum für `meshcore-cli`.

## 4. Funktionsumfang & Menüstruktur

1. **Verbindungsmanagement (USB / Serial)**
   * Automatische Erkennung und Auswahl von USB-Seriell-Ports (`/dev/ttyUSB*`, `/dev/ttyACM*`)
   * Konfiguration von Baudrate und Verbindungsstatus
2. **Node-Informationen & Telemetrie**
   * Anzeige der Node-Infos (`infos`), Firmware-Version (`ver`), eigene Telemetrie (`self_telemetry`)
   * Uhrzeit-Synchronisation (`clock sync`) und Neustart (`reboot`)
3. **Chatfenster & Chatverlauf (Kanäle & Direktnachrichten)**
   * Vollwertiges, interaktives Chatfenster mit geteiltem Bildschirm (Dual-Pane)
   * Linke Seitenleiste: Schnellauswahl aller Kanäle (`#Public (0)`, `#1`–`#7`) und Direktkontakte (`@Kontakt`) inkl. Zähler für Nachrichten
   * Hauptbereich: Scrollbarer Chatverlauf mit Zeitstempel, Absender, Empfangsstatus (`[ACK]`, `[RX]`) und Farbhervorhebung
   * Unterer Bereich: Direkte Live-Eingabezeile für unterbrechungsfreies Tippen und Absenden mit `[Enter]`
   * Integrierte Nachrichtensynchronisation (`sync_msgs`) und Speicherung des Chatverlaufs (`chat_history.json`)
4. **Kanal- & Scope-Verwaltung**
   * Kanal-Verwaltung (Konfigurieren, Anzeigen, Schlüssel/Namen für Kanäle 1–7)
   * Flood-Scope-Verwaltung (`scope`)
5. **Gehörte Nodes & Kontaktverwaltung (Interactive Dual-List)**
   * **Tab 1: 📡 Gehörte Nodes (Heard / Discovered):**
     * Interaktive Liste über Funk empfangener/gehörter Knoten (`pending_contacts`, `node_discover`) mit Signalwerten (SNR, RSSI), Knotentyp, Public Key und Zeitstempel.
     * **Übernahme in Kontakte:** Ausgewählte gehörte Knoten können direkt per Tastendruck (`[S]`) mit Namen und Typ in die feste Kontaktliste des MeshCore-Nodes gespeichert werden (`add_pending` / `add_contact`).
     * Scan- und Bereinigungsfunktionen (`node_discover`, `flush_pending`).
   * **Tab 2: 👥 Gespeicherte Kontakte (Contacts):**
     * Übersicht aller gespeicherten Kontakte mit Signalwerten, Pfad, Hops und Rollen.
     * Direkte Aktionen: Chat starten (`[C]`), Kontaktdetails (`contact_info`), Pfad-Erkennung (`disc_path`), Telemetrieabfrage (`req_telemetry`), URI-Export (`export_contact`) und Löschen (`remove_contact`).
6. **Repeater & Fernverwaltung**
   * Login/Logout bei Repeatern
   * Ausführung von Remote-Befehlen
   * Status- und Nachbarschaftsabfragen (`req_status`, `req_neighbours`)
   * Traceroute-Funktionalität
7. **Node-Einstellungen & Wartung**
   * Parameter auslesen und setzen (`get`/`set`)
   * Senden von Advertisements (Node-Bekanntmachungen)
