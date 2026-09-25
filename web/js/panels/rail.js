// Left rail: ① position, ② horizon & return assumptions, saved views.
import { html, useState } from '../lib.js';
import { S, set, setPref, updatePosition, loadPosition, savePosition, deletePosition, loadView, saveView, deleteView,
         newView, updateView, exportDocs, importDocs, resetDocs } from '../store.js';
import { fmtNum, fmtUsd, fmtT } from '../format.js';

const num = (e) => parseFloat(e.target.value);

// ---------------------------------------------------------------- bond spec selector
function BondSpec({ spec, onChange, real = false }) {
  const otr = (real ? S.market.otr_tips : S.market.otr) || [];
  const mode = spec.otr ? 'otr' : spec.maturity ? 'custom' : 'gen';
  const hasOtr = otr.some((o) => o.term === spec.otr);
  return html`<span class="row" style="gap:4px;flex-wrap:wrap">
    <select value=${mode === 'otr' ? 'otr:' + spec.otr : mode} onChange=${(e) => {
      const v = e.target.value;
      if (v.startsWith('otr:')) onChange({ otr: +v.slice(4) });
      else if (v === 'gen') onChange({ tenor: spec.otr || spec.tenor || 10, coupon: null });
      else onChange({ maturity: S.market.asof.replace(/^(\d{4})/, (y) => String(+y + 10)), coupon: real ? 1.5 : 4.5 });
    }}>
      ${otr.map((o) => html`<option value=${'otr:' + o.term}>${o.term}Y OTR · ${o.label}</option>`)}
      ${mode === 'otr' && !hasOtr && html`<option value=${'otr:' + spec.otr}>${spec.otr}Y OTR (not available — generic used)</option>`}
      <option value="gen">Generic tenor (par coupon)</option><option value="custom">Custom maturity & coupon</option>
    </select>
    ${mode === 'gen' && html`<input type="number" step="0.5" min="0.5" max="30" value=${spec.tenor} title="Tenor (years)" onChange=${(e) => onChange({ ...spec, tenor: num(e) })} style="width:48px"/><span class="muted">y</span>
      <input type="number" step="0.125" placeholder="par" value=${spec.coupon ?? ''} title=${`${real ? 'Real coupon' : 'Coupon'} %, blank = par`} onChange=${(e) => onChange({ ...spec, coupon: e.target.value === '' ? null : num(e) })} style="width:56px"/><span class="muted">%</span>`}
    ${mode === 'custom' && html`<input type="date" value=${spec.maturity} onChange=${(e) => onChange({ ...spec, maturity: e.target.value })}/>
      <input type="number" step="0.125" value=${spec.coupon ?? 4.5} onChange=${(e) => onChange({ ...spec, coupon: num(e) })} style="width:56px"/><span class="muted">%</span>`}
  </span>`;
}

const KINDS = { bond: 'Bond', tips: 'TIPS', steepener: 'Steepener', flattener: 'Flattener', butterfly: 'Butterfly', breakeven: 'Breakeven trade' };
function defaultItem(kind) {
  if (kind === 'bond') return { kind, bond: { otr: 10 }, face_mm: 1 };
  if (kind === 'tips') return { kind, bond: { otr: 10 }, face_mm: 1 };
  if (kind === 'breakeven') return { kind, legs: [{ otr: 10 }, { otr: 10 }], weighting: 'dv01', size_mm: 1, direction: 'long' };
  if (kind === 'butterfly') return { kind, legs: [{ otr: 2 }, { otr: 5 }, { otr: 10 }], weighting: 'dv01', size_mm: 1, direction: 'short_belly' };
  return { kind, legs: [{ otr: 2 }, { otr: 10 }], weighting: 'dv01', size_mm: 1 };
}

function ItemEditor({ it, k }) {
  const up = (patch) => updatePosition((p) => { p.items[k] = { ...p.items[k], ...patch }; });
  const upLeg = (q, spec) => updatePosition((p) => { p.items[k].legs[q] = spec; });
  const legNames = it.kind === 'butterfly' ? ['Wing', 'Belly', 'Wing'] : it.kind === 'breakeven' ? ['TIPS', 'Nominal'] : ['Front', 'Back'];
  const single = it.kind === 'bond' || it.kind === 'tips';
  const kinds = Object.entries(KINDS).filter(([v]) => S.market.has_real || !['tips', 'breakeven'].includes(v));
  return html`<div style="border:1px solid var(--border);border-radius:6px;padding:6px 8px" class="col">
    <div class="row">
      <select value=${it.kind} onChange=${(e) => updatePosition((p) => { p.items[k] = defaultItem(e.target.value); })}>
        ${kinds.map(([v, l]) => html`<option value=${v}>${l}</option>`)}</select>
      ${single
        ? html`<label class="ctl">face $mm <input type="number" step="0.5" value=${it.face_mm} onChange=${(e) => up({ face_mm: num(e) })} style="width:56px"/></label>`
        : html`<label class="ctl" title=${it.kind === 'butterfly' ? 'Belly face ($mm)' : it.kind === 'breakeven' ? 'TIPS face ($mm)' : 'Back-leg face ($mm)'}>size $mm <input type="number" step="0.5" min="0" value=${it.size_mm} onChange=${(e) => up({ size_mm: num(e) })} style="width:50px"/></label>`}
      <span class="sep"></span>
      <button class="btn ghost sm" title="Remove" onClick=${() => updatePosition((p) => { p.items.splice(k, 1); })}>×</button>
    </div>
    ${single
      ? html`<${BondSpec} spec=${it.bond} real=${it.kind === 'tips'} onChange=${(b) => up({ bond: b })}/>
         ${it.kind === 'bond' ? html`<div class="row"><label class="ctl">Z-spread bp <input type="number" step="5" value=${it.spread_bp || 0} onChange=${(e) => up({ spread_bp: num(e), credit: num(e) !== 0 })} style="width:52px"/></label>
           <span class="muted">${it.spread_bp ? 'credit line' : 'Treasury'}</span></div>`
           : html`<div class="muted">Index ratio set to 1.00 at valuation (face = inflation-adjusted principal).</div>`}`
      : html`${it.legs.map((lg, q) => html`<div class="row"><span class="muted" style="width:44px">${legNames[q]}</span><${BondSpec} spec=${lg} real=${it.kind === 'breakeven' && q === 0} onChange=${(b) => upLeg(q, b)}/></div>`)}
        <div class="row wrap">
          <label class="ctl">weights <select value=${it.weighting} onChange=${(e) => up({ weighting: e.target.value })}>
            <option value="dv01">DV01-neutral</option>${it.kind === 'breakeven' ? html`<option value="notional">Market-value neutral</option>` : html`<option value="pca">PCA-neutral</option>`}</select></label>
          ${it.kind === 'butterfly' && html`<select value=${it.direction} onChange=${(e) => up({ direction: e.target.value })}>
            <option value="short_belly">Sell belly / buy wings</option><option value="long_belly">Buy belly / sell wings</option></select>`}
          ${it.kind === 'breakeven' && html`<select value=${it.direction} onChange=${(e) => up({ direction: e.target.value })}>
            <option value="long">Long breakevens (buy TIPS / sell UST)</option><option value="short">Short breakevens</option></select>`}
        </div>`}
  </div>`;
}

export function PositionPanel({ r }) {
  const p = S.position;
  const [name, setName] = useState(null);
  if (!p) return null;
  const kinds = Object.entries(KINDS).filter(([v]) => S.market.has_real || !['tips', 'breakeven'].includes(v));
  return html`<section class=${'card' + (S.focusStep === 1 ? ' focus' : '')} id="step-1">
    <header><span class="stepno">1</span><h2>Position</h2><span class="sub">${S.positionDirty ? 'unsaved' : ''}</span><span class="sep"></span>
      <select value=${S.positionId || ''} onChange=${(e) => loadPosition(e.target.value)} style="max-width:170px">
        ${!S.positionId && html`<option value="">(unsaved)</option>`}
        ${S.positions.map((q) => html`<option value=${q.id}>${q.name}</option>`)}</select></header>
    <div class="body col">
      <div class="row"><input type="text" value=${name ?? p.name} onInput=${(e) => setName(e.target.value)}
          onChange=${(e) => { updatePosition((q) => { q.name = e.target.value; }); setName(null); }} style="flex:1"/>
        <button class="btn" disabled=${!S.positionDirty && S.positionId} onClick=${() => savePosition(!S.positionId)}>Save</button>
        <button class="btn ghost" onClick=${() => savePosition(true)} title="Save as a copy">Dup</button>
        <button class="btn ghost" disabled=${!S.positionId} onClick=${() => confirm(`Delete position "${p.name}"?`) && deletePosition(S.positionId)} title="Delete">Del</button></div>
      ${p.items.map((it, k) => html`<${ItemEditor} it=${it} k=${k}/>`)}
      <div class="row wrap"><span class="muted">Add</span>${kinds.map(([k, l]) => html`<button class="btn sm" onClick=${() => updatePosition((q) => { q.items.push(defaultItem(k)); })}>+ ${l}</button>`)}</div>
      ${r && html`<div class="scroll-x"><table class="t"><thead><tr><th>Line</th><th>Face</th><th>Clean</th><th>Yld</th><th data-tip="dv01">DV01</th></tr></thead>
        <tbody>${r.position.lines.map((l) => html`<tr title=${`${l.item} · ${l.role} · matures ${l.maturity} · dirty ${l.dirty.toFixed(2)} · accrued ${l.accrued.toFixed(2)} · mod dur ${l.mod_dur.toFixed(2)}${l.real ? ' · real yield' : ''}`}>
          <td>${l.label}</td><td>${fmtNum(l.face_mm, 2)}</td><td>${l.clean.toFixed(2)}</td><td>${l.yield_sa.toFixed(2)}${l.real ? 'r' : ''}</td><td>${fmtUsd(l.dv01, true)}</td></tr>`)}
          <tr class="tot"><td>Net</td><td></td><td></td><td></td><td>${fmtUsd(r.position.dv01, true)}</td></tr></tbody></table></div>
        <div class="muted"><span data-tip="gross_mv">Gross MV</span> ${fmtUsd(r.position.gross_mv, false)} · priced off the fitted curve · s.a. yields${r.position.has_real ? ' · r = real' : ''}</div>`}
    </div></section>`;
}

// ---------------------------------------------------------------- ② horizon & return assumptions
export function ReturnPanel({ r }) {
  const p = S.position;
  if (!p) return null;
  const fin = p.financing || { mode: 'flat', rate_pct: 4 };
  const basis = fin.basis || 'excess';
  const rates = S.market.rates || {};
  const implied = r?.position?.financing?.implied_mm_pct;
  const setFin = (patch) => updatePosition((q) => { q.financing = { ...fin, ...patch }; });
  const hz = [[1 / 12, '1M'], [0.25, '3M'], [0.5, '6M'], [0.75, '9M'], [1, '1Y'], [2, '2Y']];
  const isPreset = hz.some(([v]) => Math.abs(v - S.horizon) < 1e-9);
  return html`<section class=${'card' + (S.focusStep === 2 ? ' focus' : '')} id="step-2">
    <header><span class="stepno">2</span><h2>Horizon & return</h2><span class="sub">when, and measured how</span></header>
    <div class="body col">
      <div class="row wrap"><span class="muted" style="width:62px">Horizon</span>
        <span class="seg">${hz.map(([v, l]) => html`<button class=${Math.abs(S.horizon - v) < 1e-9 ? 'on' : ''} onClick=${() => setPref({ horizon: v, tIndex: null, activeNode: null, activeBeNode: null })}>${l}</button>`)}</span>
        <input type="number" min="1" max="36" step="1" value=${Math.round(S.horizon * 12)} title="Custom horizon (months)" style=${`width:46px${isPreset ? '' : ';border-color:var(--ink)'}`}
          onChange=${(e) => setPref({ horizon: Math.min(36, Math.max(1, num(e))) / 12, tIndex: null, activeNode: null, activeBeNode: null })}/><span class="muted">m</span></div>
      <div class="row wrap"><span class="muted" style="width:62px">Return</span>
        <span class="seg">${[['total', 'Holding-period return'], ['excess', 'Excess over financing']].map(([b, l]) => html`<button data-tip=${'basis_' + b} class=${basis === b ? 'on' : ''} onClick=${() => setFin({ basis: b })}>${l}</button>`)}</span></div>
      <div class="row wrap"><span class="muted" style="width:62px">${basis === 'total' ? 'Cash rate' : 'Financing'}</span>
        <span class="seg">${[['flat', basis === 'total' ? 'Flat rate' : 'Flat repo'], ['implied', 'Implied short rate']].map(([m, l]) => html`<button class=${fin.mode === m ? 'on' : ''} onClick=${() => setFin({ mode: m })}>${l}</button>`)}</span>
        ${fin.mode === 'flat'
          ? html`<input type="number" step="0.01" value=${(+fin.rate_pct).toFixed(2)} title="% ACT/360" onChange=${(e) => setFin({ rate_pct: num(e) })}/><span class="muted">%</span>
              ${rates.sofr && html`<button class="btn sm" onClick=${() => setFin({ rate_pct: rates.sofr.rate })} title=${'SOFR ' + rates.sofr.date}>SOFR ${rates.sofr.rate.toFixed(2)}</button>`}
              ${implied != null && html`<button class="btn sm" data-tip="implied_rate" onClick=${() => setFin({ rate_pct: +implied.toFixed(4) })}>Implied ${implied.toFixed(2)}</button>`}`
          : html`<label class="ctl">+ <input type="number" step="1" value=${fin.spread_bp || 0} onChange=${(e) => setFin({ spread_bp: num(e) })}/> bp</label>`}
      </div>
      <div class="muted" style="margin-left:70px">${basis === 'total'
        ? 'Unfunded: coupons are reinvested at this rate; “beat cash” compares against it.'
        : 'Funded: you borrow the price at this rate (repo); coupons reduce the loan.'}</div>
      <div class="row wrap" id="step-5"><span class="stepno sm">5</span><span class="muted" data-tip="target">Target return</span>
        <input type="number" step="0.25" value=${S.targetPct} onChange=${(e) => setPref({ targetPct: num(e) })}/><span class="muted">% a year${S.horizon !== 1 ? ` (= ${((((1 + S.targetPct / 100) ** S.horizon) - 1) * 100).toFixed(2)}% over ${fmtT(S.horizon)})` : ''}</span></div>
    </div></section>`;
}

export function ViewsPanel() {
  const [name, setName] = useState(null);
  const v = S.view;
  if (!v) return null;
  const c = S.compare;
  const pick = (id, which) => set({ compare: { ...c, mode: 'views', [which]: id } });
  return html`<section class="card">
    <header><h2>Saved views</h2><span class="sub">stored in this browser</span><span class="sep"></span>
      <button class="btn sm" onClick=${() => newView({ anchor: 'forwards', nodes: [], name: 'New view' })}>New</button></header>
    <div class="body col">
      <div class="row"><span class="dot" style=${`background:${v.color || 'var(--blue)'}`}></span>
        <input type="text" value=${name ?? v.name} onInput=${(e) => setName(e.target.value)}
          onChange=${(e) => { updateView((q) => { q.name = e.target.value; }, { record: false }); setName(null); }} style="flex:1"/>
        <button class="btn" disabled=${!S.viewDirty && S.viewId} onClick=${() => saveView(!S.viewId)}>Save</button>
        <button class="btn ghost" onClick=${() => saveView(true)} title="Duplicate as a new view">Dup</button></div>
      <div class="list">${S.views.map((q) => html`<div class=${'it' + (q.id === S.viewId ? ' on' : '')} onClick=${() => loadView(q.id)}>
          <span class="dot" style=${`background:${q.color || 'var(--blue)'}`}></span>
          <span class="nm" title=${q.notes || ''}>${q.name}</span>
          ${q.builder?.type && q.builder.type !== 'nodes' && html`<span class="tag">${q.builder.type}</span>`}
          ${q.inflation && q.inflation.mode !== 'follow' && html`<span class="tag">CPI</span>`}
          <span class=${'ab' + (c.a === q.id ? ' on' : '')} title="Compare as A" onClick=${(e) => { e.stopPropagation(); pick(q.id, 'a'); }}>A</span>
          <span class=${'ab' + (c.b === q.id ? ' on' : '')} title="Compare as B" onClick=${(e) => { e.stopPropagation(); pick(q.id, 'b'); }}>B</span>
          <button class="btn ghost sm" title="Delete view" onClick=${(e) => { e.stopPropagation(); confirm(`Delete view "${q.name}"?`) && deleteView(q.id); }}>×</button>
        </div>`)}</div>
      ${v.notes && html`<div class="muted">${v.notes}</div>`}
      <div class="row wrap"><button class="btn" onClick=${() => set({ tab: 'compare' })}>Compare A vs B →</button><span class="sep"></span>
        <button class="btn ghost sm" onClick=${exportDocs} title="Download your views and positions as JSON">Export</button>
        <label class="btn ghost sm" style="cursor:pointer">Import<input type="file" accept="application/json" style="display:none" onChange=${(e) => e.target.files[0] && importDocs(e.target.files[0])}/></label>
        <button class="btn ghost sm" onClick=${() => confirm('Restore the default views and positions? Your saved items in this browser will be replaced.') && resetDocs()}>Reset</button></div>
    </div></section>`;
}
