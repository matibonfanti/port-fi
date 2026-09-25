// Transport to the Python engine: the local FastAPI server, or — in the static build — Python running in the
// browser (Pyodide) inside a Web Worker. The engine code and its answers are identical in both.
const RUNTIME = document.querySelector('meta[name="portfi-runtime"]')?.content || 'server';
let worker = null;
const pending = new Map();
let seq = 0;
let onProgress = () => {};
export function setProgressHandler(f) { onProgress = f; }
export const runtime = RUNTIME;

function viaWorker(name, payload) {
  if (!worker) {
    worker = new Worker(new URL('./worker.js', import.meta.url));
    worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === 'progress') { onProgress(m.msg); return; }
      const p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      if (m.error || m.data?.error) p.rej(new Error(m.error || m.data.error)); else p.res(m.data);
    };
    worker.onerror = (e) => onProgress('Engine failed to load: ' + (e.message || e));
  }
  return new Promise((res, rej) => {
    const id = ++seq;
    pending.set(id, { res, rej });
    worker.postMessage({ id, name, payload });
  });
}

async function viaServer(name, payload) {
  const r = await fetch('/api/' + name, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload ?? null) });
  const d = await r.json().catch(() => ({ error: r.statusText }));
  if (!r.ok || d?.error) throw new Error(d?.error || r.statusText);
  return d;
}

const call = RUNTIME === 'pyodide' ? viaWorker : viaServer;
export const api = {
  market: (asof) => call('market', { asof }),
  analyze: (req) => call('analyze', req),
  analogue: (req) => call('analogue', req),
  preset: (req) => call('preset', req),
  methodology: () => call('methodology', {}).then((d) => d.text),
};
