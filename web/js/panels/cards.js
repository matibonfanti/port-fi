import { html, useEffect, useRef, useState } from '../lib.js';
import { S, set, setPref, analyze, focusStep } from '../store.js';
import { CurvesChart } from '../charts/curves.js';
import { HeroChart, HeroLegend } from '../charts/hero.js';
import { Waterfall, waterfallItems } from '../charts/waterfall.js';
import { Heatmap } from '../charts/heatmap.js';
import { TimingChart, DistChart, KrdChart, TIMING_COLORS } from '../charts/small.js';
import { PresetStrip } from './builder.js';
import { fmtU, fmtT, fmtBp, fmtSigned, fmtNum, fmtRate, fmtUsd, unitLabel, KEYL } from '../format.js';

const Seg = ({ value, options, onChange }) => html`<span class="seg">${options.map(([v, l]) =>
  html`<button class=${value === v ? 'on' : ''} onClick=${() => onChange(v)}>${l}</button>`)}</span>`;

// ---------------------------------------------------------------- guided steps + data notes
export function Steps({ r }) {
  const p = S.position, v = S.view;
  const fin = p?.financing || {};
  const inf = r?.inflation;
  const infTxt = !inf ? 'n/a before 2003' : { priced: 'as priced', unchanged: 'unchanged', expectations: 'your CPI path', nodes: 'your breakeven curve' }[inf.mode] || inf.mode;
  const steps = [
    [1, 'Position', p?.name],
    [2, 'Horizon & return', `${fmtT(S.horizon)} · ${fin.basis === 'total' ? 'holding-period' : 'over financing'} · ${fin.mode === 'implied' ? 'implied rate' : (+fin.rate_pct).toFixed(2) + '%'}`],
    [3, 'Rates view', (v?.name || '') + (S.viewDirty ? ' *' : '')],
    [4, 'Inflation view', infTxt],
    [5, 'Target', `${(+S.targetPct).toFixed(2)}% a year`],
  ];
  const warns = (r?.flags || []).filter((f) => f.level === 'warn');
  const infos = (r?.flags || []).filter((f) => f.level !== 'warn');
  const [open, setOpen] = useState(false);
  const go = (k) => {
    if (k === 4) set({ builderTab: 'inflation', curveMode: S.curveMode === 'nominal' && r?.inflation ? 'be' : S.curveMode });
    if (k === 3 && S.builderTab === 'inflation') set({ builderTab: 'nodes', curveMode: 'nominal' });
    focusStep(k === 4 ? 3 : k);
  };
  return html`<div class="steps">
    ${S.showGuide && html`<div class="guide"><b>How to use:</b> set these five inputs in order — everything below updates live.
      Drag points on the curve chart to state your view; the results show where the return comes from and what the market has to do.
      <button class="btn ghost sm" onClick=${() => setPref({ showGuide: false }, false)}>Got it</button></div>`}
    <div class="stepbar">${steps.map(([k, lab, val]) => html`<button class="step" onClick=${() => go(k)}>
      <span class="stepno">${k}</span><span class="col" style="gap:0;align-items:flex-start;min-width:0"><span class="lab">${lab}</span><span class="val">${val}</span></span></button>`)}
      <span class="step res"><span class="stepno">→</span><span class="col" style="gap:0;align-items:flex-start"><span class="lab">Result</span>
        <span class="val">${r ? fmtU(r.attribution.total[r.t.length - 1]) : '…'} over ${fmtT(S.horizon)}</span></span></span>
    </div>
    ${(warns.length > 0 || infos.length > 0) && html`<div class="flags">
      ${warns.map((f) => html`<div class="flag warn"><span class="ic" aria-label="warning">⚠</span><b>Data</b> ${f.msg}</div>`)}
      ${infos.length > 0 && html`<button class="btn ghost sm" onClick=${() => setOpen(!open)}>ⓘ ${infos.length} data note${infos.length > 1 ? 's' : ''} ${open ? '▴' : '▾'}</button>`}
      ${open && infos.map((f) => html`<div class="flag info"><span class="ic" aria-label="note">ⓘ</span>${f.msg}</div>`)}
    </div>`}
  </div>`;
}

// ---------------------------------------------------------------- KPI strip
export function Kpis({ r }) {
  const a = r.attribution, n = r.t.length - 1, g = r.position.gross_mv;
  const be = r.breakevens.today.parallel, bs = r.breakevens.today.slope;
  const beF = r.breakevens.forwards.parallel;
  const total = r.return_basis === 'total';
  const k = [
    { lab: `${total ? 'Holding-period return' : 'Excess return'} · ${fmtT(r.horizon)}`, val: fmtU(a.total[n]), det: S.units === 'usd' ? fmtBp(a.total[n] / g * 1e4) : `$${Math.round(a.total[n]).toLocaleString()} as sized`, tip: 'total', hero: true },
    { lab: 'If curve unchanged', val: fmtU(a.carry[n] + a.roll[n]), det: `carry ${fmtU(a.carry[n])} · roll ${fmtU(a.roll[n])}`, tip: 'carry' },
    { lab: 'Priced-in', val: fmtU(a.priced_in[n]), det: `forwards' move ${fmtU(a.priced.total[n])}`, tip: 'priced_in' },
    { lab: 'View vs forwards', val: fmtU(a.edge.total[n] + a.spread[n] + a.inflation[n]), det: 'what your view adds', tip: 'edge' },
    be != null
      ? { lab: 'Break-even (parallel)', val: `${be > 0 ? '+' : '−'}${Math.abs(be).toFixed(0)}bp`, det: `vs fwds ${beF != null ? fmtSigned(beF, 0, 'bp') : 'n/a'}`, tip: 'breakeven_parallel' }
      : { lab: 'Break-even (slope)', val: bs != null ? fmtSigned(bs, 0, 'bp') : 'none', det: 'level-neutral position', tip: 'breakeven_slope' },
    { lab: 'Horizon 1σ', val: '±' + fmtU(r.risk.sigma, { sign: false }), det: r.risk.mc ? `P(loss) ${(r.risk.mc.p_loss * 100).toFixed(0)}%` : '', tip: 'sigma' },
    { lab: 'Return / vol', val: r.risk.ratio != null ? fmtNum(r.risk.ratio, 2) : '–', det: `ann. ${r.risk.ratio_ann != null ? fmtNum(r.risk.ratio_ann, 2) : '–'}`, tip: 'ratio' },
  ];
  return html`<section class="card s12"><div class="kpis">${k.map((x) => html`<div class="kpi" data-tip=${x.tip}>
    <div class="lab">${x.lab}</div><div class=${'val num' + (x.hero ? ' hero' : '')}>${x.val}</div><div class="det">${x.det}</div></div>`)}</div></section>`;
}

// ---------------------------------------------------------------- curves + slider
export function CurvesCard({ r }) {
  const timer = useRef(null);
  const i = S.tIndex ?? r.t.length - 1;
  const layer = r.inflation ? S.curveMode : 'nominal';
  const node = layer === 'nominal' && S.activeNode != null ? r.nodes[S.activeNode] : layer === 'be' && S.activeBeNode != null ? (r.inflation?.nodes || [])[S.activeBeNode] : null;
  const t = node ? node.t : r.t[i];
  const play = () => {
    if (S.playing) { clearInterval(timer.current); set({ playing: false }); return; }
    set({ playing: true, activeNode: null, activeBeNode: null, tIndex: S.tIndex >= r.t.length - 1 ? 0 : S.tIndex });
    timer.current = setInterval(() => {
      if (S.tIndex >= S.result.t.length - 1) { clearInterval(timer.current); set({ playing: false }); return; }
      set({ tIndex: S.tIndex + 1 });
    }, 60);
  };
  useEffect(() => () => clearInterval(timer.current), []);
  const nodes = layer === 'be' ? (r.inflation?.nodes || []) : (S.view.builder?.type === 'policy' ? [] : r.view.nodes || []);
  const H = r.horizon;
  const date = new Date(Date.parse(r.asof) + t * 365 * 864e5).toISOString().slice(0, 10);
  const names = { nominal: ['zero rates (cc)', 'Market-implied @ t', 'Yours @ t'], real: ['real zero rates = nominal − breakeven', 'Market-implied @ t', 'Yours @ t'],
                  be: ['breakeven inflation (cc)', 'Priced (forward BE) @ t', 'Yours @ t'] }[layer];
  return html`<section class="card s7">
    <header><h2>Curves</h2><span class="sub">${names[0]} · ${r.asof}</span><span class="sep"></span>
      ${r.inflation && html`<${Seg} value=${layer} options=${[['nominal', 'Nominal'], ['real', 'Real'], ['be', 'Breakeven']]}
        onChange=${(v) => set({ curveMode: v, builderTab: v === 'be' ? 'inflation' : S.builderTab === 'inflation' ? 'nodes' : S.builderTab })}/>`}
      <div class="legend">
        <span class="k" data-tip="today"><span class="ln" style="background:var(--today)"></span>Today</span>
        <span class="k" data-tip="fwd"><span class="ln" style="background:var(--orange)"></span>${names[1]}</span>
        <span class="k" data-tip="yours"><span class="ln" style="background:var(--blue)"></span>${names[2]}</span>
        ${layer !== 'be' && html`<span class="k"><span class="dot" style="background:var(--ink)"></span>long <span class="dot" style="border:2px solid var(--ink);width:9px;height:9px"></span>short</span>`}
      </div></header>
    <div class="body">
      <${CurvesChart} r=${r} tIndex=${i} activeNode=${S.activeNode} activeBeNode=${S.activeBeNode} layer=${layer}/>
      <div class="slider">
        <button class="play" onClick=${play} title=${S.playing ? 'Pause' : 'Play the path'} aria-label="Play">${S.playing ? '❚❚' : '▶'}</button>
        <div style="flex:1;position:relative">
          <input type="range" min="0" max=${r.t.length - 1} value=${i} style="width:100%"
            onInput=${(e) => set({ tIndex: +e.target.value, activeNode: null, activeBeNode: null })} aria-label="Scenario date"/>
          <div style="position:relative;height:8px">${nodes.filter((n) => n.t <= H + 1e-9).map((n) => html`<span style=${`position:absolute;left:calc(${(n.t / H) * 100}% - 3px);top:0;width:6px;height:6px;border-radius:50%;background:var(--blue)`} title=${'your curve set at ' + fmtT(n.t)}></span>`)}</div>
        </div>
        <span class="tlabel">today → <b>${fmtT(t)}</b> · ${date}${node ? ' · editing' : ''}</span>
      </div>
      ${layer === 'nominal' && html`<div style="margin-top:6px"><${PresetStrip}/></div>`}
      <div class="muted" style="margin-top:4px">${layer === 'real' ? 'The real curve is derived (nominal − breakeven): edit the nominal or breakeven layer.'
        : 'Drag any point to set your curve at the date shown (a date is added if needed); moves snap to 1bp. Dots show each bond sliding down the curve as it ages.'}</div>
    </div></section>`;
}

// ---------------------------------------------------------------- hero, waterfall
export function HeroCard({ r }) {
  return html`<section class="card s8">
    <header><h2>Return over time</h2><span class="sub">${unitLabel()}</span><span class="sep"></span>
      <${Seg} value=${S.attrMode} options=${[['today', 'vs unchanged curve'], ['market', 'Priced-in + view']]} onChange=${(v) => setPref({ attrMode: v }, false)}/></header>
    <div class="body"><${HeroLegend} r=${r} mode=${S.attrMode}/>
      <${HeroChart} r=${r} mode=${S.attrMode} tIndex=${S.tIndex}/>
      <div class="muted">Click the chart to move the curve slider. Components sum exactly to the total (max identity error ${Math.max(...Object.values(r.identity)).toExponential(1)} $).</div></div></section>`;
}

export function WaterfallCard({ r }) {
  const opts = [['bucket', 'Key rates'], ['factor', 'Factors']];
  if (r.inflation) opts.push(['realbe', 'Real / BE']);
  const split = opts.some(([k]) => k === S.waterfallMode) ? S.waterfallMode : 'factor';
  const items = waterfallItems(r, S.attrMode, split, r.t.length - 1);
  return html`<section class="card s4 last">
    <header><h2>Where the return comes from</h2><span class="sub">at horizon</span><span class="sep"></span>
      <${Seg} value=${split} options=${opts} onChange=${(v) => setPref({ waterfallMode: v }, false)}/></header>
    <div class="body"><${Waterfall} r=${r} mode=${S.attrMode} split=${split}/>
      <details><summary class="muted" style="cursor:pointer">Table view</summary>
        <table class="t"><tbody>${items.map((it) => html`<tr class=${it.total ? 'tot' : ''}><td data-tip=${it.tip}>${it.label}</td><td>${fmtU(it.v)}</td></tr>`)}</tbody></table></details>
    </div></section>`;
}

// ---------------------------------------------------------------- inverse: what has to happen?
export function InverseCard({ r }) {
  const inv = r.inverse;
  const real = r.position.has_real;
  const why = (m) => (m.reason === 'always' ? html`<span class="muted" title="Met for every move tried">always met</span>`
    : html`<span class="muted" title="No move in the range tried reaches it">not reachable</span>`);
  const bp = (m) => (m.ok ? fmtSigned(m.x, 0, 'bp') : why(m));
  const rows = inv.targets;
  const lv = inv.report_tenors.map((x) => `${x}Y`);
  const tenIdx = 2;
  const worst = Math.max(0, ...rows.flatMap((t) => Object.values(t.moves).filter((m) => m.ok).map((m) => Math.abs(m.residual))));
  return html`<section class=${'card s7' + (S.focusStep === 5 ? ' focus' : '')}>
    <header><span class="stepno">5</span><h2>What has to happen?</h2><span class="sub">market outcome needed at ${fmtT(r.horizon)} · ${r.return_basis === 'total' ? 'holding-period return' : 'excess over financing'}</span></header>
    <div class="body col">
      <div class="scroll-x"><table class="t">
        <thead><tr><th>To…</th><th data-tipt="Parallel move of today's curve at the horizon (everything else as today)">Parallel vs today</th>
          <th data-tipt="Parallel move of the forward curve at the horizon">vs forwards</th>
          <th data-tip="room">Room vs your view</th><th data-tip="view_fraction">Share of your view</th><th data-tip="latest">Latest it can happen</th>
          ${real && html`<th data-tip="cpi">CPI needed</th><th data-tipt="Parallel breakeven move vs your view needed">BE vs view</th>`}</tr></thead>
        <tbody>${rows.map((t) => {
          const m = t.moves, vf = m.view_fraction;
          return html`<tr><td><b>${t.label}</b><div class="muted">${fmtU(t.value)}</div></td>
            <td>${bp(m.parallel_today)}${m.parallel_today.ok ? html`<div class="muted">10Y ${fmtRate(m.parallel_today.levels[tenIdx])}</div>` : ''}</td>
            <td>${bp(m.parallel_fwd)}</td>
            <td>${bp(m.parallel_view)}</td>
            <td>${vf.ok ? `${(vf.x * 100).toFixed(0)}%` : why(vf)}</td>
            <td>${vf.ok ? (vf.latest_t == null ? html`<span class="muted">any time</span>` : vf.x > 1 ? html`<span class="muted">needs more than your view</span>` : fmtT(vf.latest_t)) : '–'}</td>
            ${real && html`<td>${m.cpi.ok ? `${m.cpi.x.toFixed(2)}%` : why(m.cpi)}</td><td>${bp(m.be_view)}</td>`}</tr>`;
        })}</tbody></table></div>
      <div class="scroll-x"><table class="t">
        <thead><tr><th>Zero rate at horizon, %</th>${lv.map((l) => html`<th>${l}</th>`)}</tr></thead>
        <tbody>
          <tr><td>Today</td>${inv.levels_today.map((x) => html`<td>${x.toFixed(2)}</td>`)}</tr>
          <tr><td>Priced (forwards)</td>${inv.levels_fwd.map((x) => html`<td>${x.toFixed(2)}</td>`)}</tr>
          <tr><td>Your view</td>${inv.levels_view.map((x) => html`<td><b>${x.toFixed(2)}</b></td>`)}</tr>
          ${rows.map((t) => html`<tr><td>Needed to ${t.label.toLowerCase()} <span class="muted">(parallel)</span></td>${t.moves.parallel_today.ok
            ? t.moves.parallel_today.levels.map((x) => html`<td>${x.toFixed(2)}</td>`) : lv.map(() => html`<td class="muted">–</td>`)}</tr>`)}
        </tbody></table></div>
      <div class="muted">Each answer is solved on the full pricing engine and substituted back (worst residual ${fmtUsd(worst, false)}). "Share of your view" scales your curve change vs today (and your inflation view); "latest" assumes it arrives linearly.</div>
    </div></section>`;
}

export function SummaryCard({ r }) {
  return html`<section class="card s5 summary">
    <header><h2>In plain English</h2><span class="sub">auto-generated · ${r.basis === 'pca' ? 'PCA' : 'parametric'} factors</span></header>
    <div class="body"><div class="headline">${r.summary.headline}</div>
      <ul>${r.summary.sentences.map((s) => html`<li>${s}</li>`)}</ul></div></section>`;
}

// ---------------------------------------------------------------- break-even map
export function BreakevenCard({ r, stale }) {
  const be = r.breakevens, cv = r.cover;
  const f = (x, why) => (x == null ? html`<span class="muted">${why === 'always' ? 'never loses' : 'none'}</span>` : fmtSigned(x, 0, 'bp'));
  return html`<section class=${'card s4' + (stale ? ' stale' : '')}>
    <header><h2>Break-even map</h2><span class="sub">return over Δlevel × Δslope</span><span class="sep"></span>
      <${Seg} value=${S.heatBase} options=${[['today', 'vs today'], ['forwards', 'vs fwds']]} onChange=${(v) => setPref({ heatBase: v })}/></header>
    <div class="body">
      <${Heatmap} r=${r}/>
      <div class="legend" style="margin:4px 0 6px"><span class="k"><span class="sw" style="background:#6da7ec"></span>gain</span>
        <span class="k"><span class="sw" style="background:#ec7876"></span>loss</span><span class="k"><span class="ln" style="background:var(--ink)"></span>break even</span>
        ${r.return_basis === 'total' && html`<span class="k"><span class="ln" style="background:var(--ink-2)"></span>beat cash</span>`}
        <span class="k"><span class="ln" style="background:var(--violet)"></span>target</span></div>
      <table class="t"><thead><tr><th>Zero-return move at horizon</th><th>vs today</th><th>vs forwards</th></tr></thead><tbody>
        <tr><td data-tip="breakeven_parallel">Parallel</td><td>${f(be.today.parallel, be.today.parallel_reason)}</td><td>${f(be.forwards.parallel, be.forwards.parallel_reason)}</td></tr>
        <tr><td data-tip="breakeven_slope">Slope (2s10s)</td><td>${f(be.today.slope, be.today.slope_reason)}</td><td>${f(be.forwards.slope, be.forwards.slope_reason)}</td></tr></tbody></table>
      <div class="row wrap" style="margin-top:6px"><span data-tip="cover">Carry + roll cover a</span>
        <input type="number" step="5" min="1" value=${S.coverMove} onChange=${(e) => { set({ coverMove: +e.target.value }); analyze(); }}/>
        <span>bp adverse ${cv.kind} move after <b>${cv.t_star != null ? fmtT(cv.t_star) : `> ${fmtT(r.horizon)}`}</b></span></div>
    </div></section>`;
}

export function TimingCard({ r, stale }) {
  const tm = r.timing;
  return html`<section class=${'card s4' + (stale ? ' stale' : '')}>
    <header><h2 data-tip="timing">Timing</h2><span class="sub">same end-state, reached early vs late</span></header>
    <div class="body">${!tm ? html`<div class="empty">computing…</div>` : html`
      <div class="legend">${tm.profiles.map((p) => html`<span class="k"><span class="ln" style=${`background:${TIMING_COLORS[p.key]}`}></span>${p.label}</span>`)}</div>
      <${TimingChart} r=${r}/>
      <table class="t"><thead><tr><th>Profile</th><th data-tip="realised">Exit on realisation</th><th>At horizon</th><th data-tip="drawdown">Max DD</th></tr></thead>
        <tbody>${tm.profiles.map((p) => html`<tr><td>${p.label}</td>
          <td>${p.realised_t != null ? html`${fmtU(p.pnl_at_realisation)} <span class="muted">@${fmtT(p.realised_t)} (${fmtSigned(p.ann_bp_if_exit / 100, 2, '%')}/yr)</span>` : html`<span class="muted">–</span>`}</td>
          <td>${fmtU(p.pnl_H)}</td><td>${fmtU(p.max_drawdown)}</td></tr>`)}</tbody></table>
      <div class="muted" style="margin-top:4px">${tm.note}</div>`}
    </div></section>`;
}

export function RiskCard({ r, stale }) {
  const rk = r.risk, mc = rk.mc;
  return html`<section class=${'card s4 last' + (stale ? ' stale' : '')}>
    <header><h2>Risk context</h2><span class="sub">historical vol · ${(rk.window || []).join(' → ')}</span></header>
    <div class="body">
      <table class="t"><thead><tr><th>Factor</th><th>Vol/yr</th><th>1σ @H</th><th>+1σ</th><th>−1σ</th></tr></thead><tbody>
        ${rk.factors.map((f, k) => html`<tr><td data-tip=${['level', 'slope', 'curvature', 'breakevens'][k]}>${f.factor}</td><td>${f.vol_ann_bp.toFixed(0)}bp</td><td>${f.sigma_bp.toFixed(0)}bp</td>
          <td class=${f.up >= 0 ? 'pos' : 'neg'}>${fmtU(f.up)}</td><td class=${f.down >= 0 ? 'pos' : 'neg'}>${fmtU(f.down)}</td></tr>`)}
        <tr class="tot"><td data-tip="sigma">Total 1σ</td><td></td><td></td><td colspan="2">±${fmtU(rk.sigma, { sign: false })} · <span data-tip="ratio">E/σ ${rk.ratio != null ? rk.ratio.toFixed(2) : '–'}</span></td></tr>
      </tbody></table>
      <div class="row" style="margin-top:8px"><b style="font-size:11.5px" data-tip="krd">Key-rate DV01 at horizon</b><span class="muted">$ per +1bp${rk.be_krd ? ' · yellow: breakevens' : ''}</span></div>
      <${KrdChart} krd=${rk.krd} labels=${KEYL} beKrd=${rk.be_krd} beLabels=${(S.market.be_tenors || []).map((x) => x + 'Y')}/>
      <div class="row" style="margin-top:8px"><b style="font-size:11.5px" data-tip="pnl_mc">Distribution around your path</b>
        ${mc && html`<span class="muted">${mc.n.toLocaleString()} sims</span>`}</div>
      ${mc ? html`<${DistChart} r=${r}/>
        <div class="row wrap num" style="gap:12px"><span>mean ${fmtU(mc.mean)}</span><span>5% ${fmtU(mc.pct.p5)}</span><span>95% ${fmtU(mc.pct.p95)}</span>
          <span data-tip="p_loss">P(loss) ${(mc.p_loss * 100).toFixed(0)}%</span></div>`
        : html`<div class="empty">computing…</div>`}
    </div></section>`;
}
