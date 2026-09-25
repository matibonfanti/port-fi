import { S } from './store.js';

export const KEYL = ['1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y'];

/** Convert a $ amount into the active unit value: % (of gross MV), bp (of gross MV) or $. */
export function u(x, gross = S.result?.position?.gross_mv) {
  if (x == null || isNaN(x)) return null;
  const g = Math.max(gross || 1, 1);
  if (S.units === 'pct') return (x / g) * 100;
  if (S.units === 'bp') return (x / g) * 1e4;
  return x;
}
export function fmtU(x, { sign = true, gross } = {}) {
  const v = u(x, gross);
  if (v == null) return '–';
  if (S.units === 'pct') return fmtPctSigned(v, sign);
  if (S.units === 'bp') return fmtBp(v, sign);
  return fmtUsd(v, sign);
}
export function unitLabel() {
  const b = S.position?.financing?.basis === 'total' ? 'holding-period return' : 'excess over financing';
  return S.units === 'pct' ? `% of gross MV · ${b}` : S.units === 'bp' ? `bp of gross MV · ${b}` : `$ (position as sized) · ${b}`;
}
export function axisFormat() {
  if (S.units === 'pct') return (d) => `${d.toFixed(Math.abs(d) < 10 ? 1 : 0)}%`;
  if (S.units === 'bp') return (d) => window.d3.format('~s')(d);
  return (d) => window.d3.format('$~s')(d);
}
export function fmtPctSigned(v, sign = true) {
  if (v == null || isNaN(v)) return '–';
  return (v < 0 ? '−' : sign && v > 0 ? '+' : '') + Math.abs(v).toFixed(2) + '%';
}
export function fmtBp(v, sign = true) {
  if (v == null || isNaN(v)) return '–';
  const a = Math.abs(v);
  const s = a < 9.95 ? a.toFixed(1) : a.toFixed(0);
  return (v < 0 ? '−' : sign && v > 0 ? '+' : '') + s + 'bp';
}
export function fmtUsd(v, sign = true) {
  if (v == null || isNaN(v)) return '–';
  const a = Math.abs(v);
  const s = a >= 1e6 ? (a / 1e6).toFixed(2) + 'mm' : Math.round(a).toLocaleString('en-US');
  return (v < 0 ? '−' : sign && v > 0 ? '+' : '') + '$' + s;
}
export function fmtNum(v, d = 2) {
  if (v == null || isNaN(v)) return '–';
  return (v < 0 ? '−' : '') + Math.abs(v).toFixed(d);
}
export function fmtSigned(v, d = 1, suf = '') {
  if (v == null || isNaN(v)) return '–';
  return (v < 0 ? '−' : v > 0 ? '+' : '') + Math.abs(v).toFixed(d) + suf;
}
/** Rate levels: always 2 decimals. */
export function fmtRate(v) { return v == null || isNaN(v) ? '–' : v.toFixed(2) + '%'; }
export function fmtT(t) {
  if (t == null) return '–';
  if (Math.abs(t) < 1e-9) return '0';
  const m = t * 12;
  if (m < 0.5) return `${Math.round(t * 52)}w`;
  if (Math.abs(m - Math.round(m)) < 0.05) return m < 24 || Math.round(m) % 12 ? `${Math.round(m)}m` : `${Math.round(m) / 12}y`;
  return `${m.toFixed(1)}m`;
}
export function fmtTenor(tau) {
  if (tau < 1) return `${Math.round(tau * 12)}M`;
  return Number.isInteger(tau) ? `${tau}Y` : `${tau.toFixed(1)}Y`;
}
export const sgnClass = (v) => (v > 1e-12 ? 'pos' : v < -1e-12 ? 'neg' : '');
