/**
 * 功能说明：初始化 Kocotree UI Playground 的配色、密度、Tooltip、弹窗、Toast 及组件交互。
 * @param root - Playground 根元素，用于限定查询范围并同步预览状态。
 * @returns 无返回值。
 */
function initializePlayground(root) {
  const strategyName = root.querySelector("#strategy-name");
  const strategyDescription = root.querySelector("#strategy-description");
  const modalLayer = root.querySelector("#modal-layer");
  const toast = root.querySelector("#toast");
  const accountMenu = root.querySelector("#account-menu");
  const accountTrigger = root.querySelector("#account-trigger");
  const categorySelect = root.querySelector("#category-select");
  const categoryTrigger = categorySelect.querySelector(".select-trigger");
  const categoryMenu = categorySelect.querySelector(".select-menu");
  const categoryValue = categorySelect.querySelector("#category-value");
  const categoryOptions = Array.from(categorySelect.querySelectorAll(".select-option"));
  const tooltip = root.querySelector("#playground-tooltip");
  const tooltipTriggers = Array.from(root.querySelectorAll("[data-tooltip]"));
  let toastTimer = 0;
  let tooltipShowTimer = 0;
  let tooltipHideTimer = 0;
  let activeTooltipTrigger = null;

  console.info("[KocotreeUI] Playground 初始化完成");

  root.querySelectorAll("[data-color-value]").forEach((button) => {
    button.addEventListener("click", () => {
      const strategy = button.dataset.colorValue;
      root.dataset.colorStrategy = strategy;
      strategyName.textContent = strategy === "standard" ? "#009139" : "#2F8F68";
      strategyDescription.textContent = strategy === "standard" ? "识别强，主操作更鲜明" : "更克制，适合长时间使用";
      root.querySelectorAll("[data-color-value]").forEach((item) => item.classList.toggle("active", item === button));
      console.info("[KocotreeUI] 已切换主色策略", { strategy });
    });
  });

  root.querySelectorAll("[data-density-value]").forEach((button) => {
    button.addEventListener("click", () => {
      const density = button.dataset.densityValue;
      root.dataset.density = density;
      root.querySelectorAll("[data-density-value]").forEach((item) => item.classList.toggle("active", item === button));
      console.info("[KocotreeUI] 已切换组件密度", { density });
    });
  });

  root.querySelectorAll(".tag").forEach((button) => {
    button.addEventListener("click", () => {
      const selected = !button.classList.contains("selected");
      button.classList.toggle("selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  });

  root.querySelectorAll(".switch").forEach((button) => {
    button.addEventListener("click", () => {
      const enabled = !button.classList.contains("active");
      button.classList.toggle("active", enabled);
      button.setAttribute("aria-checked", String(enabled));
    });
  });

  const displayNameInput = root.querySelector("#display-name");
  const displayNameCount = root.querySelector("#display-name-count");
  displayNameInput.addEventListener("input", () => {
    displayNameCount.textContent = String(displayNameInput.value.length);
  });

  /**
   * 功能说明：同步触发元素与 Tooltip 的无障碍描述关系，并保留已有描述引用。
   * @param trigger - 当前 Tooltip 触发元素。
   * @param connected - 是否建立描述关系。
   * @returns 无返回值。
   */
  function updateTooltipDescription(trigger, connected) {
    const ids = new Set((trigger.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
    if (connected) ids.add(tooltip.id);
    else ids.delete(tooltip.id);
    if (ids.size > 0) trigger.setAttribute("aria-describedby", Array.from(ids).join(" "));
    else trigger.removeAttribute("aria-describedby");
  }

  /**
   * 功能说明：根据目标位置放置 Tooltip，在空间不足时翻转方向并限制在视口内。
   * @param trigger - 当前 Tooltip 触发元素，用于计算锚点位置。
   * @returns 无返回值。
   */
  function positionTooltip(trigger) {
    const viewportMargin = 8;
    const offset = 8;
    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const available = {
      top: triggerRect.top,
      right: window.innerWidth - triggerRect.right,
      bottom: window.innerHeight - triggerRect.bottom,
      left: triggerRect.left,
    };
    const opposite = { top: "bottom", right: "left", bottom: "top", left: "right" };
    const supportedPlacements = ["top", "right", "bottom", "left"];
    const preferredPlacement = trigger.dataset.tooltipPlacement || "top";
    let placement = supportedPlacements.includes(preferredPlacement) ? preferredPlacement : "top";
    const requiredSpace = ["top", "bottom"].includes(placement) ? tooltipRect.height + offset : tooltipRect.width + offset;
    if (available[placement] < requiredSpace && available[opposite[placement]] > available[placement]) {
      placement = opposite[placement];
    }

    const triggerCenterX = triggerRect.left + triggerRect.width / 2;
    const triggerCenterY = triggerRect.top + triggerRect.height / 2;
    let left = triggerCenterX - tooltipRect.width / 2;
    let top = triggerCenterY - tooltipRect.height / 2;
    if (placement === "top") top = triggerRect.top - tooltipRect.height - offset;
    if (placement === "bottom") top = triggerRect.bottom + offset;
    if (placement === "left") left = triggerRect.left - tooltipRect.width - offset;
    if (placement === "right") left = triggerRect.right + offset;

    left = Math.min(Math.max(left, viewportMargin), window.innerWidth - tooltipRect.width - viewportMargin);
    top = Math.min(Math.max(top, viewportMargin), window.innerHeight - tooltipRect.height - viewportMargin);
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
    tooltip.style.setProperty("--tooltip-arrow-x", `${Math.round(Math.min(Math.max(triggerCenterX - left, 8), tooltipRect.width - 8))}px`);
    tooltip.style.setProperty("--tooltip-arrow-y", `${Math.round(Math.min(Math.max(triggerCenterY - top, 8), tooltipRect.height - 8))}px`);
    tooltip.dataset.placement = placement;
  }

  /**
   * 功能说明：显示指定元素的 Tooltip，并将文本内容以纯文本方式写入浮层。
   * @param trigger - 当前 Tooltip 触发元素。
   * @param delay - 显示前等待的毫秒数，鼠标悬停使用延迟，键盘 Focus 立即显示。
   * @returns 无返回值。
   */
  function showTooltip(trigger, delay) {
    window.clearTimeout(tooltipShowTimer);
    window.clearTimeout(tooltipHideTimer);
    tooltipShowTimer = window.setTimeout(() => {
      if (activeTooltipTrigger && activeTooltipTrigger !== trigger) updateTooltipDescription(activeTooltipTrigger, false);
      activeTooltipTrigger = trigger;
      tooltip.textContent = trigger.dataset.tooltip;
      tooltip.hidden = false;
      tooltip.classList.remove("visible");
      updateTooltipDescription(trigger, true);
      positionTooltip(trigger);
      window.requestAnimationFrame(() => tooltip.classList.add("visible"));
    }, delay);
  }

  /**
   * 功能说明：关闭当前 Tooltip，并清理触发元素的无障碍描述关系。
   * @param force - 是否忽略鼠标悬停和键盘焦点状态立即关闭。
   * @returns 无返回值。
   */
  function hideTooltip(force = false) {
    window.clearTimeout(tooltipShowTimer);
    window.clearTimeout(tooltipHideTimer);
    const trigger = activeTooltipTrigger;
    if (!force && trigger && (trigger.matches(":hover") || document.activeElement === trigger)) return;
    if (trigger) updateTooltipDescription(trigger, false);
    activeTooltipTrigger = null;
    tooltip.classList.remove("visible");
    tooltip.hidden = true;
  }

  tooltipTriggers.forEach((trigger) => {
    trigger.addEventListener("mouseenter", () => showTooltip(trigger, 400));
    trigger.addEventListener("mouseleave", () => {
      tooltipHideTimer = window.setTimeout(() => hideTooltip(), 80);
    });
    trigger.addEventListener("focus", () => showTooltip(trigger, 0));
    trigger.addEventListener("blur", () => {
      tooltipHideTimer = window.setTimeout(() => hideTooltip(), 80);
    });
  });

  window.addEventListener("resize", () => {
    if (activeTooltipTrigger) positionTooltip(activeTooltipTrigger);
  });
  document.addEventListener("scroll", () => {
    if (activeTooltipTrigger) positionTooltip(activeTooltipTrigger);
  }, true);

  function closeCategorySelect() {
    categorySelect.classList.remove("open");
    categoryTrigger.setAttribute("aria-expanded", "false");
    categoryMenu.hidden = true;
    categoryOptions.forEach((option) => option.classList.remove("focused"));
  }

  function openCategorySelect() {
    categorySelect.classList.add("open");
    categoryTrigger.setAttribute("aria-expanded", "true");
    categoryMenu.hidden = false;
    const selectedOption = categoryOptions.find((option) => option.classList.contains("selected"));
    selectedOption?.classList.add("focused");
  }

  function selectCategory(option) {
    categoryOptions.forEach((item) => {
      const selected = item === option;
      item.classList.toggle("selected", selected);
      item.setAttribute("aria-selected", String(selected));
    });
    categoryValue.textContent = option.dataset.value;
    closeCategorySelect();
    categoryTrigger.focus();
    console.info("[KocotreeUI] 已选择用途分类", { category: option.dataset.value });
  }

  categoryTrigger.addEventListener("click", () => {
    if (categorySelect.classList.contains("open")) closeCategorySelect();
    else openCategorySelect();
  });

  categoryOptions.forEach((option) => option.addEventListener("click", () => selectCategory(option)));

  categoryTrigger.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    if (!categorySelect.classList.contains("open")) openCategorySelect();
    const selectedIndex = categoryOptions.findIndex((option) => option.classList.contains("selected"));
    const step = event.key === "ArrowDown" ? 1 : -1;
    const nextIndex = (selectedIndex + step + categoryOptions.length) % categoryOptions.length;
    selectCategory(categoryOptions[nextIndex]);
  });

  function showToast() {
    toast.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2800);
  }

  root.querySelectorAll("[data-toast-trigger]").forEach((button) => button.addEventListener("click", showToast));
  root.querySelector("#toast-close").addEventListener("click", () => { toast.hidden = true; });

  root.querySelectorAll("[data-modal-open]").forEach((button) => {
    button.addEventListener("click", () => {
      modalLayer.hidden = false;
      modalLayer.querySelector("[data-modal-close]").focus();
    });
  });

  root.querySelectorAll("[data-modal-close]").forEach((button) => button.addEventListener("click", () => { modalLayer.hidden = true; }));
  modalLayer.addEventListener("mousedown", (event) => {
    if (event.target === modalLayer) modalLayer.hidden = true;
  });
  root.querySelector("#confirm-install").addEventListener("click", () => { modalLayer.hidden = true; showToast(); });

  accountTrigger.addEventListener("click", () => {
    const expanded = accountTrigger.getAttribute("aria-expanded") === "true";
    accountTrigger.setAttribute("aria-expanded", String(!expanded));
    accountMenu.hidden = expanded;
  });

  document.addEventListener("mousedown", (event) => {
    if (!categorySelect.contains(event.target)) closeCategorySelect();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideTooltip(true);
      modalLayer.hidden = true;
      accountMenu.hidden = true;
      accountTrigger.setAttribute("aria-expanded", "false");
      closeCategorySelect();
    }
  });
}

const playground = document.querySelector("#playground");
if (playground) {
  initializePlayground(playground);
} else {
  console.error("[KocotreeUI] 未找到 Playground 根元素");
}
