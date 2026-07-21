document.addEventListener("DOMContentLoaded", () => {
  const links = [...document.querySelectorAll(".stepnav a[href^='#']")];
  const sections = links
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  links.forEach((link) => link.addEventListener("click", () => {
    const section = document.querySelector(link.getAttribute("href"));
    const details = section?.querySelector("details");
    if (details) details.open = true;
  }));

  document.querySelectorAll(".input-section").forEach((details) => {
    details.querySelectorAll("input, select").forEach((control) => {
      control.addEventListener("input", () => {
        const state = details.querySelector(".accepted");
        if (!state) return;
        state.textContent = "изменено";
        state.classList.add("changed");
      });
    });
  });

  if (links.length && sections.length && "IntersectionObserver" in window) {
    const activate = (id) => links.forEach((link) => {
      link.classList.toggle("active", link.getAttribute("href") === `#${id}`);
    });
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) activate(visible.target.id);
    }, { rootMargin: "-90px 0px -65%", threshold: [0.05, 0.2, 0.5] });
    sections.forEach((section) => observer.observe(section));
  }

  const form = document.querySelector("form[data-design-form]");
  if (form) {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type='submit']");
      if (!button) return;
      button.disabled = true;
      button.textContent = "Собираем комплект…";
      form.setAttribute("aria-busy", "true");
    });
  }
});
