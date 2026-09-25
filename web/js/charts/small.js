// Timing lines, outcome distribution and the policy-rate path chart.
import { html, useRef, useEffect, useWidth, d3 } from '../lib.js';
import { S } from '../store.js';
import { showTip, hideTip } from '../tip.js';
import { u, fmtU, fmtT, axisFormat, fmtUsd } from '../format.js';

export const TIMING_COLORS = { your_path: 'var(--blue)', immediate: '#184f95', early: '#3f6fa8', linear: '#7c8aa0', late: '#b3b1a8' };
export const TIMING_WIDTH = { your_path: 2.5 };

function frame(svgRef, W, H, m) {
  const svg = d3.select(svgRef.current);
  svg.selectAll('*').remove();
  const g = svg.append('g').attr('transform', `translate(${m.l},${m.t})`);
  return { g, iw: W - m.l - m.r, ih: H - m.t - m.b };
}

export function TimingChart({ r, height = 220 }) {
  const wrap = useRef(null), svgRef = useRef(null);
  const W = useWidth(wrap, 400);
  useEffect(() => {
    const tm = r?.timing;
    if (!tm) return;
    const gross = r.position.gross_mv;
    const { g, iw, ih } = frame(svgRef, W, height, { l: S.units === 'usd' ? 58 : 44, r: 10, t: 8, b: 24 });
    const T = r.t;
    const series = tm.profiles.map((p) => ({ ...p, v: p.total.map((x) => u(x, gross)) }));
    const x = d3.scaleLinear().domain([0, T[T.length - 1]]).range([0, iw]);
    const all = series.flatMap((s) => s.v);
    const y = d3.scaleLinear().domain([Math.min(0, d3.min(all)), Math.max(0, d3.max(all))]).range([ih, 0]).nice(5);
    g.append('g').attr('class', 'gridl').call(d3.axisLeft(y).ticks(5).tickSize(-iw).tickFormat(''));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(5).tickFormat(axisFormat()).tickSize(0).tickPadding(5)).call((a) => a.select('.domain').remove());
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`).call(d3.axisBottom(x).ticks(6).tickFormat(fmtT).tickSize(3));
    g.append('line').attr('x1', 0).attr('x2', iw).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--axis)');
    const line = d3.line().x((d, i) => x(T[i])).y((d) => y(d)).curve(d3.curveMonotoneX);
    [...series].reverse().forEach((s) => g.append('path').attr('d', line(s.v)).attr('fill', 'none')
      .attr('stroke', TIMING_COLORS[s.key]).attr('stroke-width', TIMING_WIDTH[s.key] || 1.75));
    const cur = g.append('line').attr('y1', 0).attr('y2', ih).attr('stroke', 'var(--axis)').attr('opacity', 0);
    g.append('rect').attr('width', iw).attr('height', ih).attr('fill', 'transparent')
      .on('mousemove', (ev) => {
        const i = Math.max(0, Math.min(T.length - 1, d3.bisectCenter(T, x.invert(d3.pointer(ev)[0]))));
        cur.attr('x1', x(T[i])).attr('x2', x(T[i])).attr('opacity', 1);
        showTip(`<b>${fmtT(T[i])}</b><table>${series.map((s) => `<tr><td><span class="dot" style="background:${TIMING_COLORS[s.key]}"></span> ${s.label}</td><td>${fmtU(s.total[i], { gross })}</td></tr>`).join('')}</table>`, ev.clientX, ev.clientY);
      })
      .on('mouseleave', () => { cur.attr('opacity', 0); hideTip(); });
  }, [r?.timing, W, S.units, height]);
  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height=${height} role="img" aria-label="P&L path by timing of the view"></svg></div>`;
}

export function DistChart({ r, height = 150 }) {
  const wrap = useRef(null), svgRef = useRef(null);
  const W = useWidth(wrap, 400);
  useEffect(() => {
    const mc = r?.risk?.mc;
    if (!mc) return;
    const gross = r.position.gross_mv;
    const { g, iw, ih } = frame(svgRef, W, height, { l: 10, r: 10, t: 14, b: 22 });
    const e = mc.edges.map((v) => u(v, gross));
    const x = d3.scaleLinear().domain([e[0], e[e.length - 1]]).range([0, iw]);
    const y = d3.scaleLinear().domain([0, d3.max(mc.hist)]).range([ih, 0]);
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`).call(d3.axisBottom(x).ticks(6).tickFormat(axisFormat()).tickSize(3));
    mc.hist.forEach((c, k) => {
      const x0 = x(e[k]) + 1, x1 = x(e[k + 1]) - 1;
      g.append('rect').attr('x', x0).attr('width', Math.max(1, x1 - x0)).attr('y', y(c)).attr('height', ih - y(c))
        .attr('fill', e[k + 1] <= 0 ? 'var(--red)' : 'var(--blue)').attr('opacity', 0.8);
    });
    const vline = (v, lab, strong) => {
      const xx = x(u(v, gross));
      g.append('line').attr('x1', xx).attr('x2', xx).attr('y1', -4).attr('y2', ih).attr('stroke', strong ? 'var(--ink)' : 'var(--ink-2)').attr('stroke-width', strong ? 1.5 : 1);
      g.append('text').attr('class', 'lbl ink2').attr('x', xx).attr('y', -6).attr('text-anchor', 'middle').text(lab);
    };
    vline(mc.pct.p5, '5%'); vline(mc.pct.p95, '95%'); vline(mc.mean, 'mean', true);
    g.append('rect').attr('width', iw).attr('height', ih).attr('fill', 'transparent')
      .on('mousemove', (ev) => {
        const v = x.invert(d3.pointer(ev)[0]);
        const k = Math.max(0, Math.min(mc.hist.length - 1, d3.bisectRight(e, v) - 1));
        showTip(`${fmtU(mc.edges[k], { gross })} to ${fmtU(mc.edges[k + 1], { gross })}<br><b>${(mc.hist[k] / mc.n * 100).toFixed(1)}%</b> of ${mc.n} paths`, ev.clientX, ev.clientY);
      })
      .on('mouseleave', hideTip);
  }, [r?.risk?.mc, W, S.units, height]);
  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height=${height} role="img" aria-label="Distribution of horizon P&L"></svg></div>`;
}

export function PolicyChart({ report, horizon, height = 190 }) {
  const wrap = useRef(null), svgRef = useRef(null);
  const W = useWidth(wrap, 400);
  useEffect(() => {
    if (!report) return;
    const { g, iw, ih } = frame(svgRef, W, height, { l: 38, r: 10, t: 8, b: 22 });
    const c = report.chart;
    const x = d3.scaleLinear().domain([0, c.s[c.s.length - 1]]).range([0, iw]);
    const all = [...c.mkt, ...c.user, ...c.fwd];
    const y = d3.scaleLinear().domain([d3.min(all) - 0.1, d3.max(all) + 0.1]).range([ih, 0]).nice(5);
    g.append('g').attr('class', 'gridl').call(d3.axisLeft(y).ticks(5).tickSize(-iw).tickFormat(''));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(5).tickFormat((d) => d.toFixed(2)).tickSize(0).tickPadding(5)).call((a) => a.select('.domain').remove());
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`).call(d3.axisBottom(x).ticks(6).tickFormat(fmtT).tickSize(3));
    g.append('rect').attr('x', x(horizon)).attr('width', Math.max(0, iw - x(horizon))).attr('height', ih).attr('fill', 'var(--surface-2)').attr('opacity', 0.7);
    const step = d3.line().x((d, i) => x(c.s[i])).y((d) => y(d)).curve(d3.curveStepAfter);
    const smooth = d3.line().x((d, i) => x(c.s[i])).y((d) => y(d));
    g.append('path').attr('d', smooth(c.fwd)).attr('fill', 'none').attr('stroke', 'var(--orange)').attr('stroke-width', 1).attr('opacity', 0.5);
    g.append('path').attr('d', step(c.mkt)).attr('fill', 'none').attr('stroke', 'var(--orange)').attr('stroke-width', 2);
    g.append('path').attr('d', step(c.user)).attr('fill', 'none').attr('stroke', 'var(--blue)').attr('stroke-width', 2);
    report.meetings.forEach((mt) => {
      if (mt.t > c.s[c.s.length - 1]) return;
      g.append('line').attr('x1', x(mt.t)).attr('x2', x(mt.t)).attr('y1', ih).attr('y2', ih - 4).attr('stroke', 'var(--axis)');
    });
    g.append('rect').attr('width', iw).attr('height', ih).attr('fill', 'transparent')
      .on('mousemove', (ev) => {
        const i = Math.max(0, Math.min(c.s.length - 1, d3.bisectCenter(c.s, x.invert(d3.pointer(ev)[0]))));
        showTip(`<b>${fmtT(c.s[i])}</b><table><tr><td>Priced (step)</td><td>${c.mkt[i].toFixed(3)}%</td></tr><tr><td>Yours</td><td>${c.user[i].toFixed(3)}%</td></tr><tr><td>Inst. forward</td><td>${c.fwd[i].toFixed(3)}%</td></tr></table>`, ev.clientX, ev.clientY);
      })
      .on('mouseleave', hideTip);
  }, [report, W, height, horizon]);
  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height=${height} role="img" aria-label="Policy-rate path: market-implied vs yours"></svg></div>`;
}


/** Key-rate DV01 bars ($ per +1bp at each key tenor; tents). Negative = loses when that rate rises. */
export function KrdChart({ krd, labels, beKrd, beLabels, height = 150 }) {
  const wrap = useRef(null), svgRef = useRef(null);
  const W = useWidth(wrap, 400);
  useEffect(() => {
    if (!krd) return;
    const items = labels.map((l, j) => ({ l, v: krd[j], be: false }));
    if (beKrd) beLabels.forEach((l, j) => items.push({ l: 'BE ' + l, v: beKrd[j], be: true }));
    const { g, iw, ih } = frame(svgRef, W, height, { l: 48, r: 8, t: 8, b: 22 });
    const x = d3.scaleBand().domain(items.map((d, k) => k)).range([0, iw]).padding(0.3);
    const ext = d3.max(items, (d) => Math.abs(d.v)) || 1;
    const y = d3.scaleLinear().domain([-ext, ext]).range([ih, 0]).nice(4);
    g.append('g').attr('class', 'gridl').call(d3.axisLeft(y).ticks(4).tickSize(-iw).tickFormat(''));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(4).tickFormat(d3.format('$~s')).tickSize(0).tickPadding(4)).call((a) => a.select('.domain').remove());
    g.append('line').attr('x1', 0).attr('x2', iw).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--axis)');
    const bw = Math.min(18, x.bandwidth());
    items.forEach((d, k) => {
      const cx = x(k) + x.bandwidth() / 2;
      g.append('rect').attr('x', cx - bw / 2).attr('width', bw).attr('y', Math.min(y(0), y(d.v))).attr('height', Math.max(1, Math.abs(y(d.v) - y(0))))
        .attr('rx', 2).attr('fill', d.be ? 'var(--yellow)' : 'var(--blue)');
      g.append('text').attr('class', 'lbl').attr('x', cx).attr('y', ih + 14).attr('text-anchor', 'middle').attr('font-size', 9.5).text(d.l);
      g.append('rect').attr('x', x(k)).attr('width', x.bandwidth()).attr('height', ih).attr('fill', 'transparent')
        .on('mousemove', (ev) => showTip(`<b>${d.l}</b> ${fmtUsd(d.v)} per +1bp`, ev.clientX, ev.clientY)).on('mouseleave', hideTip);
    });
  }, [krd, beKrd, W, height]);
  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height=${height} role="img" aria-label="Key-rate DV01 profile"></svg></div>`;
}
