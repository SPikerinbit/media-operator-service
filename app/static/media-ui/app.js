const form = document.querySelector("#batchForm");
const urlList = document.querySelector("#urlList");
const taskBody = document.querySelector("#taskBody");
const summary = document.querySelector("#summary");
const batchStatus = document.querySelector("#batchStatus");
const previewStage = document.querySelector("#previewStage");
const previewSubtitle = document.querySelector("#previewSubtitle");
const previewTask = document.querySelector("#previewTask");
const previewHint = document.querySelector("#previewHint");
const submitBatchButton = document.querySelector("#submitBatch");
const contextProfileSelect = document.querySelector("#translationContextProfile");

let events = null;
let selectedUrlId = null;
let previewCanvas = { width: 1080, height: 1920 };
let whisperModels = new Map();
let translationContextProfiles = [];
let biliCollections = [];
let biliZones = [];
let editScope = "batch";
let batchDefaults = null;
let batchCover = { cover_mode: "auto_middle_frame", cover_source: "frame", cover_time_percent: 50, cover_asset_url: "" };
let perItemCovers = {};
let coverTarget = { scope: "batch", rowId: null };
let urlRows = [
  { id: crypto.randomUUID(), kind: "youtube", value: "", overrides: {}, submit_status: "draft" },
  { id: crypto.randomUUID(), kind: "youtube", value: "", overrides: {}, submit_status: "draft" },
];

const settingsFieldIds = [
  "targetLang",
  "whisperModel",
  "whisperInferenceMode",
  "translateModel",
  "subtitleOutputMode",
  "aspectRatio",
  "resolution",
  "fps",
  "outputNameMode",
  "outputNamePrefix",
  "translationContextProfile",
  "translationContextName",
  "translationContextNote",
  "translationGlossary",
  "fontFamily",
  "fontWeight",
  "fontSize",
  "fontSizeMode",
  "primaryColor",
  "outlineColor",
  "outlineWidth",
  "shadow",
  "subtitlePosition",
  "yOffset",
  "maxWidth",
  "lineSpacing",
  "bilingualOrder",
  "backgroundEnabled",
  "backgroundColor",
  "backgroundOpacity",
  "backgroundPadding",
  "biliUploadEnabled",
  "biliLine",
  "biliTid",
  "biliCopyright",
  "biliSourceMode",
  "biliTitleTemplate",
  "biliTags",
  "biliSource",
  "biliSeries",
  "biliDesc",
];

const sample = {
  en: "I did not expect that answer.",
  zh: "我完全没想到会这样回答。",
};

function el(id) {
  return document.querySelector(`#${id}`);
}

function value(id) {
  return el(id).value;
}

function checked(id) {
  return el(id).checked;
}

function escapeHtml(input) {
  return String(input ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function splitUrls(text) {
  const seen = new Set(urlRows.map((row) => row.value.trim()).filter(Boolean));
  return text
    .split(/[\n\r,;，；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => {
      if (seen.has(item)) return false;
      seen.add(item);
      return true;
    });
}

function isYoutubeUrl(url) {
  try {
    const parsed = new URL(url);
    return ["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"].some((host) =>
      parsed.hostname.endsWith(host),
    );
  } catch {
    return false;
  }
}

function isLocalSourceValue(value) {
  const text = value.trim();
  if (!text) return false;
  if (text.startsWith("/files/") || text.startsWith("file://")) return true;
  if (/^[a-zA-Z]:[\\/]/.test(text)) return true;
  if (text.startsWith("\\\\")) return true;
  return false;
}

function rowLabel(kind) {
  return kind === "local" ? "本地" : "URL";
}

function newRow(kind = "youtube", value = "") {
  return { id: crypto.randomUUID(), kind, value, overrides: {}, submit_status: "draft" };
}

function selectedRow() {
  return urlRows.find((row) => row.id === selectedUrlId) || urlRows[0] || null;
}

function isCheckboxControl(control) {
  return control?.type === "checkbox";
}

function captureSettingsFromDom() {
  const values = {};
  for (const id of settingsFieldIds) {
    const control = el(id);
    if (!control) continue;
    values[id] = isCheckboxControl(control) ? Boolean(control.checked) : control.value;
  }
  return values;
}

function applySettingsToDom(settings) {
  for (const id of settingsFieldIds) {
    const control = el(id);
    if (!control || !(id in settings)) continue;
    if (isCheckboxControl(control)) control.checked = Boolean(settings[id]);
    else control.value = settings[id] ?? "";
  }
  renderWhisperModelStatus();
  renderBiliCollections();
  updateLabels();
  updatePreview();
  updateBiliCoverSummary();
}

function settingsEqual(a, b) {
  return String(a ?? "") === String(b ?? "");
}

function diffSettings(base, current) {
  const diff = {};
  for (const id of settingsFieldIds) {
    if (!settingsEqual(base?.[id], current?.[id])) diff[id] = current[id];
  }
  return diff;
}

function effectiveSettingsForRow(row) {
  return { ...(batchDefaults || captureSettingsFromDom()), ...(row?.overrides || {}) };
}

function rowHasOverrides(row) {
  return Boolean(row && row.overrides && Object.keys(row.overrides).length);
}

function saveCurrentEditContext() {
  const current = captureSettingsFromDom();
  if (!batchDefaults) batchDefaults = current;
  if (editScope === "batch") {
    batchDefaults = current;
    return;
  }
  const row = selectedRow();
  if (!row) return;
  row.overrides = diffSettings(batchDefaults, current);
}

function setEditScope(scope, rowId = selectedUrlId) {
  saveCurrentEditContext();
  editScope = scope === "item" ? "item" : "batch";
  if (rowId) selectedUrlId = rowId;
  const row = selectedRow();
  applySettingsToDom(editScope === "item" ? effectiveSettingsForRow(row) : batchDefaults || captureSettingsFromDom());
  updateEditContext();
  renderUrlRows();
}

function updateEditContext() {
  const batchButton = el("editBatchDefaults");
  const rowButton = el("editCurrentRow");
  const clearButton = el("clearCurrentOverride");
  const label = el("editContextLabel");
  const hint = el("editContextHint");
  const row = selectedRow();
  const index = Math.max(0, urlRows.findIndex((item) => item.id === row?.id)) + 1;
  batchButton?.classList.toggle("active", editScope === "batch");
  rowButton?.classList.toggle("active", editScope === "item");
  if (clearButton) clearButton.disabled = editScope !== "item" || !rowHasOverrides(row);
  if (label) {
    label.textContent =
      editScope === "item" && row
        ? `正在编辑：第 ${index} 条视频覆盖参数`
        : "正在编辑：批量默认参数";
  }
  if (hint) {
    hint.textContent =
      editScope === "item" && row
        ? rowHasOverrides(row)
          ? "本条已存在单独覆盖；未改动的字段继续继承批量默认。"
          : "修改任意字段后，只会覆盖当前视频。"
        : "未设置单独覆盖的视频会使用这里的参数。";
  }
}

function outputNameForRow(row, index) {
  const settings = effectiveSettingsForRow(row);
  const mode = settings.outputNameMode || value("outputNameMode");
  const prefix = String(settings.outputNamePrefix || "").trim();
  if (mode === "sequence") return `${prefix || "video"}${index}.mp4`;
  if (mode === "custom") return `${prefix || "final"}${index === 1 ? "" : index}.mp4`;
  return "使用原始标题";
}

function renderWhisperModelStatus() {
  const node = el("whisperModelStatus");
  if (!node) return;
  const selected = value("whisperModel");
  const status = whisperModels.get(selected);
  if (!status) {
    node.textContent = "模型状态未知";
    return;
  }
  node.textContent = status.available ? `本地可用：${selected}` : `未下载：${selected}`;
}

async function loadWhisperModels() {
  const node = el("whisperModelStatus");
  try {
    const response = await fetch("/ui/whisper-models");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "model status failed");
    whisperModels = new Map((data.models || []).map((item) => [item.name, item]));
    renderWhisperModelStatus();
  } catch (error) {
    if (node) node.textContent = `模型状态不可用：${error.message}`;
  }
}

function setContextStatus(message, isError = false) {
  const node = el("translationContextStatus");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("error", isError);
}

function apiErrorMessage(data, fallback) {
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        const path = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
        const message = item?.msg || JSON.stringify(item);
        return path ? `${path}: ${message}` : message;
      })
      .join("；");
  }
  if (detail && typeof detail === "object") return detail.message || JSON.stringify(detail);
  return fallback;
}

function selectedTranslationProfile() {
  const profileId = value("translationContextProfile");
  return translationContextProfiles.find((profile) => profile.profile_id === profileId) || null;
}

function renderTranslationContextProfiles(selectedId = value("translationContextProfile")) {
  if (!contextProfileSelect) return;
  contextProfileSelect.innerHTML =
    `<option value="">不使用预设</option>` +
    translationContextProfiles
      .map((profile) => `<option value="${escapeHtml(profile.profile_id)}">${escapeHtml(profile.name)}</option>`)
      .join("");
  contextProfileSelect.value = translationContextProfiles.some((profile) => profile.profile_id === selectedId)
    ? selectedId
    : "";
}

function applyTranslationProfile(profile) {
  el("translationContextProfile").value = profile?.profile_id || "";
  el("translationContextName").value = profile?.name || "";
  el("translationContextNote").value = profile?.note || "";
  el("translationGlossary").value = profile?.glossary || "";
}

function translationProfilePayload() {
  return {
    name: value("translationContextName").trim(),
    note: value("translationContextNote").trim(),
    glossary: value("translationGlossary").trim(),
  };
}

function splitBiliTags(text) {
  return String(text || "")
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 12);
}

function setBiliHint(message, isError = false) {
  const node = el("biliHint");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("error", isError);
}

function renderBiliCollections() {
  const select = el("biliSeries");
  if (!select) return;
  const current = select.value;
  select.innerHTML =
    `<option value="">不添加</option>` +
    biliCollections
      .map((item) => {
        const suffix = item.type === "series" ? "视频列表 series" : "合集 season";
        return `<option value="${escapeHtml(`${item.type}:${item.id}`)}">${escapeHtml(item.name)} · ${escapeHtml(suffix)}</option>`;
      })
      .join("");
  if (biliCollections.some((item) => `${item.type}:${item.id}` === current)) select.value = current;
}

async function loadBiliStatus() {
  const node = el("biliStatus");
  try {
    const response = await fetch("/ui/bilibili/status");
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, "bilibili status failed"));
    node.value = data.configured ? `已配置 · 并发 ${data.upload_concurrency}` : "未配置";
    setBiliHint(data.configured ? "B 站上传可用；Cookie 只在服务端读取。" : "未配置 B 站 Cookie，开启上传后会失败。", !data.configured);
  } catch (error) {
    node.value = "状态不可用";
    setBiliHint(`B 站状态不可用：${error.message}`, true);
  }
}

async function loadBiliCollections() {
  try {
    const response = await fetch("/ui/bilibili/collections");
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, "collections failed"));
    biliCollections = data.collections || [];
    renderBiliCollections();
    const errors = (data.errors || []).filter(Boolean);
    setBiliHint(
      `已载入 ${biliCollections.length} 个合集/系列。season 会在投稿时尝试绑定，series 会在投稿后添加。${errors.length ? ` 部分接口失败：${errors.join("；")}` : ""}`,
      false,
    );
  } catch (error) {
    setBiliHint(`合集/系列读取失败：${error.message}`, true);
  }
}

function renderBiliZones() {
  const select = el("biliTid");
  if (!select) return;
  const current = select.value || "130";
  const options = [];
  for (const main of biliZones) {
    const mainName = main.name || main.typename || "主分区";
    if (main.tid || main.id) {
      const tid = main.tid || main.id;
      options.push(`<option value="${escapeHtml(tid)}">${escapeHtml(`${mainName} / ${tid}`)}</option>`);
    }
    for (const sub of main.sub || []) {
      const tid = sub.tid || sub.id;
      if (!tid) continue;
      const subName = sub.name || sub.typename || "子分区";
      options.push(`<option value="${escapeHtml(tid)}">${escapeHtml(`${mainName} / ${subName} / ${tid}`)}</option>`);
    }
  }
  if (options.length) {
    select.innerHTML = options.join("");
    select.value = [...select.options].some((option) => option.value === current) ? current : "130";
  }
}

async function loadBiliZones() {
  try {
    const response = await fetch("/ui/bilibili/zones");
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, "zones failed"));
    biliZones = data.zones || [];
    renderBiliZones();
  } catch (error) {
    setBiliHint(`分区表读取失败：${error.message}`, true);
  }
}

function setting(settings, id) {
  if (settings && id in settings) return settings[id];
  return value(id);
}

function boolSetting(settings, id) {
  if (settings && id in settings) return Boolean(settings[id]);
  return checked(id);
}

function selectedCollectionPayload(settings = null) {
  const raw = setting(settings, "biliSeries");
  if (!raw) return { collection_type: "none", collection_id: "", series_id: "" };
  const [type, id] = raw.split(":", 2);
  return {
    collection_type: type === "series" || type === "season" ? type : "none",
    collection_id: id || "",
    series_id: type === "series" ? id || "" : "",
  };
}

function currentCoverForPayload() {
  return {
    cover_mode: batchCover.cover_mode || "auto_middle_frame",
    cover_source: batchCover.cover_source || "frame",
    cover_time_percent: Number(batchCover.cover_time_percent || 50),
    cover_asset_url: batchCover.cover_asset_url || "",
    per_item_covers: {},
  };
}

function coverSummaryText(config = batchCover) {
  if (!config || config.cover_mode === "auto_middle_frame") return "自动中间帧";
  if (config.cover_mode === "auto_first_frame") return "自动第一帧";
  if (config.cover_mode === "youtube_thumbnail" || config.cover_source === "youtube_thumbnail") return "YouTube 封面";
  if (config.cover_source === "uploaded_image" || config.cover_asset_url) return "上传图片";
  if (config.cover_mode === "selected_frame") return `视频帧 ${Math.round(config.cover_time_percent || 50)}%`;
  return "自动中间帧";
}

function updateBiliCoverSummary() {
  const node = el("biliCoverSummary");
  const preview = el("biliCoverPreview");
  const overrides = urlRows.filter((row) => perItemCovers[row.id]).length;
  if (node) {
    node.textContent = `批量默认封面：${coverSummaryText(batchCover)}；单条封面覆盖：${overrides} 条。批量默认仅用于未设置单条封面的视频。`;
  }
  const summary = el("biliSummary");
  if (summary) {
    const settings = editScope === "item" ? effectiveSettingsForRow(selectedRow()) : batchDefaults || captureSettingsFromDom();
    const tags = splitBiliTags(setting(settings, "biliTags"));
    const tid = setting(settings, "biliTid") || "130";
    const enabled = boolSetting(settings, "biliUploadEnabled");
    const collection = setting(settings, "biliSeries") ? "已选合集/系列" : "不添加合集";
    summary.textContent = enabled
      ? `已启用 · 分区 ${tid} · ${tags.length} 个标签 · ${collection} · 批量封面 ${coverSummaryText(batchCover)} · 单条封面 ${overrides} 条`
      : "未启用";
  }
  const batchPreviewUrl = batchCover.preview_url || batchCover.cover_asset_url;
  if (preview && batchPreviewUrl && coverTarget.scope === "batch") {
    preview.style.backgroundImage = `url("${batchPreviewUrl}")`;
    preview.innerHTML = "";
  }
}

async function loadTranslationContexts() {
  try {
    const response = await fetch("/ui/translation-contexts");
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, "context load failed"));
    translationContextProfiles = data.profiles || [];
    renderTranslationContextProfiles();
    setContextStatus("预设会完整保存；提交翻译时会按模型提示长度自动裁剪。");
  } catch (error) {
    setContextStatus(`预设不可用：${error.message}`, true);
  }
}

async function saveTranslationContextProfile() {
  const payload = translationProfilePayload();
  if (!payload.name) {
    setContextStatus("需要填写预设名称", true);
    return;
  }
  try {
    const response = await fetch("/ui/translation-contexts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, "save failed"));
    translationContextProfiles.push(data);
    renderTranslationContextProfiles(data.profile_id);
    applyTranslationProfile(data);
    setContextStatus(`已保存预设：${data.name}`);
  } catch (error) {
    setContextStatus(`保存失败：${error.message}`, true);
  }
}

async function updateTranslationContextProfile() {
  const current = selectedTranslationProfile();
  if (!current) {
    setContextStatus("先选择一个预设", true);
    return;
  }
  const payload = translationProfilePayload();
  if (!payload.name) {
    setContextStatus("需要填写预设名称", true);
    return;
  }
  try {
    const response = await fetch(`/ui/translation-contexts/${encodeURIComponent(current.profile_id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, "update failed"));
    translationContextProfiles = translationContextProfiles.map((profile) =>
      profile.profile_id === data.profile_id ? data : profile,
    );
    renderTranslationContextProfiles(data.profile_id);
    applyTranslationProfile(data);
    setContextStatus(`已更新预设：${data.name}`);
  } catch (error) {
    setContextStatus(`更新失败：${error.message}`, true);
  }
}

async function deleteTranslationContextProfile() {
  const current = selectedTranslationProfile();
  if (!current) {
    setContextStatus("先选择一个预设", true);
    return;
  }
  try {
    const response = await fetch(`/ui/translation-contexts/${encodeURIComponent(current.profile_id)}`, {
      method: "DELETE",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(data, "delete failed"));
    translationContextProfiles = translationContextProfiles.filter((profile) => profile.profile_id !== current.profile_id);
    renderTranslationContextProfiles("");
    applyTranslationProfile(null);
    setContextStatus("已删除预设");
  } catch (error) {
    setContextStatus(`删除失败：${error.message}`, true);
  }
}

function syncRowsFromDom() {
  urlRows = [...urlList.querySelectorAll(".url-row")].map((row) => ({
    id: row.dataset.id,
    kind: row.querySelector(".source-kind").value,
    value: row.querySelector(".url-input").value.trim(),
    overrides: urlRows.find((item) => item.id === row.dataset.id)?.overrides || {},
    submit_status: urlRows.find((item) => item.id === row.dataset.id)?.submit_status || "draft",
    batch_id: urlRows.find((item) => item.id === row.dataset.id)?.batch_id || "",
    item_id: urlRows.find((item) => item.id === row.dataset.id)?.item_id || "",
  }));
}

function renderUrlRows() {
  if (!selectedUrlId || !urlRows.some((row) => row.id === selectedUrlId)) selectedUrlId = urlRows[0]?.id || null;
  urlList.innerHTML = urlRows
    .map((row, index) => {
      const valid = row.kind === "local" ? isLocalSourceValue(row.value) : !row.value || isYoutubeUrl(row.value);
      const cover = perItemCovers[row.id] || null;
      const placeholder =
        row.kind === "local"
          ? "C:\\Videos\\source.mp4 或 /files/{job}/{file}"
          : "https://youtube.com/shorts/...";
      const selected = row.id === selectedUrlId ? " selected" : "";
      const submitStatus = row.submit_status || "draft";
      const stateClass =
        submitStatus === "running" || submitStatus === "submitted"
          ? " running"
          : submitStatus === "succeeded"
            ? " done"
            : submitStatus === "failed"
              ? " failed"
              : valid
                ? ""
                : " invalid";
      const stateText =
        submitStatus === "running" || submitStatus === "submitted"
          ? "运行中"
          : submitStatus === "succeeded"
            ? "已完成"
            : submitStatus === "failed"
              ? "失败"
              : row.kind === "local"
                ? valid
                  ? "未提交"
                  : row.value.trim()
                    ? "路径无效"
                    : "路径待填"
                : valid
                  ? "未提交"
                  : "URL 无效";
      const badges = [
        `<span class="row-badge${rowHasOverrides(row) ? " override" : ""}">${rowHasOverrides(row) ? "单独参数" : "批量默认"}</span>`,
        `<span class="row-badge${cover ? " cover" : ""}">${cover ? coverSummaryText(cover) : "默认封面"}</span>`,
      ].join("");
      return `<div class="url-row${selected}" data-id="${row.id}">
        <div class="url-row-top">
          <button class="row-index" type="button" data-action="select">${index + 1}</button>
          <select class="source-kind">
            <option value="youtube"${row.kind === "youtube" ? " selected" : ""}>URL</option>
            <option value="local"${row.kind === "local" ? " selected" : ""}>本地</option>
          </select>
          <div class="row-state${stateClass}">${stateText}</div>
          <div class="row-tools">
            <button class="icon-btn cover-btn" type="button" data-action="cover" title="设置单条封面">${cover ? "封" : "□"}</button>
            <button class="icon-btn" type="button" data-action="up" title="上移">↑</button>
            <button class="icon-btn" type="button" data-action="down" title="下移">↓</button>
            <button class="icon-btn danger" type="button" data-action="remove" title="删除">×</button>
          </div>
        </div>
        <div class="url-row-main">
          <input class="url-input" value="${escapeHtml(row.value)}" placeholder="${escapeHtml(placeholder)}" />
        </div>
        <div class="url-row-meta">
          <div class="name-preview">${escapeHtml(outputNameForRow(row, index + 1))}</div>
          <div class="row-badges">${badges}</div>
        </div>
      </div>`;
    })
    .join("");
  updateEditContext();
  updateBiliCoverSummary();
  updatePreview();
}

function currentStyle(settings = null) {
  return {
    font_family: setting(settings, "fontFamily"),
    font_size: Number(setting(settings, "fontSize")),
    font_size_mode: setting(settings, "fontSizeMode"),
    font_weight: Number(setting(settings, "fontWeight")),
    primary_color: setting(settings, "primaryColor"),
    outline_color: setting(settings, "outlineColor"),
    outline_width: Number(setting(settings, "outlineWidth")),
    shadow: Number(setting(settings, "shadow")),
    position: setting(settings, "subtitlePosition"),
    y_offset_percent: Number(setting(settings, "yOffset")),
    max_width_percent: Number(setting(settings, "maxWidth")),
    line_spacing: Number(setting(settings, "lineSpacing")),
    bilingual_order: setting(settings, "bilingualOrder"),
    background_enabled: boolSetting(settings, "backgroundEnabled"),
    background_color: setting(settings, "backgroundColor"),
    background_opacity: Number(setting(settings, "backgroundOpacity")),
    background_padding: Number(setting(settings, "backgroundPadding")),
  };
}

function defaultPreviewCanvas() {
  const ratio = value("aspectRatio");
  if (ratio === "16:9") return { width: 1920, height: 1080 };
  if (ratio === "1:1") return { width: 1080, height: 1080 };
  return { width: 1080, height: 1920 };
}

function payloadSettings(settings) {
  const style = currentStyle(settings);
  const collection = selectedCollectionPayload(settings);
  return {
    target_lang: setting(settings, "targetLang"),
    whisper_model: setting(settings, "whisperModel"),
    whisper_inference_mode: setting(settings, "whisperInferenceMode"),
    translate_model: setting(settings, "translateModel"),
    translation_context_profile_id: setting(settings, "translationContextProfile"),
    translation_context_note: String(setting(settings, "translationContextNote") || "").trim(),
    translation_glossary: String(setting(settings, "translationGlossary") || "").trim(),
    output_name_mode: setting(settings, "outputNameMode"),
    output_name_prefix: setting(settings, "outputNamePrefix"),
    aspect_ratio: setting(settings, "aspectRatio"),
    resolution: setting(settings, "resolution"),
    fps: setting(settings, "fps"),
    subtitle_font_size: style.font_size_mode === "auto" ? "auto" : "medium",
    subtitle_color: style.primary_color,
    subtitle_outline_color: style.outline_color,
    subtitle_position: style.position,
    subtitle_margin: "normal",
    subtitle_output_mode: setting(settings, "subtitleOutputMode"),
    subtitle_style: style,
    bilibili_upload: {
      enabled: boolSetting(settings, "biliUploadEnabled"),
      tid: Number(setting(settings, "biliTid")),
      tags: splitBiliTags(setting(settings, "biliTags")),
      desc: String(setting(settings, "biliDesc") || "").trim(),
      dynamic: "",
      copyright: Number(setting(settings, "biliCopyright")),
      source_mode: setting(settings, "biliSourceMode"),
      source: String(setting(settings, "biliSource") || "").trim(),
      no_reprint: true,
      title_template: String(setting(settings, "biliTitleTemplate") || "").trim() || "{output_name}",
      line: setting(settings, "biliLine"),
      collection_type: collection.collection_type,
      collection_id: collection.collection_id,
      series_id: collection.series_id,
    },
  };
}

function rowPayloadOverride(row) {
  if (!rowHasOverrides(row) && !perItemCovers[row.id]) return null;
  const override = payloadSettings(effectiveSettingsForRow(row));
  const cover = perItemCovers[row.id];
  if (cover) {
    override.bilibili_upload = {
      ...override.bilibili_upload,
      cover_mode: cover.cover_mode || "auto_middle_frame",
      cover_scope: "per_item",
      cover_source: cover.cover_source || "frame",
      cover_time_percent: Number(cover.cover_time_percent || 50),
      cover_asset_url: cover.cover_asset_url || "",
      per_item_covers: {},
    };
  }
  return override;
}

function payloadFromForm(options = {}) {
  saveCurrentEditContext();
  syncRowsFromDom();
  const mode = options.mode || "draft";
  const sources = [];
  const youtubeUrls = [];
  const itemOverrides = {};
  const seen = new Set();
  for (const row of urlRows) {
    const url = row.value.trim();
    if (!url || seen.has(url)) continue;
    if (mode === "draft" && row.submit_status && row.submit_status !== "draft") continue;
    if (mode === "failed" && row.submit_status !== "failed") continue;
    if (mode === "selected" && row.id !== selectedUrlId) continue;
    seen.add(url);
    sources.push({ source_kind: row.kind || "youtube", source_value: url, client_row_id: row.id });
    if ((row.kind || "youtube") === "youtube") youtubeUrls.push(url);
    const override = rowPayloadOverride(row);
    if (override) itemOverrides[row.id] = override;
  }
  const cover = currentCoverForPayload();
  const base = payloadSettings(batchDefaults || captureSettingsFromDom());
  return {
    ...base,
    sources,
    youtube_urls: youtubeUrls,
    item_overrides: itemOverrides,
    rights_confirmed: checked("rightsConfirmed"),
    batch_concurrency: Number(value("batchConcurrency")),
    bilibili_upload: {
      ...base.bilibili_upload,
      cover_mode: cover.cover_mode,
      cover_path: "",
      cover_scope: "batch",
      cover_source: cover.cover_source,
      cover_time_percent: cover.cover_time_percent,
      cover_asset_url: cover.cover_asset_url,
      per_item_covers: {},
    },
  };
}

function previewLines() {
  const mode = value("subtitleOutputMode");
  const order = value("bilingualOrder");
  if (mode === "zh_only") return [sample.zh];
  if (mode === "en_only") return [sample.en];
  return order === "zh_top_en_bottom" ? [sample.zh, sample.en] : [sample.en, sample.zh];
}

function updateLabels() {
  el("fontSizeLabel").textContent = value("fontSize");
  el("outlineWidthLabel").textContent = value("outlineWidth");
  el("shadowLabel").textContent = value("shadow");
  el("yOffsetLabel").textContent = `${value("yOffset")}%`;
  el("maxWidthLabel").textContent = `${value("maxWidth")}%`;
  el("lineSpacingLabel").textContent = value("lineSpacing");
  el("backgroundOpacityLabel").textContent = `${value("backgroundOpacity")}%`;
  el("backgroundPaddingLabel").textContent = value("backgroundPadding");
  el("previewTimeLabel").textContent = `${value("previewTimePercent")}%`;
}

function updatePreview() {
  updateLabels();
  const style = currentStyle();
  const ratio = value("aspectRatio");
  if (!previewCanvas || previewStage.dataset.ratio !== ratio) {
    previewCanvas = defaultPreviewCanvas();
  }
  previewStage.dataset.ratio = ratio;
  previewStage.dataset.canvas = `${previewCanvas.width}x${previewCanvas.height}`;
  previewSubtitle.innerHTML = previewLines().map((line) => `<span>${escapeHtml(line)}</span>`).join("");
  const previewHeight = Math.max(1, previewStage.clientHeight || previewCanvas.height);
  const scale = previewHeight / 1080;
  const fontPx = Math.max(8, style.font_size * scale);
  const outlinePx = Math.max(0, style.outline_width * scale);
  const shadowPx = Math.max(0, style.shadow * scale);
  const paddingPx = Math.max(0, style.background_padding * scale);
  previewSubtitle.style.fontFamily = `"${style.font_family}", "Microsoft YaHei", Arial, sans-serif`;
  previewSubtitle.style.fontSize = `${fontPx}px`;
  previewSubtitle.style.fontWeight = String(style.font_weight);
  previewSubtitle.style.color = style.primary_color;
  previewSubtitle.style.webkitTextStroke = `${outlinePx}px ${style.outline_color}`;
  previewSubtitle.style.textShadow = shadowPx ? `0 ${shadowPx}px ${shadowPx * 2}px rgba(0,0,0,.65)` : "none";
  previewSubtitle.style.maxWidth = `${style.max_width_percent}%`;
  previewSubtitle.style.lineHeight = String(style.line_spacing);
  previewSubtitle.style.padding = style.background_enabled ? `${paddingPx}px ${paddingPx + 8 * scale}px` : "0";
  previewSubtitle.style.background = style.background_enabled
    ? hexToRgba(style.background_color, style.background_opacity / 100)
    : "transparent";
  previewSubtitle.style.borderRadius = style.background_enabled ? "6px" : "0";
  previewSubtitle.dataset.position = style.position;
  previewSubtitle.style.top = "";
  previewSubtitle.style.bottom = "";
  previewSubtitle.style.transform = "translateX(-50%)";
  if (style.position === "top") {
    previewSubtitle.style.top = `${style.y_offset_percent}%`;
  } else if (style.position === "middle") {
    previewSubtitle.style.top = "50%";
    previewSubtitle.style.transform = "translate(-50%, -50%)";
  } else {
    previewSubtitle.style.bottom = `${style.y_offset_percent}%`;
  }
  const selectedIndex = Math.max(0, urlRows.findIndex((row) => row.id === selectedUrlId));
  previewTask.textContent = `当前：第 ${selectedIndex + 1} 条`;
  previewHint.textContent = previewStage.style.backgroundImage ? previewHint.textContent : `模拟预览 · ${previewCanvas.width}x${previewCanvas.height}`;
}

function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function stageChips(item) {
  const stages = [
    ["download", "下载"],
    ["transcribe", "转写"],
    ["translate", "翻译"],
    ["burn", "烧录"],
    ["bilibili_upload", "上传"],
  ];
  const details = item.stage_details || {};
  const stageMap = {
    download: 0,
    transcribe: 1,
    translate: 2,
    burn: 3,
    bilibili_upload: 4,
    dify_workflow: Math.max(0, Math.min(3, Math.floor((item.progress || 0) / 25))),
    done: 5,
  };
  const active = stageMap[item.stage] ?? -1;
  return `<div class="chips">${stages
    .map(([key, label], index) => {
      const detail = details[key] || {};
      let cls = "chip";
      if (detail.status === "failed" || (item.status === "failed" && index === active)) cls += " fail";
      else if (detail.status === "succeeded" || item.status === "succeeded" || index < active) cls += " done";
      else if (detail.status === "running" || index === active) cls += " active";
      const title = detail.message ? ` title="${escapeHtml(detail.message)}"` : "";
      const suffix = Number.isFinite(Number(detail.progress)) ? ` ${detail.progress}%` : "";
      return `<span class="${cls}"${title}>${label}${suffix}</span>`;
    })
    .join("")}</div><span class="small">${escapeHtml(item.progress_detail || item.message || item.stage || "")}</span>`;
}

function stageProgressDetail(item) {
  if (item.progress_detail) return item.progress_detail;
  const stage = item.stage || "queued";
  const progress = Math.max(0, Math.min(100, item.progress || 0));
  const details = {
    queued: "等待进入队列",
    download:
      progress < 10
        ? "解析链接与格式"
        : progress < 90
          ? "下载视频与音频流"
          : "封装合并输出文件",
    transcribe:
      progress < 15
        ? "初始化 Whisper"
        : progress < 45
          ? "提取音轨并切分语音"
          : progress < 85
            ? "识别语音并对齐时间轴"
            : "整理字幕段落",
    translate:
      progress < 20
        ? "准备翻译上下文"
        : progress < 80
          ? "生成双语或中文字幕"
          : "合并翻译结果",
    burn:
      progress < 20
        ? "构建字幕样式"
        : progress < 70
          ? "渲染画幅并烧录字幕"
          : "输出最终视频",
    bilibili_upload:
      progress < 20
        ? "准备 B 站投稿"
        : progress < 96
          ? "上传视频与提交稿件"
          : "添加合集/系列",
    dify_workflow:
      progress < 20
        ? "已提交到 Dify"
        : progress < 60
          ? "Dify 工作流运行中"
          : progress < 95
            ? "等待工作流产出结果"
            : "整理最终结果",
    done: "已完成",
  };
  return details[stage] || item.message || "处理中";
}

function logTailHtml(item) {
  const lines = Array.isArray(item.log_tail) ? item.log_tail.slice(-5) : [];
  if (!lines.length) return "";
  return `<div class="log-tail">${lines.map((line) => `<div>${escapeHtml(line)}</div>`).join("")}</div>`;
}

function coverTargetRow() {
  syncRowsFromDom();
  if (coverTarget.scope === "per_item") {
    return urlRows.find((row) => row.id === coverTarget.rowId) || urlRows.find((row) => row.id === selectedUrlId) || urlRows[0];
  }
  return urlRows.find((row) => row.id === selectedUrlId) || urlRows[0];
}

function openCoverModal(scope = "batch", rowId = null) {
  coverTarget = { scope, rowId };
  const modal = el("coverModal");
  const label = el("coverTargetLabel");
  const row = coverTargetRow();
  const config = scope === "per_item" ? perItemCovers[row?.id] || {} : batchCover;
  if (label) {
    label.textContent =
      scope === "per_item"
        ? `应用范围：仅第 ${Math.max(1, urlRows.findIndex((item) => item.id === row?.id) + 1)} 条视频`
        : "应用范围：批量默认，仅用于未设置单条封面的视频";
  }
  el("biliCoverTimePercent").value = String(config.cover_time_percent || batchCover.cover_time_percent || 50);
  el("biliCoverTimeLabel").textContent = `${el("biliCoverTimePercent").value}%`;
  const preview = el("biliCoverPreview");
  const previewUrl = config.preview_url || config.cover_asset_url || "";
  preview.style.backgroundImage = previewUrl ? `url("${previewUrl}")` : "";
  preview.innerHTML = previewUrl ? "" : `<span>${escapeHtml(coverSummaryText(config))}</span>`;
  const youtubeButton = el("useYoutubeThumbnail");
  if (youtubeButton) {
    const canUseYoutube = row?.kind === "youtube" && isYoutubeUrl(row.value || "");
    youtubeButton.disabled = !canUseYoutube;
    youtubeButton.title = canUseYoutube ? "使用当前 YouTube 链接的原始封面" : "本地视频没有 YouTube 封面";
  }
  el("coverStatus").textContent = "封面会直接作为最终投稿封面，不提供二次编辑。";
  modal.hidden = false;
}

function closeCoverModal() {
  el("coverModal").hidden = true;
}

function applyCoverConfig(config) {
  syncRowsFromDom();
  if (coverTarget.scope === "per_item") {
    const row = coverTargetRow();
    if (!row?.value) {
      el("coverStatus").textContent = "先填写该条来源";
      return;
    }
    perItemCovers[row.id] = config;
  } else {
    batchCover = { ...batchCover, ...config };
  }
  updateBiliCoverSummary();
  if (!urlList.contains(document.activeElement)) renderUrlRows();
}

async function useCurrentFrameAsCover() {
  const row = coverTargetRow();
  if (!row?.value) {
    el("coverStatus").textContent = "先填写来源";
    return;
  }
  if (row.kind === "youtube" && !isYoutubeUrl(row.value)) {
    el("coverStatus").textContent = "先选择有效 URL";
    return;
  }
  if (row.kind === "local" && !isLocalSourceValue(row.value)) {
    el("coverStatus").textContent = "本地路径看起来不正确";
    return;
  }
  const percent = Number(value("biliCoverTimePercent"));
  el("coverStatus").textContent = "抓取封面中";
  try {
    const response = await fetch("/ui/bilibili/cover-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_kind: row.kind || "youtube",
        source_value: row.value,
        youtube_url: row.kind === "youtube" ? row.value : "",
        preview_time_percent: percent,
        cover_source_mode: "frame",
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "cover preview failed");
    const previewUrl = `${data.cover_image_url}${data.cover_image_url.includes("?") ? "&" : "?"}v=${Date.now()}`;
    el("biliCoverPreview").style.backgroundImage = `url("${previewUrl}")`;
    el("biliCoverPreview").innerHTML = "";
    applyCoverConfig({
      cover_mode: "selected_frame",
      cover_source: "frame",
      cover_time_percent: percent,
      cover_asset_url: "",
      preview_url: data.cover_image_url,
    });
    el("coverStatus").textContent = `已选择视频帧 ${Math.round(data.preview_time_seconds || 0)}s`;
  } catch (error) {
    el("coverStatus").textContent = error.message;
  }
}

async function useYoutubeThumbnailAsCover() {
  const row = coverTargetRow();
  if (!row?.value) {
    el("coverStatus").textContent = "先填写来源";
    return;
  }
  if (row.kind !== "youtube" || !isYoutubeUrl(row.value)) {
    el("coverStatus").textContent = "本地视频没有 YouTube 封面";
    return;
  }
  el("coverStatus").textContent = "读取 YouTube 封面中";
  try {
    const response = await fetch("/ui/bilibili/cover-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_kind: "youtube",
        source_value: row.value,
        youtube_url: row.value,
        preview_time_percent: Number(value("biliCoverTimePercent")),
        cover_source_mode: "youtube_thumbnail",
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "youtube thumbnail failed");
    const previewUrl = `${data.cover_image_url}${data.cover_image_url.includes("?") ? "&" : "?"}v=${Date.now()}`;
    el("biliCoverPreview").style.backgroundImage = `url("${previewUrl}")`;
    el("biliCoverPreview").innerHTML = "";
    applyCoverConfig({
      cover_mode: "youtube_thumbnail",
      cover_source: "youtube_thumbnail",
      cover_time_percent: Number(value("biliCoverTimePercent")),
      cover_asset_url: data.cover_asset_url,
      preview_url: data.cover_image_url,
      thumbnail_url: data.thumbnail_url || "",
    });
    el("coverStatus").textContent = data.title ? `已使用 YouTube 封面：${data.title}` : "已使用 YouTube 封面";
  } catch (error) {
    el("coverStatus").textContent = error.message;
  }
}

async function uploadCoverImage(file) {
  if (!file) return;
  el("coverStatus").textContent = "上传封面中";
  const formData = new FormData();
  formData.append("file", file);
  try {
    const response = await fetch("/ui/bilibili/cover-upload", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "cover upload failed");
    const previewUrl = `${data.cover_image_url}${data.cover_image_url.includes("?") ? "&" : "?"}v=${Date.now()}`;
    el("biliCoverPreview").style.backgroundImage = `url("${previewUrl}")`;
    el("biliCoverPreview").innerHTML = "";
    applyCoverConfig({
      cover_mode: "uploaded_image",
      cover_source: "uploaded_image",
      cover_time_percent: Number(value("biliCoverTimePercent")),
      cover_asset_url: data.cover_asset_url,
    });
    el("coverStatus").textContent = `已使用上传图片：${data.filename || file.name}`;
  } catch (error) {
    el("coverStatus").textContent = error.message;
  } finally {
    el("biliCoverFile").value = "";
  }
}

function clearCoverChoice() {
  syncRowsFromDom();
  if (coverTarget.scope === "per_item") {
    const row = coverTargetRow();
    if (row?.id) delete perItemCovers[row.id];
  } else {
    batchCover = { cover_mode: "auto_middle_frame", cover_source: "frame", cover_time_percent: 50, cover_asset_url: "" };
  }
  updateBiliCoverSummary();
  renderUrlRows();
  closeCoverModal();
}

function resultLink(item) {
  const result = item.result || {};
  const finalUrl = result.final_video_url || result.result_url || "";
  const srtUrl = result.bilingual_srt_url || result.english_srt_url || "";
  const outputName = item.output_name || result.output_name || "";
  if (item.status === "failed") {
    const message = item.error?.message || item.message || "failed";
    return `<span class="small">${escapeHtml(message)}</span>`;
  }
  const links = [];
  if (finalUrl) links.push(`<a href="${escapeHtml(finalUrl)}" target="_blank" rel="noreferrer">视频</a>`);
  if (srtUrl) links.push(`<a href="${escapeHtml(srtUrl)}" target="_blank" rel="noreferrer">字幕</a>`);
  if (result.bilibili_url) links.push(`<a href="${escapeHtml(result.bilibili_url)}" target="_blank" rel="noreferrer">B站</a>`);
  if (!links.length) return `<span class="small">${escapeHtml(outputName || "-")}</span>`;
  return `${links.join(" · ")}<span class="small">${escapeHtml(outputName)}</span>`;
}

function renderBatch(batch) {
  const items = batch.items || [];
  for (const item of items) {
    const sourceValue = item.source_value || item.youtube_url || "";
    const row = urlRows.find((entry) => entry.id === item.client_row_id) || urlRows.find((entry) => entry.value === sourceValue);
    if (!row) continue;
    row.submit_status =
      item.status === "succeeded"
        ? "succeeded"
        : item.status === "failed"
          ? "failed"
          : item.status === "running" || item.status === "queued"
            ? "running"
            : row.submit_status || "submitted";
    row.batch_id = batch.batch_id;
    row.item_id = item.item_id;
  }
  renderUrlRows();
  batchStatus.textContent = batch.status || "running";
  const concurrency = batch.request?.batch_concurrency || value("batchConcurrency");
  summary.textContent = `${batch.total || items.length} 条任务，并发 ${concurrency}，成功 ${batch.succeeded || 0}，失败 ${batch.failed || 0}`;
  if (!items.length) {
    taskBody.innerHTML = `<tr><td colspan="6" class="empty">暂无任务</td></tr>`;
    return;
  }
  taskBody.innerHTML = items
    .map((item) => {
      const progress = Math.max(0, Math.min(100, item.progress || 0));
      const runId = item.workflow_run_id || item.dify_run_id || "-";
      const detail = stageProgressDetail(item);
      const stageJob = item.active_stage_job_id || item.stage_jobs?.[item.stage] || "";
      const localProgress = Number.isFinite(Number(item.local_progress)) ? Number(item.local_progress) : null;
      const sourceValue = item.source_value || item.youtube_url || "";
      const sourceLabel = item.source_kind === "local" ? "本地" : "URL";
      return `<tr>
        <td>${item.index}</td>
        <td class="url-cell"><span class="small">${sourceLabel}</span><br />${escapeHtml(sourceValue)}</td>
        <td>${stageChips(item)}</td>
        <td>
          <div class="progress"><div class="bar" style="width:${progress}%"></div></div>
          <div class="progress-meta">
            <span class="small">${progress}% · ${escapeHtml(item.status)}</span>
            <span class="progress-detail">${escapeHtml(detail)}</span>
            ${
              localProgress !== null && stageJob
                ? `<span class="small">本阶段 ${localProgress}% · ${escapeHtml(stageJob)}</span>`
                : ""
            }
            ${logTailHtml(item)}
          </div>
        </td>
        <td class="run-cell">${escapeHtml(runId)}</td>
        <td>${resultLink(item)}</td>
      </tr>`;
    })
    .join("");
}

function openEvents(batchId) {
  if (events) events.close();
  events = new EventSource(`/ui/batches/${batchId}/events`);
  events.onmessage = (event) => renderBatch(JSON.parse(event.data));
  events.onerror = () => {
    batchStatus.textContent = "连接中断";
  };
}

urlList.addEventListener("input", (event) => {
  if (!event.target.classList.contains("url-input") && !event.target.classList.contains("source-kind")) return;
  const rowNode = event.target.closest(".url-row");
  const existing = urlRows.find((item) => item.id === rowNode?.dataset.id);
  const oldKind = existing?.kind;
  const oldValue = existing?.value;
  syncRowsFromDom();
  const current = urlRows.find((item) => item.id === rowNode?.dataset.id);
  const changed = current && (oldKind !== current.kind || oldValue !== current.value);
  if (changed) {
    current.submit_status = "draft";
    current.batch_id = "";
    current.item_id = "";
  }
  const row = rowNode;
  const state = row?.querySelector(".row-state");
  const kind = row?.querySelector(".source-kind")?.value || "youtube";
  const value = row?.querySelector(".url-input")?.value.trim() || "";
  const valid = kind === "local" ? isLocalSourceValue(value) : !value || isYoutubeUrl(value);
  if (state) {
    state.textContent = kind === "local" ? (valid ? "本地就绪" : value ? "路径无效" : "路径待填") : valid ? "就绪" : "URL 无效";
    state.classList.toggle("invalid", !valid);
  }
});

urlList.addEventListener("click", (event) => {
  const row = event.target.closest(".url-row");
  const action = event.target.dataset.action;
  if (!row) return;
  saveCurrentEditContext();
  syncRowsFromDom();
  const index = urlRows.findIndex((item) => item.id === row.dataset.id);
  if (!action || action === "select") {
    if (!action && (event.target.classList.contains("url-input") || event.target.classList.contains("source-kind"))) {
      saveCurrentEditContext();
      selectedUrlId = row.dataset.id;
      editScope = "item";
      applySettingsToDom(effectiveSettingsForRow(selectedRow()));
      [...urlList.querySelectorAll(".url-row")].forEach((node) => node.classList.toggle("selected", node.dataset.id === selectedUrlId));
      updateEditContext();
      return;
    }
    setEditScope("item", row.dataset.id);
    return;
  }
  if (action === "select") selectedUrlId = row.dataset.id;
  if (action === "remove" && urlRows.length > 1) {
    delete perItemCovers[row.dataset.id];
    urlRows.splice(index, 1);
  }
  if (action === "up" && index > 0) [urlRows[index - 1], urlRows[index]] = [urlRows[index], urlRows[index - 1]];
  if (action === "down" && index < urlRows.length - 1) [urlRows[index + 1], urlRows[index]] = [urlRows[index], urlRows[index + 1]];
  if (action === "cover") {
    selectedUrlId = row.dataset.id;
    openCoverModal("per_item", row.dataset.id);
    return;
  }
  renderUrlRows();
});

el("addUrl").addEventListener("click", () => {
  syncRowsFromDom();
  const row = newRow("youtube", "");
  urlRows.push(row);
  selectedUrlId = row.id;
  setEditScope("item", row.id);
});

el("addLocal")?.addEventListener("click", () => {
  syncRowsFromDom();
  const row = newRow("local", "");
  urlRows.push(row);
  selectedUrlId = row.id;
  setEditScope("item", row.id);
});

el("pasteImport").addEventListener("click", async () => {
  syncRowsFromDom();
  let text = "";
  try {
    text = await navigator.clipboard.readText();
  } catch {
    text = prompt("粘贴多个 URL，可用换行、空格、逗号或分号分隔") || "";
  }
  const urls = splitUrls(text);
  if (!urls.length) return;
  for (const url of urls) {
    const kind = isYoutubeUrl(url) ? "youtube" : "local";
    urlRows.push(newRow(kind, url));
  }
  selectedUrlId = urlRows[urlRows.length - urls.length]?.id || selectedUrlId;
  setEditScope("item", selectedUrlId);
});

el("resetStyle").addEventListener("click", () => {
  el("fontFamily").value = "Microsoft YaHei";
  el("fontSize").value = "44";
  el("fontSizeMode").value = "manual";
  el("fontWeight").value = "700";
  el("primaryColor").value = "#ffffff";
  el("outlineColor").value = "#000000";
  el("outlineWidth").value = "3";
  el("shadow").value = "1";
  el("subtitlePosition").value = "bottom";
  el("yOffset").value = "8";
  el("maxWidth").value = "86";
  el("lineSpacing").value = "1.15";
  el("bilingualOrder").value = "en_top_zh_bottom";
  el("backgroundEnabled").checked = false;
  el("backgroundColor").value = "#000000";
  el("backgroundOpacity").value = "45";
  el("backgroundPadding").value = "12";
  saveCurrentEditContext();
  renderUrlRows();
  updatePreview();
});

el("fetchPreview").addEventListener("click", async () => {
  syncRowsFromDom();
  const row = urlRows.find((item) => item.id === selectedUrlId) || urlRows[0];
  if (!row?.value) {
    previewHint.textContent = "先填写来源";
    return;
  }
  if (row.kind === "youtube" && !isYoutubeUrl(row.value)) {
    previewHint.textContent = "先选择有效 URL";
    return;
  }
  if (row.kind === "local" && !isLocalSourceValue(row.value)) {
    previewHint.textContent = "本地路径看起来不正确";
    return;
  }
  previewHint.textContent = "抓取中";
  previewStage.style.backgroundImage = "";
  previewStage.classList.remove("rendered-preview");
  try {
    const response = await fetch("/ui/preview-frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_kind: row.kind || "youtube",
        source_value: row.value,
        youtube_url: row.kind === "youtube" ? row.value : "",
        aspect_ratio: value("aspectRatio"),
        resolution: value("resolution"),
        fps: value("fps"),
        preview_time_percent: Number(value("previewTimePercent")),
        subtitle_output_mode: value("subtitleOutputMode"),
        subtitle_style: currentStyle(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "preview failed");
    previewCanvas = {
      width: Number(data.render_width || 1080),
      height: Number(data.render_height || 1920),
    };
    const previewUrl = `${data.preview_image_url}${data.preview_image_url.includes("?") ? "&" : "?"}v=${Date.now()}`;
    previewStage.style.backgroundImage = `linear-gradient(rgba(0,0,0,.12), rgba(0,0,0,.28)), url("${previewUrl}")`;
    previewStage.classList.toggle("rendered-preview", Boolean(data.rendered_subtitle));
    const sourceLabel = data.preview_source === "thumbnail_fallback" ? "缩略图回退" : "真实帧";
    const windowLabel = data.preview_window_seconds ? Math.round(data.preview_window_seconds) : 300;
    const timeLabel = ` · ${Math.round(data.preview_time_seconds || 0)}s/${windowLabel}s`;
    previewHint.textContent = `${data.title || sourceLabel} · ${sourceLabel}${timeLabel} · ${previewCanvas.width}x${previewCanvas.height}`;
    updatePreview();
  } catch (error) {
    previewHint.textContent = error.message;
  }
});

new ResizeObserver(updatePreview).observe(previewStage);

contextProfileSelect?.addEventListener("change", () => {
  const profile = selectedTranslationProfile();
  applyTranslationProfile(profile);
  saveCurrentEditContext();
  setContextStatus(profile ? `已载入预设：${profile.name}` : "预设会完整保存；提交翻译时会按模型提示长度自动裁剪。");
});

el("saveContextProfile").addEventListener("click", saveTranslationContextProfile);
el("updateContextProfile").addEventListener("click", updateTranslationContextProfile);
el("deleteContextProfile").addEventListener("click", deleteTranslationContextProfile);
el("clearContextProfile").addEventListener("click", () => {
  applyTranslationProfile(null);
  setContextStatus("已清空本次上下文");
});

el("refreshBiliCollections")?.addEventListener("click", loadBiliCollections);
el("openBatchCover")?.addEventListener("click", () => openCoverModal("batch"));
el("openCurrentCover")?.addEventListener("click", () => openCoverModal("per_item", selectedUrlId));
el("editBatchDefaults")?.addEventListener("click", () => setEditScope("batch"));
el("editCurrentRow")?.addEventListener("click", () => setEditScope("item", selectedUrlId));
el("clearCurrentOverride")?.addEventListener("click", () => {
  const row = selectedRow();
  if (!row) return;
  row.overrides = {};
  editScope = "item";
  selectedUrlId = row.id;
  applySettingsToDom(batchDefaults || captureSettingsFromDom());
  updateEditContext();
  renderUrlRows();
});
el("closeCoverModal")?.addEventListener("click", closeCoverModal);
el("useCoverFrame")?.addEventListener("click", useCurrentFrameAsCover);
el("useYoutubeThumbnail")?.addEventListener("click", useYoutubeThumbnailAsCover);
el("biliCoverFile")?.addEventListener("change", (event) => uploadCoverImage(event.target.files?.[0]));
el("clearCoverChoice")?.addEventListener("click", clearCoverChoice);
el("biliCoverTimePercent")?.addEventListener("input", () => {
  el("biliCoverTimeLabel").textContent = `${value("biliCoverTimePercent")}%`;
});

document.querySelectorAll("input, select, textarea").forEach((control) => {
  const refresh = () => {
    if (!control.closest(".url-list")) saveCurrentEditContext();
    previewStage.classList.remove("rendered-preview");
    if (control.id === "whisperModel") renderWhisperModelStatus();
    if (
      control.closest(".url-list") ||
      control.id === "outputNameMode" ||
      control.id === "outputNamePrefix" ||
      settingsFieldIds.includes(control.id)
    ) {
      renderUrlRows();
    }
    updateEditContext();
    updateBiliCoverSummary();
    updatePreview();
  };
  control.addEventListener("input", refresh);
  control.addEventListener("change", refresh);
});

async function submitBatch(options = {}) {
  const button = submitBatchButton || form.querySelector(".primary");
  const mode = options.mode || "draft";
  const payload = payloadFromForm({ mode });
  const invalid = payload.sources.find((item) =>
    item.source_kind === "youtube" ? !isYoutubeUrl(item.source_value) : !isLocalSourceValue(item.source_value),
  );
  if (!payload.sources.length) {
    batchStatus.textContent =
      mode === "failed" ? "没有失败项可重试" : mode === "selected" ? "当前视频缺少来源" : "没有新增/未提交视频";
    return;
  }
  if (invalid) {
    batchStatus.textContent = invalid.source_kind === "local" ? "本地路径无效" : "URL 无效";
    return;
  }
  if (!payload.rights_confirmed) {
    batchStatus.textContent = "需确认授权";
    return;
  }
  button.disabled = true;
  batchStatus.textContent = mode === "failed" ? "重试失败项提交中" : mode === "selected" ? "当前视频提交中" : "新增/未提交视频提交中";
  try {
    const response = await fetch("/ui/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "submit failed");
    const submittedIds = new Set(payload.sources.map((source) => source.client_row_id).filter(Boolean));
    for (const row of urlRows) {
      if (submittedIds.has(row.id)) row.submit_status = "running";
    }
    renderBatch(data);
    openEvents(data.batch_id);
  } catch (error) {
    batchStatus.textContent = "提交失败";
    taskBody.innerHTML = `<tr><td colspan="6" class="empty">${escapeHtml(error.message)}</td></tr>`;
  } finally {
    button.disabled = false;
  }
}

submitBatchButton?.addEventListener("click", () => submitBatch({ mode: "draft" }));
el("retryFailed")?.addEventListener("click", () => submitBatch({ mode: "failed" }));
el("submitSelected")?.addEventListener("click", () => submitBatch({ mode: "selected" }));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitBatch({ mode: "draft" });
});

batchDefaults = captureSettingsFromDom();
updateEditContext();
renderUrlRows();
updatePreview();
loadWhisperModels();
loadTranslationContexts();
loadBiliStatus();
loadBiliZones();
updateBiliCoverSummary();
