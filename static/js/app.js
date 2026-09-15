// SmartPark frontend logic.
// IMPORTANT: no dashboard numbers are hardcoded here. Every figure rendered
// comes from a fetch() call to a Flask API endpoint backed by SQLite.

let CONFIG = null;
let selectedZoneId = null;
let selectedSlot = null;
let selectedDuration = 60;
let activeTimerInterval = null;

// ---------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
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
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
function fmtDuration(mins) {
  if (mins == null) return "–";
  const h = Math.floor(mins / 60), m = mins % 60;
  return (h ? h + "h " : "") + m + "m";
}

// ---------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------
const TITLES = {
  dashboard: "Dashboard", find: "Find Parking", myparking: "My Parking",
  history: "History", rewards: "Rewards",
};

document.querySelectorAll(".nav-item[data-view]").forEach(item => {
  item.addEventListener("click", () => switchView(item.dataset.view));
});

function switchView(view) {
  document.querySelectorAll(".nav-item[data-view]").forEach(i => i.classList.toggle("active", i.dataset.view === view));
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById("view-" + view).classList.add("active");
  document.getElementById("page-title").textContent = TITLES[view];

  if (view === "dashboard") loadDashboard();
  if (view === "find") loadZones();
  if (view === "myparking") loadMyParking();
  if (view === "history") loadHistory();
  if (view === "rewards") loadRewards();
}

// ---------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------
let zoneChart = null, hourlyChart = null;

async function loadDashboard() {
  const data = await api("/api/dashboard");
  if (!data.success) { toast(data.error, true); return; }
  document.getElementById("kpi-total").textContent = data.total_slots;
  document.getElementById("kpi-available").textContent = data.available;
  document.getElementById("kpi-occupied").textContent = data.occupied;
  document.getElementById("kpi-reserved").textContent = data.reserved;

  const box = document.getElementById("dashboard-current-parking");
  if (data.active_session) {
    const s = data.active_session;
    box.innerHTML = `
      <div class="flex-between">
        <div>
          <div style="font-weight:800;font-size:16px;">${s.slot_number} · ${s.zone_name}</div>
          <div class="muted" style="font-size:13px;">${s.vehicle_number} · Parked since ${fmtDateTime(s.entry_time)}</div>
        </div>
        <span class="badge OCCUPIED">Parked</span>
      </div>`;
  } else if (data.active_reservation) {
    const r = data.active_reservation;
    box.innerHTML = `
      <div class="flex-between">
        <div>
          <div style="font-weight:800;font-size:16px;">${r.slot_number} · ${r.zone_name}</div>
          <div class="muted" style="font-size:13px;">${r.vehicle_number} · Reserved, awaiting start</div>
        </div>
        <span class="badge RESERVED">Reserved</span>
      </div>`;
  } else {
    box.innerHTML = `<div class="empty-state"><div class="icon">🅿️</div>No active parking session.</div>`;
  }

  const zonesData = await api("/api/zones");
  if (zonesData.success) {
    const barsBox = document.getElementById("dashboard-zone-bars");
    barsBox.innerHTML = zonesData.zones.map(z => `
      <div style="margin-bottom:16px;">
        <div class="flex-between" style="margin-bottom:6px;font-size:13px;">
          <span style="font-weight:700;">${z.name}</span><span class="muted">${z.occupancy_pct}%</span>
        </div>
        <div class="progress-bar-track"><div class="progress-bar-fill" style="width:${z.occupancy_pct}%"></div></div>
      </div>`).join("");

    const ctx = document.getElementById("chart-zone-occupancy").getContext("2d");
    const chartData = {
      labels: zonesData.zones.map(z => z.name),
      datasets: [{ label: "Occupancy %", data: zonesData.zones.map(z => z.occupancy_pct), backgroundColor: "#3b82f6", borderRadius: 8 }],
    };
    if (zoneChart) { zoneChart.data = chartData; zoneChart.update(); }
    else {
      zoneChart = new Chart(ctx, {
        type: "bar", data: chartData,
        options: { responsive: true, plugins: { legend: { display: false }, title: { display: true, text: "Parking Occupancy by Zone", color: "#8b93a7" } },
          scales: { y: { beginAtZero: true, max: 100, ticks: { color: "#8b93a7" } }, x: { ticks: { color: "#8b93a7" } } } },
      });
    }
  }

  const hourly = await api("/api/admin/hourly-demand");
  if (hourly.success) {
    const ctx2 = document.getElementById("chart-hourly-demand").getContext("2d");
    const chartData2 = { labels: hourly.labels, datasets: [{ label: "Sessions", data: hourly.counts, borderColor: "#22c55e", backgroundColor: "rgba(34,197,94,0.15)", fill: true, tension: 0.3 }] };
    if (hourlyChart) { hourlyChart.data = chartData2; hourlyChart.update(); }
    else {
      hourlyChart = new Chart(ctx2, {
        type: "line", data: chartData2,
        options: { responsive: true, plugins: { legend: { display: false }, title: { display: true, text: "Hourly Parking Demand", color: "#8b93a7" } },
          scales: { y: { beginAtZero: true, ticks: { color: "#8b93a7" } }, x: { ticks: { color: "#8b93a7", maxTicksLimit: 8 } } } },
      });
    }
  }
}

// ---------------------------------------------------------------------
// Find Parking
// ---------------------------------------------------------------------
async function loadZones() {
  const data = await api("/api/zones");
  if (!data.success) { toast(data.error, true); return; }
  const grid = document.getElementById("zone-grid");
  grid.innerHTML = data.zones.map(z => `
    <div class="zone-card ${z.id === selectedZoneId ? 'selected' : ''}" onclick="selectZone(${z.id}, '${z.name}')">
      <h3>${z.name}</h3>
      <div class="loc">${z.location || ""}</div>
      <div class="zone-stats">
        <span><b>${z.total}</b>Total</span>
        <span style="color:var(--green)"><b>${z.available}</b>Available</span>
        <span style="color:var(--red)"><b>${z.occupied}</b>Occupied</span>
        <span style="color:var(--amber)"><b>${z.reserved}</b>Reserved</span>
      </div>
      <div class="progress-bar-track"><div class="progress-bar-fill" style="width:${z.occupancy_pct}%"></div></div>
      <div class="muted" style="font-size:11px;margin-top:6px;">Occupancy: ${z.occupancy_pct}%</div>
    </div>`).join("");

  if (selectedZoneId) loadSlotMap(selectedZoneId);
}

async function selectZone(id, name) {
  selectedZoneId = id;
  document.querySelectorAll(".zone-card").forEach(c => c.classList.remove("selected"));
  await loadZones();
  document.getElementById("slot-map-title").style.display = "flex";
  document.getElementById("slot-map-title").textContent = "Slot Map · " + name;
  document.getElementById("slot-map-card").style.display = "block";
  loadSlotMap(id);
}

async function loadSlotMap(zoneId) {
  const data = await api(`/api/zones/${zoneId}/slots`);
  if (!data.success) { toast(data.error, true); return; }
  const map = document.getElementById("slot-map");
  map.innerHTML = data.slots.map(s => `
    <div class="slot-cell ${s.status}" onclick="onSlotClick(${s.id}, '${s.slot_number}', '${s.status}')">
      ${s.slot_number}<span class="sub">${s.status}</span>
    </div>`).join("");
}

function onSlotClick(slotId, slotNumber, status) {
  if (status === "AVAILABLE") { openReserveModal(slotId, slotNumber); return; }
  const messages = {
    OCCUPIED: "Slot currently occupied.",
    RESERVED: "Slot currently reserved.",
    MAINTENANCE: "Slot unavailable.",
  };
  toast(messages[status] || "Slot unavailable.", true);
}

// ---------------------------------------------------------------------
// Reservation modal
// ---------------------------------------------------------------------
function openReserveModal(slotId, slotNumber) {
  selectedSlot = { id: slotId, number: slotNumber };
  document.getElementById("reserve-slot-label").textContent = `Slot ${slotNumber}`;
  document.getElementById("reserve-vehicle-number").value = "";
  document.getElementById("reserve-error").style.display = "none";
  selectedDuration = 60;
  document.querySelectorAll(".duration-opt").forEach(o => o.classList.toggle("selected", Number(o.dataset.mins) === 60));
  updateFeePreview();
  openModal("reserve-modal");
}

document.querySelectorAll(".duration-opt").forEach(opt => {
  opt.addEventListener("click", () => {
    document.querySelectorAll(".duration-opt").forEach(o => o.classList.remove("selected"));
    opt.classList.add("selected");
    selectedDuration = Number(opt.dataset.mins);
    updateFeePreview();
  });
});
document.getElementById("reserve-vehicle-type").addEventListener("change", updateFeePreview);

function updateFeePreview() {
  if (!CONFIG) { document.getElementById("reserve-fee-preview").textContent = "…"; return; }
  const type = document.getElementById("reserve-vehicle-type").value;
  const rate = CONFIG.rates_per_hour[type] || 0;
  const hour = new Date().getHours();
  const isPeak = CONFIG.peak_hours.some(([s, e]) => hour >= s && hour < e);
  let fee = rate * (selectedDuration / 60);
  if (isPeak) fee *= CONFIG.peak_multiplier;
  document.getElementById("reserve-fee-preview").textContent = fmtMoney(fee) + (isPeak ? " (peak)" : "");
}

document.getElementById("confirm-reservation-btn").addEventListener("click", async () => {
  const vehicleNumber = document.getElementById("reserve-vehicle-number").value.trim();
  const vehicleType = document.getElementById("reserve-vehicle-type").value;
  const errBox = document.getElementById("reserve-error");
  errBox.style.display = "none";

  if (!vehicleNumber || vehicleNumber.length < 4) {
    errBox.textContent = "Please enter a valid vehicle number.";
    errBox.style.display = "block";
    return;
  }

  const btn = document.getElementById("confirm-reservation-btn");
  btn.disabled = true; btn.textContent = "Reserving…";

  const data = await api("/api/reservations", {
    method: "POST",
    body: JSON.stringify({
      slot_id: selectedSlot.id, vehicle_number: vehicleNumber,
      vehicle_type: vehicleType, duration_minutes: selectedDuration,
    }),
  });

  btn.disabled = false; btn.textContent = "CONFIRM RESERVATION";

  if (!data.success) {
    errBox.textContent = data.error || "Unable to reserve slot.";
    errBox.style.display = "block";
    if (selectedZoneId) loadSlotMap(selectedZoneId); // refresh in case it was taken
    return;
  }

  closeModal("reserve-modal");
  toast(`Slot ${selectedSlot.number} reserved successfully.`);
  if (selectedZoneId) loadSlotMap(selectedZoneId);
  loadZones();
  loadDashboard();
});

// ---------------------------------------------------------------------
// My Parking
// ---------------------------------------------------------------------
async function loadMyParking() {
  if (activeTimerInterval) { clearInterval(activeTimerInterval); activeTimerInterval = null; }
  const data = await api("/api/parking/current");
  const box = document.getElementById("myparking-container");
  if (!data.success) { toast(data.error, true); return; }

  if (data.session) {
    const s = data.session;
    box.innerHTML = `
      <div class="active-parking-hero">
        <div class="muted" style="text-transform:uppercase;font-size:11px;letter-spacing:.08em;">Your Current Parking</div>
        <div class="slot-big">${s.slot_number}</div>
        <div class="muted" style="margin-bottom:6px;">${s.zone_name}</div>
        <div><span class="status-dot-live"></span><b>PARKED</b></div>
        <div class="muted" style="margin-top:10px;">Vehicle: <b style="color:var(--text)">${s.vehicle_number}</b></div>
        <div class="muted">Entry: ${fmtDateTime(s.entry_time)}</div>
        <div class="timer-display" id="live-timer">00:00:00</div>
        <div class="muted">Current Estimated Fee</div>
        <div class="fee-now" id="live-fee">${fmtMoney(data.current_estimated_fee || 0)}</div>
        <button class="btn btn-danger" style="margin-top:20px;" onclick="exitParking(${s.id})">EXIT PARKING</button>
      </div>`;
    startLiveTimer(s.entry_time, s.vehicle_type);
  } else if (data.reservation) {
    const r = data.reservation;
    box.innerHTML = `
      <div class="card">
        <div class="section-title" style="margin-top:0;">Active Reservation</div>
        <table>
          <tr><td>Vehicle</td><td>${r.vehicle_number}</td></tr>
          <tr><td>Zone</td><td>${r.zone_name}</td></tr>
          <tr><td>Slot</td><td>${r.slot_number}</td></tr>
          <tr><td>Status</td><td><span class="badge RESERVED">${r.status}</span></td></tr>
          <tr><td>Reserved at</td><td>${fmtDateTime(r.reservation_time)}</td></tr>
          <tr><td>Expected until</td><td>${fmtDateTime(r.expected_end_time)}</td></tr>
          <tr><td>Estimated fee</td><td>${fmtMoney(r.estimated_fee)}</td></tr>
        </table>
        <div style="display:flex;gap:10px;margin-top:18px;">
          <button class="btn btn-success btn-block" onclick="startParking(${r.id})">START PARKING</button>
          <button class="btn btn-ghost btn-block" onclick="cancelReservation(${r.id})">CANCEL</button>
        </div>
      </div>`;
  } else {
    box.innerHTML = `
      <div class="card">
        <div class="empty-state">
          <div class="icon">🅿️</div>No active parking session.
          <div style="margin-top:14px;"><button class="btn btn-primary" onclick="switchView('find')">Find Parking</button></div>
        </div>
      </div>`;
  }
}

function startLiveTimer(entryTimeStr, vehicleType) {
  const entry = new Date(entryTimeStr.replace(" ", "T"));
  function tick() {
    const elapsedMs = Date.now() - entry.getTime();
    const totalSec = Math.max(0, Math.floor(elapsedMs / 1000));
    const h = String(Math.floor(totalSec / 3600)).padStart(2, "0");
    const m = String(Math.floor((totalSec % 3600) / 60)).padStart(2, "0");
    const s = String(totalSec % 60).padStart(2, "0");
    const timerEl = document.getElementById("live-timer");
    if (timerEl) timerEl.textContent = `${h}:${m}:${s}`;
  }
  tick();
  activeTimerInterval = setInterval(tick, 1000);
  // refresh the backend-calculated fee periodically (backend is source of truth)
  setInterval(async () => {
    const data = await api("/api/parking/current");
    if (data.success && data.session) {
      const feeEl = document.getElementById("live-fee");
      if (feeEl) feeEl.textContent = fmtMoney(data.current_estimated_fee || 0);
    }
  }, 15000);
}

async function startParking(reservationId) {
  const data = await api("/api/parking/start", { method: "POST", body: JSON.stringify({ reservation_id: reservationId }) });
  if (!data.success) { toast(data.error, true); return; }
  toast("Parking started.");
  loadMyParking(); loadDashboard();
}

async function cancelReservation(id) {
  const data = await api(`/api/reservations/${id}/cancel`, { method: "POST" });
  if (!data.success) { toast(data.error, true); return; }
  toast("Reservation cancelled.");
  loadMyParking(); loadDashboard();
}

async function exitParking(sessionId) {
  const data = await api("/api/parking/exit", { method: "POST", body: JSON.stringify({ session_id: sessionId }) });
  if (!data.success) { toast(data.error, true); return; }
  toast("Parking session ended.");
  showReceipt(data.receipt);
  loadMyParking(); loadDashboard();
}

function showReceipt(r) {
  const html = `
    <h3>SMARTPARK</h3>
    <div class="sub">PARKING RECEIPT — Demo Payment</div>
    <div class="receipt-row"><span>Transaction ID</span><span>${r.transaction_reference}</span></div>
    <div class="receipt-row"><span>Vehicle Number</span><span>${r.vehicle_number}</span></div>
    <div class="receipt-row"><span>Zone</span><span>${r.zone_name}</span></div>
    <div class="receipt-row"><span>Slot</span><span>${r.slot_number}</span></div>
    <div class="receipt-row"><span>Entry Time</span><span>${fmtDateTime(r.entry_time)}</span></div>
    <div class="receipt-row"><span>Exit Time</span><span>${fmtDateTime(r.exit_time)}</span></div>
    <div class="receipt-row"><span>Duration</span><span>${fmtDuration(r.duration_minutes)}</span></div>
    <div class="receipt-row"><span>Rate</span><span>₹${r.rate_per_hour}/hr</span></div>
    <div class="receipt-row"><span>Peak Multiplier</span><span>${r.peak_multiplier_applied}x</span></div>
    <div class="receipt-row total"><span>Final Amount</span><span>${fmtMoney(r.final_amount)}</span></div>
    <div class="receipt-row"><span>Payment Status</span><span>${r.payment_status}</span></div>
  `;
  document.getElementById("receipt-content").innerHTML = html;
  openModal("receipt-modal");
}

// ---------------------------------------------------------------------
// History
// ---------------------------------------------------------------------
async function loadHistory() {
  const params = new URLSearchParams({
    vehicle: document.getElementById("filter-vehicle")?.value || "",
    zone: document.getElementById("filter-zone")?.value || "",
    date: document.getElementById("filter-date")?.value || "",
    status: document.getElementById("filter-status")?.value || "",
  });
  const data = await api(`/api/parking/history?${params.toString()}`);
  if (!data.success) { toast(data.error, true); return; }
  const tbody = document.getElementById("history-tbody");
  if (data.history.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:30px;">No history records found.</td></tr>`;
    return;
  }
  tbody.innerHTML = data.history.map(h => `
    <tr>
      <td>${h.transaction_reference}</td>
      <td>${fmtDateTime(h.created_at)}</td>
      <td>${h.vehicle_number}</td>
      <td>${h.zone_name}</td>
      <td>${h.slot_number}</td>
      <td>${fmtDateTime(h.entry_time)}</td>
      <td>${fmtDateTime(h.exit_time)}</td>
      <td>${fmtDuration(h.duration_minutes)}</td>
      <td>${fmtMoney(h.amount)}</td>
      <td><span class="badge ${h.payment_status}">${h.payment_status}</span></td>
    </tr>`).join("");
}

// ---------------------------------------------------------------------
// Rewards
// ---------------------------------------------------------------------
async function loadRewards() {
  const data = await api("/api/rewards");
  if (!data.success) { toast(data.error, true); return; }
  document.getElementById("rewards-points").textContent = data.total_points;
  const tbody = document.getElementById("rewards-tbody");
  if (data.history.length === 0) {
    tbody.innerHTML = `<tr><td colspan="3" style="text-align:center;padding:30px;">No reward activity yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = data.history.map(r => `
    <tr>
      <td>${fmtDateTime(r.created_at)}</td>
      <td>${r.reason}</td>
      <td style="color:${r.points >= 0 ? 'var(--green)' : 'var(--red)'};font-weight:700;">${r.points > 0 ? '+' : ''}${r.points}</td>
    </tr>`).join("");
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
(async function init() {
  CONFIG = await api("/api/config");
  loadDashboard();
})();
