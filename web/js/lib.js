import { h, render, Fragment } from 'preact';
import { useState, useEffect, useRef, useMemo, useCallback, useLayoutEffect } from 'preact/hooks';
import htm from 'htm';
export const html = htm.bind(h);
export { h, render, Fragment, useState, useEffect, useRef, useMemo, useCallback, useLayoutEffect };
export const d3 = window.d3;

/** Observe an element's width (for responsive charts). */
export function useWidth(ref, fallback = 600) {
  const [w, setW] = useState(fallback);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(200, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return w;
}

/** Read a CSS custom property (theme-aware colors for SVG). */
export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
