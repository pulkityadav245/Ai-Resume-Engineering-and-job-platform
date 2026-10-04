'use strict';
/* JobHunt UI -- vanilla JS, no build step, served by FastAPI itself (monolith).
   To add a feature: write a view function that returns an array of DOM nodes, then add one
   object to FEATURES below. State lives in `state`; call set({...}) to update and re-render. */

const $ = (s) => document.querySelector(s);
const h = (tag, props, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  kids.flat(Infinity).filter((c) => c !== false && c != null)
    .forEach((c) => el.append(c.nodeType ? c : document.createTextNode(String(c))));
  return el; // text goes through text nodes only: job data from outside is never parsed as HTML
};
const chip = (t, c = '') => h('span', { class: 'chip ' + c }, t);
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : null);
const JSON_H = { 'Content-Type': 'application/json' };

async function api(path, opts = {}) {
  const r = await fetch('/api/v1' + path, opts);
  let data = null;
  try { data = await r.json(); } catch (e) { /* non-JSON error body */ }
  if (!r.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : r.statusText);
  }
  return data;
}

const state = { tab: 'resume', file: null, parse: null, resume: null, roles: null, level: null,
  jobs: null, picked: new Set(), loc: '', minScore: 25, busy: '', error: '' };
const set = (p) => { Object.assign(state, p); render(); };
async function run(label, fn) {
  set({ busy: label, error: '' });
  try { await fn(); } catch (e) { state.error = e.message; }
  set({ busy: '' });
}

/* ---------- actions (each maps to one backend endpoint) ---------- */
const analyze = () => run('Parsing resume and scoring roles...', async () => {
  const fd = new FormData(); fd.append('file', state.file);
  const d = await api('/analyze', { method: 'POST', body: fd });
  Object.assign(state, { parse: d.parse, resume: d.parse.resume, roles: d.roles.roles, level: d.roles.level,
    picked: new Set(d.roles.roles.slice(0, 3).map((r) => r.role)), jobs: null, tab: 'resume' });
});
const rescoreRoles = () => run('Re-scoring roles...', async () => {
  const d = await api('/roles/infer', { method: 'POST', headers: JSON_H, body: JSON.stringify(state.resume) });
  Object.assign(state, { roles: d.roles, level: d.level, picked: new Set(d.roles.slice(0, 3).map((r) => r.role)) });
});
const searchJobs = () => run('Searching jobs...', async () => {
  const roles = [...state.picked];
  const body = { resume: state.resume, roles: roles.length ? roles : null, location: state.loc.trim() || null,
    min_score: Number(state.minScore) || 0, max_results: 30 };
  state.jobs = await api('/jobs/search', { method: 'POST', headers: JSON_H, body: JSON.stringify(body) });
  state.tab = 'jobs';
});

/* ---------- views ---------- */
function pipeline() {
  const s = [['Upload', state.file || state.resume], ['Parse + ground', state.resume], ['Target roles', state.roles],
    ['Job search', state.jobs], ['Rank + skill gap', state.jobs]];
  return h('div', { class: 'steps' }, s.map(([n, d]) => h('span', { class: d ? 'done' : '' }, (d ? '\u2713 ' : '') + n)));
}

function viewResume() {
  const btn = h('button', { class: 'btn', disabled: !state.file || !!state.busy, onclick: analyze }, 'Analyze resume');
  const upload = h('section', { class: 'card' }, h('h2', null, 'Upload resume'),
    h('p', { class: 'muted' }, 'PDF or DOCX with selectable text, max 5 MB. Nothing is stored.'),
    h('div', { class: 'row' },
      h('input', { type: 'file', accept: '.pdf,.docx', onchange: (e) => { state.file = e.target.files[0] || null; btn.disabled = !state.file; } }),
      btn));
  if (!state.resume) return [upload];

  const r = state.resume, p = r.personal || {}, ps = state.parse;
  const addIn = h('input', { placeholder: 'Add skill (use canonical name, e.g. Node.js)' });
  const addSkill = () => { const v = addIn.value.trim(); if (v && !r.skills.some((s) => s.name === v)) { r.skills.push({ name: v, source: 'skills_section' }); render(); } };
  const skillChip = (s) => {
    const c = chip(s.name + (s.source === 'inferred' ? ' (inferred)' : ''), s.source === 'inferred' ? 'warn' : '');
    c.append(h('button', { title: 'remove', onclick: () => { r.skills = r.skills.filter((x) => x !== s); render(); } }, '\u00d7'));
    return c;
  };
  return [upload,
    ps.warnings.length > 0 && h('div', { class: 'banner warn' }, ps.warnings.join(' ')),
    ps.grounding_issues.length > 0 && h('div', { class: 'banner warn' }, 'Grounding removed/flagged: ' + ps.grounding_issues.map((i) => i.value + ' (' + i.reason + ')').join('; ')),
    h('section', { class: 'card' }, h('h2', null, 'Candidate'),
      h('div', null, p.name || 'Name not found', ' \u00b7 ', p.email || 'no email', ' \u00b7 ', p.phone || 'no phone'),
      h('div', null, (p.links || []).map((l) => safeUrl(l) && h('div', null, h('a', { href: l, target: '_blank', rel: 'noopener noreferrer' }, l)))),
      h('p', { class: 'muted' }, 'Parser: ' + ps.parser + (ps.parser === 'rule_based' ? ' (no LLM used)' : ' (LLM output, grounded)'))),
    h('section', { class: 'card' }, h('h2', null, 'Education'),
      r.education.length ? r.education.map((e) => h('div', null, [e.degree, e.institute, e.years, e.score].filter(Boolean).join(' \u00b7 '))) : h('p', { class: 'muted' }, 'None detected')),
    h('section', { class: 'card' }, h('h2', null, 'Skills (' + r.skills.length + ')'),
      h('p', { class: 'muted' }, 'Review step: remove wrong skills or add missing ones, then re-score. The resume is the single source of truth.'),
      h('div', null, r.skills.map(skillChip)),
      h('div', { class: 'row' }, addIn, h('button', { class: 'btn ghost', onclick: addSkill }, 'Add'),
        h('button', { class: 'btn', disabled: !!state.busy, onclick: rescoreRoles }, 'Re-score roles'))),
    h('section', { class: 'card' }, h('h2', null, 'Projects'),
      r.projects.length ? r.projects.map((pr) => h('div', null, h('h3', null, pr.title),
        h('ul', null, pr.bullets.map((b) => h('li', null, b.text))), pr.skills_used.map((s) => chip(s)))) : h('p', { class: 'muted' }, 'None detected')),
    ['coursework', 'certifications', 'achievements'].map((k) => r[k].length > 0 && h('section', { class: 'card' },
      h('h2', null, k[0].toUpperCase() + k.slice(1)), h('ul', null, r[k].map((x) => h('li', null, x)))))];
}

function viewRoles() {
  return [h('section', { class: 'card' }, h('h2', null, 'Target roles'),
    h('p', { class: 'muted' }, 'Level: ' + state.level + '. Score = 45% core skills + 35% project evidence + 10% optional + 10% education (heuristic, rule-based, no LLM). Tick the roles to search.')),
  state.roles.length === 0 && h('div', { class: 'banner warn' }, 'No roles matched. Add skills on the Resume tab and re-score.'),
  state.roles.map((r) => h('section', { class: 'card' },
    h('div', { class: 'job' },
      h('label', null, h('input', { type: 'checkbox', checked: state.picked.has(r.role), onchange: (e) => { e.target.checked ? state.picked.add(r.role) : state.picked.delete(r.role); } }), ' ', h('b', null, r.role)),
      h('span', { class: 'score ' + (r.score >= 70 ? 'hi' : r.score >= 50 ? 'mid' : 'lo') }, r.score.toFixed(1))),
    h('div', { class: 'bar' }, h('div', { class: 'fill', style: 'width:' + Math.min(r.score, 100) + '%' })),
    h('div', null, r.matched_core.map((s) => chip(s, 'good')), r.missing_core.map((s) => chip('missing: ' + s, 'bad'))),
    h('p', { class: 'muted' }, r.explanation),
    Object.keys(r.evidence).length > 0 && h('p', { class: 'muted' }, 'Evidence: ' + Object.entries(r.evidence).map(([s, t]) => s + ' in ' + t.join(', ')).join(' | ')))),
  h('button', { class: 'btn', disabled: !!state.busy, onclick: () => { state.tab = 'jobs'; searchJobs(); } }, 'Find jobs for ticked roles')];
}

function viewJobs() {
  const j = state.jobs;
  const ctl = h('section', { class: 'card' }, h('h2', null, 'Job search'),
    h('p', { class: 'muted' }, 'Uses the roles ticked on the Target roles tab (top roles if none).'),
    h('div', { class: 'row' },
      h('input', { placeholder: 'Location (e.g. Bengaluru, Remote)', value: state.loc, oninput: (e) => { state.loc = e.target.value; } }),
      h('label', null, 'Min score ', h('input', { type: 'number', class: 'num', min: 0, max: 100, value: state.minScore, oninput: (e) => { state.minScore = e.target.value; } })),
      h('button', { class: 'btn', disabled: !!state.busy, onclick: searchJobs }, 'Search jobs')));
  if (!j) return [ctl];
  const money = (n) => new Intl.NumberFormat('en-IN').format(Math.round(n));
  return [ctl,
    j.warnings.map((w) => h('div', { class: 'banner warn' }, w)),
    h('p', { class: 'muted' }, 'Provider: ' + j.provider + ' \u00b7 level: ' + j.level + ' \u00b7 fetched ' + j.total_fetched + ', unique ' + j.after_dedup + ', shown ' + j.jobs.length
      + ' \u00b7 roles: ' + j.roles_used.map((r) => r.role + ' (' + r.fetched + ')').join(', ')),
    j.jobs.length === 0 && h('div', { class: 'banner info' }, 'No jobs above the minimum score. Lower it or change roles/location.'),
    j.jobs.map((m) => { const x = m.job, url = safeUrl(x.url), d = x.posted_at ? new Date(x.posted_at) : null;
      return h('section', { class: 'card' },
        h('div', { class: 'job' },
          h('div', null, h('b', null, x.title), h('div', { class: 'muted' }, [x.company, x.location, d && !isNaN(d) ? d.toLocaleDateString() : null, x.contract_type].filter(Boolean).join(' \u00b7 ')),
            x.salary_min && h('div', { class: 'muted' }, '\u20b9' + money(x.salary_min) + (x.salary_max ? ' - \u20b9' + money(x.salary_max) : '') + (x.salary_predicted ? ' (estimated by provider)' : ''))),
          h('span', { class: 'score ' + (m.score >= 70 ? 'hi' : m.score >= 50 ? 'mid' : 'lo') }, m.score.toFixed(1))),
        h('div', null, m.matched_skills.map((s) => chip(s, 'good')), m.missing_required.map((s) => chip('need: ' + s, 'bad')), m.missing_preferred.map((s) => chip('nice: ' + s, 'warn'))),
        m.flags.length > 0 && h('div', { class: 'muted' }, m.flags.join(' \u00b7 ')),
        h('div', { class: 'muted' }, 'via ' + m.via_roles.join(', '), url && [' \u00b7 ', h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, 'View job')]));
    })];
}

const viewDebug = () => [h('section', { class: 'card' }, h('h2', null, 'Raw API data'),
  h('p', { class: 'muted' }, 'Exactly what the backend returned. Useful to explain the pipeline.'),
  h('pre', { class: 'json' }, JSON.stringify({ parse: state.parse, roles: state.roles, jobs: state.jobs }, null, 2)))];

/* ---------- feature registry: add new features here ---------- */
const FEATURES = [
  { id: 'resume', title: '1 \u00b7 Resume', render: viewResume },
  { id: 'roles', title: '2 \u00b7 Target roles', render: viewRoles, needs: 'roles' },
  { id: 'jobs', title: '3 \u00b7 Job search', render: viewJobs, needs: 'resume' },
  { id: 'debug', title: 'Raw JSON', render: viewDebug, needs: 'resume' },
  { id: 'ats', title: 'ATS check', soon: true },
  { id: 'tailor', title: 'Tailor resume', soon: true },
  { id: 'tracker', title: 'Tracker', soon: true },
];

function render() {
  $('#nav').replaceChildren(...FEATURES.map((f) => h('button', {
    class: 'nav' + (state.tab === f.id ? ' active' : ''), disabled: !!f.soon || (f.needs && !state[f.needs]),
    onclick: () => set({ tab: f.id }) }, f.title, f.soon && h('span', { class: 'tag' }, 'soon'))));
  const f = FEATURES.find((x) => x.id === state.tab);
  $('#main').replaceChildren(...[pipeline(), state.busy && h('div', { class: 'banner info' }, state.busy),
    state.error && h('div', { class: 'banner err' }, state.error), f.render()].flat(Infinity).filter(Boolean));
}

fetch('/health').then((r) => r.json()).then(() => { $('#status').textContent = 'API online'; })
  .catch(() => { $('#status').textContent = 'API offline'; });
render();
