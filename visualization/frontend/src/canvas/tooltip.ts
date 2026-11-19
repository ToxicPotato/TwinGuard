// ─────────────────────────────────────────────────────────────────────────────
// tooltip.ts — Floating tooltip for elements with a data-tip="..." attribute.
//
// Self-contained IIFE — no external dependencies, no exported functions.
// Follows the cursor, fades in on hover, and stays within the viewport.
// ─────────────────────────────────────────────────────────────────────────────

(function () {
  const tt = document.getElementById('tt') as HTMLElement | null;
  let cur: Element | null = null;

  document.addEventListener('mouseover', (e: MouseEvent) => {
    const el = (e.target as Element | null)?.closest('[data-tip]');
    if (!el || el === cur) return;
    cur = el;
    if (tt) {
      tt.textContent = (el as HTMLElement).dataset.tip ?? '';
      tt.style.opacity = '1';
    }
  });

  document.addEventListener('mouseout', (e: MouseEvent) => {
    if (!e.relatedTarget || !(e.relatedTarget as Element).closest('[data-tip]')) {
      if (tt) tt.style.opacity = '0';
      cur = null;
    }
  });

  document.addEventListener('mousemove', (e: MouseEvent) => {
    if (!cur || !tt) return;
    const vw = window.innerWidth;
    const tw = tt.offsetWidth;
    const x  = e.clientX + 14 + tw > vw ? e.clientX - tw - 8 : e.clientX + 14;
    tt.style.left = x + 'px';
    tt.style.top  = (e.clientY - 10) + 'px';
  });
})();

export {};
