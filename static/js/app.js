let sampleCasesData = [];
let chartEnergy = null;
let chartBattery = null;
let currentScenarioInput = null;
let lastOptimizationResult = null;
let selectedHour = 12;

const DEFAULT_BTN_HTML = `<svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg> Execute LLM & LP Optimization`;

document.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  initDualCharts();
  await fetchSampleCases();

  document.getElementById("optForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    await executeOptimization(false);
  });

  if (sampleCasesData.length > 0) {
    loadPresetCase(0);
    await executeOptimization(false);
  }
});

function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(btn => {
    btn.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      document.getElementById(targetId).classList.add("active");
    });
  });
}

async function fetchSampleCases() {
  try {
    const res = await fetch("/api/sample-cases");
    if (res.ok) {
      sampleCasesData = await res.json();
      renderPresetChips();
    }
  } catch (e) {
    console.warn("Failed to load sample cases preset list", e);
  }
}

function renderPresetChips() {
  const container = document.getElementById("presetChipsContainer");
  container.innerHTML = "";

  sampleCasesData.forEach((c, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `preset-badge-btn ${idx === 0 ? "active" : ""}`;
    btn.innerHTML = `<strong>${c.id}</strong> <span style="opacity: 0.85; font-weight: 400;">${c.label}</span>`;
    btn.onclick = () => {
      loadPresetCase(idx);
      executeOptimization(false);
    };
    container.appendChild(btn);
  });
}

let basePresetInput = null;
let activeSimScenarios = {
  solar_boost: false,
  grid_cap: false,
  emergency_reserve: false,
  tariff_surge: false
};

function loadPresetCase(idx) {
  const c = sampleCasesData[idx];
  if (!c) return;

  basePresetInput = JSON.parse(JSON.stringify(c.input));
  currentScenarioInput = JSON.parse(JSON.stringify(c.input));

  // Reset active scenario flags on preset change
  activeSimScenarios = {
    solar_boost: false,
    grid_cap: false,
    emergency_reserve: false,
    tariff_surge: false
  };
  updateSimUIState();

  document.querySelectorAll(".preset-badge-btn").forEach((btn, i) => {
    btn.classList.toggle("active", i === idx);
  });

  document.getElementById("scenarioId").value = currentScenarioInput.scenario_id;
  document.getElementById("operatorNotes").value = currentScenarioInput.operator_notes.join("\n");
  document.getElementById("batCapacity").value = currentScenarioInput.battery.capacity_kwh;
  document.getElementById("batInitial").value = currentScenarioInput.battery.initial_energy_kwh;
  document.getElementById("batMinReserve").value = currentScenarioInput.battery.minimum_energy_kwh;

  const maxRate = Math.max(
    currentScenarioInput.battery.max_charge_kwh_per_hour,
    currentScenarioInput.battery.max_discharge_kwh_per_hour
  );
  document.getElementById("batMaxRate").value = maxRate;

  updateSliderControlsForHour(selectedHour);
}

function onHourSliderChange(val) {
  selectedHour = parseInt(val, 10);
  document.getElementById("selectedHourLabel").textContent = `Hour ${selectedHour}:00`;
  updateSliderControlsForHour(selectedHour);
}

function updateSliderControlsForHour(h) {
  if (!currentScenarioInput || !currentScenarioInput.hours) return;
  const inH = currentScenarioInput.hours[h];
  if (!inH) return;

  document.getElementById("sliderDemand").value = inH.demand_kwh;
  document.getElementById("lblDemandVal").textContent = inH.demand_kwh.toFixed(0);

  document.getElementById("sliderSolar").value = inH.solar_kwh;
  document.getElementById("lblSolarVal").textContent = inH.solar_kwh.toFixed(0);

  document.getElementById("sliderTariff").value = inH.tariff_bdt_per_kwh;
  document.getElementById("lblTariffVal").textContent = inH.tariff_bdt_per_kwh.toFixed(0);
}

function onParamSliderChange() {
  if (!currentScenarioInput || !currentScenarioInput.hours) return;

  const dVal = parseFloat(document.getElementById("sliderDemand").value);
  const sVal = parseFloat(document.getElementById("sliderSolar").value);
  const tVal = parseFloat(document.getElementById("sliderTariff").value);

  document.getElementById("lblDemandVal").textContent = dVal.toFixed(0);
  document.getElementById("lblSolarVal").textContent = sVal.toFixed(0);
  document.getElementById("lblTariffVal").textContent = tVal.toFixed(0);

  currentScenarioInput.hours[selectedHour].demand_kwh = dVal;
  currentScenarioInput.hours[selectedHour].solar_kwh = sVal;
  currentScenarioInput.hours[selectedHour].tariff_bdt_per_kwh = tVal;

  if (document.getElementById("autoOptToggle").checked) {
    debounceAutoOptimize();
  }
}

let debounceTimer = null;
function debounceAutoOptimize() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    executeOptimization(true);
  }, 300);
}

function simulateScenario(type) {
  if (!basePresetInput) return;

  // Toggle scenario state
  activeSimScenarios[type] = !activeSimScenarios[type];
  reapplyActiveScenarios();
  executeOptimization(false);
}

function resetSimScenarios() {
  if (!basePresetInput) return;

  activeSimScenarios = {
    solar_boost: false,
    grid_cap: false,
    emergency_reserve: false,
    tariff_surge: false
  };
  reapplyActiveScenarios();
  executeOptimization(false);
}

function reapplyActiveScenarios() {
  if (!basePresetInput) return;

  // Start with clean deep copy of base preset
  currentScenarioInput = JSON.parse(JSON.stringify(basePresetInput));

  const notesList = [...basePresetInput.operator_notes];

  if (activeSimScenarios.solar_boost) {
    currentScenarioInput.hours.forEach(h => {
      h.solar_kwh = Math.round(h.solar_kwh * 1.5);
    });
  }

  if (activeSimScenarios.tariff_surge) {
    currentScenarioInput.hours.forEach(h => {
      if (h.hour >= 18 && h.hour <= 21) {
        h.tariff_bdt_per_kwh = Math.round(h.tariff_bdt_per_kwh * 2.5);
      }
    });
  }

  if (activeSimScenarios.grid_cap) {
    notesList.unshift("From 6 PM until 9 PM, campus grid import must not exceed 100 kWh in any hour.");
  }

  if (activeSimScenarios.emergency_reserve) {
    notesList.unshift("Keep at least 150 kWh in the battery from 5 PM until 10 PM for emergency operations.");
  }

  currentScenarioInput.operator_notes = notesList;
  document.getElementById("operatorNotes").value = notesList.join("\n");

  updateSimUIState();
  updateSliderControlsForHour(selectedHour);
}

function updateSimUIState() {
  const btnSolar = document.getElementById("btnSimSolar");
  const btnGridCap = document.getElementById("btnSimGridCap");
  const btnReserve = document.getElementById("btnSimReserve");
  const btnTariff = document.getElementById("btnSimTariff");
  const badge = document.getElementById("simActiveStatus");

  if (btnSolar) btnSolar.classList.toggle("active", activeSimScenarios.solar_boost);
  if (btnGridCap) btnGridCap.classList.toggle("active", activeSimScenarios.grid_cap);
  if (btnReserve) btnReserve.classList.toggle("active", activeSimScenarios.emergency_reserve);
  if (btnTariff) btnTariff.classList.toggle("active", activeSimScenarios.tariff_surge);

  const activeNames = [];
  if (activeSimScenarios.solar_boost) activeNames.push("Solar Boost (+50%)");
  if (activeSimScenarios.grid_cap) activeNames.push("Grid Cap");
  if (activeSimScenarios.emergency_reserve) activeNames.push("Reserve Spike");
  if (activeSimScenarios.tariff_surge) activeNames.push("Tariff Surge");

  if (badge) {
    if (activeNames.length > 0) {
      badge.textContent = `Active (${activeNames.length}): ${activeNames.join(", ")}`;
      badge.style.color = "#38bdf8";
      badge.style.borderColor = "rgba(56, 189, 248, 0.4)";
    } else {
      badge.textContent = "Baseline";
      badge.style.color = "var(--text-muted)";
      badge.style.borderColor = "rgba(255, 255, 255, 0.1)";
    }
  }
}

function buildPayload() {
  const scenarioId = document.getElementById("scenarioId").value.trim() || "GRID-101";
  const notesStr = document.getElementById("operatorNotes").value.trim();
  const operatorNotes = notesStr.split("\n").map(s => s.trim()).filter(s => s.length > 0);

  const cap = parseFloat(document.getElementById("batCapacity").value) || 200;
  const initE = parseFloat(document.getElementById("batInitial").value) || 100;
  const minR = parseFloat(document.getElementById("batMinReserve").value) || 40;
  const maxR = parseFloat(document.getElementById("batMaxRate").value) || 50;

  const battery = {
    capacity_kwh: cap,
    initial_energy_kwh: initE,
    minimum_energy_kwh: minR,
    max_charge_kwh_per_hour: maxR,
    max_discharge_kwh_per_hour: maxR
  };

  const hours = currentScenarioInput ? currentScenarioInput.hours : generateFallbackHours();

  return {
    scenario_id: scenarioId,
    operator_notes: operatorNotes,
    hours: hours,
    battery: battery
  };
}

function generateFallbackHours() {
  const hours = [];
  for (let h = 0; h < 24; h++) {
    hours.push({
      hour: h,
      demand_kwh: 120 + Math.sin(h / 3) * 60,
      solar_kwh: (h >= 6 && h <= 18) ? Math.sin((h - 6) / 12 * Math.PI) * 160 : 0,
      tariff_bdt_per_kwh: (h >= 17 && h <= 21) ? 28 : 8
    });
  }
  return hours;
}

async function executeOptimization(isAutoOpt = false) {
  const execBtn = document.getElementById("execBtn");
  const latencyBadge = document.getElementById("latencyBadge");

  if (!isAutoOpt) {
    execBtn.innerHTML = `<span class="spinner-sm"></span> Processing Directive & Solver...`;
    execBtn.disabled = true;
  } else {
    latencyBadge.innerHTML = `<span class="spinner-sm"></span> Updating...`;
  }

  const startTime = performance.now();

  try {
    const payload = buildPayload();
    const res = await fetch("/optimize-energy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const elapsed = Math.round(performance.now() - startTime);
    latencyBadge.textContent = `${elapsed} ms`;

    if (!res.ok) {
      const err = await res.json();
      alert(`API Error (${res.status}): ${err.detail || "Request failed"}`);
      return;
    }

    const data = await res.json();
    lastOptimizationResult = data;
    renderResults(data, payload);
  } catch (err) {
    console.error("Optimization execution error:", err);
  } finally {
    execBtn.innerHTML = DEFAULT_BTN_HTML;
    execBtn.disabled = false;
  }
}

function renderResults(data, payload) {
  // 1. Calculate Unoptimized Baseline Cost
  let unoptimizedCost = 0;
  payload.hours.forEach(h => {
    const netNeed = Math.max(0, h.demand_kwh - h.solar_kwh);
    unoptimizedCost += netNeed * h.tariff_bdt_per_kwh;
  });

  const optCost = data.total_cost_bdt;
  const savingsBdt = Math.max(0, unoptimizedCost - optCost);
  const savingsPct = unoptimizedCost > 0 ? ((savingsBdt / unoptimizedCost) * 100).toFixed(1) : "0.0";

  document.getElementById("kpiCost").textContent = optCost.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
  document.getElementById("kpiSavingsBadge").textContent = `-${savingsPct}% (${savingsBdt.toFixed(0)} BDT Saved)`;
  document.getElementById("kpiUnoptimizedSub").textContent = `Unoptimized Base: ${unoptimizedCost.toLocaleString(undefined, {maximumFractionDigits:0})} BDT`;

  document.getElementById("kpiGrid").textContent = data.total_grid_kwh.toLocaleString();
  document.getElementById("kpiPeak").textContent = data.peak_grid_kwh.toLocaleString();

  const activeCount = data.directive_interpretation.filter(d => d.applies).length;
  document.getElementById("kpiDirectivesCount").textContent = `${activeCount} / ${data.directive_interpretation.length}`;

  const peakHour = data.hourly_plan.reduce((maxH, item) => item.grid_kwh > maxH.grid_kwh ? item : maxH, data.hourly_plan[0]);
  document.getElementById("kpiPeakHour").textContent = `Peak load ${peakHour.grid_kwh.toFixed(1)} kWh at ${peakHour.hour}:00`;

  document.getElementById("strategySummaryText").textContent = data.plan_summary;

  // 2. Directives Guardrail List
  renderDirectivesList(data.directive_interpretation);

  // 3. Update Dual Charts
  updateDualCharts(data.hourly_plan, payload.hours, payload.battery);

  // 4. Render 24h Table
  renderScheduleTable(data.hourly_plan, payload.hours);

  // 5. JSON Display
  document.getElementById("rawJsonDisplay").textContent = JSON.stringify(data, null, 2);
}

function renderDirectivesList(directives) {
  const container = document.getElementById("directivesContainer");
  container.innerHTML = "";

  directives.forEach(d => {
    const card = document.createElement("div");
    card.className = "directive-card-pro";

    const statusClass = d.applies ? "status-pill-applied" : "status-pill-noop";
    const statusText = d.applies ? "Active Directive" : "No-Op Distractor";

    let hoursHtml = "";
    let adjDetailsHtml = "";

    if (d.structured_adjustment) {
      const adj = d.structured_adjustment;
      if (adj.hours && Array.isArray(adj.hours)) {
        hoursHtml = `<div class="hours-pill-group">
          <span style="font-size: 0.72rem; color: var(--text-dim);">Affected Hours:</span>
          ${adj.hours.map(h => `<span class="hour-tag">${h}:00</span>`).join("")}
        </div>`;
      }
      adjDetailsHtml = `<div style="font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; color: #cbd5e1; background: rgba(0,0,0,0.3); padding: 0.4rem 0.6rem; border-radius: 6px;">${JSON.stringify(adj)}</div>`;
    }

    card.innerHTML = `
      <div class="directive-top-bar">
        <span class="note-badge">Operator Note #${d.note_index}</span>
        <span class="directive-type-pill">${d.directive_type}</span>
        <span class="status-pill ${statusClass}">${statusText}</span>
      </div>
      <div class="directive-desc">${d.explanation}</div>
      ${hoursHtml}
      ${adjDetailsHtml}
    `;

    container.appendChild(card);
  });
}

function initDualCharts() {
  const ctx1 = document.getElementById("chartEnergyBalance").getContext("2d");
  chartEnergy = new Chart(ctx1, {
    type: "bar",
    data: {
      labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
      datasets: [
        {
          label: "Grid Purchased (kWh)",
          data: [],
          backgroundColor: "rgba(56, 189, 248, 0.75)",
          borderColor: "#38bdf8",
          borderWidth: 1,
          stack: "generation"
        },
        {
          label: "Solar Used (kWh)",
          data: [],
          backgroundColor: "rgba(16, 185, 129, 0.75)",
          borderColor: "#10b981",
          borderWidth: 1,
          stack: "generation"
        },
        {
          label: "Battery Discharge (kWh)",
          data: [],
          backgroundColor: "rgba(244, 63, 94, 0.75)",
          borderColor: "#f43f5e",
          borderWidth: 1,
          stack: "generation"
        },
        {
          label: "Campus Demand (kWh)",
          data: [],
          type: "line",
          borderColor: "#f59e0b",
          borderWidth: 3,
          pointRadius: 2,
          tension: 0.3,
          fill: false
        }
      ]
    },
    options: getCommonChartOptions("Energy (kWh)")
  });

  const ctx2 = document.getElementById("chartBatterySOC").getContext("2d");
  chartBattery = new Chart(ctx2, {
    type: "bar",
    data: {
      labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
      datasets: [
        {
          label: "Charge (+kWh)",
          data: [],
          backgroundColor: "rgba(16, 185, 129, 0.8)",
          borderColor: "#10b981",
          borderWidth: 1
        },
        {
          label: "Discharge (-kWh)",
          data: [],
          backgroundColor: "rgba(244, 63, 94, 0.8)",
          borderColor: "#f43f5e",
          borderWidth: 1
        },
        {
          label: "Battery State of Charge (kWh)",
          data: [],
          type: "line",
          borderColor: "#a855f7",
          borderWidth: 3,
          pointRadius: 3,
          tension: 0.2,
          yAxisID: "ySOC"
        }
      ]
    },
    options: {
      ...getCommonChartOptions("Rate (kWh)"),
      scales: {
        x: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#94a3b8" } },
        y: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#94a3b8" }, title: { display: true, text: "Hourly Rate (kWh)", color: "#94a3b8" } },
        ySOC: {
          position: "right",
          grid: { drawOnChartArea: false },
          ticks: { color: "#c084fc" },
          title: { display: true, text: "SOC Level (kWh)", color: "#c084fc" }
        }
      }
    }
  });
}

function getCommonChartOptions(yLabel) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        labels: { color: "#94a3b8", font: { family: "Inter", size: 12 } }
      },
      tooltip: {
        backgroundColor: "rgba(6, 9, 19, 0.95)",
        titleColor: "#f8fafc",
        bodyColor: "#cbd5e1",
        borderColor: "rgba(255, 255, 255, 0.1)",
        borderWidth: 1
      }
    },
    scales: {
      x: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#94a3b8" } },
      y: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#94a3b8" }, title: { display: true, text: yLabel, color: "#94a3b8" } }
    }
  };
}

function updateDualCharts(hourlyPlan, inputHours, batteryConfig) {
  if (!chartEnergy || !chartBattery) return;

  const gridVals = hourlyPlan.map(h => h.grid_kwh);
  const solarVals = hourlyPlan.map(h => h.solar_used_kwh);
  const dischargeVals = hourlyPlan.map(h => h.battery_action === "discharge" ? h.battery_kwh : 0);
  const demandVals = inputHours.map(h => h.demand_kwh);

  chartEnergy.data.datasets[0].data = gridVals;
  chartEnergy.data.datasets[1].data = solarVals;
  chartEnergy.data.datasets[2].data = dischargeVals;
  chartEnergy.data.datasets[3].data = demandVals;
  chartEnergy.update();

  const chargeVals = hourlyPlan.map(h => h.battery_action === "charge" ? h.battery_kwh : 0);
  const dischgVals = hourlyPlan.map(h => h.battery_action === "discharge" ? -h.battery_kwh : 0);
  const socVals = hourlyPlan.map(h => h.battery_energy_after_kwh);

  chartBattery.data.datasets[0].data = chargeVals;
  chartBattery.data.datasets[1].data = dischgVals;
  chartBattery.data.datasets[2].data = socVals;
  chartBattery.update();
}

function renderScheduleTable(hourlyPlan, inputHours) {
  const tbody = document.getElementById("scheduleTableBody");
  tbody.innerHTML = "";

  const maxTariff = Math.max(...inputHours.map(h => h.tariff_bdt_per_kwh));

  hourlyPlan.forEach(h => {
    const tr = document.createElement("tr");
    const inH = inputHours[h.hour];

    let actionBadge = `<span style="color: var(--text-dim);">Idle</span>`;
    if (h.battery_action === "charge") {
      actionBadge = `<span style="color: #34d399; font-weight: 700;">+ Charge (${h.battery_kwh.toFixed(1)} kWh)</span>`;
    } else if (h.battery_action === "discharge") {
      actionBadge = `<span style="color: #f87171; font-weight: 700;">- Discharge (${h.battery_kwh.toFixed(1)} kWh)</span>`;
    }

    const isPeakTariff = inH.tariff_bdt_per_kwh >= maxTariff * 0.8;
    const tariffBadge = isPeakTariff
      ? `<span class="tariff-peak">${inH.tariff_bdt_per_kwh} BDT</span>`
      : `<span class="tariff-normal">${inH.tariff_bdt_per_kwh} BDT</span>`;

    tr.innerHTML = `
      <td class="mono-font" style="font-weight: 600;">${h.hour}:00</td>
      <td class="mono-font">${inH.demand_kwh.toFixed(1)}</td>
      <td class="mono-font" style="color: #6ee7b7;">${inH.solar_kwh.toFixed(1)}</td>
      <td class="mono-font" style="color: #38bdf8; font-weight: 700;">${h.grid_kwh.toFixed(1)}</td>
      <td class="mono-font" style="color: #34d399;">${h.solar_used_kwh.toFixed(1)}</td>
      <td>${actionBadge}</td>
      <td class="mono-font" style="color: #c084fc; font-weight: 700;">${h.battery_energy_after_kwh.toFixed(1)}</td>
      <td>${tariffBadge}</td>
    `;

    tbody.appendChild(tr);
  });
}

function copyResponseData() {
  if (lastOptimizationResult) {
    navigator.clipboard.writeText(JSON.stringify(lastOptimizationResult, null, 2));
    alert("Full Optimization Response JSON copied to clipboard!");
  }
}
