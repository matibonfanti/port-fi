import { html, useRef, useEffect, useWidth, d3, css } from '../lib.js';
import { S } from '../store.js';
import { showTip, hideTip } from '../tip.js';
import { u, fmtU, fmtSigned } from '../format.js';

const BLUE = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95'];
const RED = ['#fbd5d4', '#f4a7a5', '#ec7876', '#e34948', '#c33634', '#9c2a29'];

export function Heatmap({ r, height = 300 }) {
  const wrap = useRef(null), svgRef = useRef(null);
  const W = useWidth(wrap, 400);
  useEffect(() => {
    const hm = r?.heatmap;
    if (!hm) return;
    const gross = r.position.gross_mv;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    const m = { l: 44, r: 10, t: 8, b: 34 };
    const iw = W - m.l - m.r, ih = height - m.t - m.b;
    const g = svg.append('g').attr('transform', `translate(${m.l},${m.t})`);
    const L = hm.level, Sl = hm.slope, Z = hm.pnl;
    const n = L.length, ns = Sl.length;
    const x = d3.scaleLinear().domain([L[0], L[n - 1]]).range([0, iw]);
    const y = d3.scaleLinear().domain([Sl[0], Sl[ns - 1]]).range([ih, 0]);
    const mx = d3.max(Z.flat(), (v) => Math.abs(v)) || 1;
    const mid = css('--neutral-mid') || '#f0efec';
    const col = d3.scaleLinear().domain([-1, -0.6, -0.3, 0, 0.3, 0.6, 1]).range([RED[5], RED[3], RED[1], mid, BLUE[1], BLUE[3], BLUE[5]]).interpolate(d3.interpolateLab).clamp(true);
    const cw = iw / (n - 1), ch = ih / (ns - 1);
    for (let a = 0; a < ns; a++) for (let b = 0; b < n; b++) {
      g.append('rect').attr('x', x(L[b]) - cw / 2).attr('y', y(Sl[a]) - ch / 2).attr('width', cw + 0.6).attr('height', ch + 0.6)
        .attr('fill', col(Z[a][b] / mx));
    }
    // contours: break even (solid ink), beat cash and target (thinner, labelled)
    const px = d3.scaleLinear().domain([0, n - 1]).range([0, iw]);
    const py = d3.scaleLinear().domain([0, ns - 1]).range([ih, 0]);
    const proj = d3.geoTransform({ point(xx, yy) { this.stream.point(px(xx - 0.5), py(yy - 0.5)); } });
    const styles = { breakeven: ['var(--ink)', 2], cash: ['var(--ink-2)', 1.25], target: ['var(--violet)', 1.5] };
    (hm.contours || [{ key: 'breakeven', value: 0 }]).forEach((c) => {
      const [col, w] = styles[c.key] || styles.breakeven;
      const cont = d3.contours().size([n, ns]).thresholds([c.value])(Z.flat())[0];
      if (!cont || !cont.coordinates.length) return;
      const path = g.append('path').attr('d', d3.geoPath(proj)(cont)).attr('fill', 'none').attr('stroke', col).attr('stroke-width', w);
      const node = path.node();
      const len = node.getTotalLength ? node.getTotalLength() : 0;
      if (len > 40) {
        const pt = node.getPointAtLength(len * 0.12);
        const tx = g.append('text').attr('class', 'lbl ink').attr('x', pt.x + 4).attr('y', pt.y - 4).text(c.label || c.key);
        tx.clone(true).lower().attr('stroke', 'var(--surface)').attr('stroke-width', 3);
      }
    });
    // axes
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`).call(d3.axisBottom(x).ticks(6).tickSize(3));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(6).tickSize(3));
    g.append('text').attr('class', 'lbl').attr('x', iw / 2).attr('y', ih + 28).attr('text-anchor', 'middle')
      .text(`Δ ${hm.space === 'real' ? 'real-yield ' : ''}level (bp) vs ${hm.base === 'forwards' ? 'forwards' : 'today'} at horizon${hm.space === 'nominal_be_held' ? ' · breakevens held' : ''}`);
    g.append('text').attr('class', 'lbl').attr('transform', `translate(-32,${ih / 2}) rotate(-90)`).attr('text-anchor', 'middle').text('Δ slope, 2s10s (bp)');
    g.append('line').attr('x1', x(0)).attr('x2', x(0)).attr('y1', 0).attr('y2', ih).attr('stroke', 'var(--ink-2)').attr('stroke-opacity', 0.25);
    g.append('line').attr('y1', y(0)).attr('y2', y(0)).attr('x1', 0).attr('x2', iw).attr('stroke', 'var(--ink-2)').attr('stroke-opacity', 0.25);
    // markers
    const mk = [
      { k: 'today', label: 'Today', fill: 'var(--surface)', stroke: 'var(--ink)' },
      { k: 'forwards', label: 'Forwards', fill: 'var(--orange)', stroke: 'var(--surface)' },
      { k: 'view', label: 'Your view', fill: 'var(--blue)', stroke: 'var(--surface)' },
    ];
    mk.forEach((q, idx) => {
      const [a, b] = hm.markers[q.k];
      const cx = x(Math.max(L[0], Math.min(L[n - 1], a))), cy = y(Math.max(Sl[0], Math.min(Sl[ns - 1], b)));
      g.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 5).attr('fill', q.fill).attr('stroke', q.stroke).attr('stroke-width', 2);
      const t = g.append('text').attr('class', 'lbl ink').attr('x', cx + 8).attr('y', cy + 4 + (idx - 1) * 2).text(q.label);
      t.clone(true).lower().attr('stroke', 'var(--surface)').attr('stroke-width', 3);
    });
    g.append('rect').attr('width', iw).attr('height', ih).attr('fill', 'transparent')
      .on('mousemove', (ev) => {
        const [px0, py0] = d3.pointer(ev);
        const b = Math.round((x.invert(px0) - L[0]) / (L[1] - L[0])), a = Math.round((y.invert(py0) - Sl[0]) / (Sl[1] - Sl[0]));
        if (a < 0 || b < 0 || a >= ns || b >= n) return;
        showTip(`Δlevel ${fmtSigned(L[b], 0, 'bp')} · Δslope ${fmtSigned(Sl[a], 0, 'bp')}<br><b>${fmtU(Z[a][b], { gross })}</b> at horizon`, ev.clientX, ev.clientY);
      })
      .on('mouseleave', hideTip);
  }, [r?.heatmap, W, S.units, height]);
  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height=${height} role="img" aria-label="Horizon return over level and slope moves"></svg></div>`;
}
