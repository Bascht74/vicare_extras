# ViCare Extras

Eine kleine Zusatz-Integration für Home Assistant, die mehr Daten aus einer
bestehenden **Viessmann-ViCare**-Einrichtung sichtbar macht.

ViCare Extras ersetzt die eingebaute Integration `vicare` nicht, sondern läuft
daneben (eigene Domain `vicare_extras`). Sie verwendet die Anmeldung, die die
eingebaute Integration bereits hergestellt hat, und braucht deshalb keine
eigenen Zugangsdaten.

- **Nur lesend.** Es werden nie Befehle an die Heizung geschickt.
- **Keine eigenen regelmäßigen API-Abfragen.** Die Sensoren lesen ausschließlich
  Daten, die die eingebaute Integration ohnehin schon abgerufen hat.
- **Ereignishistorie nur auf Anforderung**, über eine Aktion.

> Entwickelt und geprüft gegen den Quelltext von Home Assistant Core 2026.11.1
> und PyViCare 2.63.0. Die Integration wurde **nicht** gegen die echte
> Viessmann-API und nicht in einer laufenden Home-Assistant-Instanz getestet
> (siehe [Teststand](#teststand)).

## Was sie bereitstellt

### Sensoren

Je Heizgerät (Gerätetyp `heating`), jeweils nur, wenn das zugrunde liegende
Feature in den Viessmann-Daten vorhanden ist:

| Sensor | Zustand | Attribute | Viessmann-Feature |
| --- | --- | --- | --- |
| Stromverbrauch Warmwasser Verlauf | heutiger Wert (kWh) | `day`, `week`, `month`, `year`, `*_value_read_at` | `heating.power.consumption.dhw` |
| Stromverbrauch Heizung Verlauf | heutiger Wert (kWh) | wie oben | `heating.power.consumption.heating` |
| Stromverbrauch gesamt Verlauf | heutiger Wert (kWh) | wie oben | `heating.power.consumption.total` |
| Wärmeerzeugung Warmwasser | aktueller Tag (kWh) | `current_day`, `current_month`, `current_year`, `last_month`, `last_seven_days` (und `last_year`, falls geliefert) | `heating.heat.production.summary.dhw` |
| Wärmeerzeugung Heizung | aktueller Tag (kWh) | wie oben | `heating.heat.production.summary.heating` |
| Meldungen | Code der neuesten Statusmeldung | `status`, `info`, `service` (Listen mit `errorCode`, `timestamp`, `priority`), `*_count`, `newest_status_timestamp` | `device.messages.status.raw`, `.info.raw`, `.service.raw` |

Hinweise zu den Sensoren:

- Die Listen stehen in der Reihenfolge der Viessmann-API: der **erste** Wert ist
  der aktuelle Zeitraum (`day[0]` = heute, `day[1]` = gestern, `month[0]` =
  laufender Monat usw.).
- Die Meldungslisten sind nach Zeitstempel sortiert (neueste zuerst) und auf je
  25 Einträge begrenzt; `status_count` usw. nennen die Gesamtzahl.
- Die Sensoren hängen am **selben Gerät** wie die Entitäten der eingebauten
  Integration. Wird dieses Gerät nicht gefunden, entstehen die Sensoren ohne
  Gerät; ein zweites Gerät wird nie angelegt.
- Die Energiesensoren haben bewusst **keine `state_class`** und liefern damit
  keine Langzeitstatistik: Der Wert beginnt täglich neu, und die API verrät
  nicht, wann genau. `total_increasing` würde jede Korrektur der Viessmann-Werte
  als Zählerrücksetzung deuten, `total` bräuchte einen exakten
  Rücksetz-Zeitpunkt, `measurement` ist für Energie nicht erlaubt. Für das
  Energie-Dashboard bitte die Sensoren der eingebauten Integration verwenden.
- Die Listen-Attribute werden nicht in der Recorder-Datenbank gespeichert
  (sie stünden sonst bei jeder Änderung erneut darin). Im aktuellen Zustand
  sind sie vollständig vorhanden, z. B. für Templates und Diagramm-Karten.
- Die Werte erscheinen bis zu etwa eine Minute später als bei der eingebauten
  Integration.

### Aktion `vicare_extras.get_features`

Gibt die rohen Feature-Objekte eines Geräts zurück – aus den Daten, die die
eingebaute Integration im Speicher hält. **Löst nie einen API-Aufruf aus.**

| Feld | Bedeutung |
| --- | --- |
| `device_id` | Gerät der Integration Viessmann ViCare (Geräteauswahl) |
| `vicare_device_id` | Viessmann-Geräte-ID, z. B. `0`, `TCU`, `gateway` oder `RoomControl-1`; findet auch Geräte, die die eingebaute Integration nicht einrichtet |
| `device_type` | Viessmann-Gerätetyp, z. B. `heating`, `tcu`, `roomControl` |
| `prefix` | nur Features, deren Name so beginnt, z. B. `heating.power.consumption` |
| `full` | `true`: vollständige Objekte samt `commands` und `uri`; Standard: nur `feature`, `timestamp`, `isEnabled`, `isReady`, `properties` |

Ohne Geräteangabe wird das Heizgerät genommen.

```yaml
action: vicare_extras.get_features
data:
  prefix: heating.power.consumption
response_variable: ergebnis
```

Antwort (gekürzt):

```yaml
source: cache
api_calls: 0
count: 3
devices:
  - device_id: "0"
    device_type: heating
    model: E3_Vitocal_16
    installation_id: "1234567"
    gateway_serial: "7571381500000001"
    cache_age_seconds: 12.4
    count: 3
    features:
      - feature: heating.power.consumption.dhw
        timestamp: "2026-11-12T08:00:00.000Z"
        isEnabled: true
        isReady: true
        properties:
          day: {type: array, unit: kilowattHour, value: [2.6, 5.8, 3.5]}
```

Alle Features des Raumreglers:

```yaml
action: vicare_extras.get_features
data:
  vicare_device_id: RoomControl-1
response_variable: ergebnis
```

Die Aktionen liefern nur eine Antwort. In den Entwicklerwerkzeugen unter
„Aktionen“ wird sie direkt angezeigt; in Skripten und Automationen ist
`response_variable` nötig.

### Aktion `vicare_extras.get_event_history`

Ruft die Ereignishistorie einer Anlage aus der Viessmann-Cloud ab
(`GET /iot/v2/eventhistory/installations/{id}/events`).
**Jede abgerufene Seite ist ein API-Aufruf.**

| Feld | Standard | Bedeutung |
| --- | --- | --- |
| `last_n_days` | 30 | Zeitraum in Tagen (1–365) |
| `limit` | 1000 | Ereignisse pro Seite (1–1000) |
| `max_pages` | 5 | Höchstzahl Seiten = Höchstzahl API-Aufrufe (1–20) |
| `event_type` | – | Ereignistyp(en). Ein einzelner Typ wird von der API gefiltert, mehrere werden nach dem Abruf gefiltert |
| `gateway_serials` | – | Gateway-Seriennummer(n), wird als `gatewaySerials` übergeben |
| `edited_by` | – | wird als `editedBy` übergeben |
| `installation_id` | erste Anlage | Anlagen-ID |
| `cursor` | – | setzt einen früheren Aufruf mit dessen `next_cursor` fort |

Alles der letzten 7 Tage, höchstens ein API-Aufruf:

```yaml
action: vicare_extras.get_event_history
data:
  last_n_days: 7
  max_pages: 1
response_variable: historie
```

Nur Statusmeldungen des Geräts:

```yaml
action: vicare_extras.get_event_history
data:
  last_n_days: 30
  max_pages: 1
  event_type: device-message-status
  gateway_serials: "7571381500000001"   # eigene Seriennummer, siehe unten
response_variable: historie
```

Antwort:

```yaml
installation_id: "1234567"
endpoint: /eventhistory/installations/1234567/events
count: 42            # Anzahl zurückgegebener Ereignisse (nach Filter)
fetched_count: 42    # Anzahl abgerufener Ereignisse (vor lokalem Filter)
pages: 1
api_calls: 1         # so viele Aufrufe hat dieser Abruf verbraucht
truncated: false     # true: max_pages erreicht, es gibt weitere Seiten
next_cursor: null    # für die Fortsetzung über das Feld cursor
known_gateway_serials: ["7571381500000001"]
events:
  - eventType: device-message-status
    createdAt: "2026-11-12T07:30:01.000Z"
    eventTimestamp: "2026-11-12T07:30:00.000Z"
    gatewaySerial: "7571381500000001"
    body: {...}
```

Die eigene Gateway-Seriennummer steht in jeder Antwort unter
`known_gateway_serials` (und in der Antwort von `get_features` unter
`gateway_serial`).

Bekannte Ereignistypen laut Viessmann-Dokumentation – Anlagenebene:
`installation-address-changed`, `invitation-accepted`, `invitation-terminated`,
`geofencing-activation-changed`, `diy-heating-rod-run-too-long`,
`diy-heating-curve-not-optimal`, `diy-dhw-schedule-not-optimal`,
`dynamic-smart-tip`, `snapshot-restore-status-changed`; Gateway-Ebene (Filter
über `gateway_serials`): `gateway-online`, `device-bmu-serial-changed`,
`device-boiler-serial-changed`, `device-error`, `firmware-update-status`,
`gateway-reset-command`, `device-message-info`, `device-message-service`,
`device-message-status`, `device-message-warning`, `feature-changed`,
`src-status-changed`, `remote-diagnose-session-opened`,
`remote-diagnose-session-closed`.

Beispiel: Ereignisse einmal täglich holen und die Anzahl melden.

```yaml
automation:
  - alias: ViCare Ereignisse des Tages
    triggers:
      - trigger: time
        at: "06:30:00"
    actions:
      - action: vicare_extras.get_event_history
        data:
          last_n_days: 1
          max_pages: 1
        response_variable: historie
      - action: persistent_notification.create
        data:
          title: ViCare
          message: "{{ historie.count }} Ereignisse in den letzten 24 Stunden"
```

## API-Limit

Der kostenlose Viessmann-Zugang erlaubt **1450 Aufrufe in 24 Stunden**. Dieses
Kontingent teilt sich ViCare Extras mit der eingebauten Integration.

- Die eingebaute Integration fragt (Stand Core 2026.11.1) je Gateway **alle 60
  Sekunden** einmal ab – das sind bis zu **1440 Aufrufe pro Tag** bei einem
  Gateway. Weil das Intervall erst nach Abschluss jeder Abfrage neu beginnt,
  sind es in der Praxis etwas weniger. Dazu kommen einige Aufrufe bei jedem
  Neustart oder Neuladen. **Die Reserve ist also klein.**
- Sensoren und `get_features`: **0 Aufrufe**, immer.
- `get_event_history`: **1 Aufruf je Seite**, höchstens `max_pages`. Falls der
  dokumentierte Pfad mit „nicht gefunden“ antwortet, kommt einmalig 1 Aufruf
  für den Ausweichpfad hinzu; der funktionierende Pfad wird bis zum nächsten
  Neustart gemerkt.

Empfehlung: `max_pages: 1` verwenden, die Aktion nicht in kurzen Abständen
automatisieren und `api_calls` in der Antwort beachten. Ist das Limit
erschöpft, meldet die Aktion das mit dem Zeitpunkt der Rücksetzung – und auch
die eingebaute Integration bekommt bis dahin keine Daten mehr.

## Installation

Voraussetzungen: Home Assistant **2026.11.1 oder neuer**, die Integration
**Viessmann ViCare** ist eingerichtet und geladen.

### Über HACS (benutzerdefiniertes Repository)

Dafür muss dieser Ordner in einem eigenen GitHub-Repository liegen.

1. HACS öffnen → Menü oben rechts (⋮) → **Benutzerdefinierte Repositories**.
2. Die URL des GitHub-Repositorys eintragen, Typ **Integration**, hinzufügen.
3. In HACS nach **ViCare Extras** suchen und **Herunterladen**.
4. Home Assistant **neu starten** (Einstellungen → System → Neu starten).
5. Weiter bei [Einrichtung](#einrichtung).

### Manuell

1. Den Ordner `custom_components/vicare_extras` aus diesem Repository nach
   `/config/custom_components/vicare_extras` kopieren (z. B. mit dem Add-on
   „Samba share“, „File editor“ oder „Studio Code Server“). Existiert
   `/config/custom_components` noch nicht, den Ordner anlegen.
   Danach muss es die Datei
   `/config/custom_components/vicare_extras/manifest.json` geben.
2. Home Assistant **neu starten**.
3. Weiter bei [Einrichtung](#einrichtung).

### Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen**.
2. Nach **ViCare Extras** suchen und auswählen.
3. Den Dialog bestätigen. Eingaben sind nicht nötig.

Die Sensoren erscheinen danach beim Gerät der Wärmepumpe, die Aktionen unter
**Entwicklerwerkzeuge → Aktionen**.

### Entfernen

Integrationseintrag löschen, dann den Ordner
`/config/custom_components/vicare_extras` entfernen (bzw. in HACS entfernen)
und neu starten. Die eingebaute Integration bleibt unberührt.

## Grenzen

- **Die Ereignishistorie reicht nur so weit zurück, wie das Gateway online
  ist.** Für die Zeit davor hat die Viessmann-Cloud keine Ereignisse; ein neu
  in Betrieb genommenes Gateway liefert entsprechend wenig. `last_n_days` kann
  daran nichts ändern.
- **Abhängigkeit von Interna.** ViCare Extras greift auf interne Strukturen der
  eingebauten Integration (`runtime_data`) und auf den internen
  Zwischenspeicher von PyViCare (`_cache`) zu. Ein Home-Assistant-Update kann
  das brechen. In dem Fall werden die Sensoren „nicht verfügbar“ bzw. die
  Einrichtung wird wiederholt und die Aktionen melden einen klaren Fehler; die
  eingebaute Integration wird davon nicht beeinträchtigt.
- Sensoren gibt es nur für Geräte vom Typ `heating`, die die eingebaute
  Integration einrichtet. `get_features` erreicht alle Geräte des Kontos.
- Features auf Gateway-Ebene, die keinem Gerät zugeordnet sind (z. B.
  `gateway.devices`), gibt `get_features` nicht zurück.
- Hält die eingebaute Integration gerade keine Daten (kurz während ihrer
  minütlichen Abfrage oder bei einer Störung der Viessmann-API), wartet
  `get_features` einige Sekunden und meldet sonst einen Fehler, statt selbst
  abzufragen. Die Sensoren behalten ihren letzten Wert bis zu 15 Minuten.
- Von der Ereignishistorie wird nur die Version `v2` verwendet. `v3`, die
  Parameter `date`, `timestamp` und `origins` sowie die Export-Schnittstelle
  sind nicht umgesetzt.
- Wie mehrere Werte für `gatewaySerials` zu übergeben sind, ist nicht
  dokumentiert; mehrere Seriennummern werden durch Komma getrennt gesendet.
- Der genaue Aufbau der Ereignisse (`body`) wird unverändert durchgereicht.

## Fehlersuche

- **„Die Integration Viessmann ViCare ist nicht eingerichtet oder nicht
  geladen“**: zuerst die eingebaute Integration in Ordnung bringen (z. B.
  erneut anmelden oder das Ende einer Limit-Sperre abwarten).
- **„… passt nicht zur installierten Home-Assistant-Version“**: Die Interna
  haben sich geändert; ViCare Extras muss angepasst werden.
- **Einrichtung wird wiederholt / Sensoren fehlen**: Unter Einstellungen →
  Geräte & Dienste → ViCare Extras → ⋮ → **Diagnose herunterladen** steht, ob
  Daten gefunden wurden und welche der Features vorhanden sind. Die Diagnose
  enthält keine Token, Seriennummern oder Anlagen-IDs.
- Ausführliche Protokollierung:

  ```yaml
  logger:
    logs:
      custom_components.vicare_extras: debug
  ```

  ViCare Extras protokolliert nie Token. Achtung: Das Debug-Protokoll von
  `PyViCare` selbst (Logger `PyViCare`) enthält vollständige API-Antworten.

## Teststand

Ausgeführt (ohne Home Assistant, ohne Netzwerk):

- `python -m py_compile` für alle Dateien unter Python 3.13 und 3.14,
- `python scripts/check_consistency.py` (JSON, Übersetzungen en/de,
  Fehlertexte und Platzhalter, `services.yaml`, Icons, Manifest),
- `python scripts/check_ha_imports.py <core-checkout>` gegen Core 2026.11.1
  (alle importierten Home-Assistant-Namen existieren dort),
- `pytest tests/unit`: Logik der Aktionen, des Koordinators und der Sensoren
  mit nachgebildeten PyViCare-Objekten gegen **vereinfachte Nachbildungen** von
  Home Assistant (`tests/unit/stubs`); mit `PYVICARE_SRC=<PyViCare-Checkout>`
  zusätzlich gegen den echten PyViCare-Code 2.63.0 (Cache-Verhalten,
  Fehlerbehandlung von `get()`).

Nicht ausgeführt:

- `pytest tests/ha` (Tests mit echtem Home Assistant; benötigt
  `pytest-homeassistant-custom-component` und `PyViCare`),
- jeder Test gegen die echte Viessmann-API oder eine laufende Instanz.

`tests/unit` und `tests/ha` müssen getrennt gestartet werden.

## Lizenz

MIT, siehe [LICENSE](LICENSE). Kein offizielles Produkt von Viessmann oder
Home Assistant.
