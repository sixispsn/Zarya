/* Presentation only. Commit UI updates before animation ends; never delay input. */
(() => {
  'use strict';
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const html = document.documentElement;
  let active = null;
  let pending = null;

  function clear(record) {
    if (active !== record) return; // An old finish event must not strip the next surface.
    for (const element of record.elements) element.classList.remove('studio-motion-surface');
    active = null;
    html.classList.remove('studio-dissolving');
  }
  function stop() {
    if (!active) return;
    active.transition?.skipTransition();
    active.animation?.cancel();
    clear(active);
  }
  function reveal(update, findSurface) {
    stop();
    // User-driven choices commit in this event, with no deferred DOM replacement
    // between pointer-down and click. Server response transitions use change().
    update();
    const surface = findSurface();
    if (preference.matches || document.hidden || !surface?.animate) return;
    const record = {elements:new Set(), transition:null, animation:null};
    active = record;
    record.animation = surface.animate(
      [{opacity:.25, filter:'blur(1px)'}, {opacity:1, filter:'blur(0)'}],
      {duration:220, easing:'cubic-bezier(.2,.7,.2,1)'}
    );
    record.animation.finished.catch(() => {}).then(() => clear(record));
  }
  function change(update, findSurface, animate = true) {
    const run = () => {
      stop();
      const before = findSurface();
      if (!animate || preference.matches || document.hidden || !before || !document.startViewTransition) {
        update();
        return Promise.resolve();
      }
      const record = {elements: new Set([before]), transition: null};
      active = record;
      html.classList.add('studio-dissolving');
      before.classList.add('studio-motion-surface');
      let committed = false;
      const commit = () => {
        if (committed) return;
        committed = true;
        before.classList.remove('studio-motion-surface');
        update();
        const after = findSurface();
        if (active === record && after) {
          record.elements.add(after);
          after.classList.add('studio-motion-surface');
        }
      };
      try {
        record.transition = document.startViewTransition(commit);
      } catch (error) {
        clear(record);
        // An unavailable animation must not prevent a UI update or repeat it.
        if (committed) throw error;
        commit();
        return Promise.resolve();
      }
      record.transition.ready.catch(() => {}); // A skipped snapshot is not a failed calculation.
      record.transition.finished.catch(() => {}).then(() => clear(record));
      return record.transition.updateCallbackDone;
    };
    // Serialize DOM commits, not animations. Rapid choices never queue fades.
    stop();
    const job = pending ? pending.catch(() => {}).then(run) : Promise.resolve().then(run);
    pending = job;
    const release = () => { if (pending === job) pending = null; };
    job.then(release, release);
    return job;
  }
  preference.addEventListener('change', () => { if (preference.matches) stop(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  // First real interaction reveals the live DOM, including immediate stale-result hiding.
  for (const event of ['pointerdown', 'keydown', 'input']) document.addEventListener(event, stop, true);
  window.addEventListener('pagehide', stop);
  window.ZaryaMotion = {change, reveal, stop};
})();
