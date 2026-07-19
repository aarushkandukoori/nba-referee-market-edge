(() => {
  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scenes = [...document.querySelectorAll(".scene")];
  const progress = document.getElementById("progress");
  const dots = document.getElementById("dots");

  scenes.forEach((scene, i) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("aria-label", `Go to chapter ${scene.dataset.chapter || i + 1}`);
    btn.addEventListener("click", () => {
      scene.scrollIntoView({ behavior: prefersReduced ? "auto" : "smooth" });
    });
    li.appendChild(btn);
    dots.appendChild(li);
  });

  const dotButtons = [...dots.querySelectorAll("button")];

  const setActive = (index) => {
    dotButtons.forEach((btn, i) => btn.classList.toggle("is-active", i === index));
  };

  const onScrollProgress = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const pct = max > 0 ? (window.scrollY / max) * 100 : 0;
    if (progress) progress.style.height = `${pct}%`;

    let active = 0;
    scenes.forEach((scene, i) => {
      const rect = scene.getBoundingClientRect();
      if (rect.top <= window.innerHeight * 0.45) active = i;
    });
    setActive(active);
  };

  window.addEventListener("scroll", onScrollProgress, { passive: true });
  onScrollProgress();

  if (prefersReduced || !window.gsap || !window.ScrollTrigger) {
    document.querySelectorAll(".reveal").forEach((el) => {
      el.style.opacity = "1";
      el.style.transform = "none";
    });
    return;
  }

  gsap.registerPlugin(ScrollTrigger);

  gsap.utils.toArray(".scene").forEach((scene) => {
    const reveals = scene.querySelectorAll(".reveal");
    gsap.fromTo(
      reveals,
      { autoAlpha: 0, y: 56, rotateX: 8 },
      {
        autoAlpha: 1,
        y: 0,
        rotateX: 0,
        duration: 1.05,
        ease: "power3.out",
        stagger: 0.1,
        scrollTrigger: {
          trigger: scene,
          start: "top 72%",
          toggleActions: "play none none reverse",
        },
      }
    );
  });

  gsap.fromTo(
    ".mega__line",
    { yPercent: 110 },
    {
      yPercent: 0,
      duration: 1.15,
      ease: "power4.out",
      stagger: 0.12,
      delay: 0.1,
    }
  );

  const counters = document.querySelectorAll("[data-count]");
  counters.forEach((el) => {
    const end = Number(el.dataset.count);
    const decimals = Number(el.dataset.decimals || 0);
    const prefix = el.dataset.prefix || "";
    const suffix = el.dataset.suffix || "";
    const obj = { v: 0 };

    ScrollTrigger.create({
      trigger: el,
      start: "top 80%",
      once: true,
      onEnter: () => {
        gsap.to(obj, {
          v: end,
          duration: 1.6,
          ease: "power2.out",
          onUpdate: () => {
            const value =
              decimals > 0 ? obj.v.toFixed(decimals) : Math.round(obj.v).toLocaleString();
            el.textContent = `${prefix}${value}${suffix}`;
          },
        });
      },
    });
  });

  gsap.to(".court-lines", {
    backgroundPosition: "0 120px, 0 0, 0 240px",
    ease: "none",
    scrollTrigger: {
      trigger: document.body,
      start: "top top",
      end: "bottom bottom",
      scrub: true,
    },
  });

  gsap.utils.toArray(".duel__card").forEach((card) => {
    gsap.fromTo(
      card,
      { scale: 0.92, filter: "blur(6px)" },
      {
        scale: 1,
        filter: "blur(0px)",
        duration: 1,
        ease: "power3.out",
        scrollTrigger: {
          trigger: card,
          start: "top 78%",
          toggleActions: "play none none reverse",
        },
      }
    );
  });

  gsap.utils.toArray(".pipe").forEach((pipe, i) => {
    gsap.fromTo(
      pipe,
      { y: 40, autoAlpha: 0 },
      {
        y: 0,
        autoAlpha: 1,
        duration: 0.8,
        delay: i * 0.05,
        ease: "power2.out",
        scrollTrigger: {
          trigger: "#pipeline",
          start: "top 75%",
          toggleActions: "play none none reverse",
        },
      }
    );
  });

  const title = document.querySelector(".scene--verdict .mega");
  if (title) {
    gsap.fromTo(
      title,
      { scale: 0.86, letterSpacing: "0.12em" },
      {
        scale: 1,
        letterSpacing: "-0.02em",
        ease: "none",
        scrollTrigger: {
          trigger: ".scene--verdict",
          start: "top 70%",
          end: "center center",
          scrub: true,
        },
      }
    );
  }
})();
