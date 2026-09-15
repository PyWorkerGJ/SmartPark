// SmartPark admin frontend logic. All figures come from /api/admin/* endpoints.

let selectedAdminZone = null;
let aZoneChart = null, aHourlyChart = null;

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let data;
  try { data = await res.json(); } catch (e) { data = { success: false, error: "Unexpected server response." }; }
  if (!res.ok && !data.error) data.error = "Something went wrong.";
  return data;
}

function toast(message, isError = false) {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = (isError ? "✕ " : "✓ ") + message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3800);
}
function openModal(id) { document.getElementById(id).classList.add("open"); }
function closeModal(id) { document.getElementById(id).classList.remove("open"); }
function fmtMoney(v) { return "₹" + Number(v).toFixed(2); }
function fmtDateTime(v) {
  if (!v) return "–";
  const d = new Date(v.replace(" ", "T"));
  if (isNaN(d)) return v;
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function refreshAll() {
  await loadAdminDashboard();
  await loadZonesAdmin();
  await loadActivity();
  if (selectedAdminZone) await loadSlotMapAdmin(selectedAdminZone);
}

async function loadAdminDashboard() {
  const data = await api("/api/admin/dashboard");
  if (!data.success) { toast(data.error, true); return; }
  document.getElementById("a-total").textContent = data.total_slots;
  document.getElementById("a-available").textContent = data.available;
  document.getElementById("a-occupied").textContent = data.occupied;
  document.getElementById("a-reserved").textContent = data.reserved;
  document.getElementById("a-maintenance").textContent = data.maintenance;
  document.getElementById("a-today-vehicles").textContent = data.today_vehicles;
  document.getElementById("a-today-revenue").textContent = fmtMoney(data.today_revenue);

  const zonesData = await api("/api/zones");
  if (zonesData.success) {
    const ctx = document.getElementById("a-chart-zone").getContext("2d");
    const chartData = { labels: zonesData.zones.map(z => z.name), datasets: [{ label: "Occupancy %", data: zonesData.zones.map(z => z.occupancy_pct), backgroundColor: "#3b82f6", borderRadius: 8 }] };
    if (aZoneChart) { aZoneChart.data = chartData; aZoneChart.update(); }
    else {
      aZoneChart = new Chart(ctx, { type: "bar", data: chartData,
        options: { responsive: true, plugins: { legend: { display: false }, title: { display: true, text: "Occupancy by Zone", color: "#8b93a7" } },
          scales: { y: { beginAtZero: true, max: 100, ticks: { color: "#8b93a7" } }, x: { ticks: { color: "#8b93a7" } } } } });
    }
  }

  const hourly = await api("/api/admin/hourly-demand");
  if (hourly.success) {
    const ctx2 = document.getElementById("a-chart-hourly").getContext("2d");
    const chartData2 = { labels: hourly.labels, datasets: [{ label: "Sessions", data: hourly.counts, borderColor: "#22c55e", backgroundColor: "rgba(34,197,94,0.15)", fill: true, tension: 0.3 }] };
    if (aHourlyChart) { aHourlyChart.data = chartData2; aHourlyChart.update(); }
    else {
      aHourlyChart = new Chart(ctx2, { type: "line", data: chartData2,
        options: { responsive: true, plugins: { legend: { display: false }, title: { display: true, text: "Hourly Parking Demand", color: "#8b93a7" } },
          scales: { y: { beginAtZero: true, ticks: { color: "#8b93a7" } }, x: { ticks: { color: "#8b93a7", maxTicksLimit: 8 } } } } });
    }
  }
}

async function loadZonesAdmin() {
  const data = await api("/api/zones");
  if (!data.success) { toast(data.error, true); return; }
  const box = document.getElementById("a-zones");
  box.innerHTML = data.zones.map(z => `
    <div class="flex-between" style="padding:14px 4px;border-bottom:1px solid var(--border);cursor:pointer;" onclick="selectAdminZone(${z.id}, '${z.name}')">
      <div>
        <div style="font-weight:700;">${z.name} <span class="muted" style="font-weight:400;font-size:12px;">${z.location || ""}</span></div>
        <div class="muted" style="font-size:12px;">${z.total} total · ${z.available} available · ${z.occupied} occupied · ${z.reserved} reserved · ${z.maintenance} maintenance</div>
      </div>
      <span class="badge AVAILABLE">${z.occupancy_pct}% occupied</span>
    </div>`).join("");
}

async function selectAdminZone(id, name) {
  selectedAdminZone = id;
  document.getElementById("a-slot-zone-name").textContent = name;
  document.getElementById("a-add-slot-btn").disabled = false;
  loadSlotMapAdmin(id);
}

async function loadSlotMapAdmin(zoneId) {
  const data = await api(`/api/zones/${zoneId}/slots`);
  if (!data.success) { toast(data.error, true); return; }
  const map = document.getElementById("a-slot-map");
  map.innerHTML = data.slots.map(s => `
    <div class="slot-cell ${s.status}" onclick="onAdminSlotClick(${s.id}, '${s.slot_number}', '${s.status}')">
      ${s.slot_number}<span class="sub">${s.status}</span>
    </div>`).join("");
}

function onAdminSlotClick(slotId, slotNumber, status) {
  if (status === "AVAILABLE") {
    patchSlot(slotId, "MAINTENANCE");
  } else if (status === "MAINTENANCE") {
    patchSlot(slotId, "AVAILABLE");
  } else if (status === "OCCUPIED") {
    document.getElementById("confirm-modal-text").textContent =
      `Slot ${slotNumber} is currently OCCUPIED. Forcing it to AVAILABLE will not end the active session properly. Continue anyway?`;
    document.getElementById("confirm-modal-btn").onclick = () => { closeModal("confirm-modal"); patchSlot(slotId, "AVAILABLE", true); };
    openModal("confirm-modal");
  } else {
    toast("Reserved slots must be started or cancelled by the user first.", true);
  }
}

async function patchSlot(slotId, status, confirm = false) {
  const data = await api(`/api/admin/slots/${slotId}`, { method: "PATCH", body: JSON.stringify({ status, confirm }) });
  if (!data.success) {
    if (data.requires_confirmation) {
      document.getElementById("confirm-modal-text").textContent = data.error;
      document.getElementById("confirm-modal-btn").onclick = () => { closeModal("confirm-modal"); patchSlot(slotId, status, true); };
      openModal("confirm-modal");
      return;
    }
    toast(data.error, true);
    return;
  }
  toast(`Slot updated to ${status}.`);
  refreshAll();
}

function openAddSlot() {
  if (!selectedAdminZone) return;
  document.getElementById("add-slot-zone-label").textContent = "Zone: " + document.getElementById("a-slot-zone-name").textContent;
  document.getElementById("new-slot-number").value = "";
  document.getElementById("add-slot-error").style.display = "none";
  openModal("add-slot-modal");
}

async function submitAddSlot() {
  const slotNumber = document.getElementById("new-slot-number").value.trim().toUpperCase();
  const slotType = document.getElementById("new-slot-type").value;
  const floor = Number(document.getElementById("new-slot-floor").value) || 1;
  const errBox = document.getElementById("add-slot-error");
  if (!slotNumber) { errBox.textContent = "Please enter a slot number."; errBox.style.display = "block"; return; }

  const data = await api("/api/admin/slots", { method: "POST", body: JSON.stringify({ zone_id: selectedAdminZone, slot_number: slotNumber, slot_type: slotType, floor }) });
  if (!data.success) { errBox.textContent = data.error; errBox.style.display = "block"; return; }
  closeModal("add-slot-modal");
  toast(`Slot ${slotNumber} added.`);
  refreshAll();
}

async function simulateSensor(action) {
  const slotNumberInput = document.getElementById("sensor-slot-number").value.trim().toUpperCase();
  if (!slotNumberInput) { toast("Enter a slot number first.", true); return; }

  // Look up the slot id from any zone (search across zones since admin may not have selected one)
  const zonesData = await api("/api/zones");
  let slotId = null;
  for (const z of zonesData.zones) {
    const slotsData = await api(`/api/zones/${z.id}/slots`);
    const found = slotsData.slots.find(s => s.slot_number === slotNumberInput);
    if (found) { slotId = found.id; break; }
  }
  if (!slotId) { toast("Slot not found.", true); return; }

  const endpoint = action === "detect" ? "/api/sensor/detect" : "/api/sensor/exit";
  const data = await api(endpoint, { method: "POST", body: JSON.stringify({ slot_id: slotId }) });
  if (!data.success) { toast(data.error, true); return; }
  toast(`Sensor event recorded for ${slotNumberInput}.`);
  refreshAll();
}

async function loadActivity() {
  const data = await api("/api/admin/activity");
  if (!data.success) { toast(data.error, true); return; }
  const tbody = document.getElementById("a-activity");
  if (data.activity.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;">No activity yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = data.activity.map(e => `
    <tr>
      <td>${fmtDateTime(e.timestamp)}</td>
      <td>${e.slot_number}</td>
      <td>${e.zone_name}</td>
      <td>${e.event_type}</td>
      <td>${e.source}</td>
      <td class="muted">${e.description || ""}</td>
    </tr>`).join("");
}

async function resetDemo() {
  document.getElementById("confirm-modal-text").textContent =
    "This will erase all current data and re-seed the demo database from scratch. Continue?";
  document.getElementById("confirm-modal-btn").onclick = async () => {
    closeModal("confirm-modal");
    const data = await api("/api/admin/reset-demo", { method: "POST", body: JSON.stringify({ confirm: true }) });
    if (!data.success) { toast(data.error, true); return; }
    toast("Demo data reset.");
    selectedAdminZone = null;
    document.getElementById("a-slot-map").innerHTML = "";
    document.getElementById("a-slot-zone-name").textContent = "select a zone above";
    document.getElementById("a-add-slot-btn").disabled = true;
    refreshAll();
  };
  openModal("confirm-modal");
}

refreshAll();
setInterval(refreshAll, 20000);
