export const readerPageKey = (sectionId) => `homestead:reader-page:${sectionId}`;

export function loadReaderPage(storage, sectionId) {
  const value = Number.parseInt(storage?.getItem(readerPageKey(sectionId)) || "0", 10);
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

export function saveReaderPage(storage, sectionId, page) {
  storage?.setItem(readerPageKey(sectionId), String(Math.max(0, page | 0)));
}

export function pageDeltaForGesture(dx, dy, threshold = 44) {
  if (Math.abs(dx) < threshold || Math.abs(dx) <= Math.abs(dy) * 1.15) return 0;
  return dx < 0 ? 1 : -1;
}

export function captureReturnState(win, doc, opener) {
  return { scrollX: win.scrollX, scrollY: win.scrollY, focus: opener || doc.activeElement };
}

export function restoreReturnState(win, state) {
  win.scrollTo(state.scrollX, state.scrollY);
  state.focus?.focus?.({ preventScroll: true });
  win.scrollTo(state.scrollX, state.scrollY);
}

export function pageOffset(page, pageWidth, gap = 40) {
  return -Math.max(0, page) * (Math.max(0, pageWidth) + gap);
}

export function revealLearningTarget(target, schedule = requestAnimationFrame) {
  schedule(() => schedule(() => {
    if (!target) return;
    target.focus?.({ preventScroll: true });
    target.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }));
}
