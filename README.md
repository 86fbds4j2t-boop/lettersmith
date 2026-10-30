# Lettersmith – Foto → Vektor-Schrift für Affinity Designer 2

Lokales Werkzeug: Foto hochladen, Buchstaben-Umrisse werden als Vektorpfade
erkannt, Glyphen werden beschriftet und daraus wird neuer Text als SVG
zusammengesetzt – direkt in Affinity Designer 2 öffnen und weiterbearbeiten.

## Start

**macOS / Linux:**

    pip install -r requirements.txt
    python3 app.py

**Windows (Eingabeaufforderung / PowerShell):**

    py -m pip install -r requirements.txt
    py app.py

Auf Windows heißt der Befehl `py` (oder `python`), nicht `python3`.
Die Abhängigkeiten müssen einmalig installiert werden – der Fehler
`ModuleNotFoundError: No module named 'cv2'` bedeutet, dass dieser
Schritt noch fehlt oder pip in einen anderen Python installiert hat.
Falls `py` nicht existiert: Python von python.org installieren und
beim Installer "Add python.exe to PATH" aktivieren.

Dann im Browser öffnen: http://127.0.0.1:5000

## Ablauf

1. **Foto hochladen** (JPG/PNG). Regler anpassen bis die Vorschau die
   Buchstaben sauber trennt:
   - *Kantenschärfe / Schwellen-Offset*: Binarisierung (hell/dunkel-Trennung)
   - *Glättung*: wie stark die Pfade vereinfacht werden (höher = weniger Punkte)
   - *Mindestfläche*: filtert Rauschen/flecken weg
   - *Lücken-Toleranz*: wie nah benachbarte Formen zu einem Buchstaben
     zusammengefasst werden (z. B. i-Punkt + i-Schaft)
2. **Glyphen beschriften**: unter jede erkannte Form den Buchstaben eintragen.
   Fehlende Buchstaben im Zieltext werden übersprungen (Meldung siehe Export).
   Optional eine Form mit `space` beschriften für echte Leerzeichenbreiten.
**Helle Schrift auf dunklem Grund** (z. B. gravierte Buchstaben in Stein,
Drahtbuchstaben vor dunkler Wand): das Häkchen „Helle Schrift auf dunklem
Grund" setzen. Bei grobkörnigem Material (Granit o. Ä.) hilft zusätzlich:
Mindestfläche hochdrehen und Kantenschärfe erhöhen.

3. **Text bauen**: Zieltext eingeben (Zeilenumbrüche erlaubt), Größe,
   Laufweite und Zeilenabstand einstellen → *Text als SVG exportieren*.
   Alternativ: *Alle Glyphen als SVG* (Referenzblatt).

## SVG in Affinity Designer 2

`Datei → Öffnen` bzw. per Drag&Drop. Die Pfade sind echte Vektorkurven
(`fill-rule: evenodd`, Löcher z. B. in „O" bleiben Löcher) und lassen sich
frei skalieren, einfärben und als Kurven weiterbearbeiten.

## Hinweise für gute Ergebnisse

- Gleichmäßige Beleuchtung, scharfes Foto, Buchstaben möglichst kontrastreich
  zum Hintergrund
- Das Foto sollte die Schrift waagerecht zeigen; ggf. vorher gerade drehen
- Handgeschriebene Vorlagen mit verbundenen Buchstaben: Lücken-Toleranz
  erhöhen, damit zusammenhängende Formen als ein Buchstabe erkannt werden
