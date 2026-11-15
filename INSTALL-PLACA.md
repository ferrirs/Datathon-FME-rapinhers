# Cangur Tutor: instal·lar-lo a la placa

Guia per a qui té la placa. Tot es fa des del Terminal del Mac. On posa `<IP>`, escriu l'adreça de la placa (surt a App Lab, o a la placa amb `hostname -I`).

Necessites dos fitxers a la carpeta **Descàrregues** del Mac:

- `paquet-placa-20261114.zip`: les dades de M3Kang (problemes, imatges, temes). **No el pugis mai a GitHub.**
- `cangur-tutor-final.zip`: el codi del tutor.

Els passos 0 a 8 del README ja han d'estar fets: els models i els seus serveis no es toquen.

---

## Pas 1. Copia els dos zips a la placa

```bash
cd ~/Downloads
scp paquet-placa-20261114.zip cangur-tutor-final.zip arduino@<IP>:~/datathon-UPC-maths-qualcomm-arduino-unoq/
```

Demana la contrasenya de la placa. El paquet de dades fa uns 140 MB, així que triga una mica.

**Si `scp` no connecta**, connecta la placa per USB i fes:

```bash
cd ~/Downloads
adb push paquet-placa-20261114.zip cangur-tutor-final.zip /home/arduino/datathon-UPC-maths-qualcomm-arduino-unoq/
```

Si no tens `adb`, instal·la'l amb `brew install android-platform-tools`.

---

## Pas 2. Entra a la placa i descomprimeix-ho

```bash
ssh arduino@<IP>
```

Si vas per USB, fes `adb shell` en lloc de `ssh`.

Ja dins de la placa:

```bash
cd ~/datathon-UPC-maths-qualcomm-arduino-unoq
unzip -o paquet-placa-20261114.zip
unzip -o cangur-tutor-final.zip
rm -rf app/cangur-matrix board/systemd/math-tutor.service
```

**L'ordre importa:** primer les dades, després el codi.

Comprova que les dades són al seu lloc:

```bash
wc -l data/train.jsonl data/val.jsonl
ls data/images | wc -l
ls data/temes.json
```

**Ha de sortir:** 2932 i 562 línies, 3494 imatges, i el fitxer `data/temes.json`.

---

## Pas 3. Comprova el codi

```bash
python3 -m unittest discover -s tests
```

**Ha de sortir:** `Ran 53 tests` i `OK`. No necessita ni els models ni les dades.

---

## Pas 4. Construeix el banc de problemes

Comprova que el servidor d'embeddings respon:

```bash
curl -s http://127.0.0.1:8082/health
```

**Ha de sortir:** `{"status":"ok"}`. Si no, engega'l: `sudo systemctl start math-embed`.

Construeix el banc:

```bash
python3 tutor_build.py all
```

Triga uns 10 minuts. Si s'atura, torna'l a executar i continua on s'havia quedat.

**Al final ha de sortir:**
- `1152 problems a student can answer`
- unes 350 com a text
- unes 800 com a problema escanejat

**Copia tota aquesta sortida i passa-la a l'equip:** són xifres per al pitch.

---

## Pas 5. Crea l'alumne de la demo

```bash
python3 tutor_demo.py
```

Crea un alumne anomenat `Demo` amb 80 problemes ja fets: alguns temes dominats i un repàs pendent. A la demo, s'escriu aquest nom a la pàgina. Cal dir al pitch que aquest historial és simulat.

---

## Pas 6. Instal·la i engega l'app d'App Lab

```bash
bash board/install_app.sh
arduino-app-cli app start user:cangur-tutor
```

La primera vegada triga un minut: compila el sketch de la matriu.

**Ha de sortir:** `problem bank installed` i `1747 images in 'cat' copied`, i la matriu de la placa ha de mostrar un cangur.

Per veure què diu l'app:

```bash
arduino-app-cli app logs /home/arduino/ArduinoApps/cangur-tutor --all
```

**Ha de sortir:** `Cangur Tutor: problems in 'cat', 10 topics`.

---

## Pas 7. Obre la pàgina

Obre **un altre terminal al Mac** (no a la placa).

Amb la placa connectada per USB:

```bash
adb forward tcp:7000 tcp:7000
open http://127.0.0.1:7000
```

Si el Mac i la placa són a la mateixa xarxa, també pots obrir directament `http://<IP>:7000`.

---

## Pas 8. Comprova-ho i apunta-ho

1. Escriu el nom `Demo`. Ha de sortir el mapa de temes amb alguns temes dominats.
2. Respon un problema. La matriu de la placa fa un vist o una creu, i després torna a les columnes dels temes.
3. Demana pistes amb el botó. Cada clic n'afegeix una de nova a sota del problema.
4. A la placa, amb l'app engegada, mira quanta memòria queda:
   ```bash
   free -m
   ```

Passa a l'equip els números del pas 4 i la memòria lliure.

---

## Opcional: pistes del model

El tutor funciona sense aquest pas. Si el voleu fer:

```bash
python3 tutor_hints.py --try 10
```

Escriu 10 pistes de prova i no en desa cap. Llegiu-les i decidiu si valen la pena.

Si sí:

```bash
python3 tutor_hints.py
```

Fa unes 350 pistes. A la placa triga unes dues hores, i es pot aturar i reprendre. Després:

```bash
python3 tutor_hints.py --review 20
arduino-app-cli app stop user:cangur-tutor
bash board/install_app.sh
arduino-app-cli app start user:cangur-tutor
```

L'última part torna a instal·lar l'app amb les pistes. Els alumnes que ja han practicat es conserven.

---

## Si alguna cosa falla

| Què passa | Què fer |
| --- | --- |
| `scp`: `Connection refused` o no connecta | Fes servir `adb push` (pas 1) |
| `tutor_build.py`: el servidor d'embeddings no respon | `sudo systemctl start math-embed` i torna-ho a executar |
| L'app diu `older version` | Torna a fer el pas 4 i el pas 6 |
| La pàgina no carrega al port 7000 | Mira `arduino-app-cli app logs ...` i envia el que surti |
| No es veuen les imatges | Comprova que existeix `data/images` i torna a fer `bash board/install_app.sh` |
| La matriu no canvia | Al registre de l'app hi haurà una línia `LED matrix: ...`. La pàgina continua funcionant |

**Pla B per a la demo**, si App Lab dona problemes: la mateixa pàgina, sense la matriu.

```bash
python3 tutor_server.py --host 0.0.0.0
```

Obre `http://<IP>:8090`, o per USB amb `adb forward tcp:8090 tcp:8090` i `http://127.0.0.1:8090`.

---

## Per actualitzar el codi més endavant

Copia el zip nou a la placa (pas 1) i fes:

```bash
cd ~/datathon-UPC-maths-qualcomm-arduino-unoq
unzip -o cangur-tutor-final.zip
arduino-app-cli app stop user:cangur-tutor
bash board/install_app.sh
arduino-app-cli app start user:cangur-tutor
```

Les dades, el banc i els alumnes es conserven.
