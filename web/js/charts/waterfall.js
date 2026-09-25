import { html, useRef, useEffect, useWidth, d3 } from '../lib.js';
import { S } from '../store.js';
import { showTip, hideTip } from '../tip.js';
import { u, fmtU, axisFormat } from '../format.js';

export function waterfallItems(r, mode, split, i) {
  const a = r.attribution;
  const at = (arr) => arr[i];
  const items = [
    { label: r.return_basis === 'total' ? 'Coupon & pull-to-par' : 'Carry', v: at(a.carry), tip: 'carry' },
    { label: 'Roll-down', v: at(a.roll), tip: 'roll' },
  ];
  const part = mode === 'market' ? a.edge : a.curve;
  if (mode === 'market') {
    items.push({ label: 'Priced-in move', v: at(a.priced.total), tip: 'priced_move' });
    items.push({ label: 'Priced-in', v: at(a.priced_in), total: true, tip: 'priced_in' });
  }
  const pre = mode === 'market' ? 'View ' : '';
  if (split === 'realbe') {
    items.push({ label: pre + 'real yields', v: part.fo_real[i], tip: 'real_rates', group: 'curve' });
    items.push({ label: pre + 'breakevens', v: part.fo_be[i], tip: 'breakevens', group: 'curve' });
  } else if (split === 'bucket') {
    const labs = S.market.key_labels;
    const vals = part.buckets[i];
    const mx = Math.max(1e-9, ...vals.map(Math.abs));
    vals.forEach((v, j) => { if (Math.abs(v) > 0.002 * mx) items.push({ label: pre + labs[j], v, tip: 'bucket', group: 'curve' }); });
  } else {
    const names = r.factor.labels;
    const tips = ['level', 'slope', 'curvature'];
    part.factors[i].forEach((v, k) => items.push({ label: pre + names[k], v, tip: tips[k], group: 'curve',
      beta: part.beta[i][k] }));
    items.push({ label: pre + 'other shape', v: part.other[i], tip: 'other_shape', group: 'curve' });
  }
  items.push({ label: 'Convexity / resid.', v: part.convexity[i] + part.residual[i], tip: 'convexity' });
  if (a.inflation.some((x) => Math.abs(x) > 1e-6)) items.push({ label: 'Inflation vs priced', v: at(a.inflation), tip: 'inflation' });
  if (a.spread.some((x) => Math.abs(x) > 1e-6)) items.push({ label: 'Spread', v: at(a.spread), tip: 'spread' });
  items.push({ label: 'Total', v: at(a.total), total: true, tip: 'total' });
  return items;
}

export function Waterfall({ r, mode, split, index, height = 280 }) {
  const wrap = useRef(null), svgRef = useRef(null);
  const W = useWidth(wrap, 400);
  useEffect(() => {
    if (!r) return;
    const i = index ?? r.t.length - 1;
    const gross = r.position.gross_mv;
    const items = waterfallItems(r, mode, split, i);
    let run = 0;
    const bars = items.map((it) => {
      const v = u(it.v, gross);
      if (it.total) { run = u(it.v, gross); return { ...it, y0: 0, y1: run, uv: v }; }
      const b = { ...it, y0: run, y1: run + v, uv: v };
      run += v;
      return b;
    });
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    const m = { l: S.units === 'usd' ? 58 : 44, r: 8, t: 14, b: 66 };
    const iw = W - m.l - m.r, ih = height - m.t - m.b;
    const g = svg.append('g').attr('transform', `translate(${m.l},${m.t})`);
    const x = d3.scaleBand().domain(bars.map((b, k) => k)).range([0, iw]).padding(0.25);
    const lo = Math.min(0, d3.min(bars, (b) => Math.min(b.y0, b.y1))), hi = Math.max(0, d3.max(bars, (b) => Math.max(b.y0, b.y1)));
    const y = d3.scaleLinear().domain([lo, hi]).range([ih, 0]).nice(5);
    const fmtAxis = axisFormat();
    g.append('g').attr('class', 'gridl').call(d3.axisLeft(y).ticks(5).tickSize(-iw).tickFormat(''));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(5).tickFormat(fmtAxis).tickSize(0).tickPadding(5)).call((a) => a.select('.domain').remove());
    g.append('line').attr('x1', 0).attr('x2', iw).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--axis)');
    const bw = Math.min(24, x.bandwidth());
    bars.forEach((b, k) => {
      const cx = x(k) + x.bandwidth() / 2;
      const top = y(Math.max(b.y0, b.y1)), bot = y(Math.min(b.y0, b.y1));
      const fill = b.total ? 'var(--ink-2)' : b.uv >= 0 ? 'var(--blue)' : 'var(--red)';
      g.append('rect').attr('x', cx - bw / 2).attr('width', bw).attr('y', top).attr('height', Math.max(1, bot - top))
        .attr('rx', 2).attr('fill', fill).attr('opacity', b.group === 'curve' ? 0.85 : 1);
      if (k < bars.length - 1 && !bars[k + 1].total) {
        g.append('line').attr('x1', cx + bw / 2).attr('x2', x(k + 1) + x.bandwidth() / 2 - bw / 2)
          .attr('y1', y(b.y1)).attr('y2', y(b.y1)).attr('stroke', 'var(--axis)');
      }
      if (x.bandwidth() > 26 || b.total) {
        const above = b.uv >= 0;
        g.append('text').attr('class', 'lbl ink2').attr('x', cx).attr('y', above ? top - 3 : bot + 10).attr('text-anchor', 'middle')
          .attr('font-size', 9.5).text(fmtU(b.v, { gross }).replace('bp', '').replace('%', ''));
      }
      g.append('text').attr('class', 'lbl').attr('transform', `translate(${cx},${ih + 8}) rotate(-40)`).attr('text-anchor', 'end').text(b.label);
      g.append('rect').attr('x', x(k)).attr('width', x.bandwidth()).attr('y', 0).attr('height', ih).attr('fill', 'transparent')
        .on('mousemove', (ev) => showTip(`<b>${b.label}</b> ${fmtU(b.v, { gross })}${b.beta != null ? `<br>factor move ${b.beta >= 0 ? '+' : '−'}${Math.abs(b.beta).toFixed(1)}bp` : ''}`, ev.clientX, ev.clientY))
        .on('mouseleave', hideTip);
    });
  }, [r, mode, split, index, W, S.units, height]);
  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height=${height} role="img" aria-label="Horizon attribution waterfall"></svg></div>`;
}
