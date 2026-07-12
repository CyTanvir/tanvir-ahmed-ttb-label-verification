const BATCH_VERIFY_ENDPOINT = "/verify/batch";
const BATCH_VERIFY_TIMEOUT_MS = 15000;
const MAX_BATCH_FILES = 10;
const MAX_IMAGE_BYTES = 12 * 1000 * 1000;

const NUMERIC_FIELD_VALIDATIONS = [
  { elementId: "abv", label: "ABV", example: "13.5% ALC/VOL" },
  { elementId: "net-contents", label: "Net contents", example: "750 mL" },
];

const FIELD_DEFINITIONS = [
  { key: "brand_name", label: "Brand name", elementId: "brand-name" },
  { key: "class_type", label: "Class/type", elementId: "class-type" },
  { key: "abv", label: "ABV", elementId: "abv" },
  { key: "net_contents", label: "Net contents", elementId: "net-contents" },
  { key: "producer", label: "Producer", elementId: "producer" },
  {
    key: "country_of_origin",
    label: "Country of origin",
    elementId: "country-of-origin",
  },
  {
    key: "government_warning",
    label: "Government warning",
    elementId: "government-warning",
  },
];

const form = document.querySelector("#verify-form");
const labelImage = document.querySelector("#label-image");
const fileName = document.querySelector("#file-name");
const fileError = document.querySelector("#file-error");
const previewWrap = document.querySelector("#preview-wrap");
const imagePreview = document.querySelector("#image-preview");
const verifyButton = document.querySelector("#verify-button");
const clearButton = document.querySelector("#clear-button");
const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
const errorPanel = document.querySelector("#error-panel");
const errorSummary = document.querySelector("#error-summary");
const errorDetail = document.querySelector("#error-detail");
const progressPanel = document.querySelector("#progress-panel");
const progressTitle = document.querySelector("#progress-title");
const progressCount = document.querySelector("#progress-count");
const progressMeter = document.querySelector("#progress-meter");
const progressFill = document.querySelector("#progress-fill");
const resultsArea = document.querySelector("#results-area");
const summaryPanel = document.querySelector("#summary-panel");
const batchLatency = document.querySelector("#batch-latency");
const summaryTotal = document.querySelector("#summary-total");
const summaryApproved = document.querySelector("#summary-approved");
const summaryReview = document.querySelector("#summary-review");
const summaryErrors = document.querySelector("#summary-errors");
const resultsList = document.querySelector("#results-list");
const placeholderPanel = document.querySelector("#placeholder-panel");

let previewUrl = "";
let progressTimer = 0;
let progressValue = 0;

function setStatus(kind, text) {
  statusDot.className = `status-dot ${kind}`;
  statusText.textContent = text;
}

function collectApplicationData() {
  return FIELD_DEFINITIONS.reduce((data, field) => {
    const value = document.querySelector(`#${field.elementId}`).value.trim();
    data[field.key] = value || null;
    return data;
  }, {});
}

function selectedFiles() {
  return Array.from(labelImage.files || []);
}

function validateFiles(files) {
  if (files.length === 0) {
    return "Choose at least one label image before verifying.";
  }

  if (files.length > MAX_BATCH_FILES) {
    return `Choose ${MAX_BATCH_FILES} or fewer label images.`;
  }

  for (const file of files) {
    if (file.size === 0) {
      return `${file.name || "One selected file"} is empty.`;
    }

    if (file.size > MAX_IMAGE_BYTES) {
      return `${file.name || "One selected file"} is larger than 12 MB.`;
    }

    if (file.type && !file.type.startsWith("image/")) {
      return `${file.name || "One selected file"} is not a supported image type.`;
    }
  }

  return "";
}

function validateNumericFields() {
  for (const { elementId, label, example } of NUMERIC_FIELD_VALIDATIONS) {
    const field = document.querySelector(`#${elementId}`);
    const value = field.value.trim();
    if (value && !/\d/.test(value)) {
      return {
        message: `${label} should include a number, e.g. "${example}".`,
        field,
      };
    }
  }
  return null;
}

function buildBatchVerifyPayload(files) {
  const payload = new FormData();
  payload.append("application_data", JSON.stringify(collectApplicationData()));
  for (const file of files) {
    payload.append("label_images", file, file.name);
  }
  return payload;
}

function clearError() {
  errorPanel.classList.remove("visible");
  errorSummary.textContent = "The label could not be verified.";
  errorDetail.textContent = "";
}

function setFileError(message = "") {
  labelImage.setAttribute("aria-invalid", message ? "true" : "false");
  fileError.textContent = message;
  fileError.classList.toggle("visible", Boolean(message));
}

function setResultsBusy(isBusy) {
  resultsArea.setAttribute("aria-busy", isBusy ? "true" : "false");
}

function focusWithoutJump(element) {
  window.requestAnimationFrame(() => {
    element.focus({ preventScroll: false });
  });
}

function clearResults() {
  clearError();
  setFileError();
  hideProgress();
  setResultsBusy(false);
  summaryPanel.classList.remove("visible");
  batchLatency.textContent = "";
  summaryTotal.textContent = "0";
  summaryApproved.textContent = "0";
  summaryReview.textContent = "0";
  summaryErrors.textContent = "0";
  resultsList.replaceChildren();
  placeholderPanel.classList.remove("hidden");
  setStatus("ready", "Ready");
}

function showError(message, detail = "", options = {}) {
  clearResults();
  if (options.fileError) {
    setFileError(options.fileError);
  }
  errorSummary.textContent = message;
  errorDetail.textContent = detail || message;
  errorPanel.classList.add("visible");
  placeholderPanel.classList.add("hidden");
  setStatus("error", "Error");
  focusWithoutJump(options.focusTarget || errorPanel);
}

function showProgress(total) {
  hideProgress();
  setResultsBusy(true);
  progressTitle.textContent = `Verifying ${total} ${total === 1 ? "label" : "labels"}`;
  progressPanel.classList.add("visible");
  placeholderPanel.classList.add("hidden");
  progressValue = 8;
  setProgress(progressValue);
  progressTimer = window.setInterval(() => {
    progressValue = Math.min(92, progressValue + Math.max(1, (92 - progressValue) * 0.08));
    setProgress(progressValue);
  }, 250);
}

function hideProgress() {
  if (progressTimer) {
    window.clearInterval(progressTimer);
    progressTimer = 0;
  }
  progressPanel.classList.remove("visible");
  setProgress(0);
}

function completeProgress() {
  if (progressTimer) {
    window.clearInterval(progressTimer);
    progressTimer = 0;
  }
  setProgress(100);
}

function setProgress(value) {
  const rounded = Math.round(Math.max(0, Math.min(100, value)));
  progressFill.style.width = `${rounded}%`;
  progressCount.textContent = `${rounded}%`;
  progressMeter.setAttribute("aria-valuenow", String(rounded));
}

function renderBatchResults(batch) {
  clearError();
  hideProgress();
  resultsList.replaceChildren();
  placeholderPanel.classList.add("hidden");

  const summary = batch.summary || {};
  const items = batch.items || [];
  const total = Number(summary.total || 0);
  const passed = Number(summary.passed || 0);
  const needsReview = Number(summary.needs_review || 0);
  const errors = items.filter((item) => item.status === "ERROR").length;

  summaryTotal.textContent = String(total);
  summaryApproved.textContent = String(passed);
  summaryReview.textContent = String(needsReview);
  summaryErrors.textContent = String(errors);
  batchLatency.textContent =
    typeof batch.latency_ms === "number"
      ? `${Math.round(batch.latency_ms)} ms total`
      : "";
  summaryPanel.classList.add("visible");

  const hasProblems = needsReview > 0;
  setStatus(hasProblems ? "error" : "ok", hasProblems ? "Needs Review" : "All Approved");
  focusWithoutJump(summaryPanel);

  for (const [index, label] of items.entries()) {
    resultsList.appendChild(createBatchLabelCard(label, index));
  }
}

function createBatchLabelCard(label, position) {
  const status = label.status || "ERROR";
  const normalizedStatus = String(status).toLowerCase();
  const details = document.createElement("details");
  details.className = `batch-label ${normalizedStatus}`;
  details.open = position === 0 || status !== "APPROVED";

  const summary = document.createElement("summary");
  summary.className = "batch-summary-row";

  const topline = document.createElement("div");
  topline.className = "batch-topline";

  const name = document.createElement("h3");
  name.className = "batch-name";
  const labelNumber =
    typeof label.index === "number" ? label.index + 1 : position + 1;
  name.textContent = label.filename || `Label ${labelNumber}`;

  const meta = document.createElement("div");
  meta.className = "batch-meta";

  const verdict =
    label.result && label.result.overall_verdict ? label.result.overall_verdict : status;

  const statusBadge = document.createElement("span");
  statusBadge.className = `result-status ${status === "APPROVED" ? "pass" : "fail"}`;
  statusBadge.textContent = humanize(verdict);

  const latency = document.createElement("span");
  latency.className = "batch-latency";
  latency.textContent =
    typeof label.latency_ms === "number"
      ? `${Math.round(label.latency_ms)} ms`
      : "";

  meta.append(statusBadge, latency);
  topline.append(name, meta);
  summary.append(topline);

  const body = document.createElement("div");
  body.className = "batch-body";

  if (status === "ERROR") {
    const error = document.createElement("p");
    error.className = "batch-error";
    error.textContent = label.error || "The label could not be verified.";
    body.append(error);
  } else if (label.result) {
    for (const item of label.result.results || []) {
      body.appendChild(createResultCard(item));
    }
  } else {
    const error = document.createElement("p");
    error.className = "batch-error";
    error.textContent = "No result was returned for this label.";
    body.append(error);
  }

  details.append(summary, body);
  return details;
}

function createResultCard(item) {
  const field = FIELD_DEFINITIONS.find((definition) => definition.key === item.field);
  const passed = item.status === "PASS";
  const card = document.createElement("article");
  card.className = `field-result ${passed ? "pass" : "fail"}`;

  const topline = document.createElement("div");
  topline.className = "result-topline";

  const title = document.createElement("h3");
  title.className = "result-field";
  title.textContent = field ? field.label : humanize(item.field);

  const status = document.createElement("span");
  status.className = `result-status ${passed ? "pass" : "fail"}`;
  status.textContent = passed ? "PASS" : "FAIL";

  topline.append(title, status);

  const values = document.createElement("div");
  values.className = "result-values";
  values.append(
    createValueBox("Expected", displayValue(item.expected)),
    createValueBox("Found", displayValue(item.found)),
  );

  const matchType = document.createElement("p");
  matchType.className = "match-type";
  matchType.textContent = `Match: ${humanize(item.match_type)}`;

  card.append(topline, values, matchType);
  return card;
}

function createValueBox(label, value) {
  const box = document.createElement("div");
  box.className = "value-box";

  const valueLabel = document.createElement("p");
  valueLabel.className = "value-label";
  valueLabel.textContent = label;

  const valueText = document.createElement("p");
  valueText.className = "value-text";
  valueText.textContent = value;

  box.append(valueLabel, valueText);
  return box;
}

function displayValue(value) {
  if (value === null || value === undefined || value === "") {
    return "Not provided";
  }
  return String(value);
}

function humanize(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

async function getErrorText(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const data = await response.json();
    return formatDetail(data.detail ?? data);
  }

  const text = await response.text();
  return text || `${response.status} ${response.statusText}`;
}

function formatDetail(detail) {
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail.map(formatDetailItem).join("\n");
  }

  if (detail && typeof detail === "object") {
    const lines = [];
    if (typeof detail.message === "string") {
      lines.push(detail.message);
    }
    if (Array.isArray(detail.errors)) {
      lines.push(...detail.errors.map(formatDetailItem));
    }
    if (lines.length > 0) {
      return lines.join("\n");
    }
    return JSON.stringify(detail, null, 2);
  }

  return "The server returned an error.";
}

function formatDetailItem(item) {
  if (typeof item === "string") {
    return item;
  }
  if (!item || typeof item !== "object") {
    return String(item);
  }

  const location = Array.isArray(item.loc) ? item.loc.join(" > ") : item.loc;
  const message = item.msg || item.message || JSON.stringify(item);
  return location ? `${humanize(location)}: ${message}` : message;
}

async function submitVerification(event) {
  event.preventDefault();
  clearResults();

  const files = selectedFiles();
  const validationError = validateFiles(files);
  if (validationError) {
    showError(validationError, validationError, {
      fileError: validationError,
      focusTarget: labelImage,
    });
    return;
  }

  const numericFieldError = validateNumericFields();
  if (numericFieldError) {
    showError(numericFieldError.message, numericFieldError.message, {
      focusTarget: numericFieldError.field,
    });
    return;
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), BATCH_VERIFY_TIMEOUT_MS);
  verifyButton.disabled = true;
  verifyButton.textContent = "Verifying...";
  setStatus("ready", `Verifying ${files.length}`);
  showProgress(files.length);

  try {
    const response = await fetch(BATCH_VERIFY_ENDPOINT, {
      method: "POST",
      body: buildBatchVerifyPayload(files),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(await getErrorText(response));
    }

    const batch = await response.json();
    completeProgress();
    renderBatchResults(batch);
  } catch (error) {
    const message =
      error.name === "AbortError"
        ? "Batch verification took longer than expected."
        : "The labels could not be verified.";
    const detail =
      error.name === "AbortError"
        ? "The request was stopped at the 15 second limit."
        : error.message;
    showError(message, detail);
  } finally {
    window.clearTimeout(timeoutId);
    hideProgress();
    setResultsBusy(false);
    verifyButton.disabled = false;
    verifyButton.textContent = "Verify Labels";
  }
}

function updateSelectedFile() {
  setFileError();
  const files = selectedFiles();
  const file = files[0];
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = "";
  }

  if (!file) {
    fileName.textContent = "No images selected";
    previewWrap.classList.remove("visible");
    imagePreview.removeAttribute("src");
    return;
  }

  if (files.length === 1) {
    fileName.textContent = file.name;
  } else {
    const visibleNames = files
      .slice(0, 3)
      .map((selectedFile) => selectedFile.name)
      .join(", ");
    const more = files.length > 3 ? ` + ${files.length - 3} more` : "";
    fileName.textContent = `${files.length} images selected: ${visibleNames}${more}`;
  }

  if (file.type.startsWith("image/")) {
    previewUrl = URL.createObjectURL(file);
    imagePreview.src = previewUrl;
    previewWrap.classList.add("visible");
  } else {
    previewWrap.classList.remove("visible");
    imagePreview.removeAttribute("src");
  }
}

form.addEventListener("submit", submitVerification);
labelImage.addEventListener("change", updateSelectedFile);
labelImage.addEventListener("invalid", () => {
  setFileError("Choose at least one label image before verifying.");
});
clearButton.addEventListener("click", clearResults);
window.addEventListener("beforeunload", () => {
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
  }
});
