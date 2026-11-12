# ViCare Extras

Eine kleine Zusatz-Integration für Home Assistant, die mehr Daten aus einer
bestehenden **Viessmann-ViCare**-Einrichtung sichtbar macht.

ViCare Extras ersetzt die eingebaute Integration `vicare` nicht, sondern läuft
daneben (eigene Domain `vicare_extras`). Sie verwendet die Anmeldung, die die
eingebaute Integration bereits hergestellt hat, und braucht deshalb keine
eigenen Zugangsdaten.

- **Nur lesend.** Es werden nie Befehle an die Heizung geschickt.
- **Keine eigenen regelmäßigen API-Abfragen.** Alle Sensoren lesen
  ausschließlich Daten, die die eingebaute Integration ohnehin schon abgerufen
  hat.
- **Ereignishistorie nur auf Anforderung**, über eine Aktion.
- **Meldungen im Klartext.** Statusmeldungen (S), Informationen (I), Warnungen
  (A), Wartungsmeldungen (P) und Störungen (F) werden anhand der
  Viessmann-Serviceanleitung dekodiert.

## Was live bestätigt ist

Stand 12.11.2026, Home Assistant OS mit Core 2026.11.1, Vitocal 250-A, mit
Version 0.1.0:

- Installation über den Marketplace, Einrichtung **ohne Neustart**, Eintrag
  „geladen“.
- Die Sensoren hängen am vorhandenen Gerät der eingebauten Integration
  (Bereich wird übernommen).
- Beide Aktionen funktionieren. `get_features` liest aus dem Zwischenspeicher
  (0 API-Aufrufe).
- `get_event_history` funktioniert über den Pfad
  `/events-history/installations/{id}/events`. Der in der Viessmann-API-
  Dokumentation genannte Pfad `/eventhistory/…` antwortete mit „nicht
  gefunden“. Ereignisse der Gateway-Ebene kommen auch ohne `gateway_serials`.

Mit Version 0.2.0 (gleicher Stand, nach einem Neustart von Home Assistant):

- 46 Sensoren und 18 Binärsensoren werden am Gerät der eingebauten
  Integration angelegt, ohne Fehler im Protokoll.
- Betriebszustand, 4/3-Wege-Ventil, aktive Statusmeldungen und die
  Meldungsdekodierung liefern plausible Werte.
- `get_event_history` liefert die Ereignisse mit Klartext (`decoded`,
  `summary`) über einen API-Aufruf.
- Ein Update über den Marketplace wird erst nach einem **Neustart von Home
  Assistant** wirksam; ein Neuladen des Eintrags genügt nicht.

Bekannte Einschränkungen:

- Die Zeitstempel in `device.messages.*.raw` sind offenbar die Uhrzeit des
  Geräts (Ortszeit, als UTC gekennzeichnet). Die Zeiten in den Attributen der
  Meldungs-Sensoren können deshalb um die Zeitzone und die Abweichung der
  Geräteuhr verschoben sein. Die Ereignishistorie ist davon nicht betroffen.
- Raum-Entitäten konnten nur gegen nachgebaute Daten geprüft werden, siehe
  [Teststand](#teststand).

## Entitäten

Entitäten entstehen nur, wenn das zugrunde liegende Feature in den
Viessmann-Daten vorhanden ist, und kommen automatisch hinzu, wenn es später
auftaucht. Was die eingebaute Integration schon anbietet (Temperaturen,
Drücke, Verdichter-Phase, Betriebsstunden, JAZ, Tagesverbräuche …), wird nicht
doppelt angelegt.

Allgemeines:

- Die Entitäten des Heizgeräts hängen am **selben Gerät** wie die der
  eingebauten Integration. Wird dieses Gerät nicht gefunden, entstehen sie
  ohne Gerät; ein zweites Gerät wird dafür nie angelegt.
- Momentanwerte (Temperaturen, Leistungen, Drehzahlen, Prozentwerte) haben
  `state_class: measurement` und damit Langzeitstatistik.
- Die Werte erscheinen bis zu etwa eine Minute später als bei der eingebauten
  Integration.
- „Standard aktiv: nein“ heißt: Die Entität wird angelegt, ist aber
  deaktiviert und kann unter Einstellungen → Geräte & Dienste aktiviert
  werden. Das betrifft Einstellwerte und selten Nützliches.
- `{suffix}` im Namen ist leer beim ersten Verdichter/Verdampfer/Economizer
  und „ 2“, „ 3“ … bei weiteren; `{number}` ist die Nummer (Ventilator 1/2,
  Expansionsventil 1/2, Heizkreis 1 …).
- Zustände der Auswahl-Sensoren sind übersetzt; die Rohwerte stehen in
  Kleinschreibung mit Unterstrichen im Zustand (`domestic_hot_water`,
  `normal_heating`, `14a_off`). Sendet die API einen noch unbekannten Wert,
  wird er unübersetzt angezeigt.

### Betriebszustand

Der Sensor **Betriebszustand** fasst den Zustand der Wärmepumpe für eine
Verlaufs-Zeitleiste zusammen. Mögliche Zustände: `off` (Aus), `preflow`
(Vorlauf), `heating` (Heizen), `dhw` (Warmwasser), `cooling` (Kühlen),
`defrost` (Abtauen), `afterflow` (Nachlauf). Herleitung:

| Bedingung | Zustand |
| --- | --- |
| `heating.outdoor.defrosting` aktiv | `defrost` |
| neueste aktive Statusmeldung S.123 „Wärmepumpe aus“ | `off` |
| S.124 „Wärmepumpe Vorlaufphase“ | `preflow` |
| S.125 „Wärmepumpe im Heizbetrieb“, 4/3-Wege-Ventil auf Warmwasser | `dhw` |
| S.125, 4/3-Wege-Ventil in anderer Stellung | `heating` |
| S.126 „Wärmepumpe im Kühlbetrieb“ | `cooling` |
| S.127 „Abtauen vorbereiten“, S.128 „Wärmepumpe im Abtaubetrieb“ | `defrost` |
| S.129 „Wärmepumpe Nachlaufphase“ | `afterflow` |
| keine dieser Meldungen: kein Verdichter aktiv | `off` |
| … Verdichter aktiv, Ventil auf Warmwasser | `dhw` |
| … Verdichter aktiv, Sekundärkreis im Kühlbetrieb | `cooling` |
| … Verdichter aktiv, sonst | `heating` |

`heating` umfasst Heizen über Pufferspeicher oder Heizkreis; die Ventilstellung
steht im Attribut `valve_position`, die Grundlage in `basis` und `status_code`.
Vorlauf und Nachlauf sind nur über die Statusmeldungen erkennbar.

### Meldungen

- **Meldungen**: Zustand = Code der neuesten Statusmeldung (z. B. `S.125`);
  Attribute `status`, `info`, `service` (je Eintrag `errorCode`, `timestamp`,
  `priority`, `text`, ggf. `source`), `*_count`, `newest_status_timestamp`,
  `newest_status_text`.
- **Letzte Statusmeldung**: Zustand = Klartext der neuesten Statusmeldung
  (z. B. „Wärmepumpe im Heizbetrieb“), für Zeitleisten; Attribute `code`,
  `timestamp`, `source`.
- **Aktive Statusmeldungen**: Zustand = alle derzeit aktiven Statuscodes
  (z. B. `S.115, S.120, S.125, S.165, S.217, S.218, S.219`); Attribute
  `count`, `codes`, `messages` (mit Klartext).
- **Heizstab aktive Stufen**: 0–3, aus den Statusmeldungen S.130–S.133 und
  S.217–S.219 des Heizwasser-Durchlauferhitzers.

`device.messages.status.raw` enthält nach Beobachtung an einer Vitocal 250-A
die **derzeit aktiven** Statusmeldungen: jeder Code einmal, mit dem Zeitpunkt,
seit dem er gilt; beendete Meldungen verschwinden. Das ist aus den Daten
abgeleitet, nicht aus einer Viessmann-Dokumentation.

Der Binärsensor **Heizstab aktiv** gibt `heating.heatingRod.active` wieder. Im
geprüften Datenstand war der Wert `true`, während alle drei Stufen als inaktiv
gemeldet waren – er bedeutet also vermutlich „vorhanden/freigegeben“, nicht
„heizt gerade“. Für „heizt gerade“ ist **Heizstab aktive Stufen** der bessere
Sensor.

#### Quellen der Meldungstexte

Die Tabelle liegt in `custom_components/vicare_extras/data/message_codes.json`
(542 Codes) und wird von `scripts/build_message_codes.py` aus zwei Textdateien
unter `scripts/message_sources/` erzeugt. Jeder Eintrag trägt seine Quelle:

| Quelle | Codes | Bemerkung |
| --- | --- | --- |
| `viessmann` | 470 (S 113, I 90, A 44, P 4, F 219) | Viessmann „Serviceanleitung für die Fachkraft: Viessmann One Base. Systemkonfiguration und Diagnose für Wärmepumpen mit Viessmann One Base“, 6200041, DE 6/2024 (Vitocal 150-A, 151-A, 250-A, 252-A), Kapitel „Meldungen“ |
| `vieventlog` | 72 (S 56, F 11, A 2, I 2, P 1) | [ViEventLog](https://github.com/mschneider82/vieventlog) (MIT, © 2025 Matthias Schneider), nur für Codes, die in der Viessmann-Anleitung fehlen |

- Die Viessmann-Texte wurden maschinell aus dem PDF ausgelesen und nicht
  Zeile für Zeile gegen das PDF korrekturgelesen. Störungen und Warnungen
  wurden zweimal ausgelesen (Inhaltsverzeichnis und Kapitel) mit identischem
  Ergebnis; 249 von 266 Codes, die auch ViEventLog kennt, stimmen mit dessen
  Text überein.
- Die `vieventlog`-Einträge sind unbestätigt. Ein Teil davon (S.10–S.92,
  F.5–F.23) sieht nach allgemeinen Platzhaltertexten aus und passt nicht zum
  Nummernschema der Viessmann-Anleitung.
- Texte gibt es nur auf Deutsch; bei englischer Oberfläche wird ebenfalls der
  deutsche Text gezeigt.
- Unbekannte Codes (an der Anlage gesehen: `S.1`) bleiben als Code stehen.

### Zeitprogramme

**Warmwasser Zeitprogramm**, **Zirkulation Zeitprogramm** und **Heizkreis N
Zeitprogramm**: Zustand = Modus des Zeitfensters, das jetzt gilt (`on`,
`normal`, `5_25_cycles` …), `none` außerhalb aller Zeitfenster, `inactive`
bei abgeschaltetem Zeitprogramm. Attribute: `active`, `today` (heutige
Zeitfenster), `entries` (ganze Woche). Maßgeblich ist die Ortszeit von Home
Assistant.

### COP aktuell

Wärmeleistung geteilt durch Leistungsaufnahme (`heating.heat.production.current`
/ `heating.power.consumption.current`). „Unbekannt“, solange einer der beiden
Werte unter 0,2 kW liegt (Wärmepumpe aus oder im Anlauf). Im Kühlbetrieb und
beim Abtauen ist der Wert nur eingeschränkt aussagekräftig.

### Verlaufs- und Summen-Sensoren

- **Stromverbrauch … Verlauf**: Zustand = heutiger Wert, Attribute `day`,
  `week`, `month`, `year` (erster Wert = aktueller Zeitraum) und
  `*_value_read_at`.
- **Wärmeerzeugung …**, **Heizstab Stromverbrauch …**: Zustand = aktueller
  Tag, Attribute `current_day`, `current_month`, `current_year`, `last_month`,
  `last_seven_days`, `last_year`.
- Diese Energiesensoren haben bewusst **keine `state_class`**: Der Wert
  beginnt täglich neu, und die API verrät nicht, wann genau. Für das
  Energie-Dashboard bitte die Sensoren der eingebauten Integration verwenden.
- Listen-Attribute werden nicht in der Recorder-Datenbank gespeichert.

### Räume (ViCare Smart Climate)

Räume liefert die Viessmann-API am virtuellen Gerät `RoomControl-1` (Typ
`roomControl`) als Features `rooms.<n>` (Name, Typ) und `rooms.<n>.*`. Die
eingebaute Integration richtet dieses Gerät nicht ein. ViCare Extras legt
deshalb **je Raum ein eigenes Gerät** an (Name = Raumname aus der API, sonst
„Room n“) mit den unten aufgeführten Entitäten.

- Thermostate, Klimasensoren und Fußbodenverteiler sind eigene
  Zigbee-Geräte (`trv.*`, `device.sensors.*`, `device.power.battery`). Deren
  Ventilstellung, Temperatur, Feuchte und Batteriestand stellt bereits die
  eingebaute Integration bereit; sie werden hier nicht doppelt angelegt.
- **Nicht an einer echten Anlage geprüft.** Die Raum-Features sind aus
  PyViCare 2.63.0 (`PyViCareRoomControl.py` und dessen Testdaten) und
  ViEventLog abgeleitet. Ein Raumregler ohne Räume (nur `rooms.features.*`)
  erzeugt keine Entitäten.

### Liste aller Entitäten

Erzeugt mit `python scripts/list_entities.py`.

**Heizgerät**

| Plattform | Name | Einheit | Standard aktiv | Quelle |
| --- | --- | --- | --- | --- |
| sensor | 4/3-Wege-Ventil Position |  | ja | `heating.valves.fourThreeWay.position` → `value` |
| sensor | Sekundärkreis Betriebszustand |  | ja | `heating.secondaryCircuit.operation.state` → `currentValue` |
| sensor | 4/3-Wege-Ventil Stellung Ist | % | ja | `heating.secondaryCircuit.valves.fourThreeWay` → `current` |
| sensor | 4/3-Wege-Ventil Stellung Soll | % | ja | `heating.secondaryCircuit.valves.fourThreeWay` → `target` |
| sensor | Wärmeleistung aktuell | kW | ja | `heating.heat.production.current` → `value` |
| sensor | Leistungsaufnahme aktuell | kW | ja | `heating.power.consumption.current` → `value` |
| sensor | Verdichter{suffix} Drehzahl | rps | ja | `heating.compressors.{n}.speed.current` → `value` |
| sensor | Verdichter{suffix} Drehzahl Soll | rps | ja | `heating.compressors.{n}.speed.setpoint` → `value` |
| sensor | Verdichter{suffix} Öltemperatur | °C | ja | `heating.compressors.{n}.sensors.temperature.oil` → `value` |
| sensor | Verdichter{suffix} Motorraumtemperatur | °C | ja | `heating.compressors.{n}.sensors.temperature.motorChamber` → `value` |
| binary_sensor | Verdichter{suffix} Kurbelwannenheizung |  | ja | `heating.compressors.{n}.heater.crankcase` → `active` |
| sensor | Economizer{suffix} Flüssiggastemperatur | °C | ja | `heating.economizers.{n}.sensors.temperature.liquid` → `value` |
| sensor | Expansionsventil {number} Soll | % | ja | `heating.sensors.valve.{n}.expansion.target` → `value` |
| sensor | Ventilator {number} | % | ja | `heating.primaryCircuit.fans.{n}.current` → `value` |
| binary_sensor | Abtauen |  | ja | `heating.outdoor.defrosting` → `active` |
| binary_sensor | Verdampfer{suffix} Sockelheizung |  | ja | `heating.evaporators.{n}.heater.base` → `active` |
| binary_sensor | Kondensatwannenheizung |  | ja | `heating.heater.condensatePan` → `active` |
| binary_sensor | Ventilatorringheizung |  | ja | `heating.heater.fanRing` → `active` |
| binary_sensor | Primärkreis 4/3-Wege-Ventil aktiv |  | nein | `heating.primaryCircuit.valves.fourThreeWay` → `active` |
| binary_sensor | Interne Pumpe |  | ja | `heating.boiler.pumps.internal` → `status` |
| sensor | Interne Pumpe Drehzahl | % | ja | `heating.boiler.pumps.internal.current` → `value` |
| sensor | Interne Pumpe Drehzahl Soll | % | ja | `heating.boiler.pumps.internal.target` → `value` |
| binary_sensor | Heizstab aktiv |  | ja | `heating.heatingRod` → `active` |
| binary_sensor | Heizstab Freigabe Warmwasser |  | nein | `heating.configuration.heatingRod.dhw` → `useApproved` |
| binary_sensor | Heizstab Freigabe Heizung |  | nein | `heating.configuration.heatingRod.heating` → `useApproved` |
| sensor | Heizstab maximale Außentemperatur | °C | nein | `heating.heatingRod.maximumOutsideTemperature` → `value` |
| binary_sensor | Externer Wärmeerzeuger |  | ja | `heating.secondaryHeatGenerator` → `active` |
| sensor | Heizkreis {number} aktives Programm |  | ja | `heating.circuits.{n}.operating.programs.active` → `value` |
| sensor | Heizkreis {number} Temperaturgrenze Minimum | °C | nein | `heating.circuits.{n}.temperature.levels` → `min` |
| sensor | Heizkreis {number} Temperaturgrenze Maximum | °C | nein | `heating.circuits.{n}.temperature.levels` → `max` |
| sensor | Heizkreis {number} Sommer-Eco Schwelle | °C | nein | `heating.circuits.{n}.configuration.summerEco.absolute` → `threshold` |
| sensor | Sekundärkreis Rücklauftemperatur Minimum | °C | nein | `heating.secondaryCircuit.temperature.return.minimum` → `value` |
| sensor | Kesseltemperatur | °C | nein | `heating.boiler.temperature.current` → `value` |
| sensor | Leistungsbegrenzung §14a |  | ja | `device.power.consumption.limitation` → `value` |
| sensor | Leistungsbegrenzung Status Verbrauch |  | ja | `device.power.statusReport.consumption` → `status` |
| sensor | Leistungsbegrenzung Limit Verbrauch | W | ja | `device.power.statusReport.consumption` → `limit` |
| sensor | Leistungsbegrenzung Status Erzeugung |  | nein | `device.power.statusReport.production` → `status` |
| binary_sensor | Warmwasser Hygienefunktion |  | ja | `heating.dhw.hygiene` → `enabled` |
| binary_sensor | Warmwasser Verbrühschutz |  | ja | `heating.dhw.scaldProtection` → `active` |
| binary_sensor | Externe Sperre |  | ja | `heating.external.lock` → `active` |
| binary_sensor | Externe Sperre (Gerät) |  | nein | `device.lock.external` → `active` |
| binary_sensor | Störungssperre |  | ja | `device.lock.malfunction` → `active` |
| binary_sensor | Ferienprogramm |  | ja | `heating.operating.programs.holiday` → `active` |
| binary_sensor | Ferien zu Hause |  | ja | `heating.operating.programs.holidayAtHome` → `active` |
| sensor | Stromverbrauch Warmwasser Verlauf | kWh | ja | `heating.power.consumption.dhw` |
| sensor | Stromverbrauch Heizung Verlauf | kWh | ja | `heating.power.consumption.heating` |
| sensor | Stromverbrauch gesamt Verlauf | kWh | ja | `heating.power.consumption.total` |
| sensor | Wärmeerzeugung Warmwasser | kWh | ja | `heating.heat.production.summary.dhw` |
| sensor | Wärmeerzeugung Heizung | kWh | ja | `heating.heat.production.summary.heating` |
| sensor | Wärmeerzeugung Kühlen | kWh | nein | `heating.heat.production.summary.cooling` |
| sensor | Stromverbrauch Kühlen | kWh | nein | `heating.power.consumption.summary.cooling` |
| sensor | Heizstab Stromverbrauch Warmwasser | kWh | ja | `heating.heatingRod.power.consumption.summary.dhw` |
| sensor | Heizstab Stromverbrauch Heizung | kWh | ja | `heating.heatingRod.power.consumption.summary.heating` |
| sensor | Meldungen |  | ja | `device.messages.status.raw` / `device.messages.info.raw` / `device.messages.service.raw` |
| sensor | Letzte Statusmeldung |  | ja | `device.messages.status.raw` |
| sensor | Aktive Statusmeldungen |  | ja | `device.messages.status.raw` |
| sensor | Betriebszustand |  | ja | `device.messages.status.raw` / `heating.compressors.0` |
| sensor | Heizstab aktive Stufen |  | ja | `device.messages.status.raw` + `heating.heatingRod` |
| sensor | COP aktuell |  | ja | `heating.heat.production.current` + `heating.power.consumption.current` |
| sensor | Warmwasser Zeitprogramm |  | ja | `heating.dhw.schedule` |
| sensor | Zirkulation Zeitprogramm |  | ja | `heating.dhw.pumps.circulation.schedule` |
| sensor | Heizkreis {number} Zeitprogramm |  | ja | `heating.circuits.{n}.heating.schedule` |

**Räume**

| Plattform | Name | Einheit | Standard aktiv | Quelle |
| --- | --- | --- | --- | --- |
| sensor | Temperatur | °C | ja | `rooms.{n}.sensors.temperature` → `value` |
| sensor | Luftfeuchtigkeit | % | ja | `rooms.{n}.sensors.humidity` → `value` |
| sensor | CO2 | ppm | ja | `rooms.{n}.co2` → `concentration` / `rooms.{n}.sensors.co2` → `value` |
| sensor | Solltemperatur Normal | °C | ja | `rooms.{n}.temperature.levels.normal.heating` → `temperature` / `rooms.{n}.operating.programs.normalHeating` → `temperature` |
| sensor | Solltemperatur Reduziert | °C | ja | `rooms.{n}.temperature.levels.reduced.heating` → `temperature` / `rooms.{n}.operating.programs.reducedHeating` → `temperature` |
| sensor | Solltemperatur Komfort | °C | ja | `rooms.{n}.temperature.levels.comfort.heating` → `temperature` / `rooms.{n}.operating.programs.comfortHeating` → `temperature` |
| sensor | Solltemperatur Kühlen Normal | °C | nein | `rooms.{n}.temperature.levels.normal.cooling` → `temperature` |
| sensor | Solltemperatur Kühlen Reduziert | °C | nein | `rooms.{n}.temperature.levels.reduced.cooling` → `temperature` |
| sensor | Solltemperatur Normal (gefühlt) | °C | nein | `rooms.{n}.temperature.levels.normal.perceived` → `temperature` |
| sensor | Solltemperatur Komfort (gefühlt) | °C | nein | `rooms.{n}.temperature.levels.comfort.perceived` → `temperature` |
| sensor | Betriebsstufe |  | ja | `rooms.{n}.operating.state` → `level` |
| binary_sensor | Fenster |  | ja | `rooms.{n}.sensors.openWindow` → `value` / `rooms.{n}.sensors.window.openState` → `value` |
| binary_sensor | Kondensationsrisiko |  | ja | `rooms.{n}.condensationRisk` → `value` |
| binary_sensor | Kindersicherung |  | ja | `rooms.{n}.childLock` → `active` |

## Aktion `vicare_extras.get_features`

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

## Aktion `vicare_extras.get_event_history`

Ruft die Ereignishistorie einer Anlage aus der Viessmann-Cloud ab
(`GET /iot/v2/events-history/installations/{id}/events`).
**Jede abgerufene Seite ist ein API-Aufruf.**

| Feld | Standard | Bedeutung |
| --- | --- | --- |
| `last_n_days` | 30 | Zeitraum in Tagen (1–365) |
| `limit` | 1000 | Ereignisse pro Seite (1–1000) |
| `max_pages` | 5 | Höchstzahl Seiten = Höchstzahl API-Aufrufe (1–20) |
| `event_type` | – | Ereignistyp(en). Ein einzelner Typ wird von der API gefiltert, mehrere werden nach dem Abruf gefiltert |
| `gateway_serials` | – | Gateway-Seriennummer(n), wird als `gatewaySerials` übergeben; nicht nötig, um Gateway-Ereignisse zu erhalten |
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

Nur Statusmeldungen:

```yaml
action: vicare_extras.get_event_history
data:
  last_n_days: 30
  max_pages: 1
  event_type: device-message-status
response_variable: historie
```

Antwort:

```yaml
installation_id: "1234567"
endpoint: /events-history/installations/1234567/events
count: 42            # Anzahl zurückgegebener Ereignisse (nach Filter)
fetched_count: 42    # Anzahl abgerufener Ereignisse (vor lokalem Filter)
pages: 1
api_calls: 1         # so viele Aufrufe hat dieser Abruf verbraucht
truncated: false     # true: max_pages erreicht, es gibt weitere Seiten
next_cursor: null    # für die Fortsetzung über das Feld cursor
known_gateway_serials: ["7571381500000001"]
events:
  - eventType: device-message-status          # unverändert von Viessmann
    gatewaySerial: "7571381500000001"
    body:
      errorCode: S.123
      deviceId: "0"
      modelId: E3_Vitocal_16
      active: true
      equipmentType: Boiler
      errorDescription: S.123                 # Viessmann dekodiert nicht
    createdAt: "2026-11-12T10:23:57.890Z"     # Zeiten in UTC
    eventTimestamp: "2026-11-12T10:23:27.000Z"
    editedBy: system
    origin: system
    decoded:                                  # von ViCare Extras ergänzt
      code: S.123
      text: Wärmepumpe aus
      source: viessmann
      category: status                        # status/info/warning/maintenance/fault
      active: true
    summary: "S.123: Wärmepumpe aus"          # von ViCare Extras ergänzt
  - eventType: feature-changed
    body:
      featureName: heating.circuits.1.operating.modes.active
      commandName: setMode
      commandBody: {mode: standby}
    origin: API
    summary: "heating.circuits.1.operating.modes.active: setMode(mode=standby)"
```

Die Felder von Viessmann bleiben unverändert. Ergänzt werden `decoded` (bei
`device-message-*` und `device-error`) und `summary` (zusätzlich bei
`feature-changed`). Unbekannte Codes haben `text: null` und den Code als
`summary`.

Bekannte Ereignistypen laut Viessmann-Dokumentation – Anlagenebene:
`installation-address-changed`, `invitation-accepted`, `invitation-terminated`,
`geofencing-activation-changed`, `diy-heating-rod-run-too-long`,
`diy-heating-curve-not-optimal`, `diy-dhw-schedule-not-optimal`,
`dynamic-smart-tip`, `snapshot-restore-status-changed`; Gateway-Ebene:
`gateway-online`, `device-bmu-serial-changed`, `device-boiler-serial-changed`,
`device-error`, `firmware-update-status`, `gateway-reset-command`,
`device-message-info`, `device-message-service`, `device-message-status`,
`device-message-warning`, `feature-changed`, `src-status-changed`,
`remote-diagnose-session-opened`, `remote-diagnose-session-closed`.

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
- Alle Sensoren, Binärsensoren und `get_features`: **0 Aufrufe**, immer.
- `get_event_history`: **1 Aufruf je Seite**, höchstens `max_pages`. Falls der
  erste Pfad mit „nicht gefunden“ antwortet, kommt einmalig 1 Aufruf für den
  Ausweichpfad hinzu; der funktionierende Pfad wird bis zum nächsten Neustart
  gemerkt.

Empfehlung: `max_pages: 1` verwenden, die Aktion nicht in kurzen Abständen
automatisieren und `api_calls` in der Antwort beachten. Ist das Limit
erschöpft, meldet die Aktion das mit dem Zeitpunkt der Rücksetzung – und auch
die eingebaute Integration bekommt bis dahin keine Daten mehr.

## Installation

Voraussetzungen: Home Assistant **2026.11.1 oder neuer**, die Integration
**Viessmann ViCare** ist eingerichtet und geladen.

### Über HACS (benutzerdefiniertes Repository)

1. HACS öffnen → Menü oben rechts (⋮) → **Benutzerdefinierte Repositories**.
2. `https://github.com/Bascht74/vicare_extras` eintragen, Typ **Integration**,
   hinzufügen.
3. In HACS nach **ViCare Extras** suchen und **Herunterladen**.
4. Weiter bei [Einrichtung](#einrichtung). Erscheint die Integration dort
   nicht, Home Assistant neu starten.

Live wurde Version 0.1.0 über den Marketplace installiert; dabei war kein
Neustart nötig. Nach einem **Update** auf eine neue Version Home Assistant neu
starten, falls die neuen Entitäten nicht erscheinen – bereits geladener
Python-Code wird sonst nicht ersetzt.

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

Die Entitäten erscheinen danach beim Gerät der Wärmepumpe (Räume als eigene
Geräte), die Aktionen unter **Entwicklerwerkzeuge → Aktionen**.

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
  das brechen. In dem Fall werden die Entitäten „nicht verfügbar“ bzw. die
  Einrichtung wird wiederholt und die Aktionen melden einen klaren Fehler; die
  eingebaute Integration wird davon nicht beeinträchtigt.
- Entitäten gibt es nur für Geräte vom Typ `heating`, die die eingebaute
  Integration einrichtet, und für Räume eines Raumreglers. `get_features`
  erreicht alle Geräte des Kontos.
- Der Betriebszustand und die Liste der aktiven Statusmeldungen beruhen auf
  der Beobachtung, dass `device.messages.status.raw` die aktiven Meldungen
  enthält (siehe oben).
- Die Wertebereiche der Auswahl-Sensoren (Ventilstellung, Sekundärkreis,
  §14a) sind nur teilweise bekannt; unbekannte Werte erscheinen unübersetzt.
- Features auf Gateway-Ebene, die keinem Gerät zugeordnet sind (z. B.
  `gateway.devices`), gibt `get_features` nicht zurück.
- Hält die eingebaute Integration gerade keine Daten (kurz während ihrer
  minütlichen Abfrage oder bei einer Störung der Viessmann-API), wartet
  `get_features` einige Sekunden und meldet sonst einen Fehler, statt selbst
  abzufragen. Die Entitäten behalten ihren letzten Wert bis zu 15 Minuten.
- Von der Ereignishistorie wird nur die Version `v2` verwendet. `v3`, die
  Parameter `date`, `timestamp` und `origins` sowie die Export-Schnittstelle
  sind nicht umgesetzt.
- Die Viessmann-API nennt in ihrer Dokumentation eine Schnittstelle „Service
  Documents / Error Database“. Sie wird nicht verwendet; die Meldungstexte
  stammen aus der mitgelieferten Tabelle.

## Fehlersuche

- **„Die Integration Viessmann ViCare ist nicht eingerichtet oder nicht
  geladen“**: zuerst die eingebaute Integration in Ordnung bringen (z. B.
  erneut anmelden oder das Ende einer Limit-Sperre abwarten).
- **„… passt nicht zur installierten Home-Assistant-Version“**: Die Interna
  haben sich geändert; ViCare Extras muss angepasst werden.
- **Einrichtung wird wiederholt / Entitäten fehlen**: Unter Einstellungen →
  Geräte & Dienste → ViCare Extras → ⋮ → **Diagnose herunterladen** steht, ob
  Daten gefunden wurden und welche Features vorhanden sind. Die Diagnose
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
  Entitätsnamen und Zustände, Fehlertexte und Platzhalter, `services.yaml`,
  Icons, Manifest, Meldungstabelle),
- `python scripts/check_ha_imports.py <core-checkout>` gegen Core 2026.11.1
  (alle importierten Home-Assistant-Namen existieren dort),
- `pytest tests/unit`: Logik der Aktionen, des Koordinators und der Entitäten
  mit nachgebildeten PyViCare-Objekten gegen **vereinfachte Nachbildungen** von
  Home Assistant (`tests/unit/stubs`). Grundlage ist
  `tests/fixtures/vitocal250a_features.json`: Aufbau (Feature-Namen,
  Eigenschaften, Einheiten, Auswahlwerte, Meldungscodes) von einer echten
  Vitocal 250-A, Kennungen und Zählerstände ersetzt. Mit
  `PYVICARE_SRC=<PyViCare-Checkout>` zusätzlich gegen den echten
  PyViCare-Code 2.63.0 (Cache-Verhalten, Fehlerbehandlung von `get()`).

Nicht ausgeführt:

- `pytest tests/ha` (Tests mit echtem Home Assistant; benötigt
  `pytest-homeassistant-custom-component` und `PyViCare`),
- Raum-Entitäten gegen eine echte Anlage mit Räumen,
- Version 0.2.0 in einer laufenden Instanz (0.1.0 lief dort, siehe oben).

`tests/unit` und `tests/ha` müssen getrennt gestartet werden.

## Lizenz

MIT, siehe [LICENSE](LICENSE). Kein offizielles Produkt von Viessmann oder
Home Assistant. Meldungstexte: Viessmann Climate Solutions (Serviceanleitung
6200041) und ViEventLog (MIT).
