/* Python engine in the browser (Pyodide). Loads numpy, unpacks the engine + market-data snapshot, and serves
   JSON calls through port.bridge — the same entry point the local server uses. */
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.29.5/full/';
importScripts(PYODIDE + 'pyodide.js');
const progress = (msg) => postMessage({ type: 'progress', msg });
let bridge = null;
const ready = (async () => {
  progress('Loading Python runtime (first visit ~10 MB, then cached)…');
  const py = await loadPyodide({ indexURL: PYODIDE });
  progress('Loading numpy…');
  await py.loadPackage('numpy');
  progress('Loading engine and market data…');
  const buf = await (await fetch(new URL('../engine.zip', self.location))).arrayBuffer();
  py.unpackArchive(buf, 'zip', { extractDir: '/app' });
  py.runPython(`
import os, sys
os.environ['PORT_FI_RUNTIME'] = 'browser'
os.environ['PORT_FI_DATA'] = '/app/data/snapshot'
sys.path.insert(0, '/app')
`);
  bridge = py.pyimport('port.bridge');
  progress('Fitting today\'s curves…');
})().catch((e) => { progress('Engine failed to load: ' + e); throw e; });

self.onmessage = async (e) => {
  const { id, name, payload } = e.data;
  try {
    await ready;
    const out = bridge.call(name, JSON.stringify(payload ?? null));
    postMessage({ id, data: JSON.parse(out) });
  } catch (err) {
    postMessage({ id, error: String(err) });
  }
};
