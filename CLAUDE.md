# Entrenador del Cangur en català — Datathon FME 2026 (repte Qualcomm)

Respon sempre en català.

## Què fem
Un entrenador de problemes del Cangur (M3Kang) **en català**, per a alumnes de **5è de primària a 4t d'ESO** (nivells 0–5 de M3Kang),
que funciona **sense internet** a l'Arduino UNO Q (4 GB). Track: **Teach** (guiar sense donar la resposta).
L'alumne respon A–E en una **pàgina web servida per la placa** (app d'App Lab, port 7000); la **matriu LED 8x13** mostra el seu mapa de temes, un vist o una creu.

El producte ja està implementat: es diu **Cangur Tutor**. Abans de proposar res, llegeix `docs/TUTOR.md` (com funciona) i `docs/TRASPAS.md` (com es posa en marxa).

Descartat (no ho proposis): la versió per a infants cecs amb veu (reconeixement de veu, text a veu, «versions per escoltar»).

## Regles del repte (no les trenquis)
- Tot ha de funcionar **offline a la placa** durant la demo. Res de crides a APIs externes al codi del producte.
- **Cap mòdul extern**: només la placa, la matriu LED i una pàgina web servida per la placa. No proposis botons, sensors ni Modulino.
- `predict.py` es puntua igualment (track Reason): una lletra A–E, ≤60 s/problema, temperatura 0, seed 42, sense xarxa. **No el trenquis**: el codi del tutor és a part, a `copilot/tutor/`.
- El codi que corre a la placa és **només llibreria estàndard de Python** (no hi ha `pip`). Dins d'App Lab hi ha, a més, `numpy` i els bricks.
- **Mai pujar dades de M3Kang** (llicència de recerca): `data/*` (jsonl, imatges, `temes.json`, `clusters.json`), `*.db`. Ja són al `.gitignore`. Fes `git status` abans de cada push.
- **Mai pujar claus d'API**: van a `.env` (al `.gitignore`).
- Res a la matriu no pot parpellejar més de 3 cops per segon.

## Límits de la placa
Qwen3.5 0.8B Q8_0 (port 8081) i bge-small-en-v1.5 (port 8082, **només entén anglès**) via llama.cpp `llama-server`.
Llegeix ~11 tok/s i escriu ~5–6 tok/s: **generar text triga desenes de segons**.
**L'app d'App Lab corre en un contenidor i no arriba als servidors dels models** (escolten només al `127.0.0.1` de la placa). Per tant:
- Durant la sessió el tutor no crida cap model: només SQLite, Python, la web i la matriu.
- Tot el que escriu l'LLM (una pista d'una frase per problema) es **precalcula** amb `tutor_hints.py`, es filtra en codi i es desa a `data/tutor.db`.
- El contenidor només veu la carpeta de l'app: `board/install_app.sh` hi copia el codi, el banc i les imatges.

## El producte (ja fet)
1. **Banc**: tots els problemes de nivell ≤ 5 → **1.152** en català. Uns 350 es mostren **com a text** (sense figura i amb les cinc opcions fiables: les lectures OCR de l'anglès i del català han de coincidir); la resta, **com a problema escanejat** (`data/images/<id>_cat.png`) amb botons A–E.
2. **Entrenador adaptatiu**: Elo per tema amb un 20 % d'atzar, problema objectiu al 70 % d'encert, domini i repàs espaiat (6, 12, 24, 48 problemes), descompte per pistes, problema de reparació després de dos errors. `copilot/tutor/engine.py`.
3. **Escala d'ajudes** (cada clic, un graó; mai la resposta directa): què et demanen → mètode del tema (`methods_ca` de `data/temes.json` + analogia) → problema semblant (un que l'alumne ja va encertar, o un de més fàcil amb la resposta) → descartar opcions → frase de l'LLM precalculada i filtrada → resposta.
4. **Diagnòstic de l'error** a partir de l'opció triada (regles sobre els distractors numèrics). `copilot/tutor/diagnose.py`.
5. **Temes**: els 10 de `data/temes.json`, corregits amb els 10 veïns de cada problema (k-means agrupa per vocabulari).
6. **Pont multilingüe**: embeddings i veïns amb el text anglès del mateix `id`; l'alumne veu el català.
7. **Matriu LED**: una columna per tema; vist o creu després de cada resposta; un cangur quan no hi ha ningú. `copilot/tutor/matrix.py`.

## Mesures (portàtil ≠ placa: les latències oficials es mesuren a la placa)
Ja mesurat al portàtil, 50 problemes de val: línia base **22,0%** (sempre D 22,0%; biaix: mai prediu C), latència 2,3 s;
amb `--rag 1` **16,0%** (català 10,7%) i 4,6 s. OCR: opcions llegides 63% (76% dels `text_only`).
Les xifres del tutor són a `docs/TUTOR.md`, secció «Què s'ha mesurat». No inventis xifres: si una cosa no s'ha mesurat, o només al portàtil, digues-ho.

Pendent: `tutor_build.py stats` amb tots els vectors · `tutor_hints.py --report` i `--review 20` · latència per pas i `free -m` a la placa ·
20 parelles «problema → semblant més fàcil» a mà · `predict.py` vs 22% (biaix de lletra: `calibrate_letters.py`) · anàlisi d'errors per tema, idioma i nivell · README final i article d'Arduino Project Hub.

## Estructura
- `copilot/` codi oficial (no trencar `predict.py`); `copilot/tutor/` el tutor; `copilot/debias.py` biaix de lletra (opcional)
- `app/cangur-tutor/` app d'App Lab: `python/main.py` (web_ui + Bridge) i `sketch/sketch.ino` (matriu LED)
- `tutor_web/` la pàgina (HTML, CSS, JS i tipografies; sense CDN)
- `tutor_build.py`, `tutor_hints.py`, `tutor_demo.py`, `tutor_simulate.py`, `tutor_server.py`: eines del tutor. Sortides a `data/` (no es pugen)
- `tests/` 53 tests: `python3 -m unittest discover -s tests`
- `.skills/` (o `.claude/skills/`) skills de l'organització: **fes-les servir** (unoq-board, m3kang-copilot, unoq-hardware-ui, publish-project)
- Fora del repo: `../models/` (fitxers GGUF), `../tools/` (llama.cpp per a Windows, release `b12311`)

## Entorn
- Portàtils amb **Windows** i un **Mac**. Digues sempre si una comanda va **al portàtil** o **a la placa**.
- Python al portàtil Windows: `.venv\Scripts\python`, amb `$env:PYTHONUTF8='1'`.
- Al portàtil corren els mateixos models als ports 8081/8082, perquè el codi funcioni igual que a la placa.
- Repo de l'equip (fork): https://github.com/Jowi611/datathon-UPC-maths-qualcomm-arduino-unoq

## Equip (4 persones)
P1 placa · P2 dades i precàlcul · P3 tutor i `predict.py` · P4 app web, matriu LED i pitch.
