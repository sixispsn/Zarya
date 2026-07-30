document.addEventListener("DOMContentLoaded", () => {
  const dataNode = document.getElementById("defense-data");
  if (!dataNode) return;
  const payload = JSON.parse(dataNode.textContent);
  const decisions = payload.decisions || [];
  const byId = new Map(decisions.map((item) => [item.id, item]));
  const buttons = [...document.querySelectorAll("[data-defense-decision]")];
  const status = document.querySelector("[data-defense-status]");
  const system = document.querySelector("[data-defense-system]");
  const title = document.querySelector("[data-defense-title]");
  const summary = document.querySelector("[data-defense-summary]");
  const value = document.querySelector("[data-defense-value]");
  const unit = document.querySelector("[data-defense-unit]");
  const chain = document.querySelector("[data-defense-chain]");
  const documents = document.querySelector("[data-defense-documents]");
  const viewer = document.querySelector("[data-defense-viewer]");
  const viewerEmpty = document.querySelector("[data-defense-viewer-empty]");
  const viewerCaption = document.querySelector("[data-defense-viewer-caption]");
  const viewerOpen = document.querySelector("[data-defense-viewer-open]");
  const question = document.querySelector("[data-defense-question]");
  const answerId = document.querySelector("[data-defense-answer-id]");
  let activeDecision = null;

  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const openDocument = (document, trigger) => {
    if (!document || !viewer) return;
    const fragment = document.page
      ? `#page=${document.page}&zoom=page-width`
      : "#zoom=page-width";
    const url = `${document.view_url}${fragment}`;
    viewer.src = url;
    viewer.hidden = false;
    if (viewerEmpty) viewerEmpty.hidden = true;
    if (viewerCaption) {
      viewerCaption.textContent = document.page
        ? `${document.label} · стр. ${document.page} из ${document.page_count}`
        : `${document.label} · страница требует просмотра`;
    }
    if (viewerOpen) viewerOpen.href = url;
    documents?.querySelectorAll("button").forEach((button) => {
      button.classList.toggle("active", button === trigger);
    });
  };

  const renderDecision = (id, updateHash = true) => {
    const item = byId.get(id);
    if (!item) return;
    activeDecision = item;
    buttons.forEach((button) => {
      button.classList.toggle("active", button.dataset.defenseDecision === id);
    });
    status.textContent = item.status_label;
    status.dataset.status = item.status;
    system.textContent = `${item.system} · проектное решение`;
    title.textContent = item.title;
    summary.textContent = item.summary;
    value.textContent = item.value;
    unit.textContent = item.unit;
    if (question) question.value = item.default_question;
    if (answerId) answerId.value = item.id;

    chain.replaceChildren();
    item.steps.forEach((step, index) => {
      const row = element("li");
      row.dataset.kind = step.kind;
      const number = element("span", "", String(index + 1).padStart(2, "0"));
      const kind = element("small", "", step.kind_label);
      const copy = element("div");
      copy.append(
        element("b", "", step.label),
        element("strong", "", step.value)
      );
      if (step.detail) copy.append(element("p", "", step.detail));
      row.append(number, kind, copy);
      chain.append(row);
    });

    documents.replaceChildren();
    if (item.documents.length) {
      item.documents.forEach((doc, index) => {
        const button = element("button");
        button.type = "button";
        button.append(
          element("span", "", doc.page ? `PDF · ${doc.page}` : "PDF"),
          document.createTextNode(doc.label)
        );
        button.addEventListener("click", () => openDocument(doc, button));
        documents.append(button);
        if (index === 0) openDocument(doc, button);
      });
    } else {
      documents.append(element(
        "span",
        "defense-no-document",
        "Связанный PDF в текущем комплекте не сформирован."
      ));
      if (viewer) {
        viewer.hidden = true;
        viewer.removeAttribute("src");
      }
      if (viewerEmpty) viewerEmpty.hidden = false;
      if (viewerCaption) viewerCaption.textContent = "Документ отсутствует в выпуске";
      if (viewerOpen) viewerOpen.removeAttribute("href");
    }
    if (updateHash) history.replaceState(null, "", `#${encodeURIComponent(id)}`);
  };

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      renderDecision(button.dataset.defenseDecision);
      document.querySelector(".defense-proof")?.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    });
  });

  document.querySelectorAll("[data-defense-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      const item = byId.get(button.dataset.defensePreset);
      if (!item) return;
      renderDecision(item.id);
      question?.focus();
    });
  });

  document.querySelector("[data-defense-find]")?.addEventListener("click", () => {
    const query = (question?.value || "").toLocaleLowerCase("ru").replaceAll("ё", "е");
    if (!query.trim()) return;
    let best = activeDecision;
    let bestScore = 0;
    decisions.forEach((item) => {
      const score = (item.keywords || []).reduce(
        (total, keyword) => total + (query.includes(keyword.replaceAll("ё", "е")) ? keyword.length : 0),
        0
      );
      if (score > bestScore) {
        best = item;
        bestScore = score;
      }
    });
    if (best) {
      const originalQuestion = question.value;
      renderDecision(best.id);
      question.value = originalQuestion;
    }
  });

  document.querySelector("[data-defense-copy]")?.addEventListener("click", async (event) => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      const button = event.currentTarget;
      const label = button.textContent;
      button.textContent = "Ссылка скопирована";
      setTimeout(() => { button.textContent = label; }, 1600);
    } catch (_) {
      window.prompt("Скопируйте ссылку", window.location.href);
    }
  });

  const impactForm = document.querySelector("[data-defense-impact]");
  const impactResult = document.querySelector("[data-defense-impact-result]");
  const consumerSelect = document.querySelector("[data-defense-consumer-select]");
  const consumerCount = document.querySelector("[data-defense-consumer-count]");
  consumerSelect?.addEventListener("change", () => {
    const option = consumerSelect.selectedOptions[0];
    if (option && consumerCount) consumerCount.value = option.dataset.count;
  });
  impactForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = impactForm.querySelector("button[type='submit']");
    const request = {};
    impactForm.querySelectorAll("[data-defense-impact-field]").forEach((input) => {
      if (input.value === "") return;
      const key = input.dataset.defenseImpactField;
      request[key] = key === "floors"
        ? Number.parseInt(input.value, 10)
        : Number.parseFloat(input.value.replace(",", "."));
    });
    if (consumerSelect && consumerCount) {
      const counts = [...consumerSelect.options].map((option) => Number(option.dataset.count));
      counts[Number(consumerSelect.value)] = Number.parseInt(consumerCount.value, 10);
      request.consumer_counts = counts;
    }
    submit.disabled = true;
    submit.textContent = "Пересчитываем…";
    if (impactResult) impactResult.hidden = true;
    try {
      const response = await fetch(impactForm.dataset.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Пересчёт не выполнен");
      impactResult.replaceChildren(
        element(
          "strong",
          "",
          result.summary.results_changed
            ? `${result.summary.results_changed} решений изменятся`
            : "Расчётные решения не изменятся"
        ),
        element(
          "span",
          "",
          `${result.summary.documents_affected} документов затронуто · проект не сохранён`
        )
      );
      const list = element("ul");
      result.deltas.forEach((delta) => {
        const row = element("li", delta.changed ? "changed" : "");
        row.append(
          element("b", "", delta.system),
          element("span", "", delta.label),
          element("strong", "", `${delta.before} → ${delta.after} ${delta.unit}`)
        );
        list.append(row);
      });
      impactResult.append(list);
      impactResult.hidden = false;
    } catch (error) {
      impactResult.replaceChildren(
        element("strong", "", "Пересчёт не выполнен"),
        element("span", "", error.message)
      );
      impactResult.hidden = false;
    } finally {
      submit.disabled = false;
      submit.textContent = "Пересчитать влияние";
    }
  });

  const hashId = decodeURIComponent(window.location.hash.slice(1));
  const initial = byId.has(hashId)
    ? hashId
    : buttons.find((button) => button.classList.contains("active"))?.dataset.defenseDecision;
  if (initial) renderDecision(initial, false);
});
