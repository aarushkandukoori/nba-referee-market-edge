(() => {
  const bar = document.getElementById("bar");
  const scenes = [...document.querySelectorAll(".scene")];

  const onScroll = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const t = max > 0 ? window.scrollY / max : 0;
    if (bar) bar.style.width = `${t * 100}%`;
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // Scene enter animations
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.classList.add("in-view");
          // count-up once
          e.target.querySelectorAll(".count:not(.done)").forEach(animateCount);
        }
      }
    },
    { threshold: 0.45 }
  );
  scenes.forEach((s) => io.observe(s));

  function animateCount(el) {
    el.classList.add("done");
    const to = Number(el.dataset.to);
    const decimals = Number(el.dataset.decimals || 0);
    if (!Number.isFinite(to)) return;
    const start = performance.now();
    const dur = 900;
    const tick = (now) => {
      const u = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - u, 3);
      const val = to * eased;
      el.textContent = decimals ? val.toFixed(decimals) : String(Math.round(val));
      if (u < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
})();
