const FIELD_LABELS = {
  NAME: "Название",
  SYNONYM: "Синоним",
  MINERAL: "Минерал",
  PI: "Полезное ископаемое",
  RANK: "Стадия освоения",
  DISTRICT: "Район",
  ASSOC: "Организация",
  CADASTRE: "Кадастровый номер",
  AREA: "Площадь, км²",
  LAT: "Широта",
  LON: "Долгота",
  COND: "Состояние",
  FORMATION: "Возраст / формация",
  GENTYPE: "Генетический тип",
  NOTES: "Примечание",
};

const elements = {
  count: document.querySelector("#record-count"),
  datasetName: document.querySelector("#dataset-name"),
  recordList: document.querySelector("#record-list"),
  search: document.querySelector("#search-input"),
  loadMore: document.querySelector("#load-more"),
  mapCaption: document.querySelector("#map-caption"),
  mapEmpty: document.querySelector("#map-empty"),
  mapCoordinates: document.querySelector("#map-coordinates"),
  mapFit: document.querySelector("#map-fit"),
  detailsEmpty: document.querySelector("#details-empty"),
  detailsContent: document.querySelector("#details-content"),
  recordNumber: document.querySelector("#record-number"),
  detailName: document.querySelector("#detail-name"),
  detailSummary: document.querySelector("#detail-summary"),
  fieldList: document.querySelector("#field-list"),
  sourceFieldCount: document.querySelector("#source-field-count"),
  exportOne: document.querySelector("#export-one"),
  exportOneXlsx: document.querySelector("#export-one-xlsx"),
  exportAll: document.querySelector("#export-all"),
  exportAllXlsx: document.querySelector("#export-all-xlsx"),
  toast: document.querySelector("#toast"),
  uploadOverlay: document.querySelector("#upload-overlay"),
  uploadButton: document.querySelector("#upload-button"),
  emptyUpload: document.querySelector("#empty-upload"),
  closeUpload: document.querySelector("#close-upload"),
  fileInput: document.querySelector("#file-input"),
  uploadProgress: document.querySelector("#upload-progress"),
  uploadError: document.querySelector("#upload-error"),
  passportTab: document.querySelector("#tab-passport"),
  sourceTab: document.querySelector("#tab-source"),
};

const state = {
  dataset: null,
  activeId: null,
  activeTab: "passport",
  query: "",
  offset: 0,
  total: 0,
  items: [],
  overviewLayer: null,
  selectedLayer: null,
  overviewBounds: null,
  hasOverview: false,
  toastTimer: null,
  searchTimer: null,
};

const map = L.map("map", {
  zoomControl: false,
  attributionControl: false,
  minZoom: 2,
  maxZoom: 17,
}).setView([61, 93], 3);
L.control.zoom({ position: "bottomright" }).addTo(map);
state.overviewLayer = L.featureGroup().addTo(map);
state.selectedLayer = L.featureGroup().addTo(map);
const overviewRenderer = L.canvas({ padding: 0.5 });

elements.mapFit.addEventListener("click", () => {
  if (state.overviewBounds?.isValid()) {
    map.fitBounds(state.overviewBounds.pad(0.06), { maxZoom: 5, animate: true });
  }
});

map.on("mousemove", (event) => {
  elements.mapCoordinates.textContent =
    `${event.latlng.lat.toFixed(4)}° N  ${event.latlng.lng.toFixed(4)}° E`;
});
map.on("mouseout", () => {
  elements.mapCoordinates.textContent = "WGS 84";
});

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    throw new Error(payload?.detail || `Ошибка сервера (${response.status})`);
  }
  return payload;
}

function showToast(message, isError = false) {
  clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.classList.add("visible");
  state.toastTimer = setTimeout(() => elements.toast.classList.remove("visible"), 4200);
}

function openUpload() {
  elements.uploadError.hidden = true;
  elements.uploadProgress.hidden = true;
  elements.uploadOverlay.hidden = false;
}

function closeUpload() {
  if (!elements.uploadProgress.hidden) return;
  elements.uploadOverlay.hidden = true;
}

elements.uploadButton.addEventListener("click", openUpload);
elements.emptyUpload.addEventListener("click", openUpload);
elements.closeUpload.addEventListener("click", closeUpload);
elements.uploadOverlay.addEventListener("click", (event) => {
  if (event.target === elements.uploadOverlay) closeUpload();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.uploadOverlay.hidden) closeUpload();
  if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault();
    elements.search.focus();
  }
});

function valueText(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 6 }).format(value);
  }
  return String(value);
}

function addField(label, value) {
  const row = document.createElement("div");
  row.className = "field-row";
  const name = document.createElement("span");
  name.className = "field-label";
  name.textContent = label;
  const content = document.createElement("span");
  content.className = `field-value${value === null || value === undefined || value === "" ? " empty" : ""}`;
  content.textContent = valueText(value);
  row.append(name, content);
  elements.fieldList.append(row);
}

function renderFields(record) {
  elements.fieldList.replaceChildren();
  if (state.activeTab === "source") {
    for (const [field, value] of Object.entries(record.attributes || {})) {
      addField(field, value);
    }
    return;
  }
  for (const [field, label] of Object.entries(FIELD_LABELS)) {
    const value = record.canonical?.[field];
    if (value !== null && value !== undefined && value !== "") addField(label, value);
  }
  if (!elements.fieldList.childElementCount) {
    const empty = document.createElement("div");
    empty.className = "list-empty";
    empty.textContent = "В паспорте пока нет заполненных полей.";
    elements.fieldList.append(empty);
  }
}

function renderSummary(record) {
  elements.detailSummary.replaceChildren();
  const fields = [
    record.canonical?.MINERAL || record.canonical?.PI,
    record.canonical?.DISTRICT,
    record.canonical?.CADASTRE,
  ].filter((value) => value !== null && value !== undefined && String(value).trim());
  if (record.center) {
    fields.push(`${record.center.lat.toFixed(4)}, ${record.center.lon.toFixed(4)}`);
  }
  if (!fields.length) fields.push("Паспортные данные");
  for (const [index, value] of fields.slice(0, 4).entries()) {
    const chip = document.createElement("span");
    chip.className = `summary-chip${index === fields.length - 1 && record.center ? " muted" : ""}`;
    chip.textContent = valueText(value);
    elements.detailSummary.append(chip);
  }
}

function drawGeometry(record, focusMap = true) {
  state.selectedLayer.clearLayers();
  elements.mapEmpty.hidden = state.hasOverview || Boolean(record.geometry || record.center);
  elements.mapCaption.textContent = record.name || "Обзор геометрии";
  if (record.geometry) {
    if (record.geometry.type === "Point") {
      const [lon, lat] = record.geometry.coordinates;
      L.circleMarker([lat, lon], {
        renderer: overviewRenderer,
        radius: 8,
        color: "#ffffff",
        weight: 2,
        fillColor: "#d28239",
        fillOpacity: 1,
      }).addTo(state.selectedLayer);
      if (focusMap) map.setView([lat, lon], Math.max(map.getZoom(), 8), { animate: true });
    } else {
      const layer = L.geoJSON(
        { type: "Feature", properties: {}, geometry: record.geometry },
        {
          style: {
            color: "#c77a34",
            weight: 2,
            opacity: 0.95,
            fillColor: "#e5aa66",
            fillOpacity: 0.25,
          },
          pointToLayer: (_feature, latlng) =>
            L.circleMarker(latlng, {
              renderer: overviewRenderer,
              radius: 8,
              color: "#ffffff",
              weight: 2,
              fillColor: "#d28239",
              fillOpacity: 1,
            }),
        },
      );
      state.selectedLayer.addLayer(layer);
      const bounds = layer.getBounds();
      if (focusMap && bounds.isValid()) {
        map.fitBounds(bounds.pad(0.18), { maxZoom: 14, animate: true });
      }
    }
  } else if (record.center) {
    L.circleMarker([record.center.lat, record.center.lon], {
      renderer: overviewRenderer,
      radius: 8,
      color: "#ffffff",
      weight: 2,
      fillColor: "#d28239",
      fillOpacity: 1,
    }).addTo(state.selectedLayer);
    if (focusMap) {
      map.setView(
        [record.center.lat, record.center.lon],
        Math.max(map.getZoom(), 8),
        { animate: true },
      );
    }
    elements.mapEmpty.hidden = true;
  } else if (!state.hasOverview) {
    map.setView([61, 93], 3);
  }
}

async function loadMapOverview() {
  try {
    const payload = await request("/api/map");
    state.overviewLayer.clearLayers();
    state.overviewBounds = L.latLngBounds([]);
    for (const item of payload.items) {
      const position = [item.lat, item.lon];
      state.overviewBounds.extend(position);
      const marker = L.circleMarker(position, {
        renderer: overviewRenderer,
        radius: 3.5,
        color: "#ffffff",
        weight: 1,
        fillColor: "#527c58",
        fillOpacity: 0.88,
      });
      marker.bindTooltip(item.name, { sticky: true, className: "map-tooltip" });
      marker.on("click", () => showMapRecord(item.id));
      marker.addTo(state.overviewLayer);
    }
    state.hasOverview = payload.items.length > 0;
    elements.mapEmpty.hidden = state.hasOverview;
    if (state.overviewBounds.isValid()) {
      map.fitBounds(state.overviewBounds.pad(0.06), { maxZoom: 5, animate: false });
    }
  } catch (error) {
    showToast(error.message, true);
  }
}

async function showMapRecord(recordId) {
  try {
    if (!state.items.some((item) => item.id === recordId)) {
      state.query = "";
      elements.search.value = "";
      await loadRecords({ focusFirst: false });
    }
    await selectRecord(recordId);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function selectRecord(recordId, { focusMap = true } = {}) {
  state.activeId = recordId;
  renderList();
  try {
    const record = await request(`/api/occurrences/${recordId}`);
    elements.detailsEmpty.hidden = true;
    elements.detailsContent.hidden = false;
    elements.recordNumber.textContent = `№ ${String(record.id + 1).padStart(3, "0")}`;
    elements.detailName.textContent = record.name || "Без названия";
    elements.sourceFieldCount.textContent = Object.keys(record.attributes || {}).length;
    elements.exportOne.href = `/api/export/dbf?record_id=${record.id}`;
    elements.exportOneXlsx.href = `/api/export/xlsx?record_id=${record.id}`;
    elements.exportOne.setAttribute("aria-disabled", "false");
    elements.exportOneXlsx.setAttribute("aria-disabled", "false");
    renderSummary(record);
    renderFields(record);
    drawGeometry(record, focusMap);
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderList() {
  elements.recordList.replaceChildren();
  if (!state.items.length) {
    const empty = document.createElement("div");
    empty.className = "list-empty";
    empty.textContent = state.dataset
      ? "По вашему запросу ничего не найдено."
      : "Загрузите ZIP-архив шейпа, чтобы увидеть список месторождений.";
    elements.recordList.append(empty);
    return;
  }
  for (const item of state.items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `record-item${item.id === state.activeId ? " active" : ""}`;
    button.setAttribute("aria-current", item.id === state.activeId ? "true" : "false");
    const index = document.createElement("span");
    index.className = "record-index";
    index.textContent = String(item.id + 1).padStart(2, "0");
    const content = document.createElement("span");
    const name = document.createElement("span");
    name.className = "record-name";
    name.textContent = item.name || "Без названия";
    const sub = document.createElement("span");
    sub.className = "record-sub";
    sub.textContent = [
      item.canonical?.MINERAL || item.canonical?.PI,
      item.canonical?.DISTRICT,
    ].filter(Boolean).map(valueText).join(" · ") || "Нет краткого описания";
    content.append(name, sub);
    button.append(index, content);
    button.addEventListener("click", () => selectRecord(item.id));
    elements.recordList.append(button);
  }
}

function updateDataset(dataset) {
  state.dataset = dataset;
  elements.datasetName.textContent = dataset.filename;
  elements.count.textContent = new Intl.NumberFormat("ru-RU").format(dataset.count);
  elements.exportAll.href = "/api/export/dbf";
  elements.exportAllXlsx.href = "/api/export/xlsx";
  elements.exportAll.classList.remove("disabled");
  elements.exportAllXlsx.classList.remove("disabled");
  elements.exportAll.setAttribute("aria-disabled", "false");
  elements.exportAllXlsx.setAttribute("aria-disabled", "false");
}

async function loadRecords({ reset = true, focusFirst = true } = {}) {
  if (reset) {
    state.offset = 0;
    state.items = [];
  }
  const payload = await request(
    `/api/occurrences?q=${encodeURIComponent(state.query)}&offset=${state.offset}&limit=80`,
  );
  updateDataset(payload.dataset);
  state.total = payload.total;
  state.items = reset ? payload.items : [...state.items, ...payload.items];
  state.offset = state.items.length;
  elements.count.textContent = new Intl.NumberFormat("ru-RU").format(payload.dataset.count);
  elements.loadMore.hidden = state.offset >= state.total;
  renderList();
  const selectedIsVisible = state.items.some((item) => item.id === state.activeId);
  if (reset) {
    const nextId = state.items[0]?.id ?? null;
    if (nextId === null) {
      state.activeId = null;
      elements.detailsContent.hidden = true;
      elements.detailsEmpty.hidden = false;
      state.selectedLayer.clearLayers();
      elements.mapEmpty.hidden = state.hasOverview;
    } else {
      await selectRecord(nextId, { focusMap: focusFirst });
    }
  } else if (!selectedIsVisible && state.items.length) {
    await selectRecord(state.items[0].id);
  }
}

elements.search.addEventListener("input", () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(() => {
    state.query = elements.search.value.trim();
    loadRecords().catch((error) => showToast(error.message, true));
  }, 220);
});
elements.loadMore.addEventListener("click", () => {
  loadRecords({ reset: false }).catch((error) => showToast(error.message, true));
});

elements.passportTab.addEventListener("click", () => setTab("passport"));
elements.sourceTab.addEventListener("click", () => setTab("source"));

async function setTab(tab) {
  state.activeTab = tab;
  elements.passportTab.classList.toggle("active", tab === "passport");
  elements.sourceTab.classList.toggle("active", tab === "source");
  elements.passportTab.setAttribute("aria-selected", String(tab === "passport"));
  elements.sourceTab.setAttribute("aria-selected", String(tab === "source"));
  if (state.activeId !== null) {
    try {
      renderFields(await request(`/api/occurrences/${state.activeId}`));
    } catch (error) {
      showToast(error.message, true);
    }
  }
}

elements.fileInput.addEventListener("change", async () => {
  const file = elements.fileInput.files?.[0];
  elements.fileInput.value = "";
  if (!file) return;
  elements.uploadError.hidden = true;
  elements.uploadProgress.hidden = false;
  elements.uploadButton.disabled = true;
  try {
    const body = new FormData();
    body.append("file", file);
    const payload = await request("/api/dataset", { method: "POST", body });
    updateDataset(payload.dataset);
    state.query = "";
    elements.search.value = "";
    state.activeTab = "passport";
    elements.passportTab.classList.add("active");
    elements.sourceTab.classList.remove("active");
    elements.passportTab.setAttribute("aria-selected", "true");
    elements.sourceTab.setAttribute("aria-selected", "false");
    await loadMapOverview();
    await loadRecords({ focusFirst: false });
    elements.uploadProgress.hidden = true;
    closeUpload();
    if (payload.dataset.warnings.length) {
      showToast(payload.dataset.warnings.join(" "));
    } else {
      showToast(`Загружено записей: ${payload.dataset.count}.`);
    }
  } catch (error) {
    elements.uploadError.textContent = error.message;
    elements.uploadError.hidden = false;
  } finally {
    elements.uploadProgress.hidden = true;
    elements.uploadButton.disabled = false;
  }
});

async function initialize() {
  try {
    const payload = await request("/api/status");
    if (payload.loaded) {
      updateDataset(payload.dataset);
      await loadMapOverview();
      await loadRecords({ focusFirst: false });
      if (payload.dataset.warnings.length) showToast(payload.dataset.warnings.join(" "));
    } else {
      renderList();
      openUpload();
    }
  } catch (error) {
    renderList();
    showToast(error.message, true);
  }
}

initialize();
