# Traspàs de la branca `tutor`

Aquesta branca afegeix el **Cangur Tutor** (producte del track Teach) i una correcció opcional del biaix de lletra per a `predict.py`. No modifica cap fitxer del repo original: tot és nou. La guia tècnica completa és a [`docs/TUTOR.md`](TUTOR.md).

## Què cobreix del pla de l'equip (prompt de traspàs, secció 8)

| Tasca de la secció 8 | Estat | On és |
| --- | --- | --- |
| 1. App web + matriu LED | **Fet**, diferent del previst: la web la serveix `tutor_server.py` (llibreria estàndard, port 8090) i l'app d'App Lab només dibuixa la matriu | `tutor_server.py`, `tutor_web/`, `app/cangur-matrix/` |
| 2. Màquina d'estats del tutor i de l'entrenador | **Fet** | `copilot/tutor/engine.py`, `copilot/tutor/service.py` |
| 3. Esquema SQLite i precàlcul | **Fet** | `copilot/tutor/db.py`, `tutor_build.py` |
| 4. Clustering i temes | **Fet**: k-means per explorar + classificador amb validació | `tutor_build.py clusters / sample / topics` |
| 5. Biaix de lletra a `predict.py` | **Escrit, sense mesurar** | `copilot/debias.py`, `calibrate_letters.py` |
| 6. README final i pitch | Pendent | — |
| 7. Actualitzar `CLAUDE.md` | Pendent | — |

**No torneu a fer les tasques 1 a 5.** El que queda és executar-les amb dades reals i a la placa, i ajustar.

### Diferències amb el que deia el prompt

- **`copilot/tutor/` és un paquet, no `copilot/tutor.py`.** No creeu `copilot/tutor.py`: Python no pot tenir les dues coses alhora.
- **Escala d'ajudes de sis graons**, no quatre: entendre la pregunta, estratègia i analogia del tema, problema semblant (un que l'alumne ja ha encertat, o un de més fàcil amb la resposta), descartar opcions, pista del model, resposta.
- **Entrenador amb Elo per tema** en lloc de «puja o baixa un nivell»: descompta l'atzar del 20 %, descompta les pistes, declara temes dominats i els programa repassos espaiats.
- **Pistes del model**: no es poden precalcular totes a la placa (unes 7 h). Es generen només les de la demo (`tutor_hints.py --ids`) o al moment, i sempre passen un filtre en codi abans de mostrar-se.
- **La matriu** mostra una columna per tema (perfil de l'alumne), un vist, una creu o un interrogant. No mostra lletres ni el número de nivell.

## Qui fa què ara

### Qualsevol portàtil (Windows o Mac), sense dades ni placa

```powershell
# Windows (PowerShell), des de l'arrel del repo
$env:PYTHONUTF8='1'
python -m unittest discover -s tests
python tutor_synthetic.py
python tutor_build.py all --input data/synthetic.jsonl --db data/tutor_synth.db --hand data/synthetic_labels.csv --fake-embed
python tutor_server.py --db data/tutor_synth.db --no-model
```

```bash
# Mac o Linux: les mateixes ordres amb python3
```

Obriu <http://127.0.0.1:8090>. Han de passar 40 tests. El banc sintètic és inventat: serveix per provar el codi, mai per a xifres.

### Company A (portàtil Windows, té les dades)

Quan acabi `prepare_m3kang.py`:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python tutor_build.py all
.venv\Scripts\python tutor_build.py clusters --k 12
.venv\Scripts\python tutor_build.py sample --n 100
```

Amb els dos servidors de llama.cpp engegats al portàtil, és la manera més ràpida de veure si els temes tenen sentit. Repartiu `data/hand_labels.csv` entre tots, ompliu la columna `topic` i després:

```powershell
.venv\Scripts\python tutor_build.py topics --hand data/hand_labels.csv
.venv\Scripts\python tutor_build.py stats
.venv\Scripts\python tutor_simulate.py
```

Passeu a la placa `data/train.jsonl`, `data/val.jsonl`, `data/images/` i `data/hand_labels.csv` **en mà o per `scp`, mai per Git** (contenen text de M3Kang).

### Company B (Mac, té la placa)

Al Mac no cal instal·lar res per a SSH ni `scp`. Per al túnel USB de la demo, `adb`:

```bash
brew install android-platform-tools
```

**A la placa**, per SSH, quan els passos 0 a 8 del README estiguin fets i les dades copiades a `data/`:

```bash
cd ~/datathon-UPC-maths-qualcomm-arduino-unoq
git fetch origin && git checkout tutor && git pull
python3 -m unittest discover -s tests          # 40 tests, sense model ni dades
python3 tutor_build.py all                      # uns 8-10 min: vectors de 1.747 problemes
python3 tutor_server.py                         # deixeu-lo engegat
```

**Al Mac**, en una altra terminal:

```bash
adb forward tcp:8090 tcp:8090
open http://127.0.0.1:8090
```

Després, a la placa:

- `python3 tutor_hints.py --try 10`: llegiu les pistes i decidiu si el graó del model es queda.
- Copieu `app/cangur-matrix` a `/home/arduino/ArduinoApps/`, engegueu-la des d'App Lab i comproveu que el registre no diu `tutor unreachable`.
- Per engegar el tutor a l'arrencada: `docs/TUTOR.md`, secció «A la placa».

Les latències que valen per al pitch són les de la placa. Les del portàtil no.

### Qui porti `predict.py`

```bash
python3 calibrate_letters.py --limit 3 --show   # el servidor torna logprobs per lletra?
python3 calibrate_letters.py                    # escriu copilot/letter_bias.json
```

Per activar-ho, a `copilot/pipeline.py` substituïu `from .llm import URL, answer_letter` per:

```python
from .llm import URL
from .debias import answer as answer_letter
```

Mesureu-ho amb `eval.py --limit 50 --name debias` contra `baseline`. Si no millora, desfeu el canvi. El company A ha vist que el model respon `A` a tot al portàtil; `calibrate_letters.py` ho tindrà en compte.

## Coses a comprovar primer, per ordre de risc

1. `tutor_build.py all` amb les dades reals (no s'ha executat mai amb M3Kang).
2. Que l'app d'App Lab arriba a `127.0.0.1:8090` (no s'ha provat en cap placa).
3. La qualitat dels temes amb les etiquetes a mà.
4. La correspondència nivell ↔ curs del desplegable de la pàgina (ara: nivell 0 = 5è de primària).
