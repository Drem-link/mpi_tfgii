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
  exportOneWord: document.querySelector("#export-one-word"),
  exportOneXlsx: document.querySelector("#export-one-xlsx"),
  exportAllXlsx: document.querySelector("#export-all-xlsx"),
  toast: document.querySelector("#toast"),
  accountButton: document.querySelector("#account-button"),
  accountOverlay: document.querySelector("#account-overlay"),
  closeAccount: document.querySelector("#close-account"),
  accountAnonymous: document.querySelector("#account-anonymous"),
  accountProfile: document.querySelector("#account-profile"),
  accountUsername: document.querySelector("#account-username"),
  accountPassword: document.querySelector("#account-password"),
  accountLogin: document.querySelector("#account-login"),
  accountRegister: document.querySelector("#account-register"),
  accountLogout: document.querySelector("#account-logout"),
  accountUserName: document.querySelector("#account-user-name"),
  accountError: document.querySelector("#account-error"),
  accountDatasets: document.querySelector("#account-datasets"),
  datasetSelect: document.querySelector("#dataset-select"),
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
  user: null,
  datasets: [],
  activeDatasetId: null,
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
  if (!state.user) {
    elements.accountError.textContent = "Войдите или создайте аккаунт, чтобы загрузить личный шейп.";
    elements.accountError.hidden = false;
    elements.accountOverlay.hidden = false;
    return;
  }
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
elements.accountButton.addEventListener("click", () => {
  elements.accountError.hidden = true;
  elements.accountOverlay.hidden = false;
});
elements.closeAccount.addEventListener("click", () => {
  elements.accountOverlay.hidden = true;
});
elements.accountOverlay.addEventListener("click", (event) => {
  if (event.target === elements.accountOverlay) elements.accountOverlay.hidden = true;
});
elements.uploadOverlay.addEventListener("click", (event) => {
  if (event.target === elements.uploadOverlay) closeUpload();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.uploadOverlay.hidden) closeUpload();
  if (event.key === "Escape" && !elements.accountOverlay.hidden) {
    elements.accountOverlay.hidden = true;
  }
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
    elements.mapCaption.textContent = "Обзор месторождений";
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
    } else {
      map.setView([61, 93], 3, { animate: false });
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
    elements.exportOneWord.href = `/api/export/word?record_id=${record.id}`;
    elements.exportOneWord.classList.remove("disabled");
    elements.exportOneWord.setAttribute("aria-disabled", "false");
    elements.exportOneXlsx.href = `/api/export/xlsx?record_id=${record.id}`;
    elements.exportOneXlsx.classList.remove("disabled");
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
  if (!dataset) {
    elements.count.textContent = "—";
    elements.exportOneWord.href = "#";
    elements.exportOneWord.classList.add("disabled");
    elements.exportOneWord.setAttribute("aria-disabled", "true");
    elements.exportOneXlsx.href = "#";
    elements.exportOneXlsx.classList.add("disabled");
    elements.exportOneXlsx.setAttribute("aria-disabled", "true");
    elements.exportAllXlsx.href = "#";
    elements.exportAllXlsx.classList.add("disabled");
    elements.exportAllXlsx.setAttribute("aria-disabled", "true");
    return;
  }
  elements.datasetName.textContent = dataset.name || dataset.filename;
  elements.count.textContent = new Intl.NumberFormat("ru-RU").format(dataset.count);
  elements.exportAllXlsx.href = "/api/export/xlsx";
  elements.exportAllXlsx.classList.remove("disabled");
  elements.exportAllXlsx.setAttribute("aria-disabled", "false");
}

function renderAccount() {
  const signedIn = Boolean(state.user);
  elements.accountAnonymous.hidden = signedIn;
  elements.accountProfile.hidden = !signedIn;
  elements.accountButton.textContent = signedIn ? state.user.username : "Кабинет";
  if (signedIn) elements.accountUserName.textContent = state.user.username;
  renderManagedDatasets();
}

function renderManagedDatasets() {
  elements.accountDatasets.replaceChildren();
  if (!state.user) return;
  const personal = state.datasets.filter((dataset) => !dataset.shared);
  if (!personal.length) {
    const empty = document.createElement("div");
    empty.className = "account-datasets-empty";
    empty.textContent = "Личных наборов пока нет. Нажмите «Мой шейп», чтобы загрузить ZIP.";
    elements.accountDatasets.append(empty);
    return;
  }
  for (const dataset of personal) {
    const item = document.createElement("article");
    item.className = `account-dataset${dataset.id === state.activeDatasetId ? " active" : ""}`;
    const select = document.createElement("button");
    select.type = "button";
    select.className = "account-dataset-select";
    const title = document.createElement("strong");
    title.textContent = dataset.name;
    const count = document.createElement("span");
    count.textContent = `${new Intl.NumberFormat("ru-RU").format(dataset.count)} записей`;
    select.append(title, count);
    select.addEventListener("click", () => activateDataset(dataset.id));

    const controls = document.createElement("div");
    controls.className = "account-dataset-controls";
    const name = document.createElement("input");
    name.className = "account-dataset-name";
    name.type = "text";
    name.maxLength = 80;
    name.value = dataset.name;
    name.setAttribute("aria-label", `Новое название набора ${dataset.name}`);
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "button";
    rename.textContent = "Переименовать";
    rename.addEventListener("click", async () => {
      try {
        await request(`/api/datasets/${encodeURIComponent(dataset.id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name.value }),
        });
        await loadDatasets();
        await loadRecords({ focusFirst: false });
        showToast("Набор переименован.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button delete-dataset";
    remove.textContent = "Удалить";
    remove.addEventListener("click", async () => {
      if (!window.confirm(`Удалить набор «${dataset.name}»? Это действие нельзя отменить.`)) return;
      try {
        await request(`/api/datasets/${encodeURIComponent(dataset.id)}`, { method: "DELETE" });
        await refreshDatasetView();
        showToast("Набор удалён.");
      } catch (error) {
        showToast(error.message, true);
      }
    });
    controls.append(name, rename, remove);
    item.append(select, controls);
    elements.accountDatasets.append(item);
  }
}

async function loadDatasets() {
  const payload = await request("/api/datasets");
  state.datasets = payload.items;
  state.activeDatasetId = payload.active_id;
  elements.datasetSelect.replaceChildren();
  for (const dataset of state.datasets) {
    const option = document.createElement("option");
    option.value = dataset.id;
    option.textContent = `${dataset.name} · ${new Intl.NumberFormat("ru-RU").format(dataset.count)}`;
    elements.datasetSelect.append(option);
  }
  elements.datasetSelect.value = payload.active_id || "";
  const hasChoices = state.datasets.length > 1;
  elements.datasetSelect.hidden = !hasChoices;
  elements.datasetName.hidden = hasChoices;
  if (!hasChoices) {
    elements.datasetName.textContent = state.datasets[0]?.name || "Данные не загружены";
  }
  renderAccount();
  return payload;
}

async function refreshDatasetView() {
  const payload = await loadDatasets();
  state.query = "";
  state.activeId = null;
  elements.search.value = "";
  state.selectedLayer.clearLayers();
  if (payload.active_id) {
    await loadMapOverview();
    await loadRecords({ focusFirst: false });
  } else {
    state.hasOverview = false;
    updateDataset(null);
    renderList();
    elements.detailsContent.hidden = true;
    elements.detailsEmpty.hidden = false;
    elements.mapEmpty.hidden = false;
  }
}

async function activateDataset(datasetId) {
  try {
    await request(`/api/datasets/${encodeURIComponent(datasetId)}/select`, { method: "POST" });
    await refreshDatasetView();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function submitAccount(action) {
  elements.accountError.hidden = true;
  const username = elements.accountUsername.value.trim();
  const password = elements.accountPassword.value;
  try {
    const payload = await request(`/api/auth/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    state.user = payload.user;
    elements.accountPassword.value = "";
    renderAccount();
    await refreshDatasetView();
    showToast(action === "register" ? "Аккаунт создан." : "Вы вошли в кабинет.");
  } catch (error) {
    elements.accountError.textContent = error.message;
    elements.accountError.hidden = false;
  }
}

elements.accountLogin.addEventListener("click", () => submitAccount("login"));
elements.accountRegister.addEventListener("click", () => submitAccount("register"));
for (const input of [elements.accountUsername, elements.accountPassword]) {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitAccount("login");
  });
}
elements.accountLogout.addEventListener("click", async () => {
  try {
    await request("/api/auth/logout", { method: "POST" });
    state.user = null;
    elements.accountPassword.value = "";
    renderAccount();
    await refreshDatasetView();
    elements.accountOverlay.hidden = true;
    showToast("Вы вышли из кабинета.");
  } catch (error) {
    elements.accountError.textContent = error.message;
    elements.accountError.hidden = false;
  }
});
elements.datasetSelect.addEventListener("change", () => activateDataset(elements.datasetSelect.value));

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
    const payload = await request("/api/datasets", { method: "POST", body });
    updateDataset(payload.dataset);
    state.query = "";
    elements.search.value = "";
    state.activeTab = "passport";
    elements.passportTab.classList.add("active");
    elements.sourceTab.classList.remove("active");
    elements.passportTab.setAttribute("aria-selected", "true");
    elements.sourceTab.setAttribute("aria-selected", "false");
    await loadDatasets();
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
    const account = await request("/api/auth/me");
    state.user = account.user;
    renderAccount();
    const payload = await loadDatasets();
    if (payload.active_id) {
      await loadMapOverview();
      await loadRecords({ focusFirst: false });
      if (state.dataset.warnings.length) showToast(state.dataset.warnings.join(" "));
    } else {
      updateDataset(null);
      renderList();
      if (state.user) openUpload();
      else elements.accountOverlay.hidden = false;
    }
  } catch (error) {
    renderList();
    showToast(error.message, true);
  }
}

initialize();
