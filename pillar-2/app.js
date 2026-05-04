const STOPS = [
  { id: "hbf", name: "Düsseldorf Hbf", coords: [51.2194, 6.7948], lines: ["U74", "U75", "709"], load: 82 },
  { id: "heinrich", name: "Heinrich-Heine-Allee", coords: [51.2278, 6.7735], lines: ["U70", "U76", "U77"], load: 64 },
  { id: "bilk", name: "Bilk S", coords: [51.2067, 6.7868], lines: ["S8", "S11", "S28"], load: 57 },
  { id: "medienhafen", name: "Medienhafen", coords: [51.2132, 6.7514], lines: ["706", "708"], load: 48 },
  { id: "unterbilk", name: "Unterbilk", coords: [51.2109, 6.7707], lines: ["706", "709"], load: 54 },
  { id: "friedrichstadt", name: "Friedrichstadt", coords: [51.2148, 6.7826], lines: ["704", "707"], load: 59 },
  { id: "stadtmitte", name: "Stadtmitte", coords: [51.2235, 6.7821], lines: ["701", "705", "U74"], load: 76 },
  { id: "carlstadt", name: "Carlstadt", coords: [51.2224, 6.7708], lines: ["706", "715"], load: 63 }
];

const INCIDENTS = [
  { id: "i1", stopId: "hbf", title: "Signalstörung", severity: "warn", delay: 6, type: "signal", radiusM: 180 },
  { id: "i2", stopId: "friedrichstadt", title: "Unfallmeldung (Demo)", severity: "bad", delay: 12, type: "accident", radiusM: 260 }
];

const OSTSTRASSE_HOTSPOT = L.latLng(51.22215, 6.78105);

const AI_INSIGHTS = [
  "Muster erkannt: Hohe Auslastung am Hbf zwischen 16:30 und 18:00 Uhr.",
  "Empfohlene Reserve: +1 Fahrzeug auf der U75 in 25 Minuten.",
  "Wetterkorrelation aktiv: +18% Meldehäufigkeit bei Starkregen."
];

const EMPLOYEE = {
  summary: "Heute im Einsatz: 42 Fahrer:innen, 6 in flexibler Reserve.",
  breaks: ["14:10-14:30 Uhr: Team Süd (2 Personen)", "14:35-14:55 Uhr: Team Nord (2 Personen)"],
  adjustments: ["Diensttausch Linie U76: Wagner <-> Yildiz", "Zusatzpause auf 706 wegen 12 Min. Stauversatz"]
};

const TYPE_LABELS = {
  delay: "Verspätung",
  accident: "Unfall",
  obstacle: "Hindernis",
  crowding: "Viele Passagiere"
};

const TYPE_SEVERITY = {
  delay: "warn",
  accident: "bad",
  obstacle: "bad",
  crowding: "warn"
};

const USERS = {
  user: { password: "user123", role: "user" },
  user2: { password: "user234", role: "user" },
  admin: { password: "admin123", role: "admin" }
};

const state = {
  role: null,
  username: null,
  reports: [],
  selectedStopId: null,
  routeLayers: [],
  startMarker: null,
  endMarker: null,
  accidentMarkers: [],
  affectedStopMarkers: []
};
const routingEngine = L.Routing.osrmv1();

const map = L.map("map", { zoomControl: true }).setView([51.2217, 6.7762], 13);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

const markerByStopId = new Map();
const stopByName = new Map();

for (const stop of STOPS) {
  stopByName.set(stop.name.toLowerCase(), stop);

  const marker = L.circleMarker(stop.coords, {
    radius: 9,
    color: "#1f4e95",
    fillColor: "#3f84e8",
    fillOpacity: 0.9,
    weight: 2
  }).addTo(map);

  marker.bindPopup(
    `<h3 class="popup-title">${stop.name}</h3>
     <p class="popup-line"><span>Linien</span><strong>${stop.lines.join(", ")}</strong></p>
     <p class="popup-line"><span>Auslastung</span><strong>${stop.load}%</strong></p>`
  );

  marker.on("click", () => {
    state.selectedStopId = stop.id;
    renderStopDetails();
  });

  markerByStopId.set(stop.id, marker);
}

renderIncidentList();
renderAiInsights();
renderEmployeePanel();
populateStopSelect();
populateRouteStops();
setReportDefaults();
wireReportForm();
wireAuth();
wireRouteForm();
renderStopDetails();
updateAuthUi();

function wireAuth() {
  const navLoginBtn = document.getElementById("nav-login-btn");
  const openLoginBtn = document.getElementById("open-login-btn");
  const closeLoginBtn = document.getElementById("close-login-btn");
  const logoutBtn = document.getElementById("nav-logout-btn");
  const loginForm = document.getElementById("login-form");

  navLoginBtn.addEventListener("click", openLoginModal);
  openLoginBtn.addEventListener("click", openLoginModal);
  closeLoginBtn.addEventListener("click", closeLoginModal);

  logoutBtn.addEventListener("click", () => {
    state.role = null;
    state.username = null;
    clearRoute();
    clearRouteImpact();
    setAuthMessage("Abgemeldet.", "success");
    updateAuthUi();
  });

  loginForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const formData = new FormData(loginForm);
    const username = String(formData.get("username") || "").trim().toLowerCase();
    const password = String(formData.get("password") || "");
    const user = USERS[username];

    if (!user || user.password !== password) {
      setAuthMessage("Login fehlgeschlagen. Bitte Zugangsdaten prüfen.", "error");
      return;
    }

    state.role = user.role;
    state.username = username;
    setAuthMessage(`Angemeldet als ${username} (${user.role}).`, "success");
    updateAuthUi();
    loginForm.reset();
    closeLoginModal();
  });
}

function updateAuthUi() {
  const isLoggedIn = Boolean(state.role);
  const homePage = document.getElementById("home-page");
  const dashboard = document.getElementById("dashboard");
  const authState = document.getElementById("auth-state");
  const welcomeTitle = document.getElementById("welcome-title");

  document.body.classList.remove("logged-in", "role-user", "role-admin");

  if (!isLoggedIn) {
    homePage.classList.remove("hidden");
    dashboard.classList.add("hidden");
    authState.textContent = "Nicht eingeloggt";
    welcomeTitle.textContent = "Verkehrsübersicht";
    map.invalidateSize();
    return;
  }

  document.body.classList.add("logged-in", `role-${state.role}`);
  homePage.classList.add("hidden");
  dashboard.classList.remove("hidden");
  authState.textContent = `Angemeldet als ${state.username} (${state.role})`;
  welcomeTitle.textContent = state.role === "admin" ? "Admin Leitstand" : "Nutzeransicht";
  setTimeout(() => map.invalidateSize(), 10);
}

function openLoginModal() {
  document.getElementById("login-modal").classList.remove("hidden");
}

function closeLoginModal() {
  document.getElementById("login-modal").classList.add("hidden");
}

function setAuthMessage(message, variant) {
  const el = document.getElementById("auth-message");
  el.textContent = message;
  el.classList.remove("auth-error", "auth-success");
  if (variant === "error") el.classList.add("auth-error");
  if (variant === "success") el.classList.add("auth-success");
}

function wireRouteForm() {
  document.getElementById("route-btn").addEventListener("click", async () => {
    const startInput = String(document.getElementById("route-start").value || "").trim();
    const endInput = String(document.getElementById("route-end").value || "").trim();

    if (!startInput || !endInput) {
      setRouteMessage("Bitte Start und Ziel eingeben.", "error");
      return;
    }

    setRouteMessage("Suche Route...", "success");

    const startPoint = await resolveLocation(startInput);
    const endPoint = await resolveLocation(endInput);
    if (!startPoint || !endPoint) {
      setRouteMessage("Start oder Ziel konnte nicht gefunden werden.", "error");
      return;
    }

    const routingOutcome = await computeIncidentAwareRoute(startPoint, endPoint);
    if (!routingOutcome) {
      setRouteMessage("Route konnte derzeit nicht berechnet werden.", "error");
      return;
    }

    drawRouteOutcome(routingOutcome);
    drawEndpointMarkers(startPoint, endPoint);
    renderRouteImpact(routingOutcome, startPoint, endPoint);
  });

  document.getElementById("clear-route-btn").addEventListener("click", () => {
    clearRoute();
    clearRouteImpact();
    setRouteMessage("Route entfernt.", "success");
  });
}

function drawRouteOutcome(outcome) {
  clearRoute();
  const newLayers = [];

  if (outcome.useAlternative && outcome.idealCoordinates.length > 0) {
    const blockedIdealLine = L.polyline(outcome.idealCoordinates, {
      color: "#c62828",
      weight: 5,
      opacity: 0.88
    }).addTo(map);
    newLayers.push(blockedIdealLine);
  }

  const activeCoordinates = outcome.useAlternative ? outcome.alternativeCoordinates : outcome.idealCoordinates;
  if (activeCoordinates.length > 0) {
    const activeLine = L.polyline(activeCoordinates, {
      color: "#005bbb",
      weight: 6,
      opacity: 0.95
    }).addTo(map);
    newLayers.push(activeLine);
  }

  if (newLayers.length > 0) {
    const group = L.featureGroup(newLayers);
    map.fitBounds(group.getBounds(), { padding: [24, 24] });
  }

  state.routeLayers = newLayers;
}

function drawEndpointMarkers(startPoint, endPoint) {
  clearEndpointMarkers();
  state.startMarker = L.marker([startPoint.lat, startPoint.lng], { icon: makeLetterIcon("A") }).addTo(map);
  state.endMarker = L.marker([endPoint.lat, endPoint.lng], { icon: makeLetterIcon("B") }).addTo(map);
}

function drawAccidentMarkers(incidents) {
  clearAccidentMarkers();
  for (const incident of incidents) {
    const center = getIncidentCoords(incident);
    if (!center) continue;
    state.accidentMarkers.push(
      L.marker(center, { icon: makeAccidentIcon() }).addTo(map).bindPopup(`Unfall: ${incident.title}<br/>+${incident.delay} Min`)
    );
  }
}

function drawAffectedStopMarkers(stopNames) {
  clearAffectedStopMarkers();
  for (const stopName of stopNames) {
    const stop = STOPS.find((s) => s.name === stopName);
    if (!stop) continue;
    state.affectedStopMarkers.push(
      L.circleMarker(stop.coords, {
        radius: 11,
        color: "#8c1f1f",
        fillColor: "#ffb3b3",
        fillOpacity: 0.9,
        weight: 3
      })
        .addTo(map)
        .bindPopup(`Betroffene Haltestelle: ${stop.name}`)
    );
  }
}

async function computeIncidentAwareRoute(startPoint, endPoint) {
  const startLatLng = L.latLng(startPoint.lat, startPoint.lng);
  const endLatLng = L.latLng(endPoint.lat, endPoint.lng);
  const baseRoutes = await routeWaypoints([toWaypoint(startLatLng), toWaypoint(endLatLng)]);
  if (!baseRoutes || baseRoutes.length === 0) return null;

  const baseRoute = baseRoutes[0];
  const incidentsOnRoute = findCriticalIncidentsOnRoute(baseRoute.coordinates);
  if (incidentsOnRoute.length === 0) {
    return {
      useAlternative: false,
      extraMinutes: 0,
      affectedStops: [],
      incidentsOnRoute: [],
      idealCoordinates: baseRoute.coordinates || [],
      alternativeCoordinates: [],
      alternativeStrategy: null
    };
  }

  const mainIncident = incidentsOnRoute[0];
  const detourPoint = buildDetourWaypoint(startLatLng, endLatLng, getIncidentCoords(mainIncident));
  const altRoutes = await routeWaypoints([toWaypoint(startLatLng), toWaypoint(detourPoint), toWaypoint(endLatLng)]);
  if (!altRoutes || altRoutes.length === 0) return null;

  const baseTimeSec = baseRoute.summary.totalTime || 0;
  const altTimeSec = altRoutes[0].summary.totalTime || baseTimeSec;
  const incidentDelaySec = incidentsOnRoute.reduce((sum, incident) => sum + incident.delay * 60, 0);
  const extraMinutes = Math.max(1, Math.round((Math.max(altTimeSec - baseTimeSec, 0) + incidentDelaySec) / 60));

  return {
    useAlternative: true,
    extraMinutes,
    affectedStops: getAffectedStops(incidentsOnRoute),
    incidentsOnRoute,
    primaryIncidentCenter: getIncidentCoords(mainIncident),
    idealCoordinates: baseRoute.coordinates || [],
    alternativeCoordinates: altRoutes[0].coordinates || [],
    alternativeStrategy: "Parallelstraße/Umfahrung"
  };
}

function getActiveIncidents() {
  const dynamic = state.reports
    .filter((r) => r.type === "accident" || r.type === "obstacle")
    .map((r, idx) => {
      const stop = getStopById(r.stopId);
      const nearOststrasse = stop && (stop.id === "stadtmitte" || stop.id === "friedrichstadt");
      const coords = nearOststrasse ? [OSTSTRASSE_HOTSPOT.lat, OSTSTRASSE_HOTSPOT.lng] : stop ? stop.coords : null;
      return {
        id: `racc-${idx}`,
        stopId: r.stopId,
        title: `${TYPE_LABELS[r.type]} (Meldung)`,
        severity: "bad",
        delay: Math.max(5, Number(r.delayImpact) || 5),
        type: "accident",
        coords,
        radiusM: 260
      };
    });

  return [...INCIDENTS, ...dynamic];
}

function routeWaypoints(waypoints) {
  return new Promise((resolve) => {
    routingEngine.route(waypoints, (error, routes) => resolve(error ? null : routes || null));
  });
}

function toWaypoint(latlng) {
  return new L.Routing.Waypoint(latlng);
}

function findCriticalIncidentsOnRoute(routeCoordinates) {
  const activeIncidents = getActiveIncidents();
  return activeIncidents.filter((incident) => {
    if (incident.severity !== "bad" || incident.type !== "accident") return false;
    const center = getIncidentCoords(incident);
    if (!center) return false;
    const threshold = incident.radiusM || 250;
    return routeCoordinates.some((coord) => map.distance(coord, center) <= threshold);
  });
}

function getIncidentCoords(incident) {
  if (Array.isArray(incident.coords) && incident.coords.length === 2) return L.latLng(incident.coords[0], incident.coords[1]);
  const stop = getStopById(incident.stopId);
  return stop ? L.latLng(stop.coords[0], stop.coords[1]) : null;
}

function buildDetourWaypoint(start, end, incidentCenter) {
  const dx = end.lng - start.lng;
  const dy = end.lat - start.lat;
  const length = Math.sqrt(dx * dx + dy * dy) || 0.0001;
  const normalX = -dy / length;
  const normalY = dx / length;
  const offset = 0.006;
  return L.latLng(incidentCenter.lat + normalY * offset, incidentCenter.lng + normalX * offset);
}

function getAffectedStops(incidents) {
  const affected = [];
  for (const stop of STOPS) {
    const stopLatLng = L.latLng(stop.coords[0], stop.coords[1]);
    const impacted = incidents.some((incident) => {
      const center = getIncidentCoords(incident);
      return center ? map.distance(center, stopLatLng) <= (incident.radiusM || 250) * 1.6 : false;
    });
    if (impacted) affected.push(stop.name);
  }
  return affected;
}

function renderRouteImpact(outcome, startPoint, endPoint) {
  const summary = document.getElementById("route-summary");
  const list = document.getElementById("route-impact-list");
  list.innerHTML = "";

  if (!outcome.useAlternative) {
    setRouteMessage(`Kürzeste Route von ${startPoint.label} nach ${endPoint.label} wird angezeigt.`, "success");
    summary.textContent = "Keine Unfall-Sperrung auf der Strecke erkannt.";
    drawAccidentMarkers([]);
    drawAffectedStopMarkers([]);
    return;
  }

  setRouteMessage("Unfall auf der Ideallinie erkannt. Alternative Route wurde vorgeschlagen.", "success");
  const p = outcome.primaryIncidentCenter;
  summary.textContent = `Rote Linie = Ideallinie (blockiert). Blaue Linie = Alternative (${outcome.alternativeStrategy}). Unfall nahe (${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}). Zusätzliche Fahrzeit: ca. ${outcome.extraMinutes} Minuten.`;

  drawAccidentMarkers(outcome.incidentsOnRoute);
  drawAffectedStopMarkers(outcome.affectedStops);

  for (const stopName of outcome.affectedStops) {
    const li = document.createElement("li");
    li.className = "incident-item";
    li.textContent = `Betroffene Haltestelle: ${stopName}`;
    list.appendChild(li);
  }
}

function clearRouteImpact() {
  document.getElementById("route-summary").textContent = "";
  document.getElementById("route-impact-list").innerHTML = "";
  clearEndpointMarkers();
  clearAccidentMarkers();
  clearAffectedStopMarkers();
}

function clearEndpointMarkers() {
  if (state.startMarker) map.removeLayer(state.startMarker);
  if (state.endMarker) map.removeLayer(state.endMarker);
  state.startMarker = null;
  state.endMarker = null;
}

function clearAccidentMarkers() {
  for (const marker of state.accidentMarkers) map.removeLayer(marker);
  state.accidentMarkers = [];
}

function clearAffectedStopMarkers() {
  for (const marker of state.affectedStopMarkers) map.removeLayer(marker);
  state.affectedStopMarkers = [];
}

function makeLetterIcon(letter) {
  return L.divIcon({
    className: "route-letter-icon",
    html: `<div style="width:24px;height:24px;border-radius:999px;background:#c62828;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.35);">${letter}</div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12]
  });
}

function makeAccidentIcon() {
  return L.divIcon({
    className: "accident-icon",
    html: '<div style="width:22px;height:22px;border-radius:999px;background:#8c1f1f;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.35);">!</div>',
    iconSize: [22, 22],
    iconAnchor: [11, 11]
  });
}

async function resolveLocation(rawInput) {
  const key = rawInput.toLowerCase();
  const stop = stopByName.get(key);
  if (stop) return { label: stop.name, lat: stop.coords[0], lng: stop.coords[1] };
  return geocodeAddress(rawInput);
}

async function geocodeAddress(query) {
  try {
    const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const results = await response.json();
    if (!Array.isArray(results) || results.length === 0) return null;
    const match = results[0];
    const lat = Number(match.lat);
    const lng = Number(match.lon);
    return Number.isFinite(lat) && Number.isFinite(lng) ? { label: match.display_name || query, lat, lng } : null;
  } catch (_error) {
    return null;
  }
}

function clearRoute() {
  if (!state.routeLayers || state.routeLayers.length === 0) return;
  for (const layer of state.routeLayers) map.removeLayer(layer);
  state.routeLayers = [];
}

function setRouteMessage(message, variant) {
  const el = document.getElementById("route-message");
  el.textContent = message;
  el.classList.remove("route-error", "route-success");
  if (variant === "error") el.classList.add("route-error");
  if (variant === "success") el.classList.add("route-success");
}

function populateRouteStops() {
  const datalist = document.getElementById("stop-options");
  datalist.innerHTML = "";
  for (const stop of STOPS) {
    const option = document.createElement("option");
    option.value = stop.name;
    datalist.appendChild(option);
  }
}

function getStopById(stopId) {
  return STOPS.find((s) => s.id === stopId) || null;
}

function severityClass(severity) {
  if (severity === "bad") return "status-bad";
  if (severity === "warn") return "status-warn";
  return "status-good";
}

function renderStopDetails() {
  const container = document.getElementById("stop-detail-content");
  const stop = getStopById(state.selectedStopId);
  if (!stop) {
    container.innerHTML = "";
    return;
  }

  const stopIncidents = getActiveIncidents().filter((incident) => incident.stopId === stop.id);
  const reportCount = state.reports.filter((r) => r.stopId === stop.id).length;

  container.innerHTML = `
    <div class="stop-detail-grid">
      <div class="stop-detail-row"><strong>Name</strong><small>${stop.name}</small></div>
      <div class="stop-detail-row"><strong>Linien</strong><small>${stop.lines.join(", ")}</small></div>
      <div class="stop-detail-row"><strong>Auslastung</strong><small>${stop.load}%</small></div>
      <div class="stop-detail-row"><strong>Störungen</strong><small>${stopIncidents.length}</small></div>
      <div class="stop-detail-row"><strong>Meldungen</strong><small>${reportCount}</small></div>
    </div>
  `;
}

function renderIncidentList() {
  const list = document.getElementById("incident-list");
  list.innerHTML = "";
  for (const incident of getActiveIncidents()) {
    const stop = getStopById(incident.stopId);
    const item = document.createElement("li");
    item.className = "incident-item";
    item.innerHTML = `
      <strong>${incident.title}</strong>
      <span>${stop ? stop.name : "Unbekannt"} · ${incident.delay} Min Verzögerung</span>
      <span class="status-chip ${severityClass(incident.severity)}">${incident.severity.toUpperCase()}</span>
    `;
    list.appendChild(item);
  }
}

function renderAiInsights() {
  const list = document.getElementById("ai-insight-list");
  list.innerHTML = "";
  for (const insight of AI_INSIGHTS) {
    const item = document.createElement("li");
    item.className = "incident-item";
    item.textContent = insight;
    list.appendChild(item);
  }
}

function renderReportLog() {
  const list = document.getElementById("report-log-list");
  list.innerHTML = "";
  if (state.reports.length === 0) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "Noch keine Meldungen.";
    list.appendChild(empty);
    return;
  }

  for (const report of [...state.reports].reverse()) {
    const stop = getStopById(report.stopId);
    const item = document.createElement("li");
    item.className = "incident-item";
    item.innerHTML = `
      <strong>${TYPE_LABELS[report.type] || report.type} · +${report.delayImpact} Min</strong>
      <span>${stop ? stop.name : "Unbekannt"} · ${formatDateTime(report.when)}</span>
      <span>${report.note || "Ohne Zusatzhinweis"}</span>
    `;
    list.appendChild(item);
  }
}

function renderEmployeePanel() {
  document.getElementById("employee-live-summary").textContent = EMPLOYEE.summary;
  const breakList = document.getElementById("employee-break-list");
  breakList.innerHTML = "";
  for (const line of EMPLOYEE.breaks) {
    const li = document.createElement("li");
    li.className = "incident-item";
    li.textContent = line;
    breakList.appendChild(li);
  }

  const adjustmentList = document.getElementById("employee-adjustment-list");
  adjustmentList.innerHTML = "";
  for (const line of EMPLOYEE.adjustments) {
    const li = document.createElement("li");
    li.className = "incident-item";
    li.textContent = line;
    adjustmentList.appendChild(li);
  }
}

function populateStopSelect() {
  const select = document.getElementById("report-stop-select");
  select.innerHTML = "";
  for (const stop of STOPS) {
    const option = document.createElement("option");
    option.value = stop.id;
    option.textContent = stop.name;
    select.appendChild(option);
  }
}

function setReportDefaults() {
  const dateInput = document.getElementById("report-date-input");
  const timeInput = document.getElementById("report-time-input");
  const nowBtn = document.getElementById("report-now-btn");

  const setNow = () => {
    const now = new Date();
    dateInput.value = toDateInput(now);
    timeInput.value = toTimeInput(now);
  };

  nowBtn.onclick = setNow;
  setNow();
}

function wireReportForm() {
  const form = document.getElementById("report-form");
  form.addEventListener("submit", (event) => {
    event.preventDefault();

    const formData = new FormData(form);
    const date = String(formData.get("reportDate") || "");
    const time = String(formData.get("reportTime") || "");

    const report = {
      type: String(formData.get("type")),
      stopId: String(formData.get("stopId")),
      delayImpact: Number(formData.get("delayImpact")) || 0,
      note: String(formData.get("note") || "").trim(),
      when: new Date(`${date}T${time}:00`)
    };

    state.reports.push(report);
    renderReportLog();
    renderStopDetails();
    renderIncidentList();
    maybeEscalateMarker(report);

    form.reset();
    setReportDefaults();
    populateStopSelect();
  });
}

function maybeEscalateMarker(report) {
  const marker = markerByStopId.get(report.stopId);
  if (!marker) return;
  const severity = TYPE_SEVERITY[report.type] || "warn";
  marker.setStyle({ color: severity === "bad" ? "#7d1a1a" : "#8a4a00", fillColor: severity === "bad" ? "#d64545" : "#ef8f28" });
}

function toDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function toTimeInput(date) {
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function formatDateTime(dateValue) {
  const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}
