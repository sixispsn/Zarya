document.addEventListener("DOMContentLoaded", () => {
  const root = document.documentElement;
  const themeButtons = document.querySelectorAll("[data-theme-toggle]");
  const renderTheme = () => {
    const dark = root.dataset.theme !== "light";
    themeButtons.forEach((button) => {
      const label = button.querySelector("[data-theme-label]");
      if (label) label.textContent = dark ? "Светлая" : "Тёмная";
      button.setAttribute("aria-pressed", String(!dark));
    });
  };
  themeButtons.forEach((button) => button.addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
    try { localStorage.setItem("zarya-theme", root.dataset.theme); } catch (_) { /* local only */ }
    renderTheme();
  }));
  renderTheme();

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

  let runAdvisories = () => {};
  const bindControl = (control) => {
    if (control.dataset.changeBound) return;
    control.dataset.changeBound = "true";
    control.addEventListener("input", () => {
      markChanged(control);
      runAdvisories();
    });
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
      runAdvisories();
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
      runAdvisories();
    });
  }

  const validationPanel = document.querySelector("[data-validation-panel]");
  const validationList = document.querySelector("[data-validation-list]");
  const validationCount = document.querySelector("[data-validation-count]");
  runAdvisories = () => {
    if (!validationPanel || !validationList || !validationCount) return;
    const heightRaw = document.querySelector('[name="height"]')?.value || "0";
    const height = Number.parseFloat(heightRaw.replace(",", ".")) || 0;
    const floors = Number.parseInt(
      document.querySelector('[name="floors"]')?.value || "0", 10
    ) || 0;
    const fireHeightRaw = document.querySelector('[name="fire_height"]')?.value || "0";
    const fireHeight = Number.parseFloat(fireHeightRaw.replace(",", ".")) || 0;
    const fireMode = document.querySelector('[name="fire_mode"]')?.value || "auto";
    const buildingType = document.querySelector('[name="building_type"]')?.value;
    const purposes = new Set(
      [...document.querySelectorAll("[data-consumer-select]")]
        .map((select) => select.selectedOptions[0]?.dataset.purpose)
        .filter(Boolean)
    );
    const advisories = [];
    if (fireMode === "auto" && buildingType === "residential"
        && floors < 12 && fireHeight > 30) {
      advisories.push({
        level: "warning",
        message: `При ${floors} этажах ВПВ включается по пожарно-технической высоте ${fireHeight} м. Подтвердите показатель по АР.`,
        reference: "СП 10.13130.2020, таблица 7.1, строка 1"
      });
    }
    if (buildingType === "residential" && height > 75) {
      advisories.push({
        level: "warning",
        message: `Жилое здание высотой ${height} м выше 75 м: СП 30 применяется совместно с СП 253.1325800.`,
        reference: "СП 30.13330.2020, п. 4.1"
      });
    } else if (buildingType === "public" && height > 50) {
      advisories.push({
        level: "warning",
        message: `Общественное здание высотой ${height} м выше 50 м: СП 30 применяется совместно с СП 253.1325800.`,
        reference: "СП 30.13330.2020, п. 4.1"
      });
    }
    const mixed = purposes.size > 1;
    const mismatch = purposes.size > 0
      && ["residential", "public"].includes(buildingType)
      && !purposes.has(buildingType);
    if (mixed || mismatch) {
      advisories.push({
        level: "info",
        message: "Обнаружен смешанный функциональный состав. Подтвердите назначение частей и пожарные отсеки по АР/ТЗ; расход В2 проверяется отдельно для соответствующих частей.",
        reference: "СП 30.13330.2020, пп. 1.1, 7.5–7.6"
      });
    }
    validationList.replaceChildren(...advisories.map((item) => {
      const li = document.createElement("li");
      li.dataset.level = item.level;
      const message = document.createElement("span");
      message.textContent = item.message;
      const reference = document.createElement("small");
      reference.textContent = item.reference;
      li.append(message, reference);
      return li;
    }));
    validationCount.textContent = String(advisories.length);
    validationPanel.hidden = advisories.length === 0;
  };
  runAdvisories();

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
