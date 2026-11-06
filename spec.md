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
3. **Nachrichten & Kanäle (Messaging)**
   * Kanal-Nachrichten (öffentlicher Kanal 0 sowie Kanäle 1–7)
   * Direktnachrichten an Kontakte mit Empfangsbestätigung (`wait_ack`)
   * Nachrichtenabruf / -synchronisation (`sync_msgs`, `recv`)
   * Kanalverwaltung (Konfigurieren, Anzeigen, Schlüssel/Namen)
   * Flood-Scope-Verwaltung
4. **Kontaktverwaltung (Contacts)**
   * Kontaktliste mit Signal- und Pfad-Status
   * Kontaktdetails, Pfad-Erkennung (`disc_path`), Reset und manuelle Pfadwahl
   * Telemetrie- und Min/Max/Avg-Abfrage von Sensor-Nodes
   * Kontakt-Export/-Import über URIs
5. **Repeater & Fernverwaltung**
   * Login/Logout bei Repeatern
   * Ausführung von Remote-Befehlen
   * Status- und Nachbarschaftsabfragen (`req_status`, `req_neighbours`)
   * Traceroute-Funktionalität
6. **Node-Einstellungen & Wartung**
   * Parameter auslesen und setzen (`get`/`set`)
   * Senden von Advertisements (Node-Bekanntmachungen)
