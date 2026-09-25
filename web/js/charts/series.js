// Component definitions for both attribution modes (fixed color per component identity).
// Stack order validated for CVD separation in light & dark (roll must not sit next to curve/view blue).
export function components(r, mode) {
  const a = r.attribution;
  const add = (x, y) => x.map((v, i) => v + y[i]);
  const any = (arr) => arr.some((v) => Math.abs(v) > 1e-6);
  const total = r.return_basis === 'total';
  // yellow sits between blue and magenta: validated adjacent pairs (green next to yellow fails CVD in dark mode)
  const infl = any(a.inflation) ? [{ key: 'infl', label: 'Inflation vs priced', color: 'var(--yellow)', v: a.inflation, tip: 'inflation' }] : [];
  const out = mode === 'today'
    ? [
        { key: 'roll', label: 'Roll-down', color: 'var(--violet)', v: a.roll, tip: 'roll' },
        { key: 'carry', label: total ? 'Coupon & pull-to-par' : 'Carry', color: 'var(--aqua)', v: a.carry, tip: 'carry' },
        { key: 'curve', label: 'Curve change', color: 'var(--blue)', v: a.curve.fo, tip: 'curve' },
        ...infl,
        { key: 'conv', label: 'Convexity / resid.', color: 'var(--magenta)', v: add(a.curve.convexity, a.curve.residual), tip: 'convexity' },
      ]
    : [
        { key: 'roll', label: 'Roll-down', color: 'var(--violet)', v: a.roll, tip: 'roll' },
        { key: 'carry', label: total ? 'Coupon & pull-to-par' : 'Carry', color: 'var(--aqua)', v: a.carry, tip: 'carry' },
        { key: 'priced', label: 'Priced-in move', color: 'var(--orange)', v: a.priced.total, tip: 'priced_move' },
        { key: 'edge', label: 'View vs fwds', color: 'var(--blue)', v: a.edge.fo, tip: 'edge' },
        ...infl,
        { key: 'conv', label: 'Convexity / resid.', color: 'var(--magenta)', v: add(a.edge.convexity, a.edge.residual), tip: 'convexity' },
      ];
  if (any(a.spread)) out.push({ key: 'spread', label: 'Spread', color: 'var(--green)', v: a.spread, tip: 'spread' });
  return out;
}
