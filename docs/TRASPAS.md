# Cangur Tutor: què ha de fer cadascú

Guia curta per posar en marxa el tutor amb les dades reals. Com funciona per dins: [`TUTOR.md`](TUTOR.md).

El zip es descomprimeix a l'arrel del repo (la carpeta on hi ha `predict.py`) i no modifica cap fitxer dels organitzadors. Els passos 0 a 8 del README, els models i les dades de `data/` no es toquen.

```powershell
# Windows (PowerShell)
Expand-Archive -Force cangur-tutor.zip .
```

```bash
# Mac, Linux i la placa
unzip -o cangur-tutor.zip
```

Si havíeu descomprimit una versió anterior, esborreu el que ja no es fa servir: la carpeta `app/cangur-matrix` i el fitxer `board/systemd/math-tutor.service`, si hi són.

Comprovació, a qualsevol màquina (a Windows, `python`):

```bash
python3 -m unittest discover -s tests
```

Ha d'acabar amb `Ran 53 tests` i `OK`. No necessita ni els models ni les dades.

## 1. Qui té les dades i els servidors al portàtil: construir el banc

A la carpeta `data/` hi ha d'haver `train.jsonl`, `val.jsonl`, `temes.json` i `images/`. Amb els dos servidors de llama.cpp engegats (ports 8081 i 8082):

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python tutor_build.py all
```

Triga uns minuts i es pot tornar a llançar si s'atura. Al final imprimeix el resum del banc: amb les dades del 14/11 han de sortir **1.152 problemes** al quiz, uns 350 mostrats com a text i uns 800 com a problema escanejat. Deseu aquesta sortida: són xifres del pitch.

Després, les pistes del model. Primer llegiu-ne deu i decidiu si valen la pena:

```powershell
.venv\Scripts\python tutor_hints.py --try 10
```

Si són acceptables, escriviu-les totes (uns 350 problemes; al portàtil, pocs minuts) i reviseu-ne vint a mà:

```powershell
.venv\Scripts\python tutor_hints.py
.venv\Scripts\python tutor_hints.py --review 20
```

Si no ho són, salteu aquest pas: el tutor funciona igual, amb un graó menys a l'escala.

Per acabar, l'alumne de la demo i les mesures del motor:

```powershell
.venv\Scripts\python tutor_demo.py
.venv\Scripts\python tutor_simulate.py
```

Passeu `data/tutor.db` a qui té la placa, en mà o per `scp`. **Mai per GitHub**: conté text de M3Kang.

## 2. Qui té la placa: instal·lar l'app d'App Lab

A la placa, per SSH, dins la carpeta del repo, amb el zip descomprimit. A `data/` hi ha d'haver el `tutor.db` del pas 1 i la carpeta `images/`.

```bash
python3 tutor_build.py stats                    # comprova que el banc ha arribat bé
bash board/install_app.sh                       # copia l'app, el banc i les imatges a ArduinoApps
arduino-app-cli app start user:cangur-tutor     # o engegueu-la des d'App Lab
arduino-app-cli app logs /home/arduino/ArduinoApps/cangur-tutor --all
```

Al registre ha de sortir `Cangur Tutor: problems in 'cat', 10 topics`. La primera engegada triga un minut: compila el sketch.

Al portàtil connectat per USB, amb el Wi-Fi apagat:

```bash
adb forward tcp:7000 tcp:7000
```

i obriu <http://127.0.0.1:7000>. A Mac, `adb` s'instal·la amb `brew install android-platform-tools`.

Tres coses a comprovar i apuntar:

1. La pàgina carrega i la matriu mostra un cangur.
2. Quan algú respon, la matriu dibuixa un vist o una creu i després les columnes dels temes.
3. `free -m` amb l'app i els dos servidors engegats: quanta memòria queda.

Cada vegada que canvieu el codi o el banc: atureu l'app, torneu a executar `bash board/install_app.sh` i engegueu-la. Els alumnes que ja han practicat a la placa es conserven.

## 3. Si alguna cosa falla

| Què passa | Què fer |
| --- | --- |
| `tutor_build.py` diu que el servidor d'embeddings no respon | Engegueu el servidor del port 8082 (README, pas 6 o 7) i torneu-ho a llançar: continua on s'havia aturat |
| L'app diu `This bank was built by an older version` | El `tutor.db` és d'una versió anterior: torneu a fer el pas 1 |
| La pàgina no carrega al port 7000 | Mireu `arduino-app-cli app logs ...`. Si l'app no arrenca, `python3 tutor_server.py --host 0.0.0.0` serveix la mateixa pàgina al port 8090, sense la matriu |
| No es veuen les imatges dels problemes | Falta `data/images/` a la placa quan s'ha executat `install_app.sh`. Copieu-la i torneu-lo a executar |
| La matriu no canvia | El registre de l'app ho diu amb una línia `LED matrix: ...`. La web continua funcionant |

## 4. Per a la demo

- Escriviu el nom `Demo` a la pàgina: té un historial simulat, amb temes dominats i un repàs pendent. Digueu-ho al pitch.
- Trieu abans els problemes que ensenyareu i proveu-los el mateix dia. Alguns problemes han quedat en un tema que no és el seu.
- Wi-Fi apagat, `adb forward`, i un vídeo de reserva.
