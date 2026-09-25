import { html, useRef, useEffect, useWidth, d3 } from '../lib.js';
import { S, set, setNodeLevel, ensureNode, setBeLevel, ensureBeNode, inflSpec } from '../store.js';
import { showTip, hideTip } from '../tip.js';
import { fmtTenor, fmtSigned } from '../format.js';

const TICKS = [0.25, 1, 2, 3, 5, 7, 10, 20, 30];
const H = 350;

function interp(xs, ys, x) {
  if (x <= xs[0]) return ys[0];
  for (let i = 1; i < xs.length; i++) if (x <= xs[i]) {
    const w = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
    return ys[i - 1] * (1 - w) + ys[i] * w;
  }
  return ys[ys.length - 1];
}

/** Data for one layer at slider index i (or at an active node). */
export function layerData(r, layer, i, activeNode, activeBeNode) {
  const tau = r.curves.tau;
  if (layer === 'nominal') {
    const node = activeNode != null ? r.nodes[activeNode] : null;
    return {
      tau, t: node ? node.t : r.t[i], node,
      today: r.curves.today, fwd: node ? node.curve_fwd : r.curves.fwd[i], user: node ? node.curve_user : r.curves.user[i],
      allFwd: r.curves.fwd, allUser: r.curves.user, keysUser: node ? node.user : r.keys.user[i],
      keysFwd: node ? node.fwd : r.keys.fwd[i], keysToday: r.keys.today, editable: true,
    };
  }
  const inf = r.inflation;
  const c = inf.curves;
  if (layer === 'be') {
    const node = activeBeNode != null ? (inf.nodes || [])[activeBeNode] : null;
    return {
      tau, t: node ? node.t : r.t[i], node,
      today: c.be_today, fwd: node ? node.curve_fwd : c.be_fwd[i], user: node ? node.curve_user : c.be_user[i],
      allFwd: c.be_fwd, allUser: c.be_user, keysUser: node ? node.user : inf.keys.user[i],
      keysFwd: node ? node.fwd : inf.keys.fwd[i], keysToday: inf.keys.today, editable: true,
    };
  }
  return { tau, t: r.t[i], node: null, today: c.real_today, fwd: c.real_fwd[i], user: c.real_user[i],
           allFwd: c.real_fwd, allUser: c.real_user, editable: false };
}

export function CurvesChart({ r, tIndex, activeNode, activeBeNode, layer = 'nominal' }) {
  const wrap = useRef(null);
  const svgRef = useRef(null);
  const W = useWidth(wrap, 700);
  const dragState = useRef({});

  useEffect(() => {
    if (!r || tIndex == null) return;
    const ds = dragState.current;
    if (ds.active && ds.update) { ds.update(r); return; }   // mid-drag: refresh curves in place only
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    const m = { l: 42, r: 14, t: 12, b: 28 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const g = svg.append('g').attr('transform', `translate(${m.l},${m.t})`);
    const D = layerData(r, layer, tIndex, activeNode, activeBeNode);
    const { tau, today, fwd, user, node } = D;

    let lo = d3.min(today), hi = d3.max(today);
    for (const arr of [D.allFwd, D.allUser]) for (const row of arr) { lo = Math.min(lo, d3.min(row)); hi = Math.max(hi, d3.max(row)); }
    if (D.keysUser) { lo = Math.min(lo, d3.min(D.keysUser) - 0.1); hi = Math.max(hi, d3.max(D.keysUser) + 0.1); }
    const pad = (hi - lo) * 0.1 + 0.05;
    const x = d3.scaleSqrt().domain([0, 30]).range([0, iw]);
    const y = d3.scaleLinear().domain([lo - pad, hi + pad]).range([ih, 0]).nice();

    g.append('g').attr('class', 'gridl').call(d3.axisLeft(y).ticks(6).tickSize(-iw).tickFormat(''));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(6).tickFormat((d) => d.toFixed(2)).tickSize(0).tickPadding(6))
      .call((a) => a.select('.domain').remove());
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`)
      .call(d3.axisBottom(x).tickValues(TICKS).tickFormat(fmtTenor).tickSize(3));
    if (layer === 'be') {  // no TIPS data below 5Y: shade
      g.append('rect').attr('x', 0).attr('width', x(5)).attr('height', ih).attr('fill', 'var(--surface-2)').attr('opacity', 0.6);
      g.append('text').attr('class', 'lbl').attr('x', 6).attr('y', ih - 6).text('below 5Y: held at 5Y (no TIPS data)');
    }

    const line = d3.line().x((d, i) => x(tau[i])).y((d) => y(d)).curve(d3.curveMonotoneX);
    const area = d3.area().x((d, i) => x(tau[i])).y0((d, i) => y(fwd[i])).y1((d) => y(d)).curve(d3.curveMonotoneX);
    const pArea = g.append('path').attr('d', area(user)).attr('fill', 'var(--wash-blue)');
    g.append('path').attr('d', line(today)).attr('fill', 'none').attr('stroke', 'var(--today)').attr('stroke-width', 2);
    g.append('path').attr('d', line(fwd)).attr('fill', 'none').attr('stroke', 'var(--orange)').attr('stroke-width', 2);
    const pUser = g.append('path').attr('d', line(user)).attr('fill', 'none').attr('stroke', 'var(--blue)').attr('stroke-width', 2);
    ds.update = (rr) => {
      const DD = layerData(rr, layer, tIndex, layer === 'nominal' ? S.activeNode : null, layer === 'be' ? S.activeBeNode : null);
      if (!DD.user) return;
      pArea.attr('d', area(DD.user));
      pUser.attr('d', line(DD.user));
    };

    // positions rolling down the curve (on the layer their cash flows discount on)
    if (layer !== 'be') {
      const pg = g.append('g');
      r.position.lines.forEach((ln, i) => {
        if ((layer === 'real') !== !!ln.real) return;
        const tau0 = ln.mat_t, tauT = Math.max(ln.mat_t - D.t, 0.0);
        if (tau0 > 30.5) return;
        const pts = d3.range(0, 41).map((k) => tau0 - (tau0 - tauT) * (k / 40));
        pg.append('path').attr('d', d3.line().x((d) => x(d)).y((d) => y(interp(tau, today, d)))(pts))
          .attr('fill', 'none').attr('stroke', 'var(--ink-2)').attr('stroke-width', 1).attr('opacity', 0.55);
        const yu = y(interp(tau, user, Math.max(tauT, tau[0])));
        const long = ln.face_mm > 0;
        pg.append('circle').attr('cx', x(tauT)).attr('cy', yu).attr('r', 4.5)
          .attr('fill', long ? 'var(--ink)' : 'var(--surface)').attr('stroke', long ? 'var(--surface)' : 'var(--ink)').attr('stroke-width', 2);
        pg.append('text').attr('class', 'lbl ink2').attr('x', x(tauT)).attr('y', yu - 9 - (i % 2) * 11).attr('text-anchor', 'middle')
          .text(`${long ? '+' : '−'}${Math.abs(ln.face_mm).toFixed(2)} ${fmtTenor(Math.round(ln.mat_t * 2) / 2)}${ln.real ? ' TIPS' : ''} → ${tauT.toFixed(2)}y`);
      });
    }

    // draggable key-rate handles, always shown at the displayed date (a node is created on first drag)
    if (D.editable && D.keysUser) {
      const kt = S.market.key_tenors;
      const hg = g.append('g');
      kt.forEach((k, j) => {
        const lvl0 = D.keysUser[j];
        const hgr = hg.append('g').attr('class', 'handle').attr('transform', `translate(${x(k)},${y(lvl0)})`);
        hgr.append('circle').attr('r', 12).attr('fill', 'transparent');
        hgr.append('circle').attr('class', 'h').attr('r', node ? 5 : 4).attr('fill', node ? 'var(--blue)' : 'var(--surface)')
          .attr('stroke', node ? 'var(--surface)' : 'var(--blue)').attr('stroke-width', 2);
        hgr.call(d3.drag()
          .on('start', () => {
            Object.assign(ds, { first: true, active: true, idx: null });
            hideTip();
          })
          .on('drag', (ev) => {
            const lvl = Math.round(y.invert(Math.max(0, Math.min(ih, ev.y))) * 100) / 100;   // snap to 1bp (0.01%)
            hgr.attr('transform', `translate(${x(k)},${y(lvl)})`);
            let record = ds.first;
            if (ds.idx == null) {
              if (node) ds.idx = layer === 'nominal' ? activeNode : activeBeNode;
              else { ds.idx = layer === 'nominal' ? ensureNode(D.t, { fast: true }) : ensureBeNode(D.t, { fast: true }); record = false; }
            }
            (layer === 'nominal' ? setNodeLevel : setBeLevel)(ds.idx, j, lvl, { fast: true, record });
            ds.first = false;
            showTip(`<b>${S.market.key_labels[j]}</b> ${lvl.toFixed(2)}%<br>vs fwd ${fmtSigned((lvl - D.keysFwd[j]) * 100, 0, 'bp')} · vs today ${fmtSigned((lvl - D.keysToday[j]) * 100, 0, 'bp')}`,
              ev.sourceEvent.clientX, ev.sourceEvent.clientY);
          })
          .on('end', () => {
            ds.active = false;
            hideTip();
            if (ds.idx != null) set(layer === 'nominal' ? { activeNode: ds.idx } : { activeBeNode: ds.idx });
          }));
        hgr.on('mouseenter', (ev) => showTip(`Drag to set your ${layer === 'be' ? 'breakeven' : 'zero rate'} at ${S.market.key_labels[j]} for ${node ? 'this node' : 'this date (creates a node)'}`, ev.clientX, ev.clientY))
          .on('mouseleave', hideTip);
      });
    }

    // hover crosshair
    const cross = g.append('line').attr('y1', 0).attr('y2', ih).attr('stroke', 'var(--axis)').attr('opacity', 0);
    g.insert('rect', ':first-child').attr('width', iw).attr('height', ih).attr('fill', 'transparent')
      .on('mousemove', (ev) => {
        const [mx] = d3.pointer(ev);
        const tt = Math.max(tau[0], Math.min(30, x.invert(mx)));
        cross.attr('x1', x(tt)).attr('x2', x(tt)).attr('opacity', 1);
        const a = interp(tau, today, tt), f = interp(tau, fwd, tt), u = interp(tau, user, tt);
        const what = layer === 'be' ? 'breakeven' : layer === 'real' ? 'real zero' : 'zero';
        showTip(`<b>${fmtTenor(Math.round(tt * 4) / 4)} ${what}</b><table>
          <tr><td>Today</td><td>${a.toFixed(2)}%</td></tr>
          <tr><td>Market-implied</td><td>${f.toFixed(2)}%</td></tr>
          <tr><td>Yours</td><td>${u.toFixed(2)}%</td></tr>
          <tr><td>Yours − implied</td><td>${fmtSigned((u - f) * 100, 0, 'bp')}</td></tr>
          <tr><td>Yours − today</td><td>${fmtSigned((u - a) * 100, 0, 'bp')}</td></tr></table>`, ev.clientX, ev.clientY);
      })
      .on('mouseleave', () => { cross.attr('opacity', 0); hideTip(); });
  }, [r, tIndex, activeNode, activeBeNode, layer, W, S.view]);

  return html`<div class="chartwrap" ref=${wrap}><svg ref=${svgRef} width=${W} height=${H} role="img"
    aria-label="Curves: today, market-implied and your expected curve"></svg></div>`;
}
