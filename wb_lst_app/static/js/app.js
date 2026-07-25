/* GeoHeat frontend logic
 * - Requests browser geolocation
 * - Renders an OSM street layer + Esri satellite layer via Leaflet
 * - Reverse-geocodes the point (via our own /api/reverse-geocode proxy)
 * - Fetches a heat-signature (LST) tile overlay from Earth Engine via /api/heat
 */

const DEFAULT_CENTER = [22.5726, 88.3639]; // Kolkata fallback if geolocation is denied
const DEFAULT_ZOOM = 12;

let map, marker, accuracyCircle, heatLayer;
let streetLayer, satelliteLayer;

const els = {
  status: document.getElementById("status-value"),
  city: document.getElementById("city-value"),
  region: document.getElementById("region-value"),
  lat: document.getElementById("lat-value"),
  lon: document.getElementById("lon-value"),
  acc: document.getElementById("acc-value"),
  locateBtn: document.getElementById("locate-btn"),
  locateLabel: document.getElementById("locate-label"),
  heatToggle: document.getElementById("heat-toggle"),
  heatOpacity: document.getElementById("heat-opacity"),
  toast: document.getElementById("toast"),
};

function showToast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
  els.toast.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => els.toast.classList.add("hidden"), 6000);
}

function setStatus(text) {
  els.status.textContent = text;
}

function initMap() {
  map = L.map("map", { zoomControl: true, attributionControl: true }).setView(
    DEFAULT_CENTER,
    DEFAULT_ZOOM
  );

  streetLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  });

  // Esri World Imagery — free, no-key satellite tiles that pair well with Leaflet.
  satelliteLayer = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      maxZoom: 19,
      attribution: "Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics",
    }
  );

  streetLayer.addTo(map);

  document.querySelectorAll('input[name="base"]').forEach((radio) => {
    radio.addEventListener("change", (e) => {
      if (e.target.value === "street") {
        map.removeLayer(satelliteLayer);
        streetLayer.addTo(map);
      } else {
        map.removeLayer(streetLayer);
        satelliteLayer.addTo(map);
      }
    });
  });

  els.heatToggle.addEventListener("change", (e) => {
    if (!heatLayer) return;
    if (e.target.checked) heatLayer.addTo(map);
    else map.removeLayer(heatLayer);
  });

  els.heatOpacity.addEventListener("input", (e) => {
    if (heatLayer) heatLayer.setOpacity(Number(e.target.value) / 100);
  });
}

function placeMarker(lat, lon, accuracyMeters) {
  if (marker) map.removeLayer(marker);
  if (accuracyCircle) map.removeLayer(accuracyCircle);

  marker = L.circleMarker([lat, lon], {
    radius: 6,
    color: "#ff6a1a",
    fillColor: "#ff6a1a",
    fillOpacity: 0.9,
    weight: 2,
  }).addTo(map);

  if (accuracyMeters) {
    accuracyCircle = L.circle([lat, lon], {
      radius: accuracyMeters,
      color: "#30c8e2",
      weight: 1,
      fillColor: "#30c8e2",
      fillOpacity: 0.08,
    }).addTo(map);
  }
}

async function reverseGeocode(lat, lon) {
  try {
    const res = await fetch(`/api/reverse-geocode?lat=${lat}&lon=${lon}`);
    if (!res.ok) throw new Error(`status ${res.status}`);
    const data = await res.json();
    els.city.textContent = data.city || "Unknown";
    els.region.textContent = [data.state, data.country].filter(Boolean).join(", ") || "—";
  } catch (err) {
    els.city.textContent = "lookup failed";
    els.region.textContent = "—";
    console.warn("Reverse geocode failed:", err);
  }
}

async function loadHeatLayer(lat, lon) {
  setStatus("fetching thermal data…");
  try {
    const res = await fetch(`/api/heat?lat=${lat}&lon=${lon}&radius_km=25`);
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `status ${res.status}`);
    }
    const data = await res.json();

    if (heatLayer) map.removeLayer(heatLayer);
    heatLayer = L.tileLayer(data.tile_url, {
      maxZoom: 19,
      opacity: Number(els.heatOpacity.value) / 100,
      attribution: "Google Earth Engine — " + data.dataset,
    });

    if (els.heatToggle.checked) heatLayer.addTo(map);

    setStatus("heat overlay live");
  } catch (err) {
    console.error("Heat layer failed:", err);
    setStatus("heat overlay unavailable");
    showToast(`Earth Engine overlay unavailable: ${err.message}`, true);
  }
}

function onLocationFound(lat, lon, accuracyMeters) {
  els.lat.textContent = lat.toFixed(6);
  els.lon.textContent = lon.toFixed(6);
  els.acc.textContent = accuracyMeters ? `${Math.round(accuracyMeters)} m` : "—";

  map.setView([lat, lon], 14);
  placeMarker(lat, lon, accuracyMeters);
  setStatus("position acquired");

  reverseGeocode(lat, lon);
  loadHeatLayer(lat, lon);
}

function locate() {
  if (!navigator.geolocation) {
    showToast("Geolocation is not supported by this browser.", true);
    return;
  }

  els.locateBtn.classList.add("working");
  setStatus("requesting location permission…");

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      els.locateBtn.classList.remove("working");
      onLocationFound(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy);
    },
    (err) => {
      els.locateBtn.classList.remove("working");
      setStatus("location denied — using default view");
      showToast(`Could not get your location: ${err.message}. Showing a default area instead.`, true);
      onLocationFound(DEFAULT_CENTER[0], DEFAULT_CENTER[1], null);
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

els.locateBtn.addEventListener("click", locate);

window.addEventListener("DOMContentLoaded", () => {
  initMap();
  locate(); // auto-request on load
});