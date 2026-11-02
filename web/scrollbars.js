/* Keep native scrolling and the original content nodes; only the bars are custom. */
(() => {
  const selector = '.result-list, .detail-body, .word-cloud, .modal-body, .check-list, .page-dropdown-list, .active-filter-tags, .search-controls-row';
  const instances = new Map();

  function enhance(viewport) {
    if (instances.has(viewport)) return;
    const horizontal = viewport.matches('.active-filter-tags, .search-controls-row');
    const extent = horizontal ? 'clientWidth' : 'clientHeight';
    const contentExtent = horizontal ? 'scrollWidth' : 'scrollHeight';
    const offset = horizontal ? 'scrollLeft' : 'scrollTop';
    const coordinate = horizontal ? 'clientX' : 'clientY';
    const frame = document.createElement('div');
    frame.className = 'scroll-frame';
    if (horizontal) frame.classList.add('scroll-frame-horizontal');
    if (viewport.matches('.check-list')) frame.classList.add('scroll-frame-list');
    if (viewport.matches('.result-list')) frame.classList.add('scroll-frame-results');
    const track = document.createElement('div');
    track.className = 'scroll-track';
    track.setAttribute('aria-hidden', 'true');
    const thumb = document.createElement('div');
    thumb.className = 'scroll-thumb';
    track.append(thumb);
    viewport.before(frame);
    frame.append(viewport, track);
    viewport.classList.add('custom-scroll-viewport');
    // Keyboard users operate the native viewport rather than a second control.
    if (!viewport.hasAttribute('tabindex')) viewport.tabIndex = 0;

    let travel = 0;
    let range = 0;
    let drag = null;
    let pending = false;
    function update() {
      pending = false;
      range = viewport[contentExtent] - viewport[extent];
      const scrollable = /auto|scroll/.test(getComputedStyle(viewport)[horizontal ? 'overflowX' : 'overflowY']);
      track.hidden = !scrollable || range <= 1 || viewport[extent] === 0;
      frame.classList.toggle('has-scrollbar', !track.hidden);
      if (track.hidden) return;
      const size = Math.min(track[extent], Math.max(24,
        track[extent] * viewport[extent] / viewport[contentExtent]));
      travel = track[extent] - size;
      thumb.style[horizontal ? 'width' : 'height'] = `${size}px`;
      thumb.style.transform = `translate${horizontal ? 'X' : 'Y'}(${travel * viewport[offset] / range}px)`;
    }
    function schedule() {
      if (!pending) {
        pending = true;
        requestAnimationFrame(update);
      }
    }
    const resize = new ResizeObserver(schedule);
    function observeContent() {
      resize.disconnect();
      resize.observe(viewport);
      resize.observe(frame);
      for (const child of viewport.children) resize.observe(child);
      schedule();
    }
    const mutation = new MutationObserver(observeContent);
    mutation.observe(viewport, { childList: true, subtree: true, characterData: true });
    observeContent();
    viewport.addEventListener('scroll', schedule, { passive: true });
    track.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      update();
      if (event.target !== thumb) {
        const position = event[coordinate] - track.getBoundingClientRect()[horizontal ? 'left' : 'top'] - thumb[extent] / 2;
        viewport[offset] = travel > 0 ? position / travel * range : 0;
      }
      drag = { y: event[coordinate], top: viewport[offset] };
      track.setPointerCapture(event.pointerId);
      track.classList.add('is-dragging');
    });
    track.addEventListener('pointermove', (event) => {
      if (drag && travel > 0) viewport[offset] = drag.top + (event[coordinate] - drag.y) * range / travel;
    });
    track.addEventListener('lostpointercapture', () => {
      drag = null;
      track.classList.remove('is-dragging');
    });
    track.addEventListener('wheel', (event) => {
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
      viewport[offset] += (horizontal ? event.deltaX || event.deltaY : event.deltaY) * unit;
    }, { passive: false });
    instances.set(viewport, () => { resize.disconnect(); mutation.disconnect(); });
  }

  function discover() {
    for (const [viewport, dispose] of instances) {
      if (!viewport.isConnected) { dispose(); instances.delete(viewport); }
    }
    document.querySelectorAll(selector).forEach(enhance);
  }
  discover();
  // The page picker is created anew on each opening.
  new MutationObserver(discover).observe(document.body, { childList: true, subtree: true });
})();
