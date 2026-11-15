# Cangur Tutor

Un entrenador de problemes del Cangur, en català, per a alumnes de 5è de primària a 4t d'ESO. Funciona sencer a l'Arduino UNO Q, sense internet: l'alumne respon en una pàgina web servida per la placa, i la matriu de LEDs mostra el seu mapa de temes.

Els passos per posar-lo en marxa són a [`TRASPAS.md`](TRASPAS.md). Aquest document explica què fa, com està fet i què s'ha mesurat.

## Què fa

1. **Tria el problema.** Un motor Elo per tema calcula l'habilitat de l'alumne i serveix el problema que hauria d'encertar el 70 % de les vegades. Els temes fluixos surten més; un tema dominat torna al cap de 6, 12, 24 i 48 problemes, per repassar-lo.
2. **Ajuda sense dir la resposta.** Cada clic a «Dona'm una pista» puja un graó: què et demanen, el mètode del tema, un problema semblant (un que l'alumne ja va encertar, o un de més fàcil amb la seva resposta), descartar opcions, una frase del model i, només al final, la resposta.
3. **Diagnostica l'error.** Si l'alumne falla, l'opció que ha triat sovint delata l'error: ha copiat una dada, s'ha deixat un pas, ha comptat el doble. Rep una pregunta sobre això i un segon intent. Si torna a fallar, el problema següent és un de semblant i més fàcil.
4. **Ho ensenya a la matriu.** Una columna per tema, més alta com més a prop del domini. Un vist o una creu després de cada resposta. Un cangur quan no hi ha ningú.

## Com fa servir M3Kang

| Ús | Què |
| --- | --- |
| Banc de problemes | 1.152 problemes de nivell 0 a 5, en català |
| Mapa de semblances | Els 20 veïns de cada problema, amb embeddings del text anglès (pont multilingüe: es busca en anglès, es mostra en català) |
| Memòria de l'alumne sobre el mapa | La pista «un problema que ja has resolt» creua els veïns amb l'historial de cada alumne |
| Mapa de temes | 10 temes de l'equip a partir de k-means, corregits amb els veïns de cada problema |
| Mapa de dificultat | Nivell de la prova i terç on cau la pregunta (3, 4 o 5 punts), a partir de l'`id` |
| Distractors | Les opcions incorrectes com a catàleg d'errors típics |
| Dues lectures de cada problema | L'OCR de l'anglès i el del català es comparen per saber quines opcions es poden mostrar com a text |

## Decisions que venen de les dades

**La imatge mana.** Les opcions només són a la imatge, i l'OCR s'equivoca: en un 3 % dels problemes amb opcions numèriques, la lectura de l'anglès i la del català no coincideixen («#8», «1 17»). Per això cada problema es mostra d'una de dues maneres:

- **Com a text** (uns 350 problemes): no necessita figura i les cinc opcions són fiables. Si són nombres, les dues lectures han de coincidir. L'alumne pot obrir igualment el problema original.
- **Com a problema escanejat** (uns 800): l'alumne llegeix l'enunciat, la figura i les opcions a la imatge, i respon amb la lletra. El tutor no mostra mai la lectura de l'OCR d'aquests problemes.

**Problemes repetits.** Hi ha preguntes idèntiques a les proves de nivells diferents. Dos problemes amb similitud de 0,95 o més es tracten com el mateix: no surten mai com a pista l'un de l'altre, ni se serveixen tots dos al mateix alumne.

**Semblança.** Entre problemes del Cangur, bge-small dona similituds altes (el veí més proper té 0,83 de mitjana). Un «problema semblant» ha de tenir 0,75 o més. Mesurat sobre 911 problemes: el 80 % tenen un problema semblant més fàcil, i el 80 % d'aquests són del mateix tema.

**Temes.** K-means agrupa per vocabulari i deixa problemes en un grup que no és el seu (un problema de tanques dins «Velocitat i recorreguts»). Es miren els 10 veïns de cada problema: si 6 o més són d'un altre tema, el problema hi passa; si menys de 3 són del seu, no compta per al domini. Sobre 911 problemes, 58 canvien de tema.

**Temes per curs.** Un alumne només rep un tema si té prou problemes a prop del seu curs: a 5è de primària no hi ha «Angles» ni «Triangles i segments». Cap problema és més de dos cursos per sobre del de l'alumne.

**El model no és a la sessió.** App Lab executa l'app en un contenidor, i els servidors dels models només escolten al `127.0.0.1` de la placa: des de l'app no s'hi arriba. A més, el model escriu 5 tokens per segon. Les pistes del model s'escriuen abans (`tutor_hints.py`), passen un filtre en codi i es desen al banc. Durant la sessió tot és SQLite i Python.

## Què s'executa on

```text
Microcontrolador (STM32)        app/cangur-tutor/sketch/sketch.ino
                                dibuixa a la matriu 8x13 el marc que rep pel Bridge

Linux, dins d'App Lab           app/cangur-tutor/python/main.py
                                brick web_ui: la pàgina i l'API al port 7000
                                copilot/tutor/: motor, pistes, diagnòstic, matriu
                                python/data/tutor.db: el banc i els alumnes (SQLite)

Linux, fora d'App Lab           math-llm (8081) i math-embed (8082)
                                per a predict.py i per construir el banc; el tutor no els crida
```

`board/install_app.sh` copia dins de l'app tot el que necessita, perquè el contenidor només veu la carpeta de l'app.

## Fitxers

```text
copilot/tutor/
  settings.py     paràmetres; es poden canviar a config.env amb el prefix TUTOR_
  db.py           esquema de data/tutor.db
  engine.py       Elo amb atzar, selecció de tema, domini, repàs espaiat
  service.py      la classe Tutor: start, next, hint, answer, discard, profile, frame
  diagnose.py     regles sobre els distractors i missatges
  topics.py       temes i classificador de reserva
  llmhint.py      la crida al model i el filtre de les pistes
  matrix.py       marcs de 8x13
  textutil.py     números, preguntes, neteja del text
  content/        analogies dels 10 temes; temes i targetes de reserva
copilot/debias.py           correcció del biaix de lletra per a predict.py (opcional)
app/cangur-tutor/           l'app d'App Lab
tutor_web/                  la pàgina: index.html, style.css, app.js, fonts/
board/install_app.sh        instal·la l'app a la placa
tutor_build.py              construeix el banc
tutor_hints.py              escriu, filtra i revisa les pistes del model
tutor_demo.py               crea l'alumne de la demo
tutor_simulate.py           alumnes simulats: mesures del motor
tutor_server.py             la mateixa pàgina sense App Lab, port 8090
tutor_synthetic.py          problemes inventats per provar sense M3Kang
calibrate_letters.py        mesura el biaix de lletra del model
tests/                      53 tests i substituts dels servidors per al portàtil
```

## El motor

- Dificultat inicial d'un problema: `b = 1000 + 120·nivell + 80·(franja − 1)`.
- Probabilitat d'encert, amb un terra del 20 % perquè hi ha cinc opcions: `p = 0,2 + 0,8 / (1 + 10^((b − θ)/400))`.
- Puntuació d'un intent: 1 a la primera, menys 0,2 per pista (mínim 0,4); 0,2 al segon intent; 0 si no.
- Actualització: `θ ← θ + K·(puntuació − p)`, amb `K = 32 + 96/(1 + 0,2·n)`. El que s'aprèn en un tema mou també els temes amb pocs intents.
- Domini: 5 intents o més, 3 dels 4 últims nets (a la primera i amb una pista com a màxim) i un 70 % d'encert esperat en un problema de franja 2 del seu curs.
- Mai més de tres problemes seguits del mateix tema.

## L'escala de pistes

| Graó | Què veu l'alumne | D'on surt |
| --- | --- | --- |
| Què et demanen | La pregunta subratllada i les dades marcades amb fluorescent | Codi |
| Un mètode | La frase del tema i una analogia | `data/temes.json` i `content/analogies_ca.json` |
| Un problema semblant | Un que ja va encertar, o un de més fàcil amb la resposta | Veïns i historial |
| Descarta | Ratllar opcions que no poden ser | Res a calcular |
| Per on començar | Una frase del model | Desada al banc, si ha passat el filtre |
| La resposta | La lletra i un problema anàleg | Etiqueta de M3Kang |

Un graó que no té res a dir se salta i no descompta. Només els problemes mostrats com a text poden tenir pista del model: el model no veu la figura, i sense opcions fiables no es pot comprovar que la pista no digui la resposta. Ratllar una opció no rep resposta immediata, perquè dir «aquesta no la pots ratllar» revelaria la solució.

El filtre rebutja una pista si conté el valor o la lletra de l'opció correcta, si diu «la resposta és», si té més de 40 paraules o si no comparteix cap paraula amb l'enunciat.

## Què s'ha mesurat

Fet amb les dades reals (`train.jsonl`, `val.jsonl`, imatges i `temes.json` del 14/11):

| Què | Resultat |
| --- | --- |
| Problemes al quiz | 1.152 (352 com a text, 800 escanejats) |
| Opcions numèriques on les dues lectures de l'OCR no coincideixen | 12 de 436 problemes (3 %) |
| Distractors numèrics explicats per una regla | 674 de 2.381 (28 %) |
| Problemes amb un semblant més fàcil, amb el llindar 0,75 | 80 %, sobre 911 problemes amb vectors reals |
| Problemes que canvien de tema pels seus veïns | 58 de 911 |

Alumnes simulats sobre el banc real (150 problemes, 6 llavors, 10 temes per alumne):

| Alumne simulat | Temes dominats / realment dominats | Dominis falsos | Error d'habilitat (Elo) |
| --- | --- | --- | --- |
| Fort a tot | 54 / 60 | 0 | 69 |
| A nivell de curs | 6 / 0 | 6 | 63 |
| Fluix | 1 / 0 | 1 | 81 |
| Meitat de temes forts, meitat fluixos | 19 / 30 | 0 | 90 |
| Fort, i oblida un tema | 50 / 54 | 0 | 74 |

Lectura: el motor reconeix el domini d'un alumne fort i gairebé mai el regala a un de fluix. On s'equivoca és amb l'alumne que està just al llindar (encerta el 60 % i el domini en demana el 70 %): un de cada deu temes surt dominat, i el repàs el torna a la pràctica. Els alumnes simulats responen amb el mateix model de dificultat que fa servir el tutor: això valida el motor, no que el nivell de la prova predigui la dificultat per a alumnes reals.

Encara per mesurar, i només es pot fer amb els vostres servidors i la placa:

- Les xifres de veïns i de temes amb tots els vectors (`tutor_build.py stats`).
- Quantes pistes del model passen el filtre i quantes ajuden (`tutor_hints.py --report` i `--review 20`).
- La latència per pas i la memòria lliure, a la placa.
- 20 parelles «problema i el seu semblant més fàcil», jutjades a mà.

## Sobre «tot s'executa a la placa»

Durant la sessió, tot passa a la placa. El banc i les pistes es construeixen abans, amb els mateixos models. Si voleu que també això es faci a la placa, les mateixes ordres hi funcionen: `python3 tutor_build.py all` (uns 10 minuts) i `python3 tutor_hints.py` (unes dues hores, es pot aturar i reprendre). Digueu al pitch on ho heu fet.

## Paràmetres

A `config.env`, o com a variables d'entorn:

| Clau | Per defecte | Què és |
| --- | --- | --- |
| `TUTOR_LANGUAGE` | `cat` | Llengua dels enunciats |
| `TUTOR_MAX_LEVEL` | `5` | Nivell màxim del quiz |
| `TUTOR_MASTERY_P` | `0.70` | Encert esperat que demana el domini |
| `TUTOR_MIN_SIM` | `0.75` | Similitud mínima d'un problema semblant |
| `TUTOR_DUP_SIM` | `0.95` | A partir d'aquí, dos problemes són el mateix |
| `TUTOR_HINT_LANGUAGE` | `Catalan` | Llengua en què el model escriu les pistes |
| `TUTOR_LIVE_HINTS` | `0` | `1`: el model escriu la pista al moment si no n'hi ha cap de desada. Només on s'arriba al model: amb `tutor_server.py`, no amb App Lab |

## `predict.py`: el biaix de lletra

Independent del tutor. El model respon gairebé sempre la mateixa lletra (al portàtil no va predir mai la C).

```bash
python3 calibrate_letters.py --limit 3 --show   # el servidor torna logprobs per lletra?
python3 calibrate_letters.py                    # escriu copilot/letter_bias.json
```

Per activar-ho, a `copilot/pipeline.py` canvieu `from .llm import URL, answer_letter` per:

```python
from .llm import URL
from .debias import answer as answer_letter
```

Sense `letter_bias.json` no canvia res. Mesureu-ho amb `python3 eval.py --limit 50 --name debias` contra la línia base, i desfeu el canvi si no millora. No s'ha provat contra el servidor real: si `--show` no torna cap lletra, l'únic lloc que llegeix els `logprobs` és `letter_logprobs()`.

## Limitacions

- **No hi ha solucions explicades.** M3Kang només porta la lletra correcta, i el model no sap resoldre aquests problemes. El tutor acompanya; no explica la solució.
- **Els temes no són perfectes.** Fins i tot corregits, alguns problemes són en un tema discutible.
- **La dificultat és una suposició raonable**, no una mesura amb alumnes: nivell de la prova i posició de la pregunta.
- **Les analogies** de `content/analogies_ca.json` les ha escrit una IA. Reviseu-les.
- **Un sol mapa a la matriu:** el de l'últim alumne que ha fet alguna cosa. La web admet diversos alumnes alhora.
- **No s'ha provat en cap placa.** L'app s'ha escrit contra el codi font del brick `web_ui` i provat amb un substitut seu.

## Dades

`data/tutor.db` i la carpeta de l'app a la placa contenen text i imatges de M3Kang: no es pugen mai a GitHub. `.gitignore` ja exclou `data/` i `*.db`. Les tipografies de la pàgina (Shantell Sans i Atkinson Hyperlegible Next) tenen llicència SIL Open Font License i van dins del repo.
