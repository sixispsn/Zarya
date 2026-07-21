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

  const markChanged = (control) => {
    const details = control.closest(".input-section");
    const state = details?.querySelector(".accepted");
    if (!state) return;
    state.textContent = "изменено";
    state.classList.add("changed");
  };

  const bindControl = (control) => {
    if (control.dataset.changeBound) return;
    control.dataset.changeBound = "true";
    control.addEventListener("input", () => markChanged(control));
  };
  document.querySelectorAll(".input-section input, .input-section select")
    .forEach(bindControl);

  const consumerRows = document.querySelector("#consumer-rows");
  const consumerTemplate = document.querySelector("#consumer-row-template");
  const addConsumer = document.querySelector("#add-consumer");

  const updateConsumerUnit = (row) => {
    const select = row.querySelector("[data-consumer-select]");
    const unit = row.querySelector("[data-consumer-unit]");
    if (!select || !unit) return;
    unit.textContent = select.selectedOptions[0]?.dataset.unit || "—";
  };
  const bindConsumerRow = (row) => {
    row.querySelectorAll("input, select").forEach(bindControl);
    const select = row.querySelector("[data-consumer-select]");
    if (select) select.addEventListener("input", () => updateConsumerUnit(row));
    const remove = row.querySelector(".consumer-remove");
    if (remove) remove.addEventListener("click", () => {
      if (consumerRows.querySelectorAll("[data-consumer-row]").length <= 1) return;
      row.remove();
      markChanged(consumerRows);
    });
    updateConsumerUnit(row);
  };
  consumerRows?.querySelectorAll("[data-consumer-row]").forEach(bindConsumerRow);

  if (addConsumer && consumerRows && consumerTemplate) {
    addConsumer.addEventListener("click", () => {
      const used = [...consumerRows.querySelectorAll("[data-consumer-row]")]
        .map((row) => Number(row.querySelector("[name*='_code']")?.name.match(/consumer(\d+)_/)?.[1] || 0));
      const index = Array.from({ length: 12 }, (_, i) => i + 1)
        .find((candidate) => !used.includes(candidate));
      if (!index) return;
      const wrapper = document.createElement("div");
      wrapper.innerHTML = consumerTemplate.innerHTML.replaceAll("__INDEX__", String(index)).trim();
      const row = wrapper.firstElementChild;
      consumerRows.appendChild(row);
      bindConsumerRow(row);
      row.querySelector("input")?.focus();
      markChanged(row);
    });
  }

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
