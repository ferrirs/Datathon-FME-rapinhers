# Cangur Tutor

Entrenament adaptatiu amb problemes de M3Kang, servit per la placa. L'alumne respon en una pàgina web; un motor Elo per tema tria el problema següent; una escala de sis pistes l'acompanya sense donar-li la resposta; la matriu LED mostra el seu mapa de temes.

Tot el codi nou viu en fitxers propis. No toca `predict.py`, `eval.py` ni `copilot/pipeline.py`.

## Estat: què està provat i què no

| Peça | Estat |
| --- | --- |
| Motor adaptatiu, escala de pistes, diagnòstic, API, pàgina web | Provat aquí amb 40 tests i al navegador, sobre un banc **sintètic** de 480 problemes |
| Construcció del banc (`tutor_build.py`) | Provada amb el banc sintètic. **No s'ha executat amb M3Kang**: des d'on s'ha escrit no hi havia accés a Hugging Face |
| Crides al model i als embeddings | Provades contra servidors falsos (`tests/fake_servers.py`) que imiten l'API de llama.cpp. **No provades a la placa** |
| Classificació de temes | El mètode funciona; la qualitat amb problemes reals és desconeguda fins que etiqueteu 100 problemes a mà |
| App de la matriu LED (`app/cangur-matrix`) | Escrita seguint l'exemple de la skill `unoq-hardware-ui`. **No provada en cap placa** |
| Correcció del biaix de lletra (`copilot/debias.py`) | Lògica provada amb respostes falses. El format de `logprobs` del servidor real s'ha de comprovar (vegeu més avall) |

Els números del simulador que surten en aquest document són del banc sintètic. Serveixen per comprovar el motor, no per al pitch: torneu-los a generar amb el banc real.

## Fitxers

```text
copilot/tutor/
  settings.py     paràmetres (es poden canviar a config.env amb el prefix TUTOR_)
  db.py           esquema de data/tutor.db
  engine.py       Elo amb atzar, selecció de tema, domini i repàs espaiat (funcions pures)
  service.py      la classe Tutor: start, next, hint, answer, discard, profile, frame
  diagnose.py     regles sobre els distractors i missatges en català
  topics.py       classificador de temes (prototips + paraules clau + llavors) i k-means
  llmhint.py      l'única crida al model: una frase, amb memòria cau i filtres
  matrix.py       marcs de 8x13 per a la matriu LED
  textutil.py     números, preguntes, paraules
  content/topics.json     els 10 temes: nom, descripcions en anglès, paraules clau
  content/cards_ca.json   20 targetes d'estratègia i analogia (2 per tema)
copilot/debias.py         correcció del biaix de lletra per a predict.py (opcional)
tutor_build.py            construeix data/tutor.db
tutor_server.py           pàgina web i API, port 8090
tutor_web/index.html      la pàgina (un sol fitxer, sense CDN)
tutor_simulate.py         alumnes simulats i mètriques del motor
tutor_hints.py            prova, genera i audita les pistes del model
tutor_synthetic.py        banc inventat per desenvolupar sense M3Kang
calibrate_letters.py      mesura el biaix de lletra del model
app/cangur-matrix/        app d'App Lab que dibuixa la matriu
board/systemd/math-tutor.service
tests/test_tutor.py       40 tests
tests/fake_servers.py     substituts dels dos servidors de llama.cpp per al portàtil
```

## Prova-ho al portàtil, sense placa ni M3Kang

```bash
python3 -m unittest discover -s tests
python3 tutor_synthetic.py
python3 tutor_build.py all --input data/synthetic.jsonl --db data/tutor_synth.db \
    --hand data/synthetic_labels.csv --fake-embed
python3 tutor_server.py --db data/tutor_synth.db --no-model
```

Obriu <http://127.0.0.1:8090>. Per provar també les crides al model, engegueu `python3 tests/fake_servers.py` en un altre terminal i traieu `--no-model` i `--fake-embed`.

## A la placa, amb M3Kang

Amb els passos 0 a 10 del README fets (serveis engegats, `data/train.jsonl` i `data/val.jsonl` copiats). Copieu també les imatges (`prepare_m3kang.py --save-images`, pas «Export the images»): amb imatge, l'alumne pot respondre també els problemes on l'OCR no ha llegit les opcions.

```bash
cd ~/datathon-UPC-maths-qualcomm-arduino-unoq
python3 tutor_build.py all          # banc, vectors, veïns, temes, opcions, resum
python3 tutor_server.py             # deixeu-lo engegat
```

Al portàtil, per USB i amb el Wi-Fi apagat:

```bash
adb forward tcp:8090 tcp:8090
```

`tutor_build.py all` es pot aturar i tornar a llançar: els vectors ja calculats es conserven. Els alumnes i el seu historial també es conserven quan reconstruïu el contingut. Cost estimat a la placa: uns 8 minuts de vectors per a 1.747 problemes (el README mesura 911 en 4 minuts) i els veïns en segons si hi ha `numpy`, minuts si no.

Per engegar-lo a l'arrencada:

```bash
sudo cp board/systemd/math-tutor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now math-tutor
```

### La matriu LED

Copieu `app/cangur-matrix` a `/home/arduino/ArduinoApps/` i engegueu-la des d'App Lab. L'app només demana a `http://127.0.0.1:8090/api/matrix` què ha de dibuixar. Primer que cal comprovar: que el seu registre no digui `tutor unreachable`. Si App Lab l'executa en un contenidor on `127.0.0.1` no és la placa, engegueu el tutor amb `--host 0.0.0.0` i poseu l'adreça de la placa a `TUTOR_URL` (`python/main.py`).

Què mostra: una columna per tema que creix amb el domini (plena i brillant quan està dominat), un vist o una creu durant un segon i mig després de cada resposta, i un interrogant mentre el model escriu.

## Temes: el que heu de fer vosaltres

M3Kang no porta tema. El classificador suma tres vots: la similitud amb descripcions en anglès de cada tema, paraules clau, i els temes dels 5 problemes etiquetats a mà més propers.

```bash
python3 tutor_build.py clusters --k 12       # 1. mireu què agrupen sols els embeddings
python3 tutor_build.py sample --n 100        # 2. escriu data/hand_labels.csv
#    ompliu la columna "topic" amb una clau de content/topics.json
python3 tutor_build.py topics --hand data/hand_labels.csv   # 3. classifica i valida
python3 tutor_build.py stats                 # 4. problemes per tema i nivell
```

El pas 3 imprimeix l'encert amb validació *leave-one-out* sobre les vostres etiquetes i les confusions més freqüents. És la xifra de qualitat dels temes per al pitch. Si dos temes es confonen molt, fusioneu-los a `content/topics.json` (i les seves targetes a `cards_ca.json`). Els problemes amb poc marge entre el primer i el segon tema (`TUTOR_MIN_TOPIC_MARGIN`, 0,03 per defecte) no compten per al domini; només surten com a problemes de reparació.

Si canvieu les claus dels temes, canvieu-les també a `cards_ca.json`: un tema sense targetes se salta el graó d'estratègia.

## Com funciona

### El bucle

1. `start`: nom i curs. L'habilitat inicial de cada tema surt del curs.
2. `next`: tria un tema (els febles pesen més, els dominats només quan toca repàs, mai més de 3 seguits del mateix) i, dins del tema, un dels 5 problemes no vistos amb dificultat més propera a la que dona un 70 % d'encert.
3. `hint`: puja un graó. Un graó que no té res a dir se salta i no descompta.
4. `answer`: si falla, rep un diagnòstic i un segon intent. Si torna a fallar, veu la resposta i el problema següent és el veí més semblant que sigui més fàcil.

### El motor (`engine.py`)

- Dificultat inicial: `b = 1000 + 120·nivell + 80·(franja − 1)`. La franja (1 a 3) és el terç de la prova on cau la pregunta, i surt del número de pregunta de l'`id`.
- Probabilitat d'encert amb un terra del 20 % (cinc opcions): `p = 0,2 + 0,8 / (1 + 10^((b − θ)/400))`.
- Puntuació d'un intent: 1 si encerta a la primera, menys 0,2 per pista (mínim 0,4); 0,2 si encerta al segon intent; 0 si no.
- Actualització: `θ ← θ + K·(puntuació − p)`, amb `K = 24 + 96/(1 + 0,2·n)`. El que s'aprèn en un tema mou també els temes amb pocs intents, i deixa de fer-ho de seguida que tenen dades pròpies.
- Domini: 5 intents o més, 3 dels 4 últims nets (a la primera, amb una pista com a màxim) i un 75 % d'encert esperat en un problema de franja 2 del seu curs.
- Repàs: als 6 problemes; si el supera, l'interval es duplica (12, 24, 48); si el falla, el tema torna a «consolidant».

### L'escala de pistes

| Graó | Què veu l'alumne | D'on surt |
| --- | --- | --- |
| 1 | La pregunta separada i les dades de l'enunciat | Expressions regulars |
| 2 | Una estratègia amb una analogia | `content/cards_ca.json` |
| 3 | Un problema semblant que ell ja va encertar. Si no n'hi ha, un de semblant i més fàcil amb la seva resposta | Taules `neighbors` i `attempts` |
| 4 | «Descarta una opció que segur que no pot ser» | Res a calcular |
| 5 | Una frase del model sobre el primer pas | `llmhint.py`, desada o generada al moment |
| 6 | La resposta i un problema anàleg | Etiqueta de M3Kang |

Descartar una opció no rep resposta immediata: dir «aquesta no la pots descartar» revelaria la solució. L'alumne ho sap al final.

El model llegeix el problema en anglès en segon pla quan es mostra (`cache_prompt`), de manera que la pista només ha de llegir la instrucció final. Abans d'ensenyar-la, `llmhint.check` la rebutja si conté el valor o la lletra de l'opció correcta, si diu «la resposta és», si té més de 40 paraules o si no comparteix cap paraula amb l'enunciat. Una pista rebutjada no es mostra ni descompta.

### El diagnòstic (`diagnose.py`)

Per a cada opció incorrecta numèrica es prova, en aquest ordre: és una dada de l'enunciat; és una operació entre dues dades; és el doble o la meitat de la correcta; se'n diferencia en 1; se'n diferencia en una dada; és la correcta per una potència de 10. Els missatges són preguntes i no contenen cap número. `tutor_build.py stats` dona la cobertura per nivell.

## API

Totes les rutes són GET i tornen JSON. Un error torna `{"error": "..."}` amb codi 400.

| Ruta | Què fa |
| --- | --- |
| `/api/start?name=&level=` | Crea o recupera l'alumne. Torna el perfil |
| `/api/next?student=` | El problema següent, sense l'etiqueta |
| `/api/hint?attempt=` | Un graó més. Amb `busy: true`, cal consultar `/api/status` |
| `/api/status?attempt=` | Estat de la pista del model |
| `/api/answer?attempt=&letter=` | Corregeix. Primer error: diagnòstic i segon intent |
| `/api/discard?attempt=&letter=` | Marca o desmarca una opció descartada |
| `/api/profile?student=` | Estat, habilitat i progrés per tema |
| `/api/matrix` | El marc actual de la matriu: 104 valors de 0 a 7 |
| `/api/health` | Llengua i temes disponibles |

## Mesures per al pitch

| Què | Ordre |
| --- | --- |
| Qualitat dels temes | `python3 tutor_build.py topics --hand data/hand_labels.csv` |
| Problemes per tema i nivell, cobertura del diagnòstic | `python3 tutor_build.py stats` |
| Convergència, zona de dificultat, falsos dominis, repàs | `python3 tutor_simulate.py` |
| Pistes del model: quantes passen i quant triguen | `python3 tutor_hints.py --report` |
| Latència per pas | Pestanya de xarxa del navegador, amb la placa |

Resultat del simulador amb el banc sintètic (150 problemes per alumne, llavor 42):

| Alumne simulat | A la zona 60–85 % | Error d'habilitat (Elo) | Temes dominats / realment dominats | Falsos dominis |
| --- | --- | --- | --- | --- |
| A nivell de curs | 65 % | 43 | 0 / 0 | 0 |
| Fort | 55 % | 91 | 9 / 10 | 0 |
| Fluix | 45 % | 80 | 0 / 0 | 0 |
| Desigual (meitat forts, meitat fluixos) | 43 % | 95 | 1 / 5 | 0 |
| Demana pistes quan li costa | — | 67 | 0 / 0 | 0 |
| Oblida un tema | 57 % | 90 | 7 / 9 | 0 |

Lectura honesta: el motor és conservador. En sis llavors diferents va declarar un sol domini fals entre 360 temes, però triga a reconèixer el domini real (l'alumne desigual només en veu reconeguts 13 de 30) i el tema oblidat torna a la pràctica entre 9 i 49 problemes després, segons quan toca el repàs. Si voleu dominis més ràpids per a la demo, baixeu `TUTOR_MASTERY_P` a 0,70 a `config.env` i torneu a mirar la columna de falsos dominis. Els alumnes simulats responen amb el mateix model de dificultat que fa servir el tutor: això valida el motor, no que el nivell i la franja de M3Kang prediguin la dificultat per a alumnes reals.

## Pistes del model: decidiu-ho amb dades

```bash
python3 tutor_hints.py --try 10                 # llegiu-les: són útils? són en català?
python3 tutor_hints.py --ids demo_ids.txt       # genereu les dels problemes de la demo
python3 tutor_hints.py --report
```

Si les pistes no són prou bones, `TUTOR_HINT_LANGUAGE=English` a `config.env`, o `tutor_server.py --no-model`: l'escala funciona igual amb cinc graons.

## `predict.py`: el biaix de lletra

Independent del tutor. Per activar-ho:

```bash
python3 calibrate_letters.py --limit 3 --show   # comproveu que el servidor torna logprobs per lletra
python3 calibrate_letters.py                    # uns 15 minuts; escriu copilot/letter_bias.json
```

I a `copilot/pipeline.py`, canvieu la línia d'importació:

```python
from .llm import URL
from .debias import answer as answer_letter
```

Sense `letter_bias.json`, `debias.answer` crida `answer_letter` de sempre, de manera que el canvi no fa res fins que calibreu. Mesureu-ho amb `python3 eval.py --limit 50 --name debias` abans de deixar-ho posat. Si `--show` no torna cap lletra, el servidor dona els `logprobs` en un altre format: l'únic lloc que els llegeix és `letter_logprobs()`.

## Coses que cal saber

- **`data/tutor.db` conté text de M3Kang.** No el pugeu. `.gitignore` ja exclou `*.db` i `data/`.
- **El tutor fa servir tots els problemes**, també els de validació, perquè no hi mesura l'encert del model. L'índex oficial de RAG (`data/index.db`) no es toca.
- **Nivell i curs.** La pàgina assumeix que el nivell 0 és 5è de primària i el 7, 2n de batxillerat (el README diu que el nivell 0 és «grade 5»). Comproveu-ho amb les dades i canvieu el desplegable de `tutor_web/index.html` si cal.
- **Franges de punts.** `band_of` parteix cada prova en terços segons el número de pregunta més alt que troba per a aquell nivell i any. Si M3Kang no conté totes les preguntes d'una prova, la franja pot quedar desplaçada.
- **Solucions.** M3Kang només porta la lletra correcta. El tutor no explica mai una solució pas a pas: ensenya la resposta i un problema anàleg.
- **Un sol alumne actiu a la matriu.** La matriu mostra l'últim alumne que ha fet alguna cosa. La web admet diversos alumnes alhora.
- **Llengua.** Els enunciats es mostren en `TUTOR_LANGUAGE` (`cat`). Si un problema no té text en aquesta llengua, no se serveix. Els vectors es calculen sempre sobre el text anglès.
