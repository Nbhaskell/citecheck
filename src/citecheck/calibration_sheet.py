"""The labelling sheet: one self-contained HTML file that is opened in a browser, filled in with radio buttons, and saved
as a labels file (see calibration.py and citation_calibration.py). Nothing is sent anywhere; progress is kept in the browser
while working.

The page knows nothing about what is being labelled. Its data is:
    title, intro        the heading and a short line under it
    rules               the how-to paragraphs, as HTML
    cards               one per item: `blocks` (label, text, optional css class), optional `details` (a collapsed list of
                        passages), and `groups` (the questions: dim, title, hint, options, and an optional hide_when
                        {dim, value} that hides a question once another is answered that way)
The downloaded file holds, per card, one label per visible question, an optional note and the card's stratum."""
import html
import json

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CiteCheck labelling sheet</title>
<style>
:root { --bg:#fbfaf8; --fg:#1d1d1b; --muted:#6b6a66; --card:#ffffff; --line:#dedbd4; --accent:#2f5d8a; --ok:#2e7d4f; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe8; --muted:#a09e98; --card:#1f1f1d; --line:#38372f; --accent:#7fb0e0; --ok:#6cc08b; } }
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
.passage { font-size:.92rem; margin:6px 0; white-space:pre-wrap; }
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
<h1>__TITLE__</h1>
<p class="muted">__INTRO__ &middot; <span id="count"></span></p>

<details class="card" open>
<summary>How to label (read once)</summary>
<ul class="rules" id="rules"></ul>
</details>

<div class="bar"><span id="progress"></span><button id="download">Download labels</button><button class="secondary" id="clear">Clear all answers</button></div>
<div id="cards"></div>
</main>

<script id="data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById('data').textContent);
const KEY = 'citecheck-labels-' + data.kind + '-' + data.run_id;
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { state = {}; }
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const SEP = '||';

function visible(group, entry) { return !(group.hide_when && entry[group.hide_when.dim] === group.hide_when.value); }
function needs(card, entry) { return card.groups.filter(g => visible(g, entry)).map(g => g.dim); }
function complete(card) { const entry = state[card.id] || {}; return needs(card, entry).every(d => entry[d]); }

function groupHtml(card, g, number) {
  const entry = state[card.id] || {};
  const radios = g.options.map(([v, text]) =>
    `<label class="opt"><input type="radio" name="${esc(card.id)}${SEP}${g.dim}" value="${v}" ${entry[g.dim] === v ? 'checked' : ''}> ${esc(text)}</label>`).join('');
  return `<div class="group ${visible(g, entry) ? '' : 'hidden'}"><strong>${number}. ${esc(g.title)}</strong><div class="hint">${esc(g.hint)}</div>${radios}</div>`;
}
function cardHtml(card, i) {
  const entry = state[card.id] || {};
  const blocks = card.blocks.map(b => `<div class="label">${esc(b.label)}</div><div class="box ${b.css || ''}">${esc(b.text)}</div>`).join('');
  const details = card.details && card.details.items.length ? `<details ${card.details.open ? 'open' : ''}><summary>${esc(card.details.summary)} (${card.details.items.length})</summary>${
    card.details.items.map(p => `<div class="passage"><span class="muted">${esc(p.head)}</span><br>${esc(p.text)}</div>`).join('')}</details>` : '';
  return `<section class="card ${complete(card) ? 'done' : ''}" data-id="${esc(card.id)}">
    <div class="muted">Item ${i + 1} of ${data.cards.length}</div>
    ${blocks}${details}
    ${card.groups.map((g, k) => groupHtml(card, g, k + 1)).join('')}
    <div class="group"><strong>Note (optional)</strong><textarea data-note="${esc(card.id)}" placeholder="Anything you were unsure about">${esc(entry.note || '')}</textarea></div>
  </section>`;
}
function render() {
  document.getElementById('cards').innerHTML = data.cards.map(cardHtml).join('');
  updateProgress();
}
function updateProgress() {
  const done = data.cards.filter(complete).length;
  document.getElementById('progress').textContent = done + ' of ' + data.cards.length + ' complete';
  document.getElementById('count').textContent = data.cards.length + ' to label';
}
document.getElementById('rules').innerHTML = data.rules.map(r => '<li>' + r + '</li>').join('');
document.addEventListener('change', e => {
  if (e.target.type !== 'radio') return;
  const [id, dim] = e.target.name.split(SEP);
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
    const labels = {};
    for (const g of card.groups) labels[g.dim] = need.includes(g.dim) ? (entry[g.dim] || null) : null;
    items[card.id] = { ...labels, note: entry.note || '', stratum: card.stratum };
  }
  const out = { labels_version: data.labels_version, kind: data.kind, run_id: data.run_id, golden_version: data.golden_version,
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
    intro = f"Run {data['run_id']} · question set {data['golden_version']}"
    return (PAGE.replace("__TITLE__", html.escape(data["title"])).replace("__INTRO__", html.escape(intro))
            .replace("__DATA__", embedded))
