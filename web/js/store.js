// Global app state + actions. Components subscribe with useStore(); any set() re-renders.
// Saved views/positions live in this browser (localStorage), seeded from the engine's defaults.
import { useState, useEffect } from './lib.js';
import { api, setProgressHandler } from './api.js';

const clone = (x) => JSON.parse(JSON.stringify(x));
const PREFS_KEY = 'portfi.prefs.v2';
const DOCS_KEY = 'portfi.docs.v2';

function readLS(k, d) { try { return JSON.parse(localStorage.getItem(k) || 'null') ?? d; } catch { return d; } }
function writeLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } }

const prefs = readLS(PREFS_KEY, {});
export const S = {
  market: null, views: [], positions: [],
  viewId: prefs.viewId || null, positionId: prefs.positionId || null,
  view: null, position: null, viewDirty: false, positionDirty: false,
  asof: null,
  horizon: prefs.horizon || 1.0, units: prefs.units || 'pct', basis: prefs.basis || 'parametric', pcaWindow: prefs.pcaWindow || 5,
  theme: prefs.theme || 'auto', targetPct: prefs.targetPct ?? 5,
  tIndex: null, activeNode: null, activeBeNode: null, builderTab: 'nodes', curveMode: 'nominal', playing: false,
  attrMode: prefs.attrMode || 'market', waterfallMode: prefs.waterfallMode || 'factor', heatBase: prefs.heatBase || 'today',
  coverMove: 25, focusStep: null, editScope: prefs.editScope || 'path', showGuide: prefs.showGuide ?? true,
  result: null, loading: false, fullStale: false, error: null, boot: 'Starting…',
  tab: 'workspace',
  compare: { mode: 'views', a: null, b: null, ra: null, rb: null, loading: false },
  undo: [], notice: null,
};

const listeners = new Set();
export function set(patch) {
  Object.assign(S, typeof patch === 'function' ? patch(S) : patch);
  listeners.forEach((f) => f());
}
export function useStore() {
  const [, force] = useState(0);
  useEffect(() => {
    const f = () => force((x) => x + 1);
    listeners.add(f);
    return () => listeners.delete(f);
  }, []);
  return S;
}
function savePrefs() {
  const { horizon, units, basis, pcaWindow, theme, attrMode, waterfallMode, heatBase, viewId, positionId, targetPct, showGuide, editScope } = S;
  writeLS(PREFS_KEY, { horizon, units, basis, pcaWindow, theme, attrMode, waterfallMode, heatBase, viewId, positionId, targetPct, showGuide, editScope });
}
function saveDocs() { writeLS(DOCS_KEY, { views: S.views, positions: S.positions }); }
export function setPref(patch, reanalyze = true) {
  set(patch);
  savePrefs();
  if (patch.theme !== undefined) applyTheme();
  if (reanalyze) analyze();
}
export function applyTheme() {
  const r = document.documentElement;
  if (S.theme === 'auto') r.removeAttribute('data-theme'); else r.setAttribute('data-theme', S.theme);
}
export function focusStep(k) {
  set({ focusStep: k });
  const el = document.getElementById('step-' + k);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  setTimeout(() => { if (S.focusStep === k) set({ focusStep: null }); }, 1800);
}

// ------------------------------------------------------------------ analysis scheduling
let inflight = false;
let pending = null;
let fullTimer = null;
let seq = 0;

export function buildRequest(view = S.view, position = S.position, fast = false) {
  return {
    asof: S.asof, horizon: S.horizon, basis: S.basis, pca_window: S.pcaWindow, target_pct: S.targetPct,
    view, position, fast, cover_move_bp: S.coverMove, heat_base: S.heatBase,
  };
}

/** Request an analysis. fast=true during drags (skips MC/heatmap/timing); a full run follows. */
export function analyze({ fast = false } = {}) {
  if (!S.view || !S.position) return;
  pending = { fast };
  if (fast) {
    clearTimeout(fullTimer);
    fullTimer = setTimeout(() => analyze({ fast: false }), 400);
  }
  pump();
}

async function pump() {
  if (inflight || !pending) return;
  const { fast } = pending;
  pending = null;
  inflight = true;
  const my = ++seq;
  set({ loading: true });
  try {
    const r = await api.analyze(buildRequest(S.view, S.position, fast));
    if (my !== seq) return;
    const prev = S.result;
    if (fast && prev) {
      r.heatmap = prev.heatmap; r.timing = prev.timing;
      if (prev.risk?.mc) r.risk.mc = prev.risk.mc;
    }
    let tIndex = S.tIndex;
    if (tIndex == null || !prev || prev.t.length !== r.t.length) tIndex = r.t.length - 1;
    set({ result: r, error: null, tIndex, fullStale: fast });
  } catch (e) {
    set({ error: String(e.message || e) });
  } finally {
    inflight = false;
    set({ loading: false });
    pump();
  }
}

// ------------------------------------------------------------------ init
export async function init() {
  applyTheme();
  setProgressHandler((msg) => set({ boot: msg }));
  try {
    const market = await api.market(null);
    let docs = readLS(DOCS_KEY, null);
    if (!docs || !docs.views?.length || !docs.positions?.length) {
      docs = clone(market.defaults);
    }
    const views = docs.views, positions = docs.positions;
    const view = views.find((v) => v.id === S.viewId) || views.find((v) => v.id === 'v-hike') || views[0];
    const position = positions.find((p) => p.id === S.positionId) || positions[0];
    set({ market, views, positions, asof: market.asof, view: clone(view), viewId: view.id,
          position: clone(position), positionId: position.id,
          compare: { ...S.compare, a: views[0]?.id, b: views[2]?.id || views[1]?.id } });
    saveDocs();
    analyze();
  } catch (e) {
    set({ error: 'Failed to load: ' + e.message });
  }
}

export async function setAsof(asof) {
  try {
    const market = await api.market(asof);
    set({ market, asof: market.asof, tIndex: null, activeNode: null });
    analyze();
  } catch (e) { set({ error: e.message }); }
}

// ------------------------------------------------------------------ view editing
function pushUndo() {
  S.undo.push(clone(S.view));
  if (S.undo.length > 60) S.undo.shift();
}
export function undo() {
  const v = S.undo.pop();
  if (v) { set({ view: v, viewDirty: true }); analyze(); }
}
export function updateView(fn, { fast = false, record = true } = {}) {
  if (record) pushUndo();
  const v = clone(S.view);
  const out = fn(v) || v;
  set({ view: out, viewDirty: true });
  analyze({ fast });
}

/** Nodes as displayed (compiled by the server for policy-built views). */
export function displayNodes() {
  if (S.view?.builder?.type === 'policy' && S.result?.view?.nodes) return S.result.view.nodes;
  return S.view?.nodes || [];
}

/** Turn a builder-generated view into plain nodes so it can be edited by hand. */
export function detachBuilder(v) {
  const b = v.builder?.type;
  if (b === 'policy' && S.result?.view) {
    v.nodes = clone(S.result.view.nodes);
    v.anchor = 'forwards';
    v.time_interp = S.result.view.time_interp || 'linear';
    v.builder = { type: 'nodes', from: 'policy', params: v.builder.params };
    set({ notice: 'Policy builder detached — its curve path is now editable nodes.' });
  } else if (b && b !== 'nodes') {
    v.builder = { type: 'nodes', from: b, params: v.builder.params };
  }
  return v;
}

function interpRow(rows, T, t) {
  let i = 0;
  while (i < T.length - 2 && T[i + 1] < t) i++;
  const w = T.length > 1 ? Math.min(1, Math.max(0, (t - T[i]) / (T[i + 1] - T[i]))) : 0;
  const a = rows[i], b = rows[Math.min(i + 1, T.length - 1)];
  return a.map((x, k) => x * (1 - w) + b[k] * w);
}

/** Today / forward / yours (%, key tenors) at time t for the nominal or breakeven layer. `pt` = pass-through (bp). */
export function curvesAt(t, layer = 'nominal') {
  const r = S.result;
  if (!r) return null;
  const K = layer === 'be' ? r.inflation?.keys : r.keys;
  if (!K) return null;
  const nodes = layer === 'be' ? r.inflation?.nodes || [] : r.nodes || [];
  const n = nodes.find((x) => Math.abs(x.t - t) < 1e-6);
  return {
    today: K.today,
    fwd: n ? n.fwd : interpRow(K.fwd, r.t, t),
    user: n ? n.user : interpRow(K.user, r.t, t),
    pt: layer === 'be' ? K.today.map(() => 0) : n?.pt || (K.pt ? interpRow(K.pt, r.t, t) : K.today.map(() => 0)),
  };
}

// ---- nominal nodes
/** Apply a change `delta` (bp) at tenor j of node i. Scope 'path': earlier dates move ∝ time, later dates fully,
 *  so the path stays smooth; scope 'node': only this date. */
function spread(nodes, i, j, delta) {
  const ti = nodes[i].t;
  nodes.forEach((n, q) => {
    if (q === i) n.dev[j] += delta;
    else if (S.editScope === 'path') n.dev[j] += n.t < ti ? delta * n.t / ti : delta;
  });
}
export function setNodeLevel(i, j, levelPct, opts) {
  updateView((v) => {
    detachBuilder(v);
    const n = v.nodes[i];
    const c = curvesAt(n.t);
    const a = v.anchor === 'today' ? c.today : c.fwd;
    spread(v.nodes, i, j, (levelPct - a[j]) * 100 - c.pt[j] - n.dev[j]);
  }, opts);
}
export function setNodeDev(i, j, devBp, basis, opts) {
  updateView((v) => {
    detachBuilder(v);
    const n = v.nodes[i];
    const c = curvesAt(n.t);
    const a = v.anchor === 'today' ? c.today : c.fwd;
    const ref = basis === 'today' ? c.today : c.fwd;
    spread(v.nodes, i, j, (ref[j] + devBp / 100 - a[j]) * 100 - c.pt[j] - n.dev[j]);
  }, opts);
}
/** Index of a node at (≈) t, creating one from the current path if needed. */
export function ensureNode(t, opts = {}) {
  const nodes = displayNodes();
  let i = nodes.findIndex((n) => Math.abs(n.t - t) < 4 / 365);
  if (i >= 0 && S.view.builder?.type !== 'policy') return i;
  updateView((v) => {
    detachBuilder(v);
    i = v.nodes.findIndex((n) => Math.abs(n.t - t) < 4 / 365);
    if (i >= 0) return;
    const c = curvesAt(t);
    const a = v.anchor === 'today' ? c.today : c.fwd;
    const dev = c.user.map((x, j) => (x - a[j]) * 100 - c.pt[j]);
    v.nodes = [...(v.nodes || []), { t, dev }].sort((x, y) => x.t - y.t);
    i = v.nodes.findIndex((n) => Math.abs(n.t - t) < 1e-9);
  }, opts);
  return i;
}
export function addNode(t) { const i = ensureNode(t); set({ activeNode: i }); }
export function removeNode(i) {
  updateView((v) => { detachBuilder(v); v.nodes.splice(i, 1); });
  set({ activeNode: null });
}
export function moveNode(i, t) {
  updateView((v) => { detachBuilder(v); v.nodes[i].t = t; v.nodes.sort((a, b) => a.t - b.t); });
}
export function shiftFactor(i, k, dBeta, allNodes = false) {
  const B = S.result.factor.B;
  updateView((v) => {
    detachBuilder(v);
    const targets = allNodes ? v.nodes.map((_, q) => q) : [i];
    const tref = v.nodes[i].t;
    for (const q of targets) {
      const scale = allNodes ? Math.min(1, v.nodes[q].t / tref) : 1;
      v.nodes[q].dev = v.nodes[q].dev.map((d, j) => d + dBeta * B[j][k] * scale);
    }
  });
}
export function setAnchor(anchor) {
  updateView((v) => {
    detachBuilder(v);
    if (v.anchor === anchor) return;
    for (const n of v.nodes) {
      const c = curvesAt(n.t);
      n.dev = n.dev.map((d, j) => (anchor === 'today' ? d + (c.fwd[j] - c.today[j]) * 100 : d - (c.fwd[j] - c.today[j]) * 100));
    }
    v.anchor = anchor;
  });
}

// ---- inflation (breakeven) layer
export function inflSpec(v = S.view) { return v.inflation || { mode: 'follow' }; }
export function updateInfl(fn, opts) {
  updateView((v) => { v.inflation = { passthrough: 1, ...inflSpec(v) }; fn(v.inflation, v); }, opts);
}
/** Switch the inflation view to editable breakeven nodes, preserving the current breakeven path. */
function toBeNodes(spec) {
  const r = S.result;
  if (spec.mode === 'nodes') return;
  const rep = r?.inflation;
  const mode = rep?.mode;
  if (mode === 'expectations' && rep?.nodes) {
    spec.nodes = clone(rep.nodes); spec.anchor = 'forwards'; spec.time_interp = 'linear';
    spec.cpi_pct = rep.horizon_user_yoy != null ? +rep.horizon_user_yoy.toFixed(4) : null;
  } else {
    spec.nodes = []; spec.anchor = mode === 'unchanged' ? 'today' : 'forwards'; spec.cpi_pct = null;
  }
  spec.mode = 'nodes';
}
export function ensureBeNode(t, opts = {}) {
  let i = -1;
  const cur = inflSpec();
  if (cur.mode === 'nodes') i = (cur.nodes || []).findIndex((n) => Math.abs(n.t - t) < 4 / 365);
  if (i >= 0) return i;
  updateInfl((sp) => {
    toBeNodes(sp);
    i = sp.nodes.findIndex((n) => Math.abs(n.t - t) < 4 / 365);
    if (i >= 0) return;
    const c = curvesAt(t, 'be');
    const a = sp.anchor === 'today' ? c.today : c.fwd;
    sp.nodes = [...sp.nodes, { t, dev: c.user.map((x, j) => (x - a[j]) * 100) }].sort((x, y) => x.t - y.t);
    i = sp.nodes.findIndex((n) => Math.abs(n.t - t) < 1e-9);
  }, opts);
  return i;
}
export function setBeLevel(i, j, levelPct, opts) {
  updateInfl((sp) => {
    toBeNodes(sp);
    const n = sp.nodes[i];
    const c = curvesAt(n.t, 'be');
    spread(sp.nodes, i, j, (levelPct - (sp.anchor === 'today' ? c.today : c.fwd)[j]) * 100 - n.dev[j]);
  }, opts);
}
export function setBeDev(i, j, devBp, basis, opts) {
  updateInfl((sp) => {
    toBeNodes(sp);
    const n = sp.nodes[i];
    const c = curvesAt(n.t, 'be');
    const ref = basis === 'today' ? c.today : c.fwd;
    spread(sp.nodes, i, j, (ref[j] + devBp / 100 - (sp.anchor === 'today' ? c.today : c.fwd)[j]) * 100 - n.dev[j]);
  }, opts);
}

// ------------------------------------------------------------------ saved views (this browser)
export function loadView(id) {
  const v = S.views.find((x) => x.id === id);
  if (!v) return;
  set({ view: clone(v), viewId: id, viewDirty: false, activeNode: null, activeBeNode: null, undo: [], notice: null });
  savePrefs();
  analyze();
}
const newId = (p) => p + Math.random().toString(36).slice(2, 9);
export function saveView(asNew = false, name) {
  const v = clone(S.view);
  if (asNew || !v.id) { v.id = newId('v-'); v.name = name || (asNew ? `${v.name} (copy)` : v.name); v.color = v.color || nextColor(); }
  const views = S.views.some((x) => x.id === v.id) ? S.views.map((x) => (x.id === v.id ? v : x)) : [...S.views, v];
  set({ views, view: clone(v), viewId: v.id, viewDirty: false });
  saveDocs(); savePrefs();
}
export function deleteView(id) {
  const views = S.views.filter((v) => v.id !== id);
  set({ views });
  saveDocs();
  if (S.viewId === id && views[0]) loadView(views[0].id);
}
export function newView(template) {
  const v = { name: 'New view', color: nextColor(), anchor: 'forwards', nodes: [], builder: { type: 'nodes' }, ...template };
  delete v.id;
  set({ view: v, viewId: null, viewDirty: true, activeNode: null });
  analyze();
}
const COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
function nextColor() { return COLORS[S.views.length % COLORS.length]; }

export function exportDocs() {
  const blob = new Blob([JSON.stringify({ views: S.views, positions: S.positions, exported: new Date().toISOString() }, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'portfi-views.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
export async function importDocs(file) {
  try {
    const d = JSON.parse(await file.text());
    const merge = (cur, inc) => { const m = new Map(cur.map((x) => [x.id, x])); for (const x of inc || []) m.set(x.id || newId('i-'), x); return [...m.values()]; };
    set({ views: merge(S.views, d.views), positions: merge(S.positions, d.positions), notice: 'Imported saved views and positions.' });
    saveDocs();
  } catch (e) { set({ error: 'Import failed: ' + e.message }); }
}
export function resetDocs() {
  const d = clone(S.market.defaults);
  set({ views: d.views, positions: d.positions });
  saveDocs();
  loadView(d.views[0].id); loadPosition(d.positions[0].id);
}

// ------------------------------------------------------------------ positions
export function updatePosition(fn) {
  const p = clone(S.position);
  const out = fn(p) || p;
  set({ position: out, positionDirty: true });
  analyze();
}
export function loadPosition(id) {
  const p = S.positions.find((x) => x.id === id);
  if (!p) return;
  set({ position: clone(p), positionId: id, positionDirty: false });
  savePrefs();
  analyze();
}
export function savePosition(asNew = false, name) {
  const p = clone(S.position);
  if (asNew || !p.id) { p.id = newId('p-'); p.name = name || (asNew ? `${p.name} (copy)` : p.name); }
  const positions = S.positions.some((x) => x.id === p.id) ? S.positions.map((x) => (x.id === p.id ? p : x)) : [...S.positions, p];
  set({ positions, position: clone(p), positionId: p.id, positionDirty: false });
  saveDocs(); savePrefs();
}
export function deletePosition(id) {
  const positions = S.positions.filter((p) => p.id !== id);
  set({ positions });
  saveDocs();
  if (S.positionId === id && positions[0]) loadPosition(positions[0].id);
}

// ------------------------------------------------------------------ compare
export async function runCompare() {
  const c = S.compare;
  set({ compare: { ...c, loading: true } });
  try {
    const pickV = (id) => (id === '__working' ? S.view : S.views.find((v) => v.id === id));
    const pickP = (id) => (id === '__working' ? S.position : S.positions.find((p) => p.id === id));
    const [reqA, reqB] = c.mode === 'views'
      ? [buildRequest(pickV(c.a), S.position), buildRequest(pickV(c.b), S.position)]
      : [buildRequest(S.view, pickP(c.a)), buildRequest(S.view, pickP(c.b))];
    const ra = await api.analyze(reqA);
    const rb = await api.analyze(reqB);
    set({ compare: { ...S.compare, ra, rb, loading: false } });
  } catch (e) {
    set({ compare: { ...S.compare, loading: false }, error: e.message });
  }
}
