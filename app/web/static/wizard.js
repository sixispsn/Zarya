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

  const uploadInput = document.querySelector("[data-upload-input]");
  const uploadZone = document.querySelector("[data-upload-zone]");
  const uploadLabel = document.querySelector("[data-upload-label]");
  const uploadForm = document.querySelector("form[data-analysis-upload]");
  const updateUploadLabel = () => {
    if (!uploadInput || !uploadLabel) return;
    const files = [...uploadInput.files];
    if (!files.length) {
      uploadLabel.textContent = "Можно загрузить ПЗ, расчёты, спецификацию, схемы и заключение одним комплектом";
      return;
    }
    const bytes = files.reduce((total, file) => total + file.size, 0);
    const megabytes = (bytes / 1024 / 1024).toLocaleString("ru-RU", {
      maximumFractionDigits: 1
    });
    uploadLabel.textContent = `${files.length} файл(а) · ${megabytes} МБ`;
  };
  uploadInput?.addEventListener("change", updateUploadLabel);
  ["dragenter", "dragover"].forEach((name) => {
    uploadZone?.addEventListener(name, (event) => {
      event.preventDefault();
      uploadZone.classList.add("is-dragging");
    });
  });
  uploadZone?.addEventListener("dragleave", () => {
    uploadZone.classList.remove("is-dragging");
  });
  uploadZone?.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadZone.classList.remove("is-dragging");
    if (uploadInput && event.dataTransfer?.files?.length) {
      uploadInput.files = event.dataTransfer.files;
      updateUploadLabel();
    }
  });
  uploadForm?.addEventListener("submit", () => {
    const button = uploadForm.querySelector("button[type='submit']");
    if (!button) return;
    button.disabled = true;
    button.textContent = "Анализируем комплект…";
    uploadForm.setAttribute("aria-busy", "true");
  });

  const requiredControls = [...document.querySelectorAll("[data-required-rule]")];
  const fireModeControl = document.querySelector('[name="fire_mode"]');
  const buildingTypeControl = document.querySelector('[name="building_type"]');
  const fireCategoryControl = document.querySelector('[name="fire_category"]');
  const totalAreaControl = document.querySelector('[name="total_area"]');
  const requiredLamp = (control) =>
    document.querySelector(`[data-required-for="${control.name}"]`);
  const positiveNumber = (control) => {
    const value = Number.parseFloat((control.value || "").replace(",", "."));
    return Number.isFinite(value) && value > 0;
  };
  const requiredIsActive = (control) => {
    const rule = control.dataset.requiredRule;
    if (rule === "fire-auto") {
      return (fireModeControl?.value || "auto") === "auto";
    }
    if (rule === "fire-category-auto") {
      if ((fireModeControl?.value || "auto") !== "auto") return false;
      const hasPublicPart = [...document.querySelectorAll("[data-consumer-select]")]
        .some((select) =>
          select.selectedOptions[0]?.dataset.purpose === "public"
        );
      return buildingTypeControl?.value === "public"
        || (buildingTypeControl?.value === "residential" && hasPublicPart);
    }
    if (rule === "fire-theatre") {
      return (fireModeControl?.value || "auto") === "auto"
        && fireCategoryControl?.value === "theatre_f21";
    }
    if (rule === "fire-area") {
      return (fireModeControl?.value || "auto") === "auto"
        && fireCategoryControl?.value === "library_sport"
        && !positiveNumber(totalAreaControl);
    }
    if (rule === "fire-manual") {
      return fireModeControl?.value === "manual";
    }
    return true;
  };
  const requiredIsValid = (control) => {
    const rule = control.dataset.requiredRule;
    if (["nonempty", "fire-category-auto"].includes(rule)) {
      return Boolean(control.value.trim());
    }
    if (rule === "fire-manual") {
      return ["1", "2"].includes(control.value.trim());
    }
    return positiveNumber(control);
  };
  const syncRequiredFields = () => {
    let firstMissing = null;
    requiredControls.forEach((control) => {
      const active = requiredIsActive(control);
      const valid = !active || requiredIsValid(control);
      const lamp = requiredLamp(control);
      control.required = active;
      control.setAttribute("aria-required", String(active));
      control.dataset.requiredActive = String(active);
      if (active && !valid) {
        const message = control.dataset.requiredRule === "fire-manual"
          ? "В ручном режиме задайте 1 или 2 расчётные струи."
          : control.dataset.requiredRule === "fire-category-auto"
            ? "Выберите функциональную категорию по таблице 7.1 СП 10."
            : control.dataset.requiredRule === "fire-theatre"
              ? "Для строки Ф2.1 задайте вместимость зала."
              : control.dataset.requiredRule === "fire-area"
                ? "Для строки 5 задайте площадь расчётной части или общую площадь здания."
            : control.dataset.requiredRule === "nonempty"
              ? "Выберите значение — без него расчёт не запускается."
              : "Введите положительное значение — без него расчёт не запускается.";
        control.setCustomValidity(message);
        if (!firstMissing) firstMissing = control;
      } else {
        control.setCustomValidity("");
      }
      if (lamp) {
        lamp.hidden = !active;
        lamp.classList.toggle("is-complete", active && valid);
        lamp.title = valid
          ? "Обязательное поле заполнено"
          : "Обязательно для запуска расчёта";
      }
    });
    document.querySelectorAll(".input-section").forEach((section) => {
      const missing = [...section.querySelectorAll("[data-required-active='true']")]
        .some((control) => !requiredIsValid(control));
      section.dataset.requiredMissing = String(missing);
    });
    return firstMissing;
  };
  requiredControls.forEach((control) => {
    control.addEventListener("input", syncRequiredFields);
    control.addEventListener("change", syncRequiredFields);
  });
  fireModeControl?.addEventListener("change", syncRequiredFields);
  totalAreaControl?.addEventListener("input", syncRequiredFields);
  syncRequiredFields();

  // Готовность принципиальной схемы К1 не блокирует формирование ПЗ. Если
  // проектные отметки или уклон отсутствуют, генератор оставляет их пустыми.
  const basementFloorControl = document.querySelector(
    '[name="wastewater_basement_floor_elevation_m"]'
  );
  const basementFloorLamp = document.querySelector(
    '[data-completeness-for="wastewater_basement_floor_elevation_m"]'
  );
  const outletRegistryLamp = document.querySelector(
    "[data-wastewater-outlet-registry-lamp]"
  );
  const finiteNumber = (control) => {
    if (!control || !control.value.trim()) return false;
    return Number.isFinite(
      Number.parseFloat(control.value.trim().replace(",", "."))
    );
  };
  const positiveFiniteNumber = (control) =>
    finiteNumber(control)
    && Number.parseFloat(control.value.trim().replace(",", ".")) > 0;
  const setCompletenessLamp = (lamp, complete, title) => {
    if (!lamp) return;
    lamp.hidden = false;
    lamp.classList.toggle("is-complete", complete);
    lamp.title = title;
  };
  const syncWastewaterSchemeCompleteness = () => {
    const floorComplete = finiteNumber(basementFloorControl)
      && Number.parseFloat(
        basementFloorControl.value.trim().replace(",", ".")
      ) < 0;
    setCompletenessLamp(
      basementFloorLamp,
      floorComplete,
      floorComplete
        ? "Отметка пола подвала задана"
        : "Нужна относительная отметка чистого пола подвала ниже ±0,000"
    );

    const pipeRows = [...document.querySelectorAll(
      'input[name^="sewer_pipe"][name$="_id"]'
    )].map((idControl) => ({
      row: idControl.closest("tr"),
      idControl,
    })).filter(({ row }) => row);
    const linkedSections = new Set();
    document.querySelectorAll(
      'select[name^="sewer_element"][name$="_kind"]'
    ).forEach((kindControl) => {
      if (kindControl.value !== "outlet") return;
      const prefix = kindControl.name.slice(0, -"_kind".length);
      const sectionControl = document.querySelector(`[name="${prefix}_section"]`);
      const section = sectionControl?.value.trim().toLocaleLowerCase("ru-RU");
      if (section) linkedSections.add(section);
    });

    let outletRows = [];
    if (linkedSections.size) {
      outletRows = pipeRows.filter(({ idControl }) =>
        linkedSections.has(idControl.value.trim().toLocaleLowerCase("ru-RU"))
      );
    } else {
      outletRows = pipeRows.filter(({ row }) => {
        const purpose = row.querySelector('[name$="_purpose"]')?.value || "";
        return purpose.toLocaleLowerCase("ru-RU").includes("выпуск");
      });
    }

    pipeRows.forEach(({ row }) => {
      row.querySelectorAll("[data-outlet-completeness-lamp]").forEach((lamp) => {
        lamp.hidden = true;
        lamp.classList.remove("is-complete");
      });
    });

    const unambiguous = linkedSections.size <= 1 && outletRows.length === 1;
    let outletComplete = false;
    outletRows.forEach(({ row }) => {
      const slope = row.querySelector('[data-outlet-completeness-value="slope"]');
      const invert = row.querySelector('[data-outlet-completeness-value="invert"]');
      const dn = row.querySelector('[data-outlet-completeness-value="dn"]');
      const slopeComplete = unambiguous && positiveFiniteNumber(slope);
      const invertComplete = unambiguous && finiteNumber(invert);
      const dnComplete = unambiguous && positiveFiniteNumber(dn);
      setCompletenessLamp(
        row.querySelector('[data-outlet-completeness-lamp="dn"]'),
        dnComplete,
        dnComplete ? "Номинальный диаметр выпуска задан" : "Задайте DN выпуска"
      );
      setCompletenessLamp(
        row.querySelector('[data-outlet-completeness-lamp="slope"]'),
        slopeComplete,
        slopeComplete ? "Уклон выпуска задан" : "Задайте положительный уклон выпуска"
      );
      setCompletenessLamp(
        row.querySelector('[data-outlet-completeness-lamp="invert"]'),
        invertComplete,
        invertComplete ? "Отметка лотка выпуска задана" : "Задайте относительную отметку конца выпуска"
      );
      outletComplete = dnComplete && slopeComplete && invertComplete;
    });

    const registryComplete = unambiguous && outletComplete;
    const registryTitle = registryComplete
      ? "Выпуск К1 однозначно определён; уклон и отметка лотка заданы"
      : linkedSections.size > 1 || outletRows.length > 1
        ? "Несколько выпусков К1: свяжите лист стояка с одним участком"
        : outletRows.length === 0
          ? "Добавьте элемент типа «выпуск» с участком или единственную трубу с назначением «выпуск»"
          : "Для выпуска К1 заполните DN, уклон и относительную отметку конца";
    setCompletenessLamp(outletRegistryLamp, registryComplete, registryTitle);
    outletRegistryLamp?.closest(".technical-label")?.setAttribute(
      "data-wastewater-outlet-status",
      registryComplete ? "complete" : "missing"
    );
  };
  document.querySelectorAll(
    '[name="wastewater_basement_floor_elevation_m"], '
    + '[name^="sewer_pipe"], [name^="sewer_element"]'
  ).forEach((control) => {
    control.addEventListener("input", syncWastewaterSchemeCompleteness);
    control.addEventListener("change", syncWastewaterSchemeCompleteness);
  });
  syncWastewaterSchemeCompleteness();

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
    if (select) {
      select.addEventListener("input", () => {
        updateConsumerUnit(row);
        syncRequiredFields();
      });
    }
    const remove = row.querySelector(".consumer-remove");
    if (remove) remove.addEventListener("click", () => {
      if (consumerRows.querySelectorAll("[data-consumer-row]").length <= 1) return;
      row.remove();
      markChanged(consumerRows);
      runAdvisories();
      syncRequiredFields();
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
      syncRequiredFields();
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
    const fireCategory = document.querySelector('[name="fire_category"]')?.value || "";
    const buildingType = document.querySelector('[name="building_type"]')?.value;
    const purposes = new Set(
      [...document.querySelectorAll("[data-consumer-select]")]
        .map((select) => select.selectedOptions[0]?.dataset.purpose)
        .filter(Boolean)
    );
    const advisories = [];
    if (fireMode === "auto" && !fireHeight) {
      advisories.push({
        level: "warning",
        message: "Укажите пожарно-техническую высоту по АР: без неё автоматическая проверка ВПВ невозможна.",
        reference: "СП 10.13130.2020, таблица 7.1"
      });
    } else if (fireMode === "auto" && buildingType === "residential"
        && floors < 12 && fireHeight >= 30) {
      advisories.push({
        level: "warning",
        message: `При ${floors} этажах ВПВ включается по пожарно-технической высоте ${fireHeight} м. Подтвердите показатель по АР.`,
        reference: "СП 10.13130.2020, таблица 7.1, строка 1"
      });
    }
    if (fireMode === "auto" && !fireCategory) {
      advisories.push({
        level: "warning",
        message: "Выберите диктующую функциональную категорию В2: Заря больше не подменяет общественное здание офисной строкой.",
        reference: "СП 10.13130.2020, таблица 7.1"
      });
    }
    if (buildingType === "residential" && height > 75) {
      advisories.push({
        level: "warning",
        message: `Жилое здание высотой ${height} м выше 75 м: СП 30 применяется совместно с СП 253.1325800.`,
        reference: "СП 30.13330.2020, п. 4.1"
      });
      advisories.push({
        level: "info",
        message: "Для высотного здания будут приняты раздельные В1/В2, изоляция 10/25 мм, 100%-ный резерв, частотный привод и диспетчеризация насосов.",
        reference: "СП 253.1325800.2016, пп. 10.3, 10.15, 10.23, 10.25, 10.27"
      });
    } else if (buildingType === "public" && height > 50) {
      advisories.push({
        level: "warning",
        message: `Общественное здание высотой ${height} м выше 50 м: СП 30 применяется совместно с СП 253.1325800.`,
        reference: "СП 30.13330.2020, п. 4.1"
      });
      advisories.push({
        level: "info",
        message: "Для высотного здания будут приняты раздельные В1/В2, изоляция 10/25 мм, 100%-ный резерв, частотный привод и диспетчеризация насосов.",
        reference: "СП 253.1325800.2016, пп. 10.3, 10.15, 10.23, 10.25, 10.27"
      });
    }
    const apartments = Number.parseInt(
      document.querySelector('[name="apartments"]')?.value || "0", 10
    ) || 0;
    if (buildingType === "residential" && apartments <= 0) {
      advisories.push({
        level: "info",
        message: "Задайте число квартир для квартирных кранов Ду15 со шлангом.",
        reference: "СП 54.13330.2022, п. 6.2.4.3"
      });
    }
    const roofType = document.querySelector('[name="roof_type"]')?.value || "not_set";
    const stormCity = document.querySelector('[name="storm_city"]')?.value || "";
    const roofAreaRaw = document.querySelector('[name="storm_roof_area"]')?.value || "0";
    const roofArea = Number.parseFloat(roofAreaRaw.replace(",", ".")) || 0;
    if (roofType !== "not_set" && (!stormCity || roofArea <= 0)) {
      advisories.push({
        level: "warning",
        message: "Для расчёта К2 задайте город и площадь кровли.",
        reference: "СП 30.13330.2020, раздел 21"
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

  const proofDialog = document.querySelector("[data-proof-dialog]");
  const proofPanels = proofDialog
    ? [...proofDialog.querySelectorAll("[data-proof-panel]")]
    : [];
  const proofClose = proofDialog?.querySelector("[data-proof-close]");
  let lastProofTrigger = null;
  const closeProof = () => {
    if (!proofDialog) return;
    if (typeof proofDialog.close === "function") proofDialog.close();
    else proofDialog.removeAttribute("open");
    lastProofTrigger?.focus();
  };
  const openProof = (id, trigger) => {
    if (!proofDialog) return;
    const selected = proofPanels.find((panel) => panel.dataset.proofPanel === id);
    if (!selected) return;
    proofPanels.forEach((panel) => { panel.hidden = panel !== selected; });
    lastProofTrigger = trigger;
    if (typeof proofDialog.showModal === "function") {
      if (!proofDialog.open) proofDialog.showModal();
    } else {
      proofDialog.setAttribute("open", "");
    }
    proofClose?.focus();
  };
  document.querySelectorAll("[data-proof-open]").forEach((trigger) => {
    trigger.addEventListener("click", () => openProof(trigger.dataset.proofOpen, trigger));
  });
  proofClose?.addEventListener("click", closeProof);
  proofDialog?.addEventListener("click", (event) => {
    if (event.target === proofDialog) closeProof();
  });
  proofDialog?.addEventListener("close", () => {
    proofPanels.forEach((panel) => { panel.hidden = true; });
  });

  const impactDialog = document.querySelector("[data-impact-dialog]");
  const impactOpen = document.querySelector("[data-impact-open]");
  const impactClose = impactDialog?.querySelector("[data-impact-close]");
  const impactForm = impactDialog?.querySelector("[data-impact-form]");
  const impactLoading = impactDialog?.querySelector("[data-impact-loading]");
  const impactError = impactDialog?.querySelector("[data-impact-error]");
  const impactResult = impactDialog?.querySelector("[data-impact-result]");
  let impactReturnFocus = null;
  const closeImpact = () => {
    if (!impactDialog) return;
    if (typeof impactDialog.close === "function") impactDialog.close();
    else impactDialog.removeAttribute("open");
    impactReturnFocus?.focus();
  };
  impactOpen?.addEventListener("click", () => {
    if (!impactDialog) return;
    impactReturnFocus = impactOpen;
    if (typeof impactDialog.showModal === "function") impactDialog.showModal();
    else impactDialog.setAttribute("open", "");
    impactDialog.querySelector("input:not(:disabled)")?.focus();
  });
  impactClose?.addEventListener("click", closeImpact);
  impactDialog?.addEventListener("click", (event) => {
    if (event.target === impactDialog) closeImpact();
  });

  const impactElement = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const renderImpact = (payload) => {
    if (!impactResult) return;
    const summary = impactResult.querySelector("[data-impact-summary]");
    const inputChanges = impactResult.querySelector("[data-impact-input-changes]");
    const deltas = impactResult.querySelector("[data-impact-deltas]");
    const documents = impactResult.querySelector("[data-impact-documents]");
    const warnings = impactResult.querySelector("[data-impact-warnings]");
    const fingerprints = impactResult.querySelector("[data-impact-fingerprints]");
    summary.replaceChildren();
    const headline = impactElement(
      "strong", "",
      payload.summary.results_changed
        ? `${payload.summary.results_changed} решений изменятся`
        : "Расчётные результаты не изменятся"
    );
    const summaryText = impactElement(
      "span", "",
      `${payload.summary.documents_affected} документов затронуто · ${payload.calculation_status}`
    );
    summary.append(headline, summaryText);

    inputChanges.replaceChildren();
    const inputTitle = impactElement("h3", "", "Изменённые исходные данные");
    inputChanges.append(inputTitle);
    if (!payload.input_changes.length) {
      inputChanges.append(impactElement("p", "impact-empty", "Значения совпадают с текущим проектом."));
    } else {
      const list = impactElement("div", "impact-change-chips");
      payload.input_changes.forEach((item) => {
        const chip = impactElement("span");
        const label = impactElement("b", "", item.label);
        const value = impactElement(
          "small", "",
          `${item.before}${item.unit ? ` ${item.unit}` : ""} → ${item.after}${item.unit ? ` ${item.unit}` : ""}`
        );
        chip.append(label, value);
        list.append(chip);
      });
      inputChanges.append(list);
    }

    deltas.replaceChildren();
    [...payload.deltas]
      .sort((left, right) => Number(right.changed) - Number(left.changed))
      .forEach((item) => {
        const row = impactElement("article", `impact-delta ${item.changed ? "changed" : "unchanged"}`);
        const system = impactElement("span", "proof-system", item.system);
        const copy = impactElement("div", "impact-delta-copy");
        copy.append(
          impactElement("b", "", item.label),
          impactElement("small", "", item.detail)
        );
        const values = impactElement("div", "impact-values");
        values.append(
          impactElement("span", "", item.before),
          impactElement("i", "", "→"),
          impactElement("strong", "", item.after),
          impactElement("small", "", item.unit)
        );
        const state = impactElement(
          "span",
          "impact-delta-state",
          item.changed ? "изменится" : "без изменений"
        );
        row.append(system, copy, values, state);
        deltas.append(row);
      });

    documents.replaceChildren();
    if (payload.affected_documents.length) {
      payload.affected_documents.forEach((name) => {
        documents.append(impactElement("span", "", name));
      });
    } else {
      documents.append(impactElement("span", "", "нет"));
    }
    warnings.replaceChildren();
    if (payload.warnings.length) {
      payload.warnings.forEach((warning) => {
        warnings.append(impactElement("li", "", warning));
      });
    } else {
      warnings.append(impactElement("li", "impact-ok", "Новых предупреждений нет."));
    }
    fingerprints.textContent =
      `ТЕКУЩИЙ ${payload.baseline_fingerprint} · ПРЕДПРОСМОТР ${payload.preview_fingerprint}`;
    impactResult.hidden = false;
    impactResult.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  impactForm?.addEventListener("reset", () => {
    setTimeout(() => {
      if (impactResult) impactResult.hidden = true;
      if (impactError) impactError.hidden = true;
    }, 0);
  });
  impactForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = impactForm.querySelector("button[type='submit']");
    const consumers = [...impactForm.querySelectorAll("[data-impact-consumer]:not(:disabled)")];
    const payload = {};
    if (consumers.length) {
      payload.consumer_counts = consumers
        .sort((left, right) => Number(left.dataset.impactConsumer) - Number(right.dataset.impactConsumer))
        .map((input) => Number.parseInt(input.value, 10));
    }
    impactForm.querySelectorAll("[data-impact-field]").forEach((input) => {
      if (input.value === "") return;
      const name = input.dataset.impactField;
      payload[name] = name === "floors"
        ? Number.parseInt(input.value, 10)
        : Number.parseFloat(input.value.replace(",", "."));
    });
    if (impactError) impactError.hidden = true;
    if (impactResult) impactResult.hidden = true;
    if (impactLoading) impactLoading.hidden = false;
    if (submit) {
      submit.disabled = true;
      submit.textContent = "Считаем…";
    }
    try {
      const response = await fetch(impactForm.dataset.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Предпросмотр не выполнен");
      renderImpact(result);
    } catch (error) {
      if (impactError) {
        impactError.textContent = error.message || "Предпросмотр не выполнен";
        impactError.hidden = false;
      }
    } finally {
      if (impactLoading) impactLoading.hidden = true;
      if (submit) {
        submit.disabled = false;
        submit.textContent = "Сравнить варианты";
      }
    }
  });

  const form = document.querySelector("form[data-design-form]");
  if (form) {
    form.addEventListener("submit", (event) => {
      const firstMissing = syncRequiredFields();
      if (firstMissing) {
        event.preventDefault();
        let ancestor = firstMissing.parentElement;
        while (ancestor) {
          if (ancestor.tagName === "DETAILS") ancestor.open = true;
          ancestor = ancestor.parentElement;
        }
        firstMissing.focus();
        firstMissing.reportValidity();
        return;
      }
      const button = form.querySelector("button[type='submit']");
      if (!button) return;
      button.disabled = true;
      button.textContent = "Собираем ИОС2 + ИОС3…";
      form.setAttribute("aria-busy", "true");
    });
  }
});
