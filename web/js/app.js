import { html, render, useEffect, useState } from './lib.js';
import { S, useStore, init, setPref, setAsof, set, undo } from './store.js';
import { installGlossaryTips } from './tip.js';
import { PositionPanel, ReturnPanel, ViewsPanel } from './panels/rail.js';
import { Builder } from './panels/builder.js';
import { Steps, Kpis, CurvesCard, HeroCard, WaterfallCard, InverseCard, SummaryCard, BreakevenCard, TimingCard, RiskCard } from './panels/cards.js';
import { Compare } from './panels/compare.js';
import { api, runtime } from './api.js';
import { marked } from 'marked';

const Seg = ({ value, options, onChange, label, tip }) => html`<span class="ctl" data-tip=${tip}>${label}
  <span class="seg">${options.map(([v, l]) => html`<button class=${value === v ? 'on' : ''} onClick=${() => onChange(v)}>${l}</button>`)}</span></span>`;

function TopBar() {
  const m = S.market;
  return html`<div class="topbar">
    <div class="brand"><svg width="18" height="18" viewBox="0 0 16 16"><path d="M1 13 C5 12 7 6 15 3" stroke="var(--blue)" stroke-width="2.2" fill="none"/><path d="M1 13 C6 11 9 9 15 8" stroke="var(--orange)" stroke-width="1.6" fill="none"/></svg>
      PORT·FI <small>position + time + view → return</small></div>
    <div class="tabs">${[['workspace', 'Workspace'], ['compare', 'Compare'], ['docs', 'Methodology']].map(([k, l]) =>
      html`<button class=${S.tab === k ? 'on' : ''} onClick=${() => set({ tab: k })}>${l}</button>`)}</div>
    <span class="sep"></span>
    ${m && html`<label class="ctl" title=${`Curve as-of date (any date since ${m.first_date})`}>As of
      <input type="date" value=${S.asof} min=${m.first_date} max=${m.last_date} onChange=${(e) => setAsof(e.target.value)}/></label>`}
    <${Seg} label="Units" value=${S.units} options=${[['pct', '%'], ['bp', 'bp'], ['usd', '$']]} onChange=${(v) => setPref({ units: v }, false)}/>
    <${Seg} label="Factors" value=${S.basis} options=${[['parametric', 'Parametric'], ['pca', 'PCA']]} onChange=${(v) => setPref({ basis: v })}/>
    ${S.basis === 'pca' && html`<select value=${S.pcaWindow} title="PCA / vol estimation window" onChange=${(e) => setPref({ pcaWindow: +e.target.value })}>
      ${[1, 3, 5, 10].map((y) => html`<option value=${y}>${y}y window</option>`)}</select>`}
    <button class="btn ghost" title="Theme" onClick=${() => setPref({ theme: S.theme === 'dark' ? 'light' : S.theme === 'light' ? 'auto' : 'dark' }, false)}>
      ${S.theme === 'dark' ? '☾' : S.theme === 'light' ? '☀' : '◐'}</button>
    <span class="status" title=${runtime === 'pyodide' ? 'Python engine running in your browser' : 'Local Python server'}>
      ${S.loading ? html`<span class="spin"></span>` : html`<span class="dot" style="background:var(--green)"></span>`}
      ${S.result ? `${S.result.elapsed_ms.toFixed(0)}ms` : ''}</span>
  </div>`;
}

function Workspace() {
  const r = S.result;
  if (!r || !S.view) return html`<div class="boot"><span class="spin"></span> ${S.boot}</div>`;
  const stale = S.fullStale;
  return html`<div>
    <${Steps} r=${r}/>
    <div class="shell">
      <aside class="rail"><${PositionPanel} r=${r}/><${ReturnPanel} r=${r}/><${ViewsPanel}/></aside>
      <main class="main">
        <${CurvesCard} r=${r}/>
        <div class="s5"><${Builder} r=${r}/></div>
        <div class="s12 sectionhead"><span class="stepno">→</span> Results</div>
        <${Kpis} r=${r}/>
        <${HeroCard} r=${r}/>
        <${WaterfallCard} r=${r}/>
        <${InverseCard} r=${r}/>
        <${SummaryCard} r=${r}/>
        <${BreakevenCard} r=${r} stale=${stale}/>
        <${TimingCard} r=${r} stale=${stale}/>
        <${RiskCard} r=${r} stale=${stale}/>
        <${MarketCard} r=${r}/>
      </main></div></div>`;
}

function MarketCard({ r }) {
  const m = S.market;
  const rates = m.rates || {};
  const ten = (t) => (t < 1 ? `${Math.round(t * 12 * 2) / 2}M` : `${t}Y`);
  return html`<section class="card s12"><header><h2>Market data</h2><span class="sub">US Treasury par curves (treasury.gov) ${m.asof} · smoothed zero fit${m.real ? ' · TIPS real curve' : ''}</span></header>
    <div class="body scroll-x"><table class="t"><thead><tr><th>Tenor</th>${m.par.tenors.map((t) => html`<th>${ten(t)}</th>`)}</tr></thead><tbody>
      <tr><td>Par yield %</td>${m.par.yields.map((y) => html`<td>${y.toFixed(2)}</td>`)}</tr>
      <tr><td data-tip="fit">Fit error bp</td>${m.par.fit_bp.map((e) => html`<td class="muted">${e.toFixed(1)}</td>`)}</tr></tbody></table>
      ${m.real && html`<table class="t" style="margin-top:6px"><thead><tr><th>TIPS</th>${m.real.tenors.map((t) => html`<th>${ten(t)}</th>`)}</tr></thead><tbody>
        <tr><td>Real par yield %</td>${m.real.yields.map((y) => html`<td>${y.toFixed(2)}</td>`)}</tr>
        <tr><td data-tip="be_curve">Zero breakeven %</td>${m.real.be_knots.map((y) => html`<td>${y.toFixed(2)}</td>`)}</tr></tbody></table>`}
      <div class="muted" style="margin-top:4px">${rates.sofr ? `SOFR ${rates.sofr.rate.toFixed(2)}% (${rates.sofr.date}) · ` : ''}${rates.effr ? `EFFR ${rates.effr.rate.toFixed(2)}%, target ${rates.effr.target.join('–')}% · ` : ''}curve-implied overnight ${m.implied_short.toFixed(2)}% ·
        PCA explains ${(r.factor.explained || []).map((x) => (x * 100).toFixed(0) + '%').join(' / ')} (level/slope/curvature, ${(r.factor.window || []).join(' → ')})</div></div></section>`;
}

function Docs() {
  const [md, setMd] = useState(null);
  useEffect(() => { api.methodology().then(setMd).catch((e) => setMd('Could not load: ' + e.message)); }, []);
  return html`<div class="card" style="margin:12px 16px"><div class="doc" dangerouslySetInnerHTML=${{ __html: md ? marked.parse(md) : 'Loading…' }}></div></div>`;
}

function App() {
  useStore();
  useEffect(() => {
    installGlossaryTips();
    init();
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) { e.preventDefault(); undo(); }
      if (e.key === 'Escape') set({ activeNode: null, activeBeNode: null });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  return html`<${TopBar}/>
    ${S.error && html`<div class="err">${S.error} <button class="btn ghost sm" onClick=${() => set({ error: null })}>dismiss</button></div>`}
    ${S.tab === 'workspace' && html`<${Workspace}/>`}
    ${S.tab === 'compare' && html`<${Compare}/>`}
    ${S.tab === 'docs' && html`<${Docs}/>`}`;
}

render(html`<${App}/>`, document.getElementById('app'));
