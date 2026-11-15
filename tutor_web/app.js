// Cangur Tutor: the page. It only draws what the board says: every decision
// (which problem, which hint, right or wrong, the LED frame) is taken in Python.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const COURSES = ["5è de primària", "6è de primària", "1r d'ESO", "2n d'ESO", "3r d'ESO", "4t d'ESO"];
const STATES = { new: "per començar", learning: "aprenent", consolidating: "consolidant", mastered: "dominat" };
const KANGAROO = ["........#.#..", "........###..", "........####.", ".......###...",
                  "......####.#.", "#....#####...", ".########....", "......#####.."];
const TICK = '<svg viewBox="0 0 54 54" aria-hidden="true"><path pathLength="100" d="M9 29 L22 43 L46 12"/></svg>';
const CROSS = '<svg viewBox="0 0 54 54" aria-hidden="true"><path pathLength="100" d="M12 12 L42 42"/><path pathLength="100" d="M42 12 L12 42"/></svg>';

let student = null;      // id
let profile = null;      // the last profile the board sent
let base = null;         // the profile when today's session started
let step = null;         // the problem on the page
let closed = false;      // the problem is finished
let polling = null;
let flashTimer = null;

// Every route is /api/<action>/<arg>/<arg>: the same in the App Lab app and in tutor_server.py
async function call(action, ...args) {
  const path = ["/api", action, ...args.map((a) => encodeURIComponent(String(a)))].join("/");
  let data;
  try { data = await (await fetch(path)).json(); }
  catch { throw new Error("No puc parlar amb la placa. Comprova que l'app està engegada i torna-ho a provar."); }
  if (data && data.error) throw new Error(data.error);
  return data;
}

// --- The LED matrix, on screen -------------------------------------------------

function buildLeds(el) {
  el.innerHTML = "<i></i>".repeat(104);
}
function paintLeds(el, frame) {
  [...el.children].forEach((led, i) => { led.dataset.v = frame[i] || 0; });
}
function artFrame(art, level) {
  return art.flatMap((row) => [...row.padEnd(13, ".")].map((c) => (c === "#" ? level : 0)));
}
function flashLeds(frame) {
  clearTimeout(flashTimer);
  paintLeds($("leds"), frame);
  flashTimer = setTimeout(() => { flashTimer = null; if (profile) paintLeds($("leds"), profile.matrix); }, 1500);
}
function lightColumn(index, on) {
  const offset = Math.floor((13 - profile.topics.length) / 2) + index;
  [...$("leds").children].forEach((led, i) => led.classList.toggle("lit-topic", on && i % 13 === offset));
}

// --- The side panel --------------------------------------------------------------

function showProfile(next) {
  profile = next;
  if (!flashTimer) paintLeds($("leds"), profile.matrix);
  const done = profile.done - base.done, first = profile.correct_first - base.first;
  $("today").textContent = done === 0 ? "Avui encara no has fet cap problema."
    : `Avui: ${done} ${done === 1 ? "problema" : "problemes"}, ${first} a la primera.`;
  $("topics").innerHTML = profile.topics.map((t) => {
    const state = t.state === "mastered" && t.review_in != null ? `dominat, repàs d'aquí a ${t.review_in}` : STATES[t.state];
    const now = step && step.topic.key === t.topic ? " now" : "";
    return `<li class="${t.state}${now}"><span class="name">${esc(t.name)}</span><span class="state">${state}</span></li>`;
  }).join("");
  [...$("topics").children].forEach((row, i) => {
    row.onmouseenter = () => lightColumn(i, true);
    row.onmouseleave = () => lightColumn(i, false);
  });
}

// --- The problem ------------------------------------------------------------------

// Underline the question and highlight the numbers, as a student would with pen and marker
function markedStatement(text, question, data) {
  const start = question ? text.indexOf(question) : -1;
  const mark = (part) => (data ? esc(part).replace(/(?<![\w.,/])[-−]?\d+(?:[.,]\d+)?/g, "<mark>$&</mark>") : esc(part));
  if (start < 0) return mark(text);
  return mark(text.slice(0, start)) + "<u>" + mark(question) + "</u>" + mark(text.slice(start + question.length));
}

function problemQuote(problem) {
  if (problem.mode === "image") {
    return `<div class="other"><img src="${esc(problem.image)}" alt="${esc(problem.text)}"></div>`;
  }
  const choices = Object.entries(problem.options).map(([k, v]) => `${k}) ${esc(v)}`).join(" &nbsp; ");
  return `<div class="other"><p>${esc(problem.text)}</p><p class="choices">${choices}</p></div>`;
}

function showStep(data) {
  step = data; closed = false;
  clearInterval(polling);
  const problem = data.problem, textMode = problem.mode === "text";
  $("topicName").textContent = data.topic.name;
  $("topicTag").textContent = data.is_review ? "repàs" : data.is_repair ? "un de semblant, més fàcil" : "";

  $("statement").hidden = !textMode;
  $("scan").hidden = textMode;
  $("original").hidden = !textMode || !problem.image;
  $("original").open = false;
  if (textMode) {
    $("statement").textContent = problem.text;
    if (problem.image) $("originalImage").src = problem.image;
  } else {
    $("scan").src = problem.image;
    $("scan").alt = problem.text;
  }

  const values = problem.options;
  const long = textMode && Object.values(values).some((v) => String(v).length > 9);
  $("options").className = "options" + (textMode ? (long ? " long" : "") : " letters");
  $("page").classList.toggle("scanned", !textMode);
  $("options").innerHTML = [..."ABCDE"].map((letter) => `
    <div class="option" data-letter="${letter}">
      <button class="pick" aria-label="Respon ${letter}${values[letter] ? ": " + esc(values[letter]) : ""}">
        <span class="letter">${letter}</span>${textMode ? `<span class="value">${esc(values[letter] ?? "")}</span>` : ""}
      </button>
      <button class="strike" aria-label="Ratlla l'opció ${letter}" title="Ratlla-la si segur que no pot ser">✕</button>
    </div>`).join("");
  for (const row of $("options").children) {
    row.querySelector(".pick").onclick = () => answer(row.dataset.letter);
    row.querySelector(".strike").onclick = () => strike(row.dataset.letter);
  }
  markStruck(data.discarded || []);
  if (data.first_answer) markWrong(data.first_answer);

  $("notes").innerHTML = "";
  $("verdict").hidden = true;
  $("nextButton").hidden = true;
  $("hintButton").hidden = false;
  $("hintButton").disabled = false;
  $("hintButton").textContent = "Dona'm una pista";
  if (profile) showProfile(profile);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

const option = (letter) => $("options").querySelector(`[data-letter="${letter}"]`);
function markStruck(letters) {
  for (const row of $("options").children) row.classList.toggle("struck", letters.includes(row.dataset.letter));
}
function lock(row) { for (const button of row.querySelectorAll("button")) button.disabled = true; }
function markWrong(letter) { option(letter).classList.add("wrong"); lock(option(letter)); }

function verdict(kind, title, body) {
  const box = $("verdict");
  box.hidden = false;
  box.className = "verdict " + kind;
  box.innerHTML = kind === "plain" ? esc(title)
    : `${kind === "good" ? TICK : CROSS}<div><strong>${esc(title)}</strong>${body ? `<p>${body}</p>` : ""}</div>`;
}

async function next() {
  try { showStep(await call("next", student)); }
  catch (error) { verdict("plain", error.message); $("hintButton").hidden = true; $("nextButton").hidden = true; }
}

async function strike(letter) {
  if (closed) return;
  try { markStruck((await call("discard", step.attempt_id, letter)).discarded); }
  catch (error) { verdict("plain", error.message); }
}

async function answer(letter) {
  if (closed || option(letter).classList.contains("wrong")) return;
  try {
    const result = await call("answer", step.attempt_id, letter);
    if (result.retry) {
      markWrong(letter);
      flashLeds(result.flash);
      verdict("bad", "Aquesta no és", `${esc(result.diagnosis.message)} Et queda un intent.`);
    } else finish(result, letter);
  } catch (error) { verdict("plain", error.message); }
}

function finish(result, letter) {
  closed = true;
  clearInterval(polling);
  if (letter && !result.correct) option(letter).classList.add("wrong");
  option(result.label).classList.add("right");
  option(result.label).classList.remove("struck");
  for (const row of $("options").children) lock(row);

  const notes = [], topic = result.topic, name = esc(step.topic.name);
  const solution = `La resposta és la ${result.label}${result.value ? ": " + esc(result.value) : ""}.`;
  if (!result.correct_first) notes.push(solution);
  if (topic.state === "mastered" && topic.state_before !== "mastered") notes.push(`Has dominat «${name}». Tornarà més endavant, per repassar-lo.`);
  if (topic.state !== "mastered" && topic.state_before === "mastered") notes.push(`«${name}» torna a la pràctica: l'has de refrescar.`);
  if (result.discarded_correct) notes.push("Havies ratllat l'opció correcta. Quan ratllis, digues-te per què no pot ser.");
  if (!result.correct && !step.is_repair) notes.push("Ara te'n poso un de semblant, una mica més fàcil.");
  if (result.correct_first) verdict("good", "Correcte", notes.join(" "));
  else if (result.correct) verdict("good", "Ara sí", notes.join(" "));
  else verdict("bad", "No era aquesta", notes.join(" "));

  flashLeds(result.flash);
  showProfile(result.profile);
  $("hintButton").hidden = true;
  $("nextButton").hidden = false;
  $("nextButton").focus();
}

// --- Hints -------------------------------------------------------------------------

function answerText(h) { return `<strong>${esc(h.label)}${h.value ? ": " + esc(h.value) : ""}</strong>`; }

function noteHtml(h) {
  if (h.kind === "understand") {
    if (step.problem.mode === "text") {
      $("statement").innerHTML = markedStatement(step.problem.text, h.question, h.data.length);
      return "<h3>Què et demanen</h3>" + (h.data.length
        ? "<p>He subratllat la pregunta i he marcat les dades amb fluorescent.</p><p class=\"ask\">Quines dades necessites, i quines no?</p>"
        : "<p>He subratllat la pregunta.</p><p class=\"ask\">Digues-la amb les teves paraules abans de continuar.</p>");
    }
    return `<h3>Què et demanen</h3><p>${esc(h.question)}</p>` +
      (h.data.length ? `<p>${h.data.map((d) => `<span class="chip">${esc(d)}</span>`).join("")}</p><p class="ask">Aquestes són les dades de l'enunciat. Quines necessites, i quines no?</p>` : "");
  }
  if (h.kind === "strategy") {
    return `<h3>Un mètode</h3><p>${esc(h.title)}</p>` + (h.body ? `<p>${esc(h.body)}</p>` : "") +
      (h.analogy ? `<p class="ask">${esc(h.analogy)}</p>` : "");
  }
  if (h.kind === "solved_before") {
    return `<h3>Un problema que ja has resolt</h3><p>Aquest el vas encertar a la primera, amb la ${answerText(h)}.</p>${problemQuote(h.problem)}` +
      "<p class=\"ask\">En què s'assembla al d'ara? Et serveix la mateixa idea?</p>";
  }
  if (h.kind === "easier_example") {
    return `<h3>Un de semblant, més fàcil</h3>${problemQuote(h.problem)}<p>La resposta d'aquest és la ${answerText(h)}.</p>` +
      "<p class=\"ask\">Com s'hi arriba? Prova el mateix camí amb el teu problema.</p>";
  }
  if (h.kind === "discard") {
    $("options").classList.add("nudge");
    return "<h3>Descarta</h3><p>Toca la ✕ d'una opció que segur que no pot ser, i digues-te per què. Després tria entre les que queden.</p>";
  }
  if (h.kind === "model") {
    return h.text ? `<h3>Per on començar</h3><p>${esc(h.text)}</p>`
      : "<h3>Per on començar</h3><p class=\"ask\">Per a aquest problema no tinc cap pista prou segura. Demana'n una altra.</p>";
  }
  if (h.kind === "answer") {
    return `<h3>La resposta</h3><p>És la ${answerText(h)}.</p>` +
      (h.example ? `<p>Per entendre-ho, mira aquest, que és semblant i més fàcil. La seva resposta és la ${answerText(h.example)}.</p>${problemQuote(h.example.problem)}` : "");
  }
  return "";
}

function addNote(html) {
  const note = document.createElement("li");
  note.innerHTML = html;
  $("notes").append(note);
  note.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return note;
}

async function hint() {
  if (closed || $("hintButton").hidden || $("hintButton").disabled) return;
  $("hintButton").disabled = true;
  try {
    const h = await call("hint", step.attempt_id);
    if (h.busy) {
      const note = addNote('<h3>Per on començar</h3><p class="ask writing">Estic escrivint la pista</p>');
      polling = setInterval(async () => {
        const s = await call("status", step.attempt_id).catch(() => ({ busy: true }));
        if (s.busy) return;
        clearInterval(polling);
        note.innerHTML = noteHtml(s);
        $("hintButton").disabled = false;
      }, 1000);
    } else {
      addNote(noteHtml(h));
      if (h.kind === "answer") return finish(h.result, null);
      $("hintButton").disabled = false;
    }
    $("hintButton").textContent = h.last ? "Ensenya'm la resposta" : "Una altra pista";
  } catch (error) { verdict("plain", error.message); $("hintButton").disabled = false; }
}

// --- Starting and ending -------------------------------------------------------------

function show(screen) {
  for (const id of ["welcome", "practice", "summary"]) $(id).hidden = id !== screen;
  $("endButton").hidden = screen !== "practice";
  document.querySelector(".keys").hidden = screen !== "practice";
}

async function start() {
  const name = $("name").value.trim();
  if (!name) { $("welcomeError").textContent = "Escriu el teu nom per començar."; $("name").focus(); return; }
  try {
    const first = await call("start", name, document.querySelector('input[name="level"]:checked').value);
    student = first.student_id;
    base = { done: first.done, first: first.correct_first, topics: first.topics };
    $("who").textContent = `${first.name}, ${COURSES[first.level] || ""}`;
    $("who").hidden = false;
    profile = first;
    show("practice");
    showProfile(first);
    next();
  } catch (error) { $("welcomeError").textContent = error.message; }
}

function end() {
  const done = profile.done - base.done, first = profile.correct_first - base.first;
  $("summaryTitle").textContent = `Fins aquí, ${profile.name}`;
  $("summaryLead").textContent = done === 0 ? "Avui encara no has acabat cap problema."
    : `Avui has fet ${done} ${done === 1 ? "problema" : "problemes"} i n'has encertat ${first} a la primera.`;
  // Only the topics practised today, and only the changes worth saying: at most six lines
  const before = Object.fromEntries(base.topics.map((t) => [t.topic, t]));
  const practised = profile.topics.map((t) => ({ ...t, was: before[t.topic] || t }))
    .filter((t) => t.attempts > t.was.attempts)
    .sort((a, b) => (b.progress - b.was.progress) - (a.progress - a.was.progress));
  const mastered = practised.filter((t) => t.state === "mastered" && t.was.state !== "mastered");
  const up = practised.filter((t) => !mastered.includes(t) && t.progress - t.was.progress >= 0.05).slice(0, 3);
  const down = practised.filter((t) => t.was.progress - t.progress >= 0.05).slice(-2);
  const lines = [
    ...mastered.map((t) => `<b>Has dominat</b> ${esc(t.name)}.`),
    ...up.map((t) => `<b>Has avançat</b> en ${esc(t.name)}.`),
    ...down.map((t) => `<b>T'ha costat</b> ${esc(t.name)}. El proper dia en faràs més.`),
  ];
  $("recap").innerHTML = lines.slice(0, 6).map((line) => `<li>${line}</li>`).join("");
  paintLeds($("summaryLeds"), profile.matrix);
  show("summary");
}

for (const id of ["welcomeLeds", "leds", "summaryLeds"]) buildLeds($(id));
paintLeds($("welcomeLeds"), artFrame(KANGAROO, 6));
show("welcome");

$("go").onclick = start;
$("name").onkeydown = (e) => { if (e.key === "Enter") start(); };
$("hintButton").onclick = hint;
$("nextButton").onclick = next;
$("endButton").onclick = end;
$("resumeButton").onclick = () => show("practice");
$("leaveButton").onclick = () => location.reload();
$("scan").onclick = () => { $("zoomImage").src = $("scan").src; $("zoom").hidden = false; };
$("zoom").onclick = () => { $("zoom").hidden = true; };
document.addEventListener("keydown", (e) => {
  if ($("practice").hidden || e.target.tagName === "INPUT" || e.ctrlKey || e.metaKey || e.altKey) return;
  const key = e.key.toUpperCase();
  if (key === "ESCAPE") $("zoom").hidden = true;
  else if (key.length === 1 && "ABCDE".includes(key)) answer(key);
  else if (key === "P") hint();
  else if (key === "ENTER" && closed) { e.preventDefault(); next(); }
});
$("name").focus();
