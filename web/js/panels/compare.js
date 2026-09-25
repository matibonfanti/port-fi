import { html, useEffect, useRef, useWidth, d3 } from '../lib.js';
import { S, set, runCompare } from '../store.js';
import { HeroChart, HeroLegend } from '../charts/hero.js';
import { waterfallItems } from '../charts/waterfall.js';
import { components } from '../charts/series.js';
import { fmtU, fmtT, fmtSigned, fmtNum, u, unitLabel } from '../format.js';

function OverlayCurves({ ra, rb, na, nb }) {
  const wrap = useRef(null), svgRef = useRef(null);
  const W = useWidth(wrap, 600);
  useEffect(() => {
    const svg = d3.select(svgRef.current); svg.selectAll('*').remove();
    const m = { l: 42, r: 10, t: 10, b: 24 }, H = 240, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const g = svg.append('g').attr('transform', `translate(${m.l},${m.t})`);
    const tau = ra.curves.tau, n = ra.t.length - 1;
    const series = [
      { v: ra.curves.today, c: 'var(--today)' }, { v: ra.curves.fwd[n], c: 'var(--orange)' },
      { v: ra.curves.user[n], c: 'var(--blue)' }, { v: rb.curves.user[rb.t.length - 1], c: 'var(--violet)' },
    ];
    const all = series.flatMap((s) => s.v);
    const x = d3.scaleSqrt().domain([0, 30]).range([0, iw]);
    const y = d3.scaleLinear().domain(d3.extent(all)).range([ih, 0]).nice();
    g.append('g').attr('class', 'gridl').call(d3.axisLeft(y).ticks(5).tickSize(-iw).tickFormat(''));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(5).tickFormat((d) => d.toFixed(2)).tickSize(0).tickPadding(5)).call((a) => a.select('.domain').remove());
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`).call(d3.axisBottom(x).tickValues([0.25, 1, 2, 5, 10, 20, 30]).tickFormat((d) => d < 1 ? `${d * 12}M` : `${d}Y`).tickSize(3));
    const line = d3.line().x((d, i) => x(tau[i])).y((d) => y(d)).curve(d3.curveMonotoneX);
    series.forEach((s) => g.append('path').attr('d', line(s.v)).attr('fill', 'none').attr('stroke', s.c).attr('stroke-width', 2));
  }, [ra, rb, W]);
  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height="240"></svg></div>`;
}

export function Compare() {
  const c = S.compare;
  const views = c.mode === 'views';
  const list = views ? S.views : S.positions;
  const opts = [{ id: '__working', name: views ? `(working) ${S.view?.name}` : `(working) ${S.position?.name}` }, ...list];
  const nameOf = (id) => opts.find((o) => o.id === id)?.name || '–';
  const { ra, rb } = c;
  let dom = null;
  if (ra && rb) {
    const lo = [], hi = [];
    for (const r of [ra, rb]) {
      const g = r.position.gross_mv;
      const comps = components(r, S.attrMode);
      r.t.forEach((_, i) => {
        let p = 0, q = 0;
        comps.forEach((cc) => { const v = u(cc.v[i], g); if (v > 0) p += v; else q += v; });
        hi.push(p, u(r.attribution.total[i], g)); lo.push(q, u(r.attribution.total[i], g));
      });
    }
    dom = [Math.min(0, ...lo), Math.max(0, ...hi)];
  }
  const rows = ra && rb ? waterfallItems(ra, S.attrMode, S.waterfallMode, ra.t.length - 1).map((it, k) => {
    const jt = waterfallItems(rb, S.attrMode, S.waterfallMode, rb.t.length - 1).find((x) => x.label === it.label);
    return { label: it.label, a: it.v, b: jt ? jt.v : 0, total: it.total, tip: it.tip };
  }) : [];
  const metrics = ra && rb ? [
    ['Break-even parallel vs today', ra.breakevens.today.parallel, rb.breakevens.today.parallel, 'bp'],
    ['Break-even parallel vs fwds', ra.breakevens.forwards.parallel, rb.breakevens.forwards.parallel, 'bp'],
    ['Break-even slope vs today', ra.breakevens.today.slope, rb.breakevens.today.slope, 'bp'],
    ['Horizon 1σ', ra.risk.sigma, rb.risk.sigma, 'u'],
    ['Return / vol', ra.risk.ratio, rb.risk.ratio, 'x'],
    ['Net DV01 ($/bp)', ra.position.dv01, rb.position.dv01, '$'],
  ] : [];
  const fm = (v, k) => v == null ? '–' : k === 'bp' ? fmtSigned(v, 1, 'bp') : k === 'u' ? fmtU(v, { sign: false }) : k === 'x' ? fmtNum(v, 2) : '$' + Math.round(v).toLocaleString();
  return html`<div class="main" style="padding:12px 16px">
    <section class="card s12"><header><h2>Compare</h2><span class="sub">two views on the current position, or two positions under the current view</span></header>
      <div class="body row wrap">
        <span class="seg">${[['views', 'Two views'], ['positions', 'Two positions']].map(([m, l]) => html`<button class=${c.mode === m ? 'on' : ''}
          onClick=${() => set({ compare: { ...c, mode: m, a: (m === 'views' ? S.views : S.positions)[0]?.id, b: (m === 'views' ? S.views : S.positions)[1]?.id, ra: null, rb: null } })}>${l}</button>`)}</span>
        <label class="ctl">A <select value=${c.a} onChange=${(e) => set({ compare: { ...c, a: e.target.value } })}>${opts.map((o) => html`<option value=${o.id}>${o.name}</option>`)}</select></label>
        <label class="ctl">B <select value=${c.b} onChange=${(e) => set({ compare: { ...c, b: e.target.value } })}>${opts.map((o) => html`<option value=${o.id}>${o.name}</option>`)}</select></label>
        <button class="btn primary" onClick=${runCompare} disabled=${c.loading}>${c.loading ? 'Running…' : 'Run comparison'}</button>
        <span class="muted">${views ? `Position: ${S.position?.name}` : `View: ${S.view?.name}`} · horizon ${fmtT(S.horizon)} · ${unitLabel()}</span>
      </div></section>
    ${ra && rb ? html`
      ${[['A', ra, c.a], ['B', rb, c.b]].map(([k, r, id]) => html`<section class="card s6"><header><h2>${k}: ${nameOf(id)}</h2>
          <span class="sub">total ${fmtU(r.attribution.total[r.t.length - 1])}</span></header>
        <div class="body"><${HeroLegend} r=${r} mode=${S.attrMode}/><${HeroChart} r=${r} mode=${S.attrMode} tIndex=${r.t.length - 1} height=${240} yDomain=${dom} compact=${true}/>
          <div class="summary" style="margin-top:6px"><div class="headline">${r.summary.headline}</div><ul>${r.summary.sentences.slice(0, 4).map((s) => html`<li>${s}</li>`)}</ul></div></div></section>`)}
      <section class="card s6"><header><h2>Attribution at horizon</h2><span class="sub">${S.attrMode === 'market' ? 'priced-in + edge' : 'vs today'} · ${S.waterfallMode === 'bucket' ? 'key rates' : 'factors'}</span></header>
        <div class="body"><table class="t"><thead><tr><th></th><th>A</th><th>B</th><th>B − A</th></tr></thead><tbody>
          ${rows.map((x) => html`<tr class=${x.total ? 'tot' : ''}><td data-tip=${x.tip}>${x.label}</td><td>${fmtU(x.a, { gross: ra.position.gross_mv })}</td>
            <td>${fmtU(x.b, { gross: rb.position.gross_mv })}</td><td>${views ? fmtU(x.b - x.a, { gross: ra.position.gross_mv }) : html`<span class="muted">n/a</span>`}</td></tr>`)}
          ${metrics.map(([l, a, b, k]) => html`<tr><td>${l}</td><td>${fm(a, k)}</td><td>${fm(b, k)}</td><td>${a != null && b != null && k !== 'u' ? fm(b - a, k) : ''}</td></tr>`)}
        </tbody></table>${!views && html`<div class="muted" style="margin-top:4px">bp for each position are relative to its own gross MV.</div>`}</div></section>
      <section class="card s6"><header><h2>Curves at horizon</h2></header><div class="body">
        <div class="legend"><span class="k"><span class="ln" style="background:var(--today)"></span>Today</span><span class="k"><span class="ln" style="background:var(--orange)"></span>Forwards</span>
          <span class="k"><span class="ln" style="background:var(--blue)"></span>A</span><span class="k"><span class="ln" style="background:var(--violet)"></span>B</span></div>
        <${OverlayCurves} ra=${ra} rb=${rb}/></div></section>`
    : html`<section class="card s12"><div class="empty">Pick A and B, then run the comparison.</div></section>`}
  </div>`;
}
