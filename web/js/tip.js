import { GLOSSARY } from './glossary.js';

const el = () => document.getElementById('tip');
export function showTip(html, x, y) {
  const t = el();
  t.innerHTML = html;
  t.classList.add('on');
  const r = t.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > window.innerHeight - 8) top = y - r.height - 14;
  t.style.left = Math.max(8, left) + 'px';
  t.style.top = Math.max(8, top) + 'px';
}
export function hideTip() { el().classList.remove('on'); }

// Global: any element with data-tip="glossary-key" or data-tipt="free text" shows a definition on hover.
export function installGlossaryTips() {
  document.addEventListener('mouseover', (e) => {
    const n = e.target.closest?.('[data-tip],[data-tipt]');
    if (!n) return;
    const key = n.getAttribute('data-tip');
    const txt = key ? GLOSSARY[key] : n.getAttribute('data-tipt');
    if (!txt) return;
    const move = (ev) => showTip(txt, ev.clientX, ev.clientY);
    move(e);
    const out = () => { hideTip(); n.removeEventListener('mousemove', move); n.removeEventListener('mouseleave', out); };
    n.addEventListener('mousemove', move);
    n.addEventListener('mouseleave', out);
  });
  document.addEventListener('focusin', (e) => {
    const n = e.target.closest?.('[data-tip]');
    if (!n) return;
    const txt = GLOSSARY[n.getAttribute('data-tip')];
    if (!txt) return;
    const r = n.getBoundingClientRect();
    showTip(txt, r.left, r.bottom);
    n.addEventListener('focusout', hideTip, { once: true });
  });
}
