# ViCare Extras

Eine kleine Zusatz-Integration für Home Assistant, die mehr Daten aus einer
bestehenden **Viessmann-ViCare**-Einrichtung sichtbar macht.

ViCare Extras ersetzt die eingebaute Integration `vicare` nicht, sondern läuft
daneben (eigene Domain `vicare_extras`). Sie verwendet die Anmeldung, die die
eingebaute Integration bereits hergestellt hat, und braucht deshalb keine
eigenen Zugangsdaten.

- **Sensoren lesen nur.** Sensoren und Binärsensoren schicken nie Befehle an
  die Heizung.
- **Befehle nur auf Wunsch.** Seit Version 0.3.0 gibt es Klima-Entitäten für
  Räume und Heizkörperthermostate. Wird dort die Solltemperatur geändert,
  sendet ViCare Extras genau diesen einen Befehl – nie von sich aus und nie
  nach Zeitplan. Dazu kommt die Experten-Aktion
  [`send_command`](#aktion-vicare_extrassend_command-experten). Die
  Integration ist damit nicht mehr rein lesend.
- **Keine eigenen regelmäßigen API-Abfragen.** Alle Entitäten lesen
  ausschließlich Daten, die die eingebaute Integration ohnehin schon abgerufen
  hat.
- **Ereignishistorie nur auf Anforderung**, über eine Aktion.
- **Meldungen im Klartext.** Statusmeldungen (S), Informationen (I), Warnungen
  (A), Wartungsmeldungen (P) und Störungen (F) werden dekodiert. Die Bedeutung
  stammt aus Viessmann-Serviceanleitungen, die Formulierungen sind eigene.
- **Abfrageintervall einstellbar.** Auf Wunsch fragt die eingebaute
  Integration seltener ab; nur so lassen sich API-Aufrufe sparen.

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

Mit Version 0.3.0 (drei weitere Instanzen mit Core 2026.11.1 und echten
Raumregler-Daten):

- Die Integration lädt und arbeitet. Raum-Geräte und Raum-Klima-Entitäten
  werden angelegt (7 Entitäten je Raum), die Klima-Entitäten der
  Heizkörperthermostate hängen an den Geräten der eingebauten Integration.
- Mit dem kostenlosen Zugang liefert die API für Räume und Thermostate keine
  Befehle, keine Namen und keine Ist-Temperatur der Thermostate, siehe
  [Was der kostenlose Zugang liefert](#was-der-kostenlose-zugang-basic-liefert).
  Die Klima-Entitäten sind dort reine Anzeigen.

Nicht live bestätigt sind das Senden eines Befehls, die Option für das
Abfrageintervall und alles Neue in Version 0.3.1, siehe
[Teststand](#teststand).

Die gelernte Raumzuordnung der Thermostate (0.3.3) lief am 12.11.2026 in
einer Instanz mit 12 Räumen und 16 Thermostaten: Nach 30 Minuten waren 6
Thermostate drei Räumen zugeordnet, mit dem Raum-Gerät verknüpft, und die
drei Räume hatten Namen und Bereich ihrer Thermostate; die übrigen zeigten
ihre Kandidaten, ohne Fehler im Protokoll. Nicht live bestätigt sind dabei
das Wiedereinlesen nach einem Neustart, das Zurücknehmen einer Verknüpfung
und der Vorrang von `actors` aus der API (nur Unit-Tests).

Bekannte Einschränkungen:

- **Gerätezeit.** Die Zeitstempel in `device.messages.*.raw` sind die Uhrzeit
  des Geräts: Ortszeit, aber als UTC gekennzeichnet (`…Z`). An der geprüften
  Anlage ging die Geräteuhr außerdem etwa 4 Minuten vor. ViCare Extras
  rechnet diese Zeiten nicht um, sondern gibt sie unverändert weiter; die
  eigenen Attribute heißen deshalb `device_time` und
  `newest_status_device_time`. Die Zeiten der Ereignishistorie sind dagegen
  echte UTC-Zeiten.
- Ein Raumregler ohne eingerichtete Räume liefert nur `rooms.features.*`;
  dort entstehen keine Raum-Entitäten.
- Das Einstellen einer Solltemperatur konnte nur gegen nachgebaute Daten
  geprüft werden: Mit dem kostenlosen Zugang bietet die API keinen Befehl an.

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
  Integration (mit verlängertem
  [Abfrageintervall](#abfrageintervall-der-eingebauten-integration) bis zu
  zwei Minuten).
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
| neueste aktive Statusmeldung S.123 (Wärmepumpe ist aus) | `off` |
| S.124 (Vorlaufphase) | `preflow` |
| S.125 (Wärmepumpe heizt), 4/3-Wege-Ventil auf Warmwasser | `dhw` |
| S.125, 4/3-Wege-Ventil in anderer Stellung | `heating` |
| S.126 (Wärmepumpe kühlt) | `cooling` |
| S.127 (Abtauen wird vorbereitet), S.128 (Wärmepumpe taut ab) | `defrost` |
| S.129 (Nachlaufphase) | `afterflow` |
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
  `priority`, `text`, ggf. `source` und `verified: false`), `*_count`,
  `newest_status_device_time`, `newest_status_text`.
- **Letzte Statusmeldung**: Zustand = Klartext der neuesten Statusmeldung
  (z. B. „Wärmepumpe heizt“), für Zeitleisten; Attribute `code`,
  `device_time`, `source`, `verified`.
- **Aktive Statusmeldungen**: Zustand = alle derzeit aktiven Statuscodes
  (z. B. `S.115, S.120, S.125, S.165, S.217, S.218, S.219`); Attribute
  `count`, `codes`, `messages` (mit Klartext).
- **Heizstab aktive Stufen**: 0–3, aus den Statusmeldungen S.130–S.133 und
  S.217–S.219 des Heizwasser-Durchlauferhitzers.

`device.messages.status.raw` enthält nach Beobachtung an einer Vitocal 250-A
die **derzeit aktiven** Statusmeldungen: jeder Code einmal, mit dem Zeitpunkt,
seit dem er gilt; beendete Meldungen verschwinden. Das ist aus den Daten
abgeleitet, nicht aus einer Viessmann-Dokumentation.

Alle Zeitangaben dieser Sensoren (`timestamp` in den Listen, `device_time`,
`newest_status_device_time`) sind **Gerätezeit**: die Ortszeit der
Wärmepumpe, von der API fälschlich mit `Z` (UTC) gekennzeichnet. Sie werden
unverändert weitergegeben und nicht umgerechnet. Wer sie in einer Vorlage als
Zeit verwendet, sollte das `Z` ignorieren, z. B. mit
`{{ state_attr('sensor.…_letzte_statusmeldung', 'device_time')[:19] }}`.

Der Binärsensor **Heizstab aktiv** gibt `heating.heatingRod.active` wieder. Im
geprüften Datenstand war der Wert `true`, während alle drei Stufen als inaktiv
gemeldet waren – er bedeutet also vermutlich „vorhanden/freigegeben“, nicht
„heizt gerade“. Für „heizt gerade“ ist **Heizstab aktive Stufen** der bessere
Sensor.

#### Meldungstexte: Herkunft und Verlässlichkeit

Die Tabelle liegt in `custom_components/vicare_extras/data/message_codes.json`
(500 Codes) und wird von `scripts/build_message_codes.py` aus
`scripts/message_sources/messages_de.txt` erzeugt.

**Die Texte sind eigene Formulierungen dieses Projekts.** Aus den
Viessmann-Unterlagen stammt nur die *Bedeutung* eines Codes, nicht der
Wortlaut; die Anleitungen selbst und deren Textauszüge liegen nicht im
Repository. `source` nennt je Eintrag, woher die Bedeutung kommt:

| `source` | Codes | Bedeutung aus | geprüft |
| --- | --- | --- | --- |
| `viessmann` | 470 (S 113, I 90, A 44, P 4, F 219) | Viessmann-Serviceanleitung „Viessmann One Base. Systemkonfiguration und Diagnose für Wärmepumpen mit Viessmann One Base“, 6200041 (DE 6/2024 und DE 7/2024; Vitocal 150-A, 151-A, 250-A, 252-A) | ja |
| `viessmann_6221420` | 18 (F 11, A 7) | Viessmann-Serviceanleitung „Einzelraumregelung mit ViCare Smart Climate“, 6221420, DE 2/2025 (Meldungen der Thermostate, Sensoren und Fußbodenverteiler) | ja |
| `viessmann_6179923` | 5 (F.23, F.24, F.518, F.542, F.543) | Viessmann-Serviceanleitung für Wärmepumpen mit Viessmann One Base, 6179923, DE 3/2022 | ja |
| `vieventlog` | 6 (S.119, S.427, A.130, I.94, I.95, P.35) | [ViEventLog](https://github.com/mschneider82/vieventlog) (MIT, © 2025 Matthias Schneider); Text wie dort | **nein** |
| `fhem` | 1 (S.1) | FHEM-Modul `98_vitoconnect.pm`; Text wie dort | **nein** |

Was das für die Anzeige heißt:

- Einträge mit Viessmann-Quelle erscheinen als Klartext, z. B.
  „Wärmepumpe heizt“.
- Einträge, die **keine Viessmann-Unterlage bestätigt**, tragen in der Tabelle
  `"verified": false` und erscheinen als
  `S.427 (ungeprüft: Leistungsbegrenzung durch den Netzbetreiber nach § 14a
  EnWG)`. In Listen-Attributen und in der Ereignishistorie steht der Text in
  `text`, dazu `verified: false`. So bleibt der Code sichtbar, und der Text
  wird nicht als gesichert ausgegeben.
- Codes ohne Eintrag bleiben als Code stehen (z. B. `S.999`).
- Texte gibt es nur auf Deutsch; bei englischer Oberfläche wird der deutsche
  Text gezeigt (der Zusatz heißt dann „unverified“).

Was geprüft wurde (Stand 12.11.2026):

- ViEventLog kennt 72 Codes, die in der Anleitung 6200041 fehlen. Davon ist
  **1 bestätigt** (A.27, Anleitung 6221420), **4 widersprechen** einer
  Viessmann-Anleitung und wurden durch deren Bedeutung ersetzt (F.23, F.518,
  F.542, F.543; Anleitung 6179923), **67 sind unbestätigt**.
- Von den unbestätigten wurden **61 entfernt**: die Blöcke S.10–S.15,
  S.20–S.25, S.30–S.35, S.40–S.43, S.50–S.53, S.61–S.63, S.70–S.72,
  S.80–S.82, S.90–S.92, S.100–S.105, S.110, S.111, S.160, S.168,
  S.170–S.172, S.180, S.191, S.192 (durchnummerierte, allgemein gehaltene
  Texte, die nicht zum Nummernschema der Viessmann-Anleitung passen) sowie
  F.5, F.10–F.12 und F.20–F.22 (passen nicht zum Schema der
  Sensor-Störungen in der Viessmann-Anleitung). Diese Codes erscheinen als
  Code. **6 bleiben als „ungeprüft“** (siehe Tabelle), weil sie konkret und
  plausibel sind, sich aber nicht belegen ließen.
- **S.1** steht in keiner der drei Viessmann-Anleitungen. Das FHEM-Modul
  nennt „Netzspannung eingeschaltet“; das passt zur Beobachtung an der Anlage
  (S.1 trägt den Zeitpunkt des Einschaltens), ist aber nicht belegt und
  deshalb als ungeprüft markiert. Die Meldungstabelle des FHEM-Moduls ist im
  Übrigen eine Kopie der ViEventLog-Tabelle und damit keine unabhängige
  Quelle.
- Bei den 266 Codes, die sowohl die Anleitung 6200041 als auch ViEventLog
  kennen, weicht ViEventLog bei 11 in der Bedeutung ab (F.13, F.454, F.472,
  F.519, F.686, F.687, F.770, F.771, F.788, S.118, I.120) und ergänzt bei
  I.149 einen Hinweis zur Firmware. ViCare Extras folgt dort der
  Viessmann-Anleitung.
- Die Bedeutungen wurden maschinell aus den PDFs ausgelesen und anschließend
  umformuliert, aber nicht Zeile für Zeile gegen die PDFs korrekturgelesen.

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

### Räume und Heizkörperthermostate (ViCare Smart Climate)

So ist die Einzelraumregelung aufgebaut (Viessmann-Serviceanleitung 6221420,
PyViCare 2.63.0 und dessen Testdaten):

- **Räume** liefert die Viessmann-API am virtuellen Gerät `RoomControl-1`
  (Typ `roomControl`) als Features `rooms.<n>` (Name, Typ, `actors`) und
  `rooms.<n>.*`. Die eingebaute Integration richtet dieses Gerät nicht ein.
  ViCare Extras legt deshalb **je Raum ein eigenes Gerät** an. Es heißt wie
  der Raum in der API; liefert die API keinen Namen (so beim kostenlosen
  Zugang), heißt es „Raum n“ bei deutscher Spracheinstellung von Home
  Assistant, sonst „Room n“. Ein in Home Assistant selbst vergebener
  Gerätename bleibt erhalten.
- Das Raum-Gerät ist mit dem Gerät des Wärmeerzeugers verknüpft („verbunden
  über“): dem ersten Heizgerät desselben Gateways, das die eingebaute
  Integration eingerichtet hat. So erscheint der Raum bei der Wärmepumpe
  unter den verbundenen Geräten. Zum Eintrag der eingebauten Integration
  selbst kann ein fremdes Gerät nicht gehören. Bestehende Raum-Geräte
  erhalten Verknüpfung und Namen beim nächsten Start.
- **Raumtemperatur und Luftfeuchtigkeit sind eigene Sensor-Entitäten** am
  Raum-Gerät (`state_class: measurement`, also mit Langzeitstatistik) – nicht
  nur Attribute der Klima-Entität.
- **Heizkörperthermostate, Klimasensoren und Fußbodenthermostate** sind
  eigene Zigbee-Geräte (`trv.*`, `fht.*`, `device.sensors.*`,
  `device.power.battery`). Sie werden in der ViCare-App einem Raum
  zugeordnet; `rooms.<n>.actors` nennt die Geräte-IDs. Diese Geräte richtet
  die eingebaute Integration ein, mit Sensoren für Raumtemperatur,
  Solltemperatur, Feuchte, Ventilstellung und Batterie. ViCare Extras legt
  davon nichts doppelt an.
- **Geregelt wird der Raum.** Alle Thermostate eines Raums folgen dessen
  Solltemperatur; ein Thermostat hat kein eigenes Zeitprogramm. Eine
  Änderung direkt am Thermostat gilt laut Anleitung nur vorübergehend (24 h
  mit Viessmann One Base, 2 h mit Vitoconnect), danach gilt wieder das
  Zeitprogramm des Raums. Die Raumtemperatur ist der Mittelwert der
  Klimasensoren des Raums, ohne Klimasensor der Mittelwert der Thermostate.

#### Welches Thermostat gehört zu welchem Raum?

Die API nennt die Thermostate eines Raums nur in `rooms.<n>.actors`, und das
fehlt beim kostenlosen Zugang. ViCare Extras **lernt die Zuordnung deshalb
aus den Solltemperaturen** (ab Version 0.3.3, ohne API-Abruf):

- Jedes Thermostat meldet seine Solltemperatur (`trv.temperature`), jeder
  Raum seine Solltemperaturen (Normal, Reduziert, Komfort). Ein Thermostat
  folgt dem Sollwert seines Raums. Passt der Sollwert eines Thermostats
  30 Minuten lang unverändert zu **keinem** Sollwert eines Raums, scheidet
  dieser Raum für das Thermostat aus.
- Bleibt genau ein Raum übrig, ist das Thermostat zugeordnet. Bis dahin
  nennt das Attribut `room_candidates` der Thermostat-Klima-Entität die noch
  möglichen Räume.
- Welche Stufe (Normal/Reduziert) in einem Raum gerade gilt, liefert der
  kostenlose Zugang nicht. Verglichen wird deshalb mit allen Sollwerten des
  Raums. Das ist langsamer, schließt aber nie den richtigen Raum aus, nur
  weil das Zeitprogramm umgeschaltet hat.
- **Räume mit gleichen Sollwerten lassen sich nicht unterscheiden.** Sie
  trennen sich, sobald die Sollwerte auseinanderlaufen: durch die
  Nachtabsenkung oder indem man in der ViCare-App einen Raum für mindestens
  eine halbe Stunde um 0,5 °C anders einstellt.
- Wird ein Thermostat von Hand verstellt (sein Sollwert passt dann zu keinem
  Raum), wird nichts ausgeschlossen. Scheiden einmal alle Räume aus, etwa
  weil ein Thermostat in einen anderen Raum umgezogen ist, beginnt das
  Lernen für dieses Thermostat von vorn.
- Nennt die API die Zuordnung (`actors`), gilt diese und nicht die gelernte.
  Das Attribut `room_source` sagt, woher die Zuordnung stammt: `api` oder
  `learned`.

Was aus der Zuordnung folgt:

- Das Thermostat-Gerät (es gehört der eingebauten Integration) bekommt das
  Raum-Gerät als „verbunden über“ und erscheint damit beim Raum. Eine
  Verknüpfung, die jemand anderes gesetzt hat, bleibt unangetastet; fällt
  die Zuordnung weg, nimmt ViCare Extras die eigene Verknüpfung zurück.
- **Der Raum bekommt einen Namen:** Liefert die API keinen, heißt das
  Raum-Gerät wie der Home-Assistant-Bereich, in dem seine Thermostate
  liegen. Teilen sich mehrere Räume denselben Bereich, heißt ein Raum mit
  genau einem Thermostat wie dieses Thermostat (sofern es in Home Assistant
  umbenannt wurde). Ersetzt wird nur der Standardname „Raum n“; ein selbst
  vergebener Name bleibt. Die Entitäts-IDs ändern sich dadurch nicht.
- Ein Raum-Gerät ohne Bereich bekommt einmalig den Bereich seiner
  Thermostate.
- Attribute: `room`, `room_source`, `room_candidates` an der
  Thermostat-Klima-Entität; `thermostats` (Namen der zugeordneten
  Thermostate) und `actors` (Geräte-IDs laut API) an der Raum-Klima-Entität.

Das Gelernte liegt in `.storage/vicare_extras.<Eintrag>.rooms`, übersteht
Neustarts und wird mit dem Löschen der Integration entfernt.

Geprüft an den Daten einer echten Anlage (12 Räume, 16 Thermostate): 6
Thermostate waren sofort eindeutig, weitere trennen sich mit der ersten
Nachtabsenkung, der Rest braucht einmalig einen geänderten Raum-Sollwert.

#### Was der kostenlose Zugang (Basic) liefert

Viessmann kennzeichnet in seiner Datenpunktliste
(api.viessmann-climatesolutions.com/documentation/data-points) jeden
Datenpunkt mit „View Basic Feature Data“, „View Advanced Feature Data“
und/oder „Control Advanced Features“. Für die Einzelraumregelung heißt das,
und so zeigte es sich auch an echten Anlagen mit kostenlosem Zugang:

| Datenpunkte | Basic (kostenlos) | Advanced |
| --- | --- | --- |
| `rooms.<n>.sensors.*` (Temperatur, Feuchte), `rooms.<n>.temperature.levels.*`, `trv.*` | lesbar | lesbar |
| `device.name`, `device.sensors.temperature`, `device.sensors.humidity` der Zigbee-Geräte | – | lesbar |
| `rooms.<n>.operating.programs.*`, `rooms.<n>.schedule`, `rooms.<n>.quickmodes.*` | – | lesbar und steuerbar |
| Raumnamen | – | kein eigener Datenpunkt (nur `rooms.others`) |

Folgen mit dem kostenlosen Zugang:

- **Thermostate haben keine Ist-Temperatur und keinen Namen** in den Daten
  (`device.sensors.temperature` und `device.name` fehlen). Die Klima-Entität
  eines Thermostats zeigt deshalb Solltemperatur und Ventil, aber keine
  Ist-Temperatur. Die Ist-Temperatur gibt es am Raum
  (`rooms.<n>.sensors.temperature`).
- **Räume haben keinen Namen**, kein `rooms.<n>` (Typ, `actors`) und kein
  `rooms.<n>.operating.state`. Die Geräte heißen „Raum n“; die Attribute
  `actors`, `level`, `demand` und die Aktion der Klima-Entität bleiben leer,
  die Zuordnung Thermostat ↔ Raum ist nicht erkennbar.
- **Alle `commands`-Objekte sind leer**, auch an `trv.temperature`. Die
  Klima-Entitäten sind damit **reine Anzeigen**: Sie zeigen Ist- und
  Solltemperatur, lassen sich aber nicht verstellen (`setpoint_writable:
  false`). Ob die API einen nicht angebotenen Befehl trotzdem annimmt, lässt
  sich mit der Aktion
  [`send_command`](#aktion-vicare_extrassend_command-experten) ausprobieren.

Die Datenpunktliste selbst wurde für dieses Projekt nicht automatisiert
ausgewertet; die Tabelle gibt den Befund aus der Liste und von den echten
Anlagen wieder.

#### Klima-Entitäten

| | Raum | Heizkörperthermostat |
| --- | --- | --- |
| Gerät | Raum-Gerät von ViCare Extras | vorhandenes Gerät der eingebauten Integration |
| Name | wie das Gerät (Raumname) | wie das Gerät |
| Ist-Temperatur | `rooms.<n>.sensors.temperature` | `device.sensors.temperature`, nur bei `status: connected` |
| Luftfeuchtigkeit | `rooms.<n>.sensors.humidity` | – |
| Solltemperatur | erstes Feature mit ausführbarem Befehl `setTemperature`: `…temperature.levels.normal.perceived`, dann `…temperature.levels.normal.heating`, dann `…operating.programs.normalHeating` | `trv.temperature` mit Befehl `setTargetTemperature` |
| Grenzen, Schrittweite | aus dem Befehl der API (`min`, `max`, `stepping`) | ebenso |
| Betriebsart | nur `heat` | nur `heat` |
| Aktion | `rooms.<n>.operating.state` → `demand` (`heating`, `cooling`, sonst Leerlauf) | Heizen, solange `trv.valve.position` über 0 liegt |
| Attribute | `setpoint`, `setpoint_feature`, `setpoint_writable`, `level`, `demand`, `actors` | `setpoint`, `setpoint_feature`, `setpoint_writable`, `valve_position`, `room` |

- Eine Klima-Entität entsteht nur, wenn eine Solltemperatur lesbar ist.
- **Geschrieben wird nur, was die API als ausführbar meldet** (`isExecutable:
  true` im `commands`-Objekt des Features). Fehlt ein solcher Befehl, hat die
  Entität keine Solltemperatur-Einstellung; der Sollwert steht dann im
  Attribut `setpoint`.
- Ein Befehl wird **nur** gesendet, wenn in Home Assistant die Solltemperatur
  geändert wird (Oberfläche, Automation, `climate.set_temperature`). Jeder
  Befehl ist **ein API-Aufruf**. Danach zeigt die Entität den gesendeten Wert,
  bis die eingebaute Integration das nächste Mal abgefragt hat; die Sensoren
  (auch die der eingebauten Integration) zeigen den neuen Sollwert erst nach
  dieser Abfrage. Meldet die API dann noch den alten Wert, springt die
  Anzeige bis zur folgenden Abfrage zurück.
- Der Befehl geht über die Anmeldung der eingebauten Integration (PyViCare).
  Deren Zwischenspeicher wird dabei bewusst **nicht** geleert: Sonst würde die
  eingebaute Integration gleich danach alles neu abrufen – ein zweiter
  API-Aufruf je Befehl.
- Werte außerhalb der Grenzen der API werden abgelehnt, ohne dass ein Aufruf
  gesendet wird. Lehnt die API einen Befehl ab oder ist das Limit erschöpft,
  erscheint eine Fehlermeldung in Home Assistant.
- Die Solltemperatur des Raums ist die der Stufe **Normal**. Gilt gerade
  „Reduziert“ oder „Komfort“, wirkt eine Änderung erst, wenn wieder „Normal“
  gilt; die aktive Stufe steht im Attribut `level`. Zeitprogramme und Stufen
  werden nicht umgeschaltet.
- Ob eine über die API gesetzte Solltemperatur eines **Thermostats** wie eine
  Änderung am Gerät nur vorübergehend gilt, ist nicht bekannt. Dauerhaft
  sinnvoll ist die Einstellung am Raum.
- **Ist-Temperatur des Thermostats:** Meldet ein Thermostat keine eigene
  Temperatur (oder `status` ist nicht `connected`), bleibt die Ist-Temperatur
  leer; die Entität funktioniert trotzdem. Was das Thermostat liefert, zeigt:

  ```yaml
  action: vicare_extras.get_features
  data:
    device_type: zigbee
    prefix: device.sensors.temperature
  response_variable: ergebnis
  ```

  Enthält die Antwort für das Thermostat kein Feature
  `device.sensors.temperature` oder darin `status: notConnected`, gibt es
  keine Ist-Temperatur. Ohne `prefix` zeigt derselbe Aufruf alle Features der
  Zigbee-Geräte, mit `full: true` auch die angebotenen Befehle.

**Das Einstellen ist nicht an einer echten Anlage geprüft.** Anlegen und
Anzeigen der Räume und Thermostate sind live bestätigt (kostenloser Zugang,
ohne Befehle). Das Datenmodell mit Befehlen ist aus PyViCare 2.63.0 (Code und Testdaten
`RoomControl.json`, `gatewayWithDevices/heatbox2/Vitodens-300-W-WB3D-with-TRV.json`,
`zigbee_zk03840_trv.json`, `zigbee_zk03838_fht_*.json`,
`zigbee_zk03839_cs.json`), ViEventLog und der Serviceanleitung 6221420
abgeleitet. In den PyViCare-Testdaten bietet nur
`rooms.<n>.operating.programs.normalHeating` den Befehl `setTemperature` an;
ViEventLog sendet ihn an `…temperature.levels.normal.perceived`. Deshalb
nimmt ViCare Extras das erste Feature, das den Befehl als ausführbar meldet.
Ob die API die Befehle so annimmt, ist offen. Ein Raumregler ohne Räume (nur
`rooms.features.*`) erzeugt keine Entitäten.

### Liste aller Entitäten

Erzeugt mit `python scripts/list_entities.py`. Spalte „Kategorie“: „Diagnose“ heißt,
die Entität steht auf der Geräteseite unter „Diagnose“ (Werte für die
Fachkraft, nicht für den Alltag).

**Heizgerät**

| Plattform | Name | Einheit | Standard aktiv | Kategorie | Quelle |
| --- | --- | --- | --- | --- | --- |
| sensor | 4/3-Wege-Ventil Position |  | ja |  | `heating.valves.fourThreeWay.position` → `value` |
| sensor | Sekundärkreis Betriebszustand |  | ja |  | `heating.secondaryCircuit.operation.state` → `currentValue` |
| sensor | 4/3-Wege-Ventil Stellung Ist | % | ja | Diagnose | `heating.secondaryCircuit.valves.fourThreeWay` → `current` |
| sensor | 4/3-Wege-Ventil Stellung Soll | % | ja | Diagnose | `heating.secondaryCircuit.valves.fourThreeWay` → `target` |
| sensor | Wärmeleistung aktuell | kW | ja |  | `heating.heat.production.current` → `value` |
| sensor | Leistungsaufnahme aktuell | kW | ja |  | `heating.power.consumption.current` → `value` |
| sensor | Verdichter{suffix} Drehzahl | rps | ja |  | `heating.compressors.{n}.speed.current` → `value` |
| sensor | Verdichter{suffix} Drehzahl Soll | rps | ja | Diagnose | `heating.compressors.{n}.speed.setpoint` → `value` |
| sensor | Verdichter{suffix} Öltemperatur | °C | ja | Diagnose | `heating.compressors.{n}.sensors.temperature.oil` → `value` |
| sensor | Verdichter{suffix} Motorraumtemperatur | °C | ja | Diagnose | `heating.compressors.{n}.sensors.temperature.motorChamber` → `value` |
| binary_sensor | Verdichter{suffix} Kurbelwannenheizung |  | ja | Diagnose | `heating.compressors.{n}.heater.crankcase` → `active` |
| sensor | Economizer{suffix} Flüssiggastemperatur | °C | ja | Diagnose | `heating.economizers.{n}.sensors.temperature.liquid` → `value` |
| sensor | Expansionsventil {number} Soll | % | ja | Diagnose | `heating.sensors.valve.{n}.expansion.target` → `value` |
| sensor | Ventilator {number} | % | ja | Diagnose | `heating.primaryCircuit.fans.{n}.current` → `value` |
| binary_sensor | Abtauen |  | ja |  | `heating.outdoor.defrosting` → `active` |
| binary_sensor | Verdampfer{suffix} Sockelheizung |  | ja | Diagnose | `heating.evaporators.{n}.heater.base` → `active` |
| binary_sensor | Kondensatwannenheizung |  | ja | Diagnose | `heating.heater.condensatePan` → `active` |
| binary_sensor | Ventilatorringheizung |  | ja | Diagnose | `heating.heater.fanRing` → `active` |
| binary_sensor | Primärkreis 4/3-Wege-Ventil aktiv |  | nein | Diagnose | `heating.primaryCircuit.valves.fourThreeWay` → `active` |
| binary_sensor | Interne Pumpe |  | ja |  | `heating.boiler.pumps.internal` → `status` |
| sensor | Interne Pumpe Drehzahl | % | ja |  | `heating.boiler.pumps.internal.current` → `value` |
| sensor | Interne Pumpe Drehzahl Soll | % | ja | Diagnose | `heating.boiler.pumps.internal.target` → `value` |
| binary_sensor | Heizstab aktiv |  | ja | Diagnose | `heating.heatingRod` → `active` |
| binary_sensor | Heizstab Freigabe Warmwasser |  | nein | Diagnose | `heating.configuration.heatingRod.dhw` → `useApproved` |
| binary_sensor | Heizstab Freigabe Heizung |  | nein | Diagnose | `heating.configuration.heatingRod.heating` → `useApproved` |
| sensor | Heizstab maximale Außentemperatur | °C | nein | Diagnose | `heating.heatingRod.maximumOutsideTemperature` → `value` |
| binary_sensor | Externer Wärmeerzeuger |  | ja | Diagnose | `heating.secondaryHeatGenerator` → `active` |
| sensor | Heizkreis {number} aktives Programm |  | ja |  | `heating.circuits.{n}.operating.programs.active` → `value` |
| sensor | Heizkreis {number} Temperaturgrenze Minimum | °C | nein | Diagnose | `heating.circuits.{n}.temperature.levels` → `min` |
| sensor | Heizkreis {number} Temperaturgrenze Maximum | °C | nein | Diagnose | `heating.circuits.{n}.temperature.levels` → `max` |
| sensor | Heizkreis {number} Sommer-Eco Schwelle | °C | nein | Diagnose | `heating.circuits.{n}.configuration.summerEco.absolute` → `threshold` |
| sensor | Sekundärkreis Rücklauftemperatur Minimum | °C | nein | Diagnose | `heating.secondaryCircuit.temperature.return.minimum` → `value` |
| sensor | Kesseltemperatur | °C | nein | Diagnose | `heating.boiler.temperature.current` → `value` |
| sensor | Leistungsbegrenzung §14a |  | ja | Diagnose | `device.power.consumption.limitation` → `value` |
| sensor | Leistungsbegrenzung Status Verbrauch |  | ja | Diagnose | `device.power.statusReport.consumption` → `status` |
| sensor | Leistungsbegrenzung Limit Verbrauch | W | ja | Diagnose | `device.power.statusReport.consumption` → `limit` |
| sensor | Leistungsbegrenzung Status Erzeugung |  | nein | Diagnose | `device.power.statusReport.production` → `status` |
| binary_sensor | Warmwasser Hygienefunktion |  | ja | Diagnose | `heating.dhw.hygiene` → `enabled` |
| binary_sensor | Warmwasser Verbrühschutz |  | ja | Diagnose | `heating.dhw.scaldProtection` → `active` |
| binary_sensor | Externe Sperre |  | ja | Diagnose | `heating.external.lock` → `active` |
| binary_sensor | Externe Sperre (Gerät) |  | nein | Diagnose | `device.lock.external` → `active` |
| binary_sensor | Störungssperre |  | ja | Diagnose | `device.lock.malfunction` → `active` |
| binary_sensor | Ferienprogramm |  | ja |  | `heating.operating.programs.holiday` → `active` |
| binary_sensor | Ferien zu Hause |  | ja |  | `heating.operating.programs.holidayAtHome` → `active` |
| sensor | Stromverbrauch Warmwasser Verlauf | kWh | ja |  | `heating.power.consumption.dhw` |
| sensor | Stromverbrauch Heizung Verlauf | kWh | ja |  | `heating.power.consumption.heating` |
| sensor | Stromverbrauch gesamt Verlauf | kWh | ja |  | `heating.power.consumption.total` |
| sensor | Wärmeerzeugung Warmwasser | kWh | ja |  | `heating.heat.production.summary.dhw` |
| sensor | Wärmeerzeugung Heizung | kWh | ja |  | `heating.heat.production.summary.heating` |
| sensor | Wärmeerzeugung Kühlen | kWh | nein |  | `heating.heat.production.summary.cooling` |
| sensor | Stromverbrauch Kühlen | kWh | nein |  | `heating.power.consumption.summary.cooling` |
| sensor | Heizstab Stromverbrauch Warmwasser | kWh | ja |  | `heating.heatingRod.power.consumption.summary.dhw` |
| sensor | Heizstab Stromverbrauch Heizung | kWh | ja |  | `heating.heatingRod.power.consumption.summary.heating` |
| sensor | Meldungen |  | ja | Diagnose | `device.messages.status.raw` / `device.messages.info.raw` / `device.messages.service.raw` |
| sensor | Letzte Statusmeldung |  | ja |  | `device.messages.status.raw` |
| sensor | Aktive Statusmeldungen |  | ja | Diagnose | `device.messages.status.raw` |
| sensor | Betriebszustand |  | ja |  | `device.messages.status.raw` / `heating.compressors.0` |
| sensor | Heizstab aktive Stufen |  | ja |  | `device.messages.status.raw` + `heating.heatingRod` |
| sensor | COP aktuell |  | ja |  | `heating.heat.production.current` + `heating.power.consumption.current` |
| sensor | Warmwasser Zeitprogramm |  | ja |  | `heating.dhw.schedule` |
| sensor | Zirkulation Zeitprogramm |  | ja |  | `heating.dhw.pumps.circulation.schedule` |
| sensor | Heizkreis {number} Zeitprogramm |  | ja |  | `heating.circuits.{n}.heating.schedule` |

**Räume**

| Plattform | Name | Einheit | Standard aktiv | Kategorie | Quelle |
| --- | --- | --- | --- | --- | --- |
| sensor | Temperatur | °C | ja |  | `rooms.{n}.sensors.temperature` → `value` |
| sensor | Luftfeuchtigkeit | % | ja |  | `rooms.{n}.sensors.humidity` → `value` |
| sensor | CO2 | ppm | ja |  | `rooms.{n}.co2` → `concentration` / `rooms.{n}.sensors.co2` → `value` |
| sensor | Solltemperatur Normal | °C | ja |  | `rooms.{n}.temperature.levels.normal.heating` → `temperature` / `rooms.{n}.operating.programs.normalHeating` → `temperature` |
| sensor | Solltemperatur Reduziert | °C | ja |  | `rooms.{n}.temperature.levels.reduced.heating` → `temperature` / `rooms.{n}.operating.programs.reducedHeating` → `temperature` |
| sensor | Solltemperatur Komfort | °C | ja |  | `rooms.{n}.temperature.levels.comfort.heating` → `temperature` / `rooms.{n}.operating.programs.comfortHeating` → `temperature` |
| sensor | Solltemperatur wirksam | °C | ja |  | `rooms.{n}.temperature.levels.heating` → `temperature` |
| sensor | Solltemperatur Kühlen Normal | °C | nein |  | `rooms.{n}.temperature.levels.normal.cooling` → `temperature` |
| sensor | Solltemperatur Kühlen Reduziert | °C | nein |  | `rooms.{n}.temperature.levels.reduced.cooling` → `temperature` |
| sensor | Solltemperatur Normal (gefühlt) | °C | nein |  | `rooms.{n}.temperature.levels.normal.perceived` → `temperature` |
| sensor | Solltemperatur Komfort (gefühlt) | °C | nein |  | `rooms.{n}.temperature.levels.comfort.perceived` → `temperature` |
| sensor | Betriebsstufe |  | ja |  | `rooms.{n}.operating.state` → `level` |
| binary_sensor | Fenster |  | ja |  | `rooms.{n}.sensors.openWindow` → `value` / `rooms.{n}.sensors.window.openState` → `value` |
| binary_sensor | Kondensationsrisiko |  | ja |  | `rooms.{n}.condensationRisk` → `value` |
| binary_sensor | Kindersicherung |  | ja | Diagnose | `rooms.{n}.childLock` → `active` |

**Klima (Räume und Heizkörperthermostate)**

| Plattform | Gerät | Ist-Temperatur | Soll-Temperatur | Befehl | Aktion |
| --- | --- | --- | --- | --- | --- |
| climate | Raum (eigenes Gerät) | `rooms.{n}.sensors.temperature` → `value` | `rooms.{n}.temperature.levels.normal.perceived` → `temperature` / `rooms.{n}.temperature.levels.normal.heating` → `temperature` / `rooms.{n}.operating.programs.normalHeating` → `temperature` | `setTemperature` | `rooms.{n}.operating.state` → `demand` |
| climate | Heizkörperthermostat (Gerät der eingebauten Integration) | `device.sensors.temperature` → `value` (nur bei `status: connected`) | `trv.temperature` → `value` | `setTargetTemperature` | `trv.valve.position` → `position` > 0 |

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

`get_features` und `get_event_history` liefern nur eine Antwort. In den
Entwicklerwerkzeugen unter „Aktionen“ wird sie direkt angezeigt; in Skripten und Automationen ist
`response_variable` nötig.

## Aktion `vicare_extras.send_command` (Experten)

> **Achtung.** Diese Aktion schreibt. Sie sendet einen Befehl unverändert an
> die Viessmann-API und kann Einstellungen der Heizung ändern. Sie prüft
> weder, ob die API den Befehl anbietet, noch die Parameter. Nur verwenden,
> wenn klar ist, was der Befehl bewirkt. Sie ist **Administratoren
> vorbehalten** und gedacht für Diagnose, nicht für Automationen.

Zweck: herausfinden, ob die API einen Befehl annimmt, den sie am Feature
nicht anbietet (z. B. mit dem kostenlosen Zugang, siehe
[oben](#was-der-kostenlose-zugang-basic-liefert)). ViEventLog etwa sendet
`rooms.<n>.temperature.levels.normal.perceived` → `setTemperature` ohne diese
Prüfung.

| Feld | Pflicht | Bedeutung |
| --- | --- | --- |
| `vicare_device_id` | ja | Viessmann-Geräte-ID, z. B. `RoomControl-1`, `0` oder `zigbee-…` (siehe `get_features`) |
| `feature` | ja | Name des Features, z. B. `rooms.0.temperature.levels.normal.perceived` |
| `command` | ja | Name des Befehls, z. B. `setTemperature` |
| `params` | nein | Parameter als Objekt, Standard `{}`; werden ungeprüft gesendet |
| `gateway_serial` | nein | nur nötig, wenn mehrere Gateways ein Gerät mit derselben ID haben |

```yaml
action: vicare_extras.send_command
data:
  vicare_device_id: RoomControl-1
  feature: rooms.0.temperature.levels.normal.perceived
  command: setTemperature
  params:
    targetTemperature: 21
response_variable: antwort
```

Antwort:

```yaml
sent: true           # der Befehl wurde gesendet
advertised: false    # das Feature im Zwischenspeicher nennt den Befehl (nicht)
executable: null     # dessen isExecutable; null, wenn unbekannt
api_calls: 1         # immer genau ein Aufruf (ein POST)
success: true        # false, wenn die API den Befehl abgelehnt hat
response:            # Antwort der API …
  data: {success: true, reason: COMMAND_EXECUTION_SUCCESS}
```

Lehnt die API ab, meldet die Aktion **keinen Fehler**, sondern gibt die
Ablehnung zurück (`success: false`). `response` ist dann die Antwort der API
oder – wenn PyViCare sie in einen Fehler umwandelt – dessen Beschreibung:

```yaml
success: false
response:
  error_type: PyViCareCommandError
  message: "Command failed with status code 404. Reason given was: COMMAND_NOT_FOUND"
  status_code: 404            # wenn in der Meldung enthalten
  vi_error_id: "…"            # ViCare-Fehler-ID, wenn in der Meldung enthalten
```

Einen Fehler meldet die Aktion nur bei lokalen Problemen: Gerät nicht
gefunden oder mehrdeutig, eingebaute Integration nicht geladen, ungültige
Namen (erlaubt sind Buchstaben, Ziffern, Punkt, `-` und `_`).

- **Genau ein API-Aufruf** je Aufruf, auch bei Ablehnung; kein erneuter
  Versuch. Der Zwischenspeicher der eingebauten Integration wird nicht
  geleert, die Wirkung ist also erst nach deren nächster Abfrage sichtbar.
- `advertised` und `executable` stammen aus dem Zwischenspeicher (kein
  Aufruf).
- **Nicht gegen die echte API geprüft.**

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
      text: Wärmepumpe ist aus
      source: viessmann
      verified: true                          # false: Text unbestätigt
      category: status                        # status/info/warning/maintenance/fault
      active: true
    summary: "S.123: Wärmepumpe ist aus"      # von ViCare Extras ergänzt
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
`summary`; unbestätigte Texte haben `verified: false` und eine `summary` der
Form `S.1 (ungeprüft: …)`. Die Zeiten der Ereignishistorie sind echte
UTC-Zeiten (anders als die Gerätezeit in `device.messages.*.raw`).

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
- Alle Sensoren, Binärsensoren, Klima-Entitäten (lesend) und `get_features`:
  **0 Aufrufe**, immer.
- `get_event_history`: **1 Aufruf je Seite**, höchstens `max_pages`. Falls der
  erste Pfad mit „nicht gefunden“ antwortet, kommt einmalig 1 Aufruf für den
  Ausweichpfad hinzu; der funktionierende Pfad wird bis zum nächsten Neustart
  gemerkt.
- Solltemperatur an einer Klima-Entität ändern: **1 Aufruf je Änderung**.
- `send_command`: **1 Aufruf je Aufruf**.

Empfehlung: `max_pages: 1` verwenden, die Aktion nicht in kurzen Abständen
automatisieren und `api_calls` in der Antwort beachten. Ist das Limit
erschöpft, meldet die Aktion das mit dem Zeitpunkt der Rücksetzung – und auch
die eingebaute Integration bekommt bis dahin keine Daten mehr.

### Abfrageintervall der eingebauten Integration

**Die Sensoren von ViCare Extras kosten keine Aufrufe.** Sie seltener
aktualisieren zu lassen, spart deshalb nichts. Sparen lässt sich nur, indem die
*eingebaute* Integration seltener abfragt. Dafür gibt es eine Option:

**Einstellungen → Geräte & Dienste → ViCare Extras → Konfigurieren →
„Abfrageintervall der ViCare-Integration“** (Sekunden, 60 bis 900).

| Intervall | Aufrufe pro Tag (ein Gateway) |
| --- | --- |
| leer (Standard, 60 s) | bis 1440 |
| 90 s | bis 960 |
| 120 s | bis 720 |
| 300 s | bis 288 |

- **Leer lassen** heißt: ViCare Extras fasst die eingebaute Integration nicht
  an. Das ist die Voreinstellung.
- **Setzen und Löschen wirken ohne Neustart.** Beim Speichern wird nur der
  Eintrag von ViCare Extras neu geladen. Die eingebaute Integration verwendet
  den neuen Wert ab ihrer nächsten Abfrage, also nach höchstens einem alten
  Intervall. Wird das Feld geleert (oder ViCare Extras entfernt bzw.
  deaktiviert), gilt wieder der ursprüngliche Wert (60 s je Gateway).
- Das Intervall wird nie *kürzer* als das, was die eingebaute Integration
  selbst festlegt (bei zwei Gateways z. B. 120 s). Ein kleinerer Wert bleibt
  dann wirkungslos.
- Lädt die eingebaute Integration neu, setzt ViCare Extras den Wert innerhalb
  von höchstens zwei Minuten erneut.
- Alle Werte in Home Assistant – auch die der eingebauten Integration –
  werden entsprechend seltener aktualisiert. Die Entitäten von ViCare Extras
  folgen dem Intervall: Sie schauen jeweils 5 Sekunden früher nach, als die
  eingebaute Integration abfragt (55 s bei 60 s, 85 s bei 90 s), höchstens
  aber alle 120 Sekunden – ohne API-Aufruf. Ihre Werte erscheinen damit bis
  zu ein Intervall (höchstens zwei Minuten) später als bei der eingebauten
  Integration.
- Im Protokoll steht je Änderung eine Zeile auf Stufe „info“:
  `Poll interval of the ViCare integration set to 90 s (was 60 s)` bzw.
  `Poll interval of the ViCare integration restored to 60 s`. Home Assistant
  zeigt Info-Zeilen nur, wenn sie eingeschaltet sind:

  ```yaml
  logger:
    logs:
      custom_components.vicare_extras: info
  ```

  Ohne diese Einstellung zeigt die Diagnose (siehe [Fehlersuche](#fehlersuche))
  unter `poll_interval` die Option, das Intervall der eingebauten Integration
  und das eigene.

Technisch setzt ViCare Extras dafür `update_interval` am Koordinator der
eingebauten Integration und verlängert die Cache-Dauer von PyViCare
entsprechend (sonst würde ein Lesezugriff zwischen zwei Abfragen erneut
abrufen). Passt die innere Struktur einer künftigen Home-Assistant-Version
nicht mehr, wird nichts verändert und einmalig eine Warnung protokolliert.
**Nicht in einer laufenden Instanz geprüft**, siehe [Teststand](#teststand).

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
Neustart nötig. Nach einem **Update** auf eine neue Version muss Home
Assistant **neu gestartet** werden; ein Neuladen des Eintrags genügt nicht,
weil bereits geladener Python-Code sonst nicht ersetzt wird.

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
Geräte, Klima-Entitäten der Heizkörperthermostate bei deren Geräten), die
Aktionen unter **Entwicklerwerkzeuge → Aktionen**.

### Optionen

Über **Konfigurieren** am Eintrag gibt es eine einzige, freiwillige Option:
das [Abfrageintervall der eingebauten Integration](#abfrageintervall-der-eingebauten-integration).

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
  eingebauten Integration (`runtime_data`, für die Intervall-Option auch
  `coordinator.update_interval`) und von PyViCare (`_cache`,
  `_cacheDuration`, für Befehle `setProperty`) zu. Ein Home-Assistant-Update kann
  das brechen. In dem Fall werden die Entitäten „nicht verfügbar“ bzw. die
  Einrichtung wird wiederholt und die Aktionen melden einen klaren Fehler; die
  eingebaute Integration wird davon nicht beeinträchtigt.
- Entitäten gibt es nur für Geräte vom Typ `heating`, die die eingebaute
  Integration einrichtet, für Räume eines Raumreglers und (nur Klima) für
  Heizkörperthermostate, die die eingebaute Integration einrichtet.
  `get_features` erreicht alle Geräte des Kontos.
- **Befehle** sendet ViCare Extras von sich aus nur für die Solltemperatur
  von Räumen und Heizkörperthermostaten (und nur, wenn die API den Befehl
  anbietet – beim kostenlosen Zugang also gar nicht); alles Weitere nur über
  die Experten-Aktion `send_command`. Betriebsarten, Zeitprogramme, Stufen, Warmwasser
  usw. werden nicht geschaltet. Die Option für das Abfrageintervall greift in
  die eingebaute Integration ein (siehe oben); alles andere liest nur.
- Der Betriebszustand und die Liste der aktiven Statusmeldungen beruhen auf
  der Beobachtung, dass `device.messages.status.raw` die aktiven Meldungen
  enthält (siehe oben).
- Die Wertebereiche der Auswahl-Sensoren (Ventilstellung, Sekundärkreis,
  §14a) sind nur teilweise bekannt; unbekannte Werte erscheinen unübersetzt.
- Features auf Gateway-Ebene, die keinem Gerät zugeordnet sind (z. B.
  `gateway.devices`), gibt `get_features` nicht zurück.
- Hält die eingebaute Integration gerade keine Daten (kurz während ihrer
  regelmäßigen Abfrage oder bei einer Störung der Viessmann-API), wartet
  `get_features` einige Sekunden und meldet sonst einen Fehler, statt selbst
  abzufragen. Die Entitäten behalten ihren letzten Wert bis zu 15 Minuten.
- Von der Ereignishistorie wird nur die Version `v2` verwendet. `v3`, die
  Parameter `date`, `timestamp` und `origins` sowie die Export-Schnittstelle
  sind nicht umgesetzt.
- Die Viessmann-API nennt in ihrer Dokumentation eine Schnittstelle „Service
  Documents / Error Database“ (das FHEM-Modul `98_vitoconnect.pm` fragt sie
  je Störungscode ab). Sie wird nicht verwendet, weil jede Abfrage ein
  API-Aufruf wäre; die Meldungstexte stammen aus der mitgelieferten Tabelle.

## Fehlersuche

- **„Die Integration Viessmann ViCare ist nicht eingerichtet oder nicht
  geladen“**: zuerst die eingebaute Integration in Ordnung bringen (z. B.
  erneut anmelden oder das Ende einer Limit-Sperre abwarten).
- **„… passt nicht zur installierten Home-Assistant-Version“**: Die Interna
  haben sich geändert; ViCare Extras muss angepasst werden.
- **Einrichtung wird wiederholt / Entitäten fehlen**: Unter Einstellungen →
  Geräte & Dienste → ViCare Extras → ⋮ → **Diagnose herunterladen** steht, ob
  Daten gefunden wurden, welche Features vorhanden sind und welche
  Abfrageintervalle gelten. Die Diagnose enthält keine Token, Seriennummern,
  Anlagen-IDs oder Zigbee-Adressen.
- **Klima-Entität fehlt**: Es wurde keine Solltemperatur gefunden. Mit
  `get_features` (`vicare_device_id: RoomControl-1` bzw. `device_type: zigbee`)
  prüfen, welche Features das Gerät liefert.
- **Solltemperatur lässt sich nicht einstellen**: Die API meldet für dieses
  Feature keinen ausführbaren Befehl (Attribut `setpoint_writable: false`).
  Mit `get_features` und `full: true` sind die angebotenen Befehle sichtbar.
- Ausführliche Protokollierung:

  ```yaml
  logger:
    logs:
      custom_components.vicare_extras: debug
  ```

  ViCare Extras protokolliert nie Token. Achtung: Das Debug-Protokoll von
  `PyViCare` selbst (Logger `PyViCare`) enthält vollständige API-Antworten.

## Teststand

Ausgeführt (ohne Home Assistant, ohne Netzwerk, ohne Viessmann-API):

- `python -m py_compile` für alle Dateien unter Python 3.13 und 3.14,
- `python scripts/check_consistency.py` (JSON, Übersetzungen en/de,
  Entitätsnamen und Zustände, Fehlertexte und Platzhalter, `services.yaml`,
  Icons, Manifest, Options-Dialog, Plattformen, Meldungstabelle samt
  Kennzeichnung unbestätigter Texte),
- `python scripts/build_message_codes.py --check` (Tabelle passt zur
  Textdatei),
- `python scripts/check_ha_imports.py <core-checkout>` gegen Core 2026.11.1
  (alle importierten Home-Assistant-Namen existieren dort),
- `pytest tests/unit`: Logik der Aktionen, des Koordinators, der Entitäten,
  der Klima-Entitäten, der Befehle und des Abfrageintervalls mit
  nachgebildeten PyViCare-Objekten gegen **vereinfachte Nachbildungen** von
  Home Assistant (`tests/unit/stubs`). Grundlage ist
  `tests/fixtures/vitocal250a_features.json`: Aufbau (Feature-Namen,
  Eigenschaften, Einheiten, Auswahlwerte, Meldungscodes) von einer echten
  Vitocal 250-A, Kennungen und Zählerstände ersetzt. Mit
  `PYVICARE_SRC=<PyViCare-Checkout>` zusätzlich gegen den echten
  PyViCare-Code 2.63.0 (Cache-Verhalten, Fehlerbehandlung von `get()`,
  Senden eines Befehls über `setProperty` an eine nachgebildete
  HTTP-Sitzung) und gegen dessen Testdaten für Räume und Zigbee-Geräte.

Nicht ausgeführt bzw. nicht geprüft:

- `pytest tests/ha` (Tests mit echtem Home Assistant; benötigt
  `pytest-homeassistant-custom-component` und `PyViCare`),
- Version 0.3.1 in einer laufenden Instanz (0.3.0 lief dort, siehe oben):
  Verknüpfung der Raum-Geräte mit dem Wärmeerzeuger, Raumname „Raum n“,
  Aktion `send_command`,
- der Options-Dialog und das Abfrageintervall in einem echten Home Assistant
  (insbesondere, dass die eingebaute Integration danach tatsächlich seltener
  abfragt),
- das Einstellen einer Solltemperatur und überhaupt das Senden eines Befehls
  an die Viessmann-API (auch über `send_command`).

`tests/unit` und `tests/ha` müssen getrennt gestartet werden.

## Lizenz

MIT, siehe [LICENSE](LICENSE). Kein offizielles Produkt von Viessmann oder
Home Assistant.

Meldungstexte: eigene Formulierungen; die Bedeutung der Codes folgt den
Viessmann-Serviceanleitungen 6200041, 6221420 und 6179923 (Viessmann Climate
Solutions). Sieben als ungeprüft gekennzeichnete Texte stammen aus
[ViEventLog](https://github.com/mschneider82/vieventlog) (MIT, © 2025
Matthias Schneider) bzw. dem FHEM-Modul `98_vitoconnect.pm`.
