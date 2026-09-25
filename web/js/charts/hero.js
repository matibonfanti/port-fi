import { html, useRef, useEffect, useWidth, d3 } from '../lib.js';
import { S, set } from '../store.js';
import { showTip, hideTip } from '../tip.js';
import { u, fmtU, fmtT, axisFormat } from '../format.js';
import { components } from './series.js';

export function HeroChart({ r, mode, tIndex, height = 300, yDomain = null, compact = false }) {
  const wrap = useRef(null), svgRef = useRef(null);
  const W = useWidth(wrap, 800);
  useEffect(() => {
    if (!r) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    const m = { l: S.units === 'usd' ? 62 : 46, r: 12, t: 10, b: 26 };
    const iw = W - m.l - m.r, ih = height - m.t - m.b;
    const g = svg.append('g').attr('transform', `translate(${m.l},${m.t})`);
    const gross = r.position.gross_mv;
    const comps = components(r, mode);
    const T = r.t;
    const rows = T.map((t, i) => Object.fromEntries(comps.map((c) => [c.key, u(c.v[i], gross)])));
    const stack = d3.stack().keys(comps.map((c) => c.key)).offset(d3.stackOffsetDiverging)(rows);
    const total = r.attribution.total.map((v) => u(v, gross));
    const pin = r.attribution.priced_in.map((v) => u(v, gross));
    const x = d3.scaleLinear().domain([0, T[T.length - 1]]).range([0, iw]);
    let lo = d3.min(stack, (s) => d3.min(s, (d) => d[0])), hi = d3.max(stack, (s) => d3.max(s, (d) => d[1]));
    lo = Math.min(lo, d3.min(total), 0); hi = Math.max(hi, d3.max(total), 0);
    const y = d3.scaleLinear().domain(yDomain || [lo, hi]).range([ih, 0]).nice(6);
    const fmtAxis = axisFormat();

    g.append('g').attr('class', 'gridl').call(d3.axisLeft(y).ticks(6).tickSize(-iw).tickFormat(''));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(6).tickFormat(fmtAxis).tickSize(0).tickPadding(6)).call((a) => a.select('.domain').remove());
    const months = Math.round(T[T.length - 1] * 12);
    const step = months <= 6 ? 1 : months <= 12 ? 2 : months <= 24 ? 3 : 6;
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`)
      .call(d3.axisBottom(x).tickValues(d3.range(0, months + 1, step).map((mm) => mm / 12)).tickFormat((d) => fmtT(d)).tickSize(3));
    g.append('line').attr('x1', 0).attr('x2', iw).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--axis)');

    const area = d3.area().x((d, i) => x(T[i])).y0((d) => y(d[0])).y1((d) => y(d[1])).curve(d3.curveMonotoneX);
    stack.forEach((s, k) => {
      g.append('path').attr('d', area(s)).attr('fill', comps[k].color).attr('fill-opacity', 0.78)
        .attr('stroke', 'var(--surface)').attr('stroke-width', 1);
    });
    const line = d3.line().x((d, i) => x(T[i])).y((d) => y(d)).curve(d3.curveMonotoneX);
    if (mode === 'market') {
      g.append('path').attr('d', line(pin)).attr('fill', 'none').attr('stroke', 'var(--surface)').attr('stroke-width', 4);
      g.append('path').attr('d', line(pin)).attr('fill', 'none').attr('stroke', 'var(--orange)').attr('stroke-width', 1.5);
    }
    g.append('path').attr('d', line(total)).attr('fill', 'none').attr('stroke', 'var(--surface)').attr('stroke-width', 5);
    g.append('path').attr('d', line(total)).attr('fill', 'none').attr('stroke', 'var(--ink)').attr('stroke-width', 2);
    const last = total.length - 1;
    g.append('circle').attr('cx', x(T[last])).attr('cy', y(total[last])).attr('r', 4).attr('fill', 'var(--ink)').attr('stroke', 'var(--surface)').attr('stroke-width', 2);
    if (!compact) g.append('text').attr('class', 'lbl ink').attr('x', x(T[last]) - 6).attr('y', y(total[last]) - 8).attr('text-anchor', 'end')
      .attr('font-weight', 600).text(`Total ${fmtU(r.attribution.total[last], { gross })}`);

    // cursor + hover
    const cur = g.append('line').attr('y1', 0).attr('y2', ih).attr('stroke', 'var(--ink-2)').attr('stroke-width', 1)
      .attr('x1', x(T[tIndex ?? last])).attr('x2', x(T[tIndex ?? last]));
    const dot = g.append('circle').attr('r', 4).attr('fill', 'var(--ink)').attr('stroke', 'var(--surface)').attr('stroke-width', 2)
      .attr('cx', x(T[tIndex ?? last])).attr('cy', y(total[tIndex ?? last]));
    const nearest = (mx) => { const t = x.invert(mx); let i = d3.bisectCenter(T, t); return Math.max(0, Math.min(T.length - 1, i)); };
    g.append('rect').attr('width', iw).attr('height', ih).attr('fill', 'transparent').style('cursor', 'crosshair')
      .on('mousemove', (ev) => {
        const i = nearest(d3.pointer(ev)[0]);
        cur.attr('x1', x(T[i])).attr('x2', x(T[i]));
        dot.attr('cx', x(T[i])).attr('cy', y(total[i]));
        const rowsHtml = comps.map((c) => `<tr><td><span class="dot" style="background:${c.color}"></span> ${c.label}</td><td>${fmtU(c.v[i], { gross })}</td></tr>`).join('');
        const extra = mode === 'market' ? `<tr><td>Priced-in</td><td>${fmtU(r.attribution.priced_in[i], { gross })}</td></tr>` : '';
        showTip(`<b>${fmtT(T[i])} · ${r.dates[i]}</b><table>${rowsHtml}${extra}<tr><td><b>Total</b></td><td><b>${fmtU(r.attribution.total[i], { gross })}</b></td></tr></table>`, ev.clientX, ev.clientY);
      })
      .on('mouseleave', () => { hideTip(); cur.attr('x1', x(T[S.tIndex ?? last])).attr('x2', x(T[S.tIndex ?? last])); })
      .on('click', (ev) => { if (!compact) set({ tIndex: nearest(d3.pointer(ev)[0]), activeNode: null }); });
  }, [r, mode, tIndex, W, S.units, height, yDomain]);
  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height=${height} role="img" aria-label="Return over time by component"></svg></div>`;
}

export function HeroLegend({ r, mode }) {
  if (!r) return null;
  const comps = components(r, mode);
  return html`<div class="legend">
    ${comps.map((c) => html`<span class="k" data-tip=${c.tip}><span class="sw" style=${`background:${c.color}`}></span>${c.label}</span>`)}
    ${mode === 'market' && html`<span class="k" data-tip="priced_in"><span class="ln" style="background:var(--orange)"></span>Priced-in</span>`}
    <span class="k" data-tip="total"><span class="ln" style="background:var(--ink)"></span>Total</span>
  </div>`;
}
