(() => {
  const beats = [...document.querySelectorAll(".beat")];
  const bar = document.getElementById("bar");
  const ball = document.getElementById("ball");
  const refs = document.getElementById("refs");
  const board = document.getElementById("board");
  const totalEl = document.getElementById("total");
  const subEl = document.getElementById("sub");
  const splash = document.getElementById("splash");
  const hoop = document.querySelector(".hoop");

  // Ball path keyframes as fractions of scroll through the film (0..1)
  // [x%, y%, rotate deg, scale]
  const path = [
    { t: 0.00, x: 18, y: 72, r: 0,   s: 1 },    // intro dribble start
    { t: 0.10, x: 28, y: 58, r: 90,  s: 1 },
    { t: 0.18, x: 40, y: 70, r: 180, s: 1 },    // bounce
    { t: 0.26, x: 48, y: 55, r: 270, s: 1 },
    { t: 0.34, x: 50, y: 68, r: 360, s: 1 },    // refs arrive
    { t: 0.46, x: 62, y: 50, r: 480, s: 1 },    // market board
    { t: 0.58, x: 55, y: 42, r: 600, s: 0.95 }, // gather
    { t: 0.70, x: 50, y: 22, r: 780, s: 0.85 }, // shot rising
    { t: 0.78, x: 50, y: 10, r: 900, s: 0.75 }, // rim
    { t: 0.86, x: 58, y: 28, r: 1020,s: 0.9 },  // miss / iron
    { t: 0.94, x: 70, y: 78, r: 1200,s: 1 },    // bounce out
    { t: 1.00, x: 78, y: 86, r: 1320,s: 1 },
  ];

  const lerp = (a, b, u) => a + (b - a) * u;

  function samplePath(t) {
    const clamped = Math.min(1, Math.max(0, t));
    let i = 0;
    while (i < path.length - 1 && path[i + 1].t < clamped) i++;
    const a = path[i];
    const b = path[Math.min(i + 1, path.length - 1)];
    const span = b.t - a.t || 1;
    const u = (clamped - a.t) / span;
    // ease in-out for smoother "film"
    const e = u * u * (3 - 2 * u);
    return {
      x: lerp(a.x, b.x, e),
      y: lerp(a.y, b.y, e),
      r: lerp(a.r, b.r, e),
      s: lerp(a.s, b.s, e),
    };
  }

  function setBall(t) {
    const p = samplePath(t);
    // subtle vertical bounce overlay early in the story
    const bounce = t < 0.4 ? Math.abs(Math.sin(t * Math.PI * 10)) * 2.5 : 0;
    ball.style.transform = `translate(${p.x}vw, ${p.y - bounce}vh) rotate(${p.r}deg) scale(${p.s})`;
  }

  function setScene(t, beat) {
    // refs walk on mid-story
    refs.classList.toggle("on", t > 0.28 && t < 0.82);
    // scoreboard during market / test chapters
    board.classList.toggle("on", t > 0.40 && t < 0.92);

    if (t > 0.40 && t < 0.55) {
      totalEl.textContent = "228.5";
      subEl.textContent = "market line";
    } else if (t >= 0.55 && t < 0.72) {
      totalEl.textContent = "P(over)";
      subEl.textContent = "baseline vs treatment";
    } else if (t >= 0.72) {
      totalEl.textContent = "NULL";
      subEl.textContent = "p ≈ 0.57 · no edge";
    }

    // rim flash / splash on the miss
    if (t > 0.76 && t < 0.84) {
      splash.style.opacity = String(1 - Math.abs(t - 0.80) * 12);
      splash.style.width = "40vmin";
      splash.style.height = "40vmin";
      if (hoop) hoop.style.opacity = "1";
    } else {
      splash.style.opacity = "0";
    }

    // dim court slightly at the end
    document.body.style.setProperty(
      "--floor",
      t > 0.88 ? "#b89768" : "#c4a574"
    );
  }

  function activeBeat() {
    const mid = window.scrollY + window.innerHeight * 0.62;
    let best = 0;
    let bestDist = Infinity;
    beats.forEach((el, i) => {
      const rect = el.getBoundingClientRect();
      const center = window.scrollY + rect.top + rect.height * 0.55;
      const d = Math.abs(center - mid);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    return best;
  }

  function onScroll() {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const t = max > 0 ? window.scrollY / max : 0;
    if (bar) bar.style.width = `${t * 100}%`;

    const idx = activeBeat();
    beats.forEach((el, i) => el.classList.toggle("active", i === idx));

    setBall(t);
    setScene(t, idx);
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  onScroll();
})();
