# Cangur Tutor: an offline Kangaroo math coach on the Arduino UNO Q

Write-up for Arduino Project Hub (step 15.2). It's here because we could not create the project on Project Hub before the deadline.

## 1. Introduction

Math skills in Catalonia are falling, and students need guidance, not answers. Cangur Tutor is a practice coach for Kangaroo problems (grade 5 to grade 10), built on the M3Kang dataset. It runs entirely on an Arduino UNO Q with no internet, so no student data leaves the device.

The student answers A–E on a web page served by the board. The 8×13 LED matrix shows a column per topic, and a tick or a cross after each answer. When the student is stuck, each click on the hint button gives the next rung of a hint ladder, and the ladder never gives the answer away directly. For the Reason track, `predict.py` answers any Kangaroo-style problem with one letter, within 60 s.

## 2. Components and apps

- Arduino UNO Q 4 GB
- Arduino App Lab (app `cangur-tutor`: Python + sketch, connected through the Bridge)
- llama.cpp `llama-server` (pinned commit, see `config.env`)
- Qwen3.5 0.8B Q8_0 (language model, port 8081)
- bge-small-en-v1.5 Q8_0 (embeddings, port 8082)
- M3Kang dataset (Qualcomm)

## 3. Architecture

- **Linux side (QRB2210, 4 Arm cores):**
  - The two model servers.
  - `predict.py`.
  - The App Lab container. It serves the page on port 7000 from SQLite (`data/tutor.db`).
- **Microcontroller side:** `app/cangur-tutor/sketch/sketch.ino` draws the LED matrix, with orders sent over the Bridge.
- **Why we precompute:** the App Lab container can't reach the model servers. So the problem bank, the embeddings, the nearest neighbours and the LLM hints are all precomputed (`tutor_build.py`, `tutor_hints.py`). A live session uses only SQLite and Python.
- **How we use M3Kang:**
  - As the problem bank: 1,152 problems of level ≤ 5, in Catalan.
  - As a difficulty map: Elo per topic.
  - As a multilingual bridge: we embed the English text of the same problem id, and the student sees the Catalan one.
  - As a source of "a similar, easier problem": embedding neighbours, found for 54% of the problems, 92% of them of the same topic.
  - As a source of error diagnosis: rules on the numeric distractors explain 28% of the wrong options.

## 4. Step by step

See the [README](../README.md) and [`INSTALL-PLACA.md`](../INSTALL-PLACA.md):

1. Set up the board: llama.cpp, models and services (steps 0–8 of the README).
2. Copy the data package and the code, then unzip them.
3. Run the tests: `python3 -m unittest discover -s tests` → `Ran 53 tests`, `OK`.
4. Build the bank: `python3 tutor_build.py all` → `1152 problems a student can answer`.
5. Create the demo student and start the app: `python3 tutor_demo.py`, `bash board/install_app.sh`, `arduino-app-cli app start user:cangur-tutor`.
6. Open the page: `http://<board-ip>:7000`, or over USB with `adb forward tcp:7000 tcp:7000`.
7. Reason track: `python3 predict.py --input problems.jsonl --output predictions.csv`.

M3Kang data is not redistributed: get it from the [dataset card](https://huggingface.co/datasets/qualcomm/M3Kang).

## 5. Results (measured on the board)

| Experiment | Data | n | Accuracy | Mean time | Worst |
| --- | --- | --- | --- | --- | --- |
| One letter, no reasoning | M3Kang val | 50 | 22% | 2.3 s | 3.6 s |
| + RAG, 1 example | M3Kang val | 50 | 16% | 4.6 s | 7.4 s |
| One letter | practice set (eng) | 50 | 24% | 7.2 s | 10.1 s |
| One letter | practice set (eng), the same 20 problems as below | 20 | 40% | — | — |
| **Reason first (250 tokens / 20 s)** | practice set (eng), the same 20 problems | 20 | **45%** | 41.3 s | 46.6 s |

- Random guessing gives 20%.
- With n = 20, the gain from reasoning (one more problem) is not significant.
- The model leans towards D (13 of 20 answers).
- No problem went over the 60 s limit.
- With the app running, the board had 2.7 GB of memory available (`free -m`).

Error analysis by topic, language and level: not done yet.

## 6. What we learned, and what's next

- A 0.8B model gets worse with retrieved examples: RAG lowered its accuracy.
- Reasoning helps a little, but on the board it costs about 40 s per problem. A 35 s budget came too close to the limit (54 s), so we lowered it to 20 s.
- Fine-tuning wasn't feasible in the time of the datathon.
- Next: an error analysis by topic, language and level; correcting the bias towards D (`calibrate_letters.py`); and LLM hints reviewed by teachers.

## Credits

- **M3Kang:** Torres-Camps et al., 2026, [arXiv:2601.16218](https://arxiv.org/abs/2601.16218). Research-use licence, so the data is not included.
- **llama.cpp:** MIT licence.
- **Qwen3.5:** the Qwen team.
- **bge-small-en-v1.5:** BAAI.
