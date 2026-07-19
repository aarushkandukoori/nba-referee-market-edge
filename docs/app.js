(() => {
  const progress = document.querySelector(".scroll-progress i");
  const ticker = document.getElementById("ticker");

  // Market-tape atmosphere for the hero (visual only)
  if (ticker) {
    const bits = [
      "KXNBATOTAL", "O/U 229.5", "CREW·FOUL+", "PACE 98.4", "FTA↑",
      "WALK-FORWARD", "PERMUTATION", "PRE-TIP 0.64", "NULL", "LOGLOSS",
      "POLYMARKET", "SHRINKAGE", "NO LEAKAGE", "Δ +0.00038", "p≈0.57",
    ];
    const line = Array(8).fill(bits.join("   ·   ")).join("   ·   ");
    ticker.textContent = line + "   ·   " + line;
  }

  const onScroll = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const p = max > 0 ? window.scrollY / max : 0;
    if (progress) progress.style.width = `${Math.min(1, Math.max(0, p)) * 100}%`;
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // Reveal checklist / rail cards
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) e.target.classList.add("in");
      }
    },
    { threshold: 0.25, rootMargin: "0px 0px -8% 0px" }
  );
  document.querySelectorAll(".rail-card, .checklist li").forEach((el) => io.observe(el));

  // Count-up stats
  const animateCount = (el) => {
    const target = Number(el.dataset.count);
    if (!Number.isFinite(target)) return;
    const dur = 1100;
    const start = performance.now();
    const step = (t) => {
      const u = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - u, 3);
      el.textContent = Math.round(target * eased).toLocaleString("en-US");
      if (u < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };

  const animateFloat = (el) => {
    const target = Number(el.dataset.countFloat);
    if (!Number.isFinite(target)) return;
    const dur = 900;
    const start = performance.now();
    const step = (t) => {
      const u = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - u, 3);
      el.textContent = (target * eased).toFixed(2);
      if (u < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };

  const countIo = new IntersectionObserver(
    (entries, obs) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        if (e.target.dataset.count != null) animateCount(e.target);
        if (e.target.dataset.countFloat != null) animateFloat(e.target);
        obs.unobserve(e.target);
      }
    },
    { threshold: 0.5 }
  );
  document.querySelectorAll("[data-count], [data-count-float]").forEach((el) => countIo.observe(el));

  // Soft parallax on hero court lines
  const court = document.querySelector(".court-lines");
  if (court) {
    window.addEventListener(
      "scroll",
      () => {
        const y = Math.min(window.scrollY, window.innerHeight);
        court.style.transform = `translateY(${y * 0.12}px)`;
      },
      { passive: true }
    );
  }
})();
