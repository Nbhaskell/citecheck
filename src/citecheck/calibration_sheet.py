"""The labelling sheet: one self-contained HTML file that is opened in a browser, filled in with radio buttons, and saved
as a labels file (see calibration.py). Nothing is sent anywhere; progress is kept in the browser while working."""
import json

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CiteCheck labelling sheet</title>
<style>
:root { --bg:#fbfaf8; --fg:#1d1d1b; --muted:#6b6a66; --card:#ffffff; --line:#dedbd4; --accent:#2f5d8a; --ok:#2e7d4f; --warn:#a15c00; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe8; --muted:#a09e98; --card:#1f1f1d; --line:#38372f; --accent:#7fb0e0; --ok:#6cc08b; --warn:#e0a24a; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; }
main { max-width:860px; margin:0 auto; padding:16px; }
h1 { font-size:1.4rem; margin:.2em 0; }
.muted { color:var(--muted); }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:16px 0; }
.card.done { border-left:5px solid var(--ok); }
.q { font-weight:600; font-size:1.05rem; }
.box { border-left:3px solid var(--line); padding:4px 12px; margin:8px 0; white-space:pre-wrap; }
.box.answer { border-color:var(--accent); }
.box.reference { border-color:var(--ok); }
.label { font-size:.8rem; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin-top:12px; }
details summary { cursor:pointer; color:var(--accent); }
.passage { font-size:.92rem; margin:6px 0; }
.group { margin:14px 0 4px; padding-top:8px; border-top:1px dashed var(--line); }
.group strong { display:block; }
.hint { font-size:.9rem; color:var(--muted); margin:2px 0 6px; }
label.opt { display:block; padding:6px 8px; border-radius:6px; cursor:pointer; }
label.opt:hover { background:var(--bg); }
textarea { width:100%; min-height:48px; background:var(--bg); color:var(--fg); border:1px solid var(--line); border-radius:6px; padding:6px; font:inherit; }
.bar { position:sticky; top:0; background:var(--bg); padding:8px 0; border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:center; flex-wrap:wrap; z-index:2; }
button { background:var(--accent); color:#fff; border:0; border-radius:6px; padding:8px 14px; font:inherit; cursor:pointer; }
button.secondary { background:transparent; color:var(--accent); border:1px solid var(--accent); }
.rules li { margin:4px 0; }
.hidden { display:none; }
</style>
</head>
<body>
<main>
<h1>Label the answers</h1>
<p class="muted">Run __RUN_ID__ &middot; question set __GOLDEN__ &middot; <span id="count"></span></p>

<details class="card" open>
<summary>How to label (read once)</summary>
<ul class="rules">
<li>You are judging the <b>answer</b> the system gave. The system's own verdicts are not shown, on purpose.</li>
<li><b>Did it decline?</b> Choose <i>abstained</i> if the answer says it does not know, or that the documents do not mention or cover the question, and gives no real answer. "No, the context does not mention X" counts as abstained. Choose <i>answered</i> if it gives a real answer, even with a caveat. Choose <i>partly answered</i> if it answers some parts of a multi-part question and says it does not know the rest.</li>
<li><b>Is it backed by the passages?</b> Use only the passages shown (the text the system was given), not what you know. A statement is <i>supported</i> if a passage says it, or it follows directly (for example adding two prices). Choose <i>supported</i> if everything is backed, <i>partly supported</i> if the main points are backed but something smaller is not, <i>unsupported</i> if the main points are not. Saying "the documents do not mention X" is fine when true. Do not judge whether the answer is right or complete here.</li>
<li><b>Is it correct?</b> Compare with the reference answer. <i>Correct</i>: it agrees on everything the question asks (extra harmless detail is fine). <i>Partly correct</i>: it gets some right but misses a part or hedges where the reference is definite. <i>Incorrect</i>: it contradicts the reference, answers differently, or declines.</li>
<li>Your answers are saved in this browser as you go. When all are done, press <b>Download labels</b> and send or place the file where asked. A note is optional but helpful when you were unsure.</li>
</ul>
</details>

<div class="bar"><span id="progress"></span><button id="download">Download labels</button><button class="secondary" id="clear">Clear all answers</button></div>
<div id="cards"></div>
</main>

<script id="data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById('data').textContent);
const LABELS = {
  abstention: [['abstained','Abstained (declined to answer)'],['answered','Answered'],['partly_answered','Partly answered']],
  faithfulness: [['supported','Supported'],['partly_supported','Partly supported'],['unsupported','Unsupported']],
  correctness: [['correct','Correct'],['partly_correct','Partly correct'],['incorrect','Incorrect']]
};
const KEY = 'citecheck-labels-' + data.run_id;
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { state = {}; }
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function needs(card, entry) {
  const need = ['abstention'];
  if (entry.abstention !== 'abstained') need.push('faithfulness');
  if (card.answerable) need.push('correctness');
  return need;
}
function complete(card) {
  const entry = state[card.id] || {};
  return needs(card, entry).every(d => entry[d]);
}
function group(card, dim, title, hint) {
  const entry = state[card.id] || {};
  const radios = LABELS[dim].map(([v, text]) =>
    `<label class="opt"><input type="radio" name="${card.id}-${dim}" value="${v}" ${entry[dim] === v ? 'checked' : ''}> ${text}</label>`).join('');
  return `<div class="group" data-dim="${dim}"><strong>${title}</strong><div class="hint">${hint}</div>${radios}</div>`;
}
function render() {
  const root = document.getElementById('cards');
  root.innerHTML = data.cards.map((card, i) => {
    const entry = state[card.id] || {};
    const history = card.history.length ? `<div class="label">Earlier in the conversation</div><div class="box">${card.history.map(t => esc(t.role + ': ' + t.content)).join('\n')}</div>` : '';
    const passages = card.passages.map(p => `<div class="passage"><span class="muted">[${p.rank}] ${esc(p.doc)}</span><br>${esc(p.text)}</div>`).join('') || '<div class="muted">(none)</div>';
    return `<section class="card ${complete(card) ? 'done' : ''}" id="card-${card.id}" data-id="${card.id}">
      <div class="muted">Item ${i + 1} of ${data.cards.length}</div>
      ${history}
      <div class="label">Question</div><div class="q">${esc(card.question)}</div>
      <div class="label">The system's answer</div><div class="box answer">${esc(card.answer)}</div>
      ${card.answerable ? `<div class="label">Reference answer (known correct)</div><div class="box reference">${esc(card.reference_answer)}</div>` : ''}
      <details><summary>Passages the system was given (${card.passages.length})</summary>${passages}</details>
      ${group(card, 'abstention', '1. Did the answer decline to answer?', 'Says it does not know, or that the documents do not cover it.')}
      <div class="${entry.abstention === 'abstained' ? 'hidden' : ''}">${group(card, 'faithfulness', '2. Is every statement backed by the passages?', 'Use only the passages above.')}</div>
      ${card.answerable ? group(card, 'correctness', '3. Does it match the reference answer?', 'Same facts for what the question asks.') : ''}
      <div class="group"><strong>Note (optional)</strong><textarea data-note="${card.id}" placeholder="Anything you were unsure about">${esc(entry.note || '')}</textarea></div>
    </section>`;
  }).join('');
  updateProgress();
}
function updateProgress() {
  const done = data.cards.filter(complete).length;
  document.getElementById('progress').textContent = done + ' of ' + data.cards.length + ' complete';
  document.getElementById('count').textContent = data.cards.length + ' answers to label';
}
document.addEventListener('change', e => {
  if (e.target.type !== 'radio') return;
  const [id, dim] = [e.target.name.replace(/-(abstention|faithfulness|correctness)$/, ''), e.target.name.split('-').pop()];
  state[id] = state[id] || {};
  state[id][dim] = e.target.value;
  save();
  const top = window.scrollY;
  render();
  window.scrollTo(0, top);
});
document.addEventListener('input', e => {
  if (!e.target.dataset.note) return;
  const id = e.target.dataset.note;
  state[id] = state[id] || {};
  state[id].note = e.target.value;
  save();
});
document.getElementById('download').addEventListener('click', () => {
  const items = {};
  for (const card of data.cards) {
    const entry = state[card.id] || {};
    const need = needs(card, entry);
    items[card.id] = {
      abstention: entry.abstention || null,
      faithfulness: need.includes('faithfulness') ? (entry.faithfulness || null) : null,
      correctness: need.includes('correctness') ? (entry.correctness || null) : null,
      note: entry.note || '', stratum: card.stratum };
  }
  const out = { labels_version: data.labels_version, run_id: data.run_id, golden_version: data.golden_version,
                golden_hash: data.golden_hash, population: data.population, items };
  const blob = new Blob([JSON.stringify(out, null, 1) + '\n'], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'labels.json';
  a.click();
});
document.getElementById('clear').addEventListener('click', () => {
  if (confirm('Clear every answer on this sheet?')) { state = {}; save(); render(); }
});
render();
</script>
</body>
</html>
"""


def render(data: dict) -> str:
    """The sheet as HTML. The data is embedded as JSON with '<' escaped, so no text can close the script tag."""
    embedded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return (PAGE.replace("__RUN_ID__", data["run_id"]).replace("__GOLDEN__", data["golden_version"])
            .replace("__DATA__", embedded))
