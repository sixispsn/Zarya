(() => {
  const form = document.querySelector("[data-architecture-confirmation]");
  const svg = document.querySelector("[data-plan-preview]");
  if (!form || !svg) return;

  const status = document.querySelector("[data-pick-status]");
  const height = Number(svg.dataset.pdfHeight || 0);
  const definitions = {
    calibration: ["calibration_ax", "calibration_ay", "calibration_bx", "calibration_by"],
    cut: ["cut_ax", "cut_ay", "cut_bx", "cut_by"],
  };
  let mode = "";
  let pointIndex = 0;

  const input = (name) => form.elements.namedItem(name);
  const number = (name) => {
    const value = String(input(name)?.value || "").replace(",", ".");
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const format = (value) => value.toFixed(3).replace(".", ",");

  function setLine(kind) {
    const names = definitions[kind];
    const values = names.map(number);
    const line = svg.querySelector(`[data-preview-${kind}]`);
    if (!line) return;
    if (values.some((value) => value === null)) {
      line.setAttribute("hidden", "");
      return;
    }
    line.removeAttribute("hidden");
    line.setAttribute("x1", values[0]);
    line.setAttribute("y1", height - values[1]);
    line.setAttribute("x2", values[2]);
    line.setAttribute("y2", height - values[3]);
  }

  function refresh() {
    setLine("calibration");
    setLine("cut");
  }

  function activate(nextMode) {
    mode = nextMode;
    pointIndex = 0;
    document.querySelectorAll("[data-pick-mode]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.pickMode === mode);
    });
    if (status) {
      status.textContent = mode === "calibration"
        ? "Калибровка: укажите точку A, затем B."
        : "Разрез: укажите начало A, затем конец B.";
    }
    svg.classList.add("is-picking");
  }

  document.querySelectorAll("[data-pick-mode]").forEach((button) => {
    button.addEventListener("click", () => activate(button.dataset.pickMode));
  });

  svg.addEventListener("click", (event) => {
    if (!mode || !definitions[mode]) return;
    const matrix = svg.getScreenCTM();
    if (!matrix) return;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(matrix.inverse());
    const pdfX = local.x;
    const pdfY = height - local.y;
    const names = definitions[mode];
    const offset = pointIndex === 0 ? 0 : 2;
    input(names[offset]).value = format(pdfX);
    input(names[offset + 1]).value = format(pdfY);
    pointIndex += 1;
    refresh();
    if (pointIndex >= 2) {
      if (status) status.textContent = `${mode === "calibration" ? "Калибровка" : "Разрез"}: точки A и B заданы.`;
      mode = "";
      pointIndex = 0;
      svg.classList.remove("is-picking");
      document.querySelectorAll("[data-pick-mode]").forEach((button) => button.classList.remove("is-active"));
    } else if (status) {
      status.textContent = `Точка A: X ${format(pdfX)}, Y ${format(pdfY)}. Теперь выберите B.`;
    }
  });

  Object.values(definitions).flat().forEach((name) => {
    input(name)?.addEventListener("input", refresh);
  });
  refresh();
})();
