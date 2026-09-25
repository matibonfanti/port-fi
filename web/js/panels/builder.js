import { html, useState } from '../lib.js';
import { S, set, setPref, updateView, setNodeDev, setNodeLevel, addNode, removeNode, moveNode, shiftFactor, setAnchor,
         displayNodes, detachBuilder, curvesAt, undo, inflSpec, updateInfl, ensureBeNode, setBeDev, setBeLevel } from '../store.js';
import { api } from '../api.js';
import { fmtT, fmtSigned, fmtRate, KEYL } from '../format.js';
import { PolicyChart } from '../charts/small.js';

const num = (e) => parseFloat(e.target.value);
const nearestIdx = (T, t) => T.reduce((best, x, k) => (Math.abs(x - t) < Math.abs(T[best] - t) ? k : best), 0);

// ---------------------------------------------------------------- preset strip (shows exact node moves)
export function PresetStrip({ compact = false }) {
  const [mag, setMag] = useState(25);
  const [rel, setRel] = useState('today');
  const m = S.market;
  const apply = async (kind, magnitude) => {
    const out = await api.preset({ kind, magnitude_bp: magnitude, horizon: S.horizon, anchor: kind === 'unchanged' ? 'today' : kind === 'forwards' ? 'forwards' : rel });
    updateView((v) => {
      detachBuilder(v);
      v.anchor = out.anchor; v.nodes = out.nodes; v.time_interp = out.time_interp;
      v.builder = { type: 'nodes', from: 'preset', params: { kind, magnitude } };
    });
    set({ activeNode: null });
  };
  const tip = (kind, s) => {
    const sh = m.shapes[kind];
    if (!sh) return kind === 'unchanged' ? "Today's curve held for the whole horizon." : 'The forward curve is realised at every date.';
    const idx = [1, 4, 6, 8, 10];
    return `Moves reached linearly by the horizon, vs ${rel}: ` + idx.map((j) => `${KEYL[j]} ${fmtSigned(sh[j] * s, 0)}`).join(' · ') + 'bp';
  };
  const chips = [['parallel', -1, `Parallel −${mag}`], ['parallel', 1, `Parallel +${mag}`], ['bull_steepener', 1, 'Bull steepener'],
    ['bear_steepener', 1, 'Bear steepener'], ['bull_flattener', 1, 'Bull flattener'], ['bear_flattener', 1, 'Bear flattener'],
    ['twist', 1, 'Twist'], ['belly_rally', 1, 'Belly rally'], ['belly_selloff', 1, 'Belly selloff']];
  return html`<div class="row wrap" style="gap:4px">
    <span class="muted">Quick views</span>
    <input type="number" step="5" min="0" value=${mag} onChange=${(e) => setMag(num(e))} title="Size in bp (2s10s change for curve shapes; 5y move for belly)" style="width:48px"/>
    <span class="muted">bp vs</span>
    <select value=${rel} onChange=${(e) => setRel(e.target.value)}><option value="today">today</option><option value="forwards">fwds</option></select>
    ${chips.map(([k, sg, l]) => html`<button class="chip" data-tipt=${tip(k, sg * mag)} onClick=${() => apply(k, sg * mag)}>${l}</button>`)}
    <button class="chip" data-tipt=${tip('unchanged')} onClick=${() => apply('unchanged', 0)}>Unchanged</button>
    <button class="chip" data-tipt=${tip('forwards')} onClick=${() => apply('forwards', 0)}>Forwards realised</button>
  </div>`;
}

// ---------------------------------------------------------------- node timeline
function NodeBar({ r }) {
  const nodes = displayNodes();
  const t = r.t[S.tIndex ?? r.t.length - 1];
  const b = S.view.builder?.type || 'nodes';
  return html`<div class="row wrap" style="margin-bottom:8px">
    <span class="muted">Dates</span>
    ${b === 'policy' ? html`<span class="ink2">${nodes.length} dates compiled from your policy path</span>
      <button class="btn sm" onClick=${() => updateView((v) => detachBuilder(v))} title="Convert to editable nodes">Detach to edit</button>` : html`<div class="chips">
      ${nodes.length === 0 && html`<span class="muted">none yet — drag a point on the chart, or add one</span>`}
      ${nodes.map((n, i) => html`<button class=${'chip' + (S.activeNode === i ? ' on' : '')}
          onClick=${() => set({ activeNode: S.activeNode === i ? null : i, tIndex: nearestIdx(r.t, n.t) })}
          title=${`Your curve at ${fmtT(n.t)} — click to edit`}>${fmtT(n.t)}</button>`)}
      <button class="chip add" onClick=${() => addNode(Math.max(t, 1 / 52))} title="Add a date at the slider, starting from the current path">+ at ${fmtT(t)}</button>
    </div>`}
    <span class="sep"></span>
    ${b !== 'nodes' && html`<span class="tag">${b === 'policy' ? 'policy-built' : b}</span>`}
    <span class="ctl" data-tip="anchor">between dates, vs
      <span class="seg">${['forwards', 'today'].map((a) => html`<button class=${S.view.anchor === a ? 'on' : ''} onClick=${() => setAnchor(a)}>${a === 'forwards' ? 'Fwds' : 'Today'}</button>`)}</span>
    </span>
    <button class="btn ghost sm" disabled=${!S.undo.length} onClick=${undo} title="Undo last edit (⌘Z)">↶ Undo</button>
  </div>
  <${ScopeToggle}/>`;
}

export function ScopeToggle() {
  return html`<div class="row" style="margin:-4px 0 8px"><span class="ctl" data-tipt="How an edit at one date affects the rest of your path">Edits move
    <span class="seg">${[['path', 'the whole path (smooth)'], ['node', 'this date only']].map(([k, l]) => html`<button class=${S.editScope === k ? 'on' : ''}
      onClick=${() => setPref({ editScope: k }, false)}>${l}</button>`)}</span></span></div>`;
}

// ---------------------------------------------------------------- key-rate table (nominal or breakeven)
function KeyTable({ r, layer }) {
  const be = layer === 'be';
  const i = be ? S.activeBeNode : S.activeNode;
  const nodes = be ? (inflSpec().mode === 'nodes' ? inflSpec().nodes || [] : []) : displayNodes();
  const node = i != null ? nodes[i] : null;
  const t = node ? node.t : r.t[S.tIndex ?? r.t.length - 1];
  const c = curvesAt(t, be ? 'be' : 'nominal');
  if (!c) return null;
  const anchorSel = be ? (inflSpec().anchor || 'forwards') : S.view.anchor;
  const anchor = anchorSel === 'today' ? c.today : c.fwd;
  const user = node ? anchor.map((a, j) => a + (node.dev[j] + (c.pt[j] || 0)) / 100) : c.user;
  const edit = node != null;
  const ensure = () => (edit ? i : be ? ensureBeNode(t) : null);
  const onLevel = (j, v) => { if (be) { const k = ensure(); setBeLevel(k, j, v); set({ activeBeNode: k }); } else setNodeLevel(i, j, v); };
  const onDev = (j, v, basis) => { if (be) { const k = ensure(); setBeDev(k, j, v, basis); set({ activeBeNode: k }); } else setNodeDev(i, j, v, basis); };
  const canEdit = edit || be;
  const maxEdge = Math.max(5, ...user.map((x, j) => Math.abs(x - c.fwd[j]) * 100));
  const what = be ? 'breakeven' : 'zero rate';
  return html`<div>
    <div class="row" style="margin-bottom:4px">
      <b style="font-size:11.5px">${edit ? `Your ${what}s at ${fmtT(t)}` : `Readout at ${fmtT(t)}`}</b>
      <span class="muted">${edit || be ? 'type a level or a change, or drag the points on the chart' : 'drag a point on the chart or pick a date to edit'}</span>
      <span class="sep"></span>
      ${edit && !be && html`<button class="btn ghost sm" onClick=${() => removeNode(i)}>Remove date</button>
        <input type="number" step="0.25" min="0.25" value=${(node.t * 12).toFixed(2)} title="Date (months from today)"
          onChange=${(e) => moveNode(i, Math.max(0.02, num(e) / 12))} style="width:54px"/><span class="muted">m</span>`}
    </div>
    <div class="scroll-x"><table class="t">
      <thead><tr><th>Tenor</th><th data-tip=${be ? 'be_curve' : 'today'}>Today</th><th data-tip="fwd">Implied</th><th data-tip="yours">Yours</th>
        <th data-tip="vs_today">vs today</th><th data-tip="edge_bp">vs implied</th><th style="width:90px"></th></tr></thead>
      <tbody>${KEYL.map((lab, j) => {
        const vt = (user[j] - c.today[j]) * 100, vf = (user[j] - c.fwd[j]) * 100;
        const w = Math.min(44, Math.abs(vf) / maxEdge * 44);
        return html`<tr>
          <td>${lab}</td><td>${c.today[j].toFixed(2)}</td><td>${c.fwd[j].toFixed(2)}</td>
          <td>${canEdit ? html`<input type="number" step="0.01" value=${user[j].toFixed(2)} onChange=${(e) => onLevel(j, num(e))}/>` : user[j].toFixed(2)}</td>
          <td>${canEdit ? html`<input type="number" step="1" value=${vt.toFixed(0)} onChange=${(e) => onDev(j, num(e), 'today')}/>` : fmtSigned(vt, 0)}</td>
          <td>${canEdit ? html`<input type="number" step="1" value=${vf.toFixed(0)} onChange=${(e) => onDev(j, num(e), 'fwd')}/>` : fmtSigned(vf, 0)}</td>
          <td style="text-align:left"><span style="display:inline-block;width:44px;text-align:right">
            ${vf < 0 && html`<span class="edgebar" style=${`width:${w}px;background:var(--blue)`}></span>`}</span><span style="display:inline-block;width:1px;height:10px;background:var(--axis);vertical-align:middle"></span>${vf > 0 && html`<span class="edgebar" style=${`width:${w}px;background:var(--red)`}></span>`}
          </td></tr>`;
      })}</tbody></table></div>
    <div class="muted" style="margin-top:4px">Levels in % (${be ? 'cc breakeven' : 'cc zero'}), changes in bp. Bars: yours below the market-implied level (blue) or above (red).</div>
  </div>`;
}

// ---------------------------------------------------------------- factors & relative
function FactorsTab({ r }) {
  const [all, setAll] = useState(false);
  const [rel, setRel] = useState({ j: 8, bp: 25, basis: 'today', scope: 'node' });
  const i = S.activeNode;
  const info = i != null ? r.nodes[i] : null;
  const labels = r.factor.labels;
  const tips = ['level', 'slope', 'curvature'];
  const applyRel = () => {
    updateView((v) => {
      detachBuilder(v);
      const targets = rel.scope === 'all' ? v.nodes.map((_, q) => q) : [i];
      const tref = v.nodes[i].t;
      for (const q of targets) {
        const n = v.nodes[q];
        const c = curvesAt(n.t);
        const a = v.anchor === 'today' ? c.today : c.fwd;
        const ref = rel.basis === 'today' ? c.today : c.fwd;
        const scale = rel.scope === 'all' ? Math.min(1, n.t / tref) : 1;
        n.dev[rel.j] = (ref[rel.j] + rel.bp * scale / 100 - a[rel.j]) * 100 - c.pt[rel.j];
      }
    });
  };
  if (info == null) return html`<div class="note">Pick a date above (or drag a point on the chart) to express your curve there in factor or relative terms.</div>`;
  const B = r.factor.B;
  return html`<div class="col">
    <div class="row"><b style="font-size:11.5px">Your curve at ${fmtT(info.t)} in factor terms</b>
      <span class="muted">${S.basis === 'pca' ? 'PCA factors from history' : 'Nelson–Siegel factors'}</span><span class="sep"></span>
      <label class="ctl"><input type="checkbox" checked=${all} onChange=${(e) => setAll(e.target.checked)}/> apply to all dates ∝ time</label></div>
    <table class="t"><thead><tr><th>Factor</th><th data-tip="vs_today">vs today</th><th data-tip="edge_bp">vs fwds</th><th>set vs today</th><th>set vs fwds</th><th>1bp moves 2Y / 5Y / 10Y / 30Y</th></tr></thead>
      <tbody>${labels.map((lab, k) => html`<tr><td><span data-tip=${tips[k]}>Δ${lab.toLowerCase()}</span></td>
        <td>${fmtSigned(info.beta_today[k], 1, 'bp')}</td><td>${fmtSigned(info.beta_fwd[k], 1, 'bp')}</td>
        <td><input type="number" step="1" value=${info.beta_today[k].toFixed(1)} onChange=${(e) => shiftFactor(i, k, num(e) - info.beta_today[k], all)}/></td>
        <td><input type="number" step="1" value=${info.beta_fwd[k].toFixed(1)} onChange=${(e) => shiftFactor(i, k, num(e) - info.beta_fwd[k], all)}/></td>
        <td class="muted">${[4, 6, 8, 10].map((j) => B[j][k].toFixed(2)).join(' / ')}</td></tr>`)}</tbody></table>
    <div class="muted">Editing a factor adds Δβ × loadings (right column) to the curve at this date; other factors and the non-factor shape are untouched.</div>
    <div class="row wrap" style="margin-top:4px">
      <b style="font-size:11.5px">Relative view</b>
      <select value=${rel.j} onChange=${(e) => setRel({ ...rel, j: +e.target.value })}>${KEYL.map((l, j) => html`<option value=${j}>${l}</option>`)}</select>
      <input type="number" step="5" value=${rel.bp} onChange=${(e) => setRel({ ...rel, bp: num(e) })}/><span class="muted">bp vs</span>
      <select value=${rel.basis} onChange=${(e) => setRel({ ...rel, basis: e.target.value })}><option value="today">today</option><option value="fwd">forwards</option></select>
      <select value=${rel.scope} onChange=${(e) => setRel({ ...rel, scope: e.target.value })}><option value="node">at this date</option><option value="all">all dates ∝ time</option></select>
      <button class="btn" onClick=${applyRel}>Apply</button>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- policy path
function PolicyTab({ r }) {
  const rep = r.policy;
  const active = r.policy_active && S.view.builder?.type === 'policy';
  const params = active ? (S.view.builder.params || {}) : {};
  const setParams = (patch) => updateView((v) => { v.builder = { type: 'policy', params: { ...(v.builder?.params || {}), ...patch } }; });
  const currentMoves = () => rep.meetings.map((m) => +m.user_move_bp.toFixed(2));
  const setMove = (k, bp) => { const mv = currentMoves(); mv[k] = bp; setParams({ moves: mv, moves_scale: undefined, mode: 'meetings' }); };
  const activate = (extra = {}) => updateView((v) => {
    v.builder = { type: 'policy', params: { mode: 'meetings', half_life: 2.0, convergence_months: 3, tp: { 2: 0, 5: 0, 10: 0, 30: 0 }, ...extra } };
    v.anchor = 'forwards';
  });
  const hz = S.horizon;
  const cum = rep.cumulative;
  const n25 = (x) => (x / 25).toFixed(1);
  const smoothPts = [0.25, 0.5, 1, 1.5, 2];
  const smoothVals = params.smooth || smoothPts.map((t) => {
    const k = rep.chart.s.findIndex((s) => s >= t);
    return { t, level: +rep.chart.user[Math.max(0, k)].toFixed(2) };
  });
  return html`<div class="col">
    <div class="row wrap">
      ${!active && html`<div class="note" style="flex:1">The orange path is what the forwards price for the policy rate, meeting by meeting. Build your rates view from your own path:
        <div class="row wrap" style="margin-top:6px">
          <button class="btn primary" onClick=${() => activate()}>Start from priced path</button>
          <button class="btn" onClick=${() => activate({ moves_scale: 0 })}>Fed on hold</button>
          <button class="btn" onClick=${() => activate({ moves_scale: 0.5 })}>Half of priced</button></div></div>`}
      ${active && html`<span class="ctl">Input <span class="seg">${['meetings', 'smooth'].map((m) => html`<button class=${(params.mode || 'meetings') === m ? 'on' : ''}
          onClick=${() => setParams(m === 'smooth' ? { mode: 'smooth', smooth: smoothVals } : { mode: 'meetings' })}>${m === 'meetings' ? 'Meeting by meeting' : 'Smooth path'}</button>`)}</span></span>
        <span class="sep"></span>
        <button class="btn sm" onClick=${() => setParams({ moves: null, moves_scale: 1, mode: 'meetings' })}>As priced</button>
        <button class="btn sm" onClick=${() => setParams({ moves: null, moves_scale: 0, mode: 'meetings' })}>Hold</button>
        <button class="btn sm" onClick=${() => setParams({ moves: rep.meetings.map(() => 25), mode: 'meetings' })}>+25 each</button>
        <button class="btn sm" onClick=${() => setParams({ moves: rep.meetings.map(() => -25), mode: 'meetings' })}>−25 each</button>`}
    </div>
    <div class="legend"><span class="k"><span class="ln" style="background:var(--orange)"></span>Priced (forwards, step per meeting)</span>
      <span class="k"><span class="ln" style="background:var(--blue)"></span>Yours</span><span class="muted">shaded: beyond horizon</span></div>
    <${PolicyChart} report=${rep} horizon=${hz}/>
    <div class="scroll-x"><table class="t"><thead><tr><th>Cumulative from ${rep.r0.toFixed(2)}%</th>${Object.keys(cum).map((k) => html`<th>by ${k}</th>`)}</tr></thead>
      <tbody><tr><td>Priced</td>${Object.values(cum).map((c) => html`<td>${fmtSigned(c.mkt_bp, 0, 'bp')} <span class="muted">(${n25(c.mkt_bp)}×25)</span></td>`)}</tr>
        <tr><td>Yours</td>${Object.values(cum).map((c) => html`<td>${fmtSigned(c.user_bp, 0, 'bp')} <span class="muted">(${n25(c.user_bp)}×25)</span></td>`)}</tr></tbody></table></div>
    ${active && (params.mode || 'meetings') === 'smooth' && html`<div class="row wrap"><b style="font-size:11.5px">Your policy rate at</b>
      ${smoothVals.map((p, k) => html`<label class="field"><span>${fmtT(p.t)}</span><input type="number" step="0.05" value=${(+p.level).toFixed(2)}
        onChange=${(e) => { const sv = smoothVals.map((q) => ({ ...q })); sv[k].level = num(e); setParams({ smooth: sv, mode: 'smooth' }); }}/></label>`)}</div>`}
    <div class="scroll-x" style="max-height:230px;overflow-y:auto"><table class="t">
      <thead><tr><th>FOMC</th><th>Priced move</th><th>Priced level</th><th>Your move</th><th>Your level</th><th>Gap</th></tr></thead>
      <tbody>${rep.meetings.map((m, k) => html`<tr style=${m.t > hz ? 'opacity:.55' : ''}>
        <td>${m.date}${m.estimated ? html` <span class="muted" title="Estimated date">est.</span>` : ''}</td>
        <td>${fmtSigned(m.mkt_move_bp, 1)}</td><td>${m.mkt_level.toFixed(2)}</td>
        <td>${active && (params.mode || 'meetings') === 'meetings'
          ? html`<span class="row" style="justify-content:flex-end;gap:2px">
              <button class="btn sm ghost" onClick=${() => setMove(k, Math.round((m.user_move_bp - 25) / 25) * 25)}>−</button>
              <input type="number" step="25" value=${m.user_move_bp.toFixed(1)} onChange=${(e) => setMove(k, num(e))}/>
              <button class="btn sm ghost" onClick=${() => setMove(k, Math.round((m.user_move_bp + 25) / 25) * 25)}>+</button></span>`
          : fmtSigned(m.user_move_bp, 1)}</td>
        <td>${m.user_level.toFixed(2)}</td><td class=${m.user_level - m.mkt_level < 0 ? 'pos' : m.user_level - m.mkt_level > 0 ? 'neg' : ''}>${fmtSigned((m.user_level - m.mkt_level) * 100, 0)}</td></tr>`)}</tbody></table></div>
    ${active && html`<div class="grid2">
      <div class="col"><b style="font-size:11.5px">Beyond your meetings</b>
        <label class="field"><span data-tip="half_life">Deviation half-life (years, blank = hold)</span>
          <input type="number" step="0.5" min="0" value=${params.half_life ?? ''} onChange=${(e) => setParams({ half_life: e.target.value === '' ? 'hold' : num(e) })}/></label>
        <label class="field"><span data-tip="convergence">Market converges to your path over (months)</span>
          <input type="number" step="1" min="0" value=${params.convergence_months ?? 3} onChange=${(e) => setParams({ convergence_months: num(e) })}/></label></div>
      <div class="col"><b style="font-size:11.5px" data-tip="tp">Term premium change by horizon (bp)</b>
        <div class="row">${[2, 5, 10, 30].map((k) => html`<label class="field"><span>${k}Y</span><input type="number" step="5" style="width:52px"
          value=${(params.tp || {})[k] ?? 0} onChange=${(e) => setParams({ tp: { ...(params.tp || {}), [k]: num(e) } })}/></label>`)}</div>
        <div class="muted">Your curve at t = forwards + average (your − priced) short rate over [t, t+τ] + term-premium change.</div></div>
    </div>`}
  </div>`;
}

// ---------------------------------------------------------------- inflation
function InflationTab({ r }) {
  const inf = r.inflation;
  if (!inf) return html`<div class="note">No TIPS real curve for this date (Treasury publishes it from 2003-01-02), so inflation views are unavailable.</div>`;
  const sp = inflSpec();
  const mode = inf.mode;
  const setMode = (m) => updateInfl((s) => {
    if (m === 'expectations' && !s.buckets) s.buckets = inf.buckets.map((b) => +b.mkt_yoy.toFixed(2));
    if (m === 'nodes' && s.mode !== 'nodes') { s.nodes = []; s.anchor = mode === 'unchanged' ? 'today' : 'forwards'; }
    s.mode = m;
  });
  const i = S.activeBeNode;
  const bn = sp.mode === 'nodes' ? sp.nodes || [] : [];
  const tI = S.tIndex ?? r.t.length - 1;
  const idx = [6, 8, 10];
  const u = inf.keys.user[tI], f = inf.keys.fwd[tI], z = inf.keys.today;
  const ptH = inf.passthrough_H_bp || [];
  const beShift = (bp) => updateInfl((s) => { s.mode = 'nodes'; s.anchor = 'forwards'; s.nodes = [{ t: S.horizon, dev: KEYL.map(() => bp) }]; s.cpi_pct = s.cpi_pct ?? null; });
  const modes = [['follow', 'Follow rates view'], ['priced', 'As priced'], ['unchanged', 'Unchanged'], ['expectations', 'My CPI expectations'], ['nodes', 'My breakeven curve']];
  return html`<div class="col">
    <div class="row wrap"><span class="muted">Inflation view</span>
      <span class="seg">${modes.map(([k, l]) => html`<button class=${(sp.mode || 'follow') === k ? 'on' : ''} onClick=${() => setMode(k)}>${l}</button>`)}</span></div>
    ${mode === 'expectations' && html`<div class="scroll-x"><table class="t">
      <thead><tr><th>Average CPI inflation, % a year</th><th data-tip="be_curve">Priced by breakevens</th><th>Yours</th><th>Gap</th></tr></thead>
      <tbody>${inf.buckets.map((b, k) => html`<tr><td>${b.label}${b.b <= 5 ? html` <span class="muted" title="No TIPS data below 5Y: priced = 5Y breakeven">*</span>` : ''}</td>
        <td>${b.mkt_yoy.toFixed(2)}</td>
        <td><input type="number" step="0.05" value=${(+b.user_yoy).toFixed(2)} onChange=${(e) => updateInfl((s) => {
          const arr = (s.buckets || inf.buckets.map((q) => q.user_yoy)).slice(); arr[k] = num(e); s.buckets = arr; s.mode = 'expectations'; })}/></td>
        <td class=${b.user_yoy - b.mkt_yoy > 0 ? 'neg' : b.user_yoy - b.mkt_yoy < 0 ? 'pos' : ''}>${fmtSigned((b.user_yoy - b.mkt_yoy) * 100, 0, 'bp')}</td></tr>`)}</tbody></table>
      <div class="muted">* Treasury publishes TIPS yields from 5Y, so near-term priced inflation equals the 5Y breakeven.</div></div>
      <div class="row wrap">
        <label class="field"><span data-tip="convergence">Breakevens converge to your path over (months)</span>
          <input type="number" step="1" min="0" value=${sp.convergence_months ?? 3} onChange=${(e) => updateInfl((s) => { s.convergence_months = num(e); })}/></label>
        <span class="field"><span data-tipt="Change in the inflation risk premium embedded in breakevens, by horizon (bp)">Inflation risk premium change (bp)</span>
          <span class="row">${[2, 5, 10, 30].map((k) => html`<label class="field"><span>${k}Y</span><input type="number" step="5" style="width:50px"
            value=${(sp.irp || {})[k] ?? 0} onChange=${(e) => updateInfl((s) => { s.irp = { ...(s.irp || {}), [k]: num(e) }; })}/></label>`)}</span></span>
      </div>`}
    ${mode === 'nodes' && html`<div class="row wrap"><span class="muted">Dates</span>
      <div class="chips">${bn.map((n, k) => html`<button class=${'chip' + (i === k ? ' on' : '')} onClick=${() => set({ activeBeNode: i === k ? null : k, tIndex: nearestIdx(r.t, n.t), curveMode: 'be' })}>${fmtT(n.t)}</button>`)}
        ${!bn.length && html`<span class="muted">drag a point on the Breakeven chart, or use a quick view:</span>`}</div>
      <span class="sep"></span>
      <label class="ctl" data-tip="cpi">realised CPI % a yr <input type="number" step="0.05" placeholder=${inf.horizon_mkt_yoy?.toFixed(2)} value=${sp.cpi_pct ?? ''}
        onChange=${(e) => updateInfl((s) => { s.cpi_pct = e.target.value === '' ? null : num(e); })}/></label></div>
      <div class="row wrap" style="gap:4px"><span class="muted">Quick views</span>
        ${[-50, -25, 25, 50].map((b) => html`<button class="chip" data-tipt=${`Breakevens ${b > 0 ? '+' : ''}${b}bp vs forwards at every tenor by the horizon`} onClick=${() => beShift(b)}>BE ${b > 0 ? '+' : ''}${b}bp</button>`)}</div>
      <${KeyTable} r=${r} layer="be"/>`}
    ${['expectations', 'nodes'].includes(mode) && html`<label class="field"><span data-tip="passthrough">Pass-through of your breakeven change to nominal yields: ${Math.round((sp.passthrough ?? 1) * 100)}%
        ${ptH.length ? ` → 10Y nominal ${fmtSigned(ptH[8], 0, 'bp')} at horizon` : ''}</span>
      <input type="range" min="0" max="1" step="0.05" value=${sp.passthrough ?? 1} onChange=${(e) => updateInfl((s) => { s.passthrough = num(e); })}/></label>`}
    <table class="t"><thead><tr><th>At ${fmtT(r.t[tI])}</th>${idx.map((j) => html`<th>${KEYL[j]} BE</th>`)}<th data-tip="cpi">CPI to horizon</th></tr></thead>
      <tbody><tr><td>Today</td>${idx.map((j) => html`<td>${z[j].toFixed(2)}</td>`)}<td></td></tr>
        <tr><td>Priced</td>${idx.map((j) => html`<td>${f[j].toFixed(2)}</td>`)}<td>${inf.horizon_mkt_yoy?.toFixed(2)}%</td></tr>
        <tr><td>Yours</td>${idx.map((j) => html`<td>${u[j].toFixed(2)}</td>`)}<td>${inf.horizon_user_yoy?.toFixed(2)}%</td></tr></tbody></table>
    <div class="muted">Breakevens = nominal − real (TIPS) zero rates. They include inflation-risk and liquidity premia; "priced" treats them as expectations by convention. Affects TIPS/breakeven positions directly, and nominal bonds through pass-through.</div>
  </div>`;
}

// ---------------------------------------------------------------- presets & analogues
function PresetsTab({ r }) {
  const [custom, setCustom] = useState({ start: '2022-01-03', scale: 1 });
  const m = S.market;
  const analog = async (start, label) => {
    try {
      const out = await api.analogue({ asof: S.asof, start, horizon: S.horizon, scale: custom.scale });
      updateView((v) => {
        v.anchor = 'today'; v.nodes = out.nodes; v.time_interp = out.time_interp;
        v.builder = { type: 'analogue', params: { start, scale: custom.scale, label, ...out.meta } };
      });
      set({ activeNode: null, notice: `Applied the zero-curve changes from ${out.meta.from} to ${out.meta.to}${custom.scale !== 1 ? ` ×${custom.scale}` : ''}.` });
    } catch (e) { set({ error: e.message }); }
  };
  return html`<div class="col">
    <${PresetStrip}/>
    <div class="row" style="margin-top:6px"><b style="font-size:11.5px">Historical analogues</b><span class="muted">apply a past period's zero-curve changes over the same elapsed time</span></div>
    <div class="list" style="max-height:190px;overflow-y:auto">${m.analogues.map((a) => html`<div class="it" onClick=${() => analog(a.start, a.label)}>
      <span class="nm"><b>${a.label}</b> <span class="muted">from ${a.start} — ${a.desc}</span></span></div>`)}</div>
    <div class="row wrap"><span class="muted">Custom start</span>
      <input type="date" value=${custom.start} min=${m.first_date} max=${m.asof} onChange=${(e) => setCustom({ ...custom, start: e.target.value })}/>
      <span class="muted">scale ×</span><input type="number" step="0.25" value=${custom.scale} onChange=${(e) => setCustom({ ...custom, scale: num(e) })}/>
      <button class="btn" onClick=${() => analog(custom.start, 'Custom')}>Apply analogue</button></div>
  </div>`;
}

// ---------------------------------------------------------------- live readout vs priced
function Readout({ r }) {
  const i = S.tIndex ?? r.t.length - 1;
  const idx = [4, 6, 8, 10];
  const u = r.keys.user[i], f = r.keys.fwd[i];
  const pol = r.policy?.cumulative;
  const hzKey = S.horizon >= 2 ? '24m' : S.horizon >= 1 ? '12m' : S.horizon >= 0.5 ? '6m' : '3m';
  return html`<div class="row wrap" style="border-top:1px solid var(--border);margin:10px -12px -4px;padding:8px 12px 0;gap:14px">
    <b style="font-size:11.5px">Yours vs priced at ${fmtT(r.t[i])}</b>
    ${idx.map((j) => { const e = (u[j] - f[j]) * 100; return html`<span class="num" data-tip="edge_bp">${KEYL[j]} <b class=${e < 0 ? 'pos' : e > 0 ? 'neg' : ''}>${fmtSigned(e, 0, 'bp')}</b></span>`; })}
    <span class="num" data-tipt="Change in 2s10s: yours minus forwards">2s10s <b>${fmtSigned(((u[8] - u[4]) - (f[8] - f[4])) * 100, 0, 'bp')}</b></span>
    ${pol && html`<span class="muted">Policy by ${hzKey}: priced ${fmtSigned(pol[hzKey].mkt_bp, 0, 'bp')}, yours ${fmtSigned(pol[hzKey].user_bp, 0, 'bp')}</span>`}
  </div>`;
}

export function Builder({ r }) {
  const tabs = [['nodes', 'Key rates'], ['factors', 'Factors & relative'], ['policy', 'Policy path'], ['presets', 'Presets & history'], ['inflation', 'Inflation']];
  const onTab = (k) => set({ builderTab: k, curveMode: k === 'inflation' ? (S.curveMode === 'nominal' ? 'be' : S.curveMode) : 'nominal' });
  return html`<section class=${'card' + (S.focusStep === 3 || S.focusStep === 4 ? ' focus' : '')} style="height:100%" id="step-3">
    <header><span class="stepno">3</span><h2>Your view</h2><span class="sub">${S.view.name}${S.viewDirty ? ' · unsaved' : ''}</span>
      <span class="sep"></span><span class="stepno" id="step-4" title="Step 4: inflation view">4</span><button class="btn ghost sm" onClick=${() => onTab('inflation')}>Inflation →</button></header>
    <div class="body">
      <div class="subtabs">${tabs.map(([k, l]) => html`<button class=${S.builderTab === k ? 'on' : ''} onClick=${() => onTab(k)}>${l}</button>`)}</div>
      ${S.builderTab !== 'inflation' && html`<${NodeBar} r=${r}/>`}
      ${S.notice && html`<div class="note row" style="margin-bottom:8px"><span style="flex:1">${S.notice}</span><button class="btn ghost sm" onClick=${() => set({ notice: null })}>×</button></div>`}
      ${S.builderTab === 'nodes' && html`<${KeyTable} r=${r} layer="nominal"/>`}
      ${S.builderTab === 'factors' && html`<${FactorsTab} r=${r}/>`}
      ${S.builderTab === 'policy' && html`<${PolicyTab} r=${r}/>`}
      ${S.builderTab === 'presets' && html`<${PresetsTab} r=${r}/>`}
      ${S.builderTab === 'inflation' && html`<${InflationTab} r=${r}/>`}
      <${Readout} r=${r}/>
    </div></section>`;
}
