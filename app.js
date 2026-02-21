// PDF Studio frontend controller.
// This file coordinates:
// 1) workspace source/result state
// 2) modal-based tool execution
// 3) interactive visual text editing

const state = {
  sourceBlob: null,
  sourceName: "",
  sourceType: "",
  resultBlob: null,
  resultName: "",
  resultType: "",
  urls: {
    source: null,
    result: null,
    modalBefore: null,
    modalAfter: null,
  },
  modal: {
    activeTool: "",
    editor: null,
  },
};

const endpointFallbackNames = {
  "/api/rotate": "rotated.pdf",
  "/api/reorder": "reordered.pdf",
  "/api/reverse": "reversed.pdf",
  "/api/duplicate-pages": "duplicated-pages.pdf",
  "/api/delete-pages": "deleted-pages.pdf",
  "/api/extract-pages": "extracted-pages.pdf",
  "/api/split": "split.zip",
  "/api/merge": "merged.pdf",
  "/api/add-text": "text-added.pdf",
  "/api/replace-text": "text-replaced.pdf",
  "/api/watermark": "watermarked.pdf",
  "/api/page-numbers": "page-numbered.pdf",
  "/api/crop": "cropped.pdf",
  "/api/pdf-to-images": "pdf-images.zip",
  "/api/images-to-pdf": "images-to-pdf.pdf",
  "/api/encrypt": "encrypted.pdf",
  "/api/decrypt": "decrypted.pdf",
  "/api/metadata": "metadata-updated.pdf",
  "/api/optimize": "optimized.pdf",
  "/api/text-editor/apply": "text-edited.pdf",
  "/api/text-editor/add": "text-added-interactive.pdf",
};

const statusEl = document.getElementById("status");
const workspaceFile = document.getElementById("workspaceFile");
const clearSourceBtn = document.getElementById("clearSourceBtn");
const sourcePreview = document.getElementById("sourcePreview");
const resultPreview = document.getElementById("resultPreview");
const sourceMeta = document.getElementById("sourceMeta");
const resultMeta = document.getElementById("resultMeta");
const useResultBtn = document.getElementById("useResultBtn");
const downloadResultBtn = document.getElementById("downloadResultBtn");

const toolModal = document.getElementById("toolModal");
const modalPanel = document.getElementById("modalPanel");
const modalTitle = document.getElementById("modalTitle");
const modalCloseBtn = document.getElementById("modalCloseBtn");
const modalFormHost = document.getElementById("modalFormHost");
const modalBeforePreview = document.getElementById("modalBeforePreview");
const modalAfterPreview = document.getElementById("modalAfterPreview");
const modalBeforeMeta = document.getElementById("modalBeforeMeta");
const modalAfterMeta = document.getElementById("modalAfterMeta");
const modalDownloadBtn = document.getElementById("modalDownloadBtn");
const modalUseResultBtn = document.getElementById("modalUseResultBtn");

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

// URL object lifecycle helpers avoid memory leaks from repeated previews.
function revokeUrl(key) {
  const current = state.urls[key];
  if (current) {
    URL.revokeObjectURL(current);
    state.urls[key] = null;
  }
}

function setIframeSource(iframe, url) {
  iframe.src = url || "about:blank";
}

function isPdfOutput(contentType, filename) {
  const type = (contentType || "").toLowerCase();
  const name = (filename || "").toLowerCase();
  return type.includes("application/pdf") || name.endsWith(".pdf");
}

function filenameFromDisposition(disposition, fallback) {
  if (!disposition) return fallback;
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8 && utf8[1]) return decodeURIComponent(utf8[1]);
  const ascii = disposition.match(/filename="?([^";]+)"?/i);
  if (ascii && ascii[1]) return ascii[1];
  return fallback;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1200);
}

async function parseErrorMessage(response) {
  try {
    const data = await response.json();
    if (data?.error) return data.error;
  } catch {
    // ignore
  }
  return `Request failed with HTTP ${response.status}.`;
}

async function fetchJsonOrThrow(response) {
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response));
  }
  return response.json();
}

function sourceBlobAsFile() {
  if (!state.sourceBlob) return null;
  return new File([state.sourceBlob], state.sourceName || "source.pdf", {
    type: state.sourceType || "application/pdf",
  });
}

function clearSource() {
  state.sourceBlob = null;
  state.sourceName = "";
  state.sourceType = "";
  revokeUrl("source");
  setIframeSource(sourcePreview, "");
  sourceMeta.textContent = "No source loaded.";
  workspaceFile.value = "";
  refreshModalBeforePreview();

  if (state.modal.activeTool === "visual-text-editor" && state.modal.editor) {
    resetVisualEditorState(state.modal.editor, true);
  }
}

function setSourceFromBlob(blob, filename, contentType) {
  state.sourceBlob = blob;
  state.sourceName = filename || "source.pdf";
  state.sourceType = contentType || "application/pdf";

  revokeUrl("source");
  state.urls.source = URL.createObjectURL(blob);

  if (isPdfOutput(state.sourceType, state.sourceName)) {
    setIframeSource(sourcePreview, state.urls.source);
    sourceMeta.textContent = `${state.sourceName}`;
  } else {
    setIframeSource(sourcePreview, "");
    sourceMeta.textContent = `${state.sourceName} loaded (preview unavailable).`;
  }

  refreshModalBeforePreview();
}

function setResultFromBlob(blob, filename, contentType, extraNote = "") {
  state.resultBlob = blob;
  state.resultName = filename || "output.bin";
  state.resultType = contentType || "application/octet-stream";

  revokeUrl("result");
  state.urls.result = URL.createObjectURL(blob);

  const isPdf = isPdfOutput(state.resultType, state.resultName);
  if (isPdf) {
    setIframeSource(resultPreview, state.urls.result);
    resultMeta.textContent = `${state.resultName}${extraNote ? ` | ${extraNote}` : ""}`;
  } else {
    setIframeSource(resultPreview, "");
    resultMeta.textContent = `${state.resultName} generated. Preview unavailable for this file type.${extraNote ? ` ${extraNote}` : ""}`;
  }

  useResultBtn.disabled = false;
  downloadResultBtn.disabled = false;

  applyModalAfterPreview(blob, filename, contentType, extraNote);
}

function setModalDownloadState(enabled) {
  modalDownloadBtn.disabled = !enabled;
  modalUseResultBtn.disabled = !enabled;
}

function refreshModalBeforePreview() {
  if (state.modal.activeTool === "visual-text-editor") {
    return;
  }

  revokeUrl("modalBefore");
  setIframeSource(modalBeforePreview, "");

  const form = modalFormHost.querySelector("form");
  if (!form) {
    modalBeforeMeta.textContent = "Load a source file in workspace or this form.";
    return;
  }

  const singleFileInput = form.querySelector('input[type="file"][name="file"]');
  const multiFileInput = form.querySelector('input[type="file"][name="files"]');

  if (singleFileInput?.files?.length) {
    const file = singleFileInput.files[0];
    modalBeforeMeta.textContent = `Popup file: ${file.name}`;
    if (isPdfOutput(file.type, file.name)) {
      state.urls.modalBefore = URL.createObjectURL(file);
      setIframeSource(modalBeforePreview, state.urls.modalBefore);
    }
    return;
  }

  if (multiFileInput?.files?.length) {
    const file = multiFileInput.files[0];
    modalBeforeMeta.textContent = `First selected file: ${file.name}`;
    if (isPdfOutput(file.type, file.name)) {
      state.urls.modalBefore = URL.createObjectURL(file);
      setIframeSource(modalBeforePreview, state.urls.modalBefore);
    }
    return;
  }

  if (state.sourceBlob) {
    modalBeforeMeta.textContent = `Workspace source: ${state.sourceName}`;
    if (state.urls.source && isPdfOutput(state.sourceType, state.sourceName)) {
      setIframeSource(modalBeforePreview, state.urls.source);
    }
    return;
  }

  modalBeforeMeta.textContent = "No source yet. Load one in workspace or select a file in this popup.";
}

function applyModalAfterPreview(blob, filename, contentType, extraNote = "") {
  if (state.modal.activeTool === "visual-text-editor") {
    return;
  }

  revokeUrl("modalAfter");
  setIframeSource(modalAfterPreview, "");

  if (!blob) {
    modalAfterMeta.textContent = "Run this tool to preview output.";
    setModalDownloadState(false);
    return;
  }

  const isPdf = isPdfOutput(contentType, filename);
  if (isPdf) {
    state.urls.modalAfter = URL.createObjectURL(blob);
    setIframeSource(modalAfterPreview, state.urls.modalAfter);
    modalAfterMeta.textContent = `${filename}${extraNote ? ` | ${extraNote}` : ""}`;
  } else {
    modalAfterMeta.textContent = `${filename} generated. Preview unavailable for this file type.${extraNote ? ` ${extraNote}` : ""}`;
  }

  setModalDownloadState(true);
}

// -------- Visual Editor (interactive text mode) --------

function resetVisualEditorState(editor, clearBadge = false) {
  editor.analysis = null;
  editor.pageData = null;
  editor.selected = null;
  editor.currentPage = 1;
  editor.mode = "edit";
  editor.addPoint = null;
  editor.renderScale = null;
  editor.pageImage.src = "";
  editor.overlay.replaceChildren();
  editor.addMarker.classList.add("hidden");
  editor.prevPageBtn.disabled = true;
  editor.nextPageBtn.disabled = true;
  editor.newText.value = "";
  editor.newText.disabled = true;
  editor.fontSize.value = "";
  editor.fontSize.disabled = true;
  editor.addColor.disabled = true;
  editor.applyBtn.disabled = true;
  editor.selectionLabel.textContent = "No text selected.";
  editor.textLabel.textContent = "Edit selected text";
  editor.modeEdit.checked = true;
  editor.modeAdd.checked = false;
  editor.pageIndicator.textContent = "Page - / -";

  if (clearBadge) {
    editor.scanBadge.textContent = "Not analyzed";
    editor.scanBadge.classList.remove("ok", "warn");
    editor.scanMessage.textContent = "Analyze to start visual text editing.";
  }
}

function activeVisualPdfFile(editor) {
  if (editor.fileInput.files.length > 0) {
    return editor.fileInput.files[0];
  }
  const sourceFile = sourceBlobAsFile();
  if (sourceFile) return sourceFile;
  throw new Error("No PDF selected. Upload in this popup or load one in Workspace source.");
}

function updatePageIndicator(editor) {
  if (!editor.analysis || !editor.analysis.page_count) {
    editor.pageIndicator.textContent = "Page - / -";
    return;
  }
  editor.pageIndicator.textContent = `Page ${editor.currentPage} / ${editor.analysis.page_count}`;
}

function updatePageNavState(editor) {
  if (!editor.analysis || editor.analysis.is_scanned) {
    editor.prevPageBtn.disabled = true;
    editor.nextPageBtn.disabled = true;
    return;
  }
  editor.prevPageBtn.disabled = editor.currentPage <= 1;
  editor.nextPageBtn.disabled = editor.currentPage >= editor.analysis.page_count;
}

function updateApplyButton(editor) {
  if (!editor.pageData || editor.analysis?.is_scanned) {
    editor.applyBtn.disabled = true;
    return;
  }

  if (editor.mode === "add") {
    editor.applyBtn.disabled = !editor.addPoint || !editor.newText.value.trim();
  } else {
    editor.applyBtn.disabled = !editor.selected;
  }
}

function setVisualMode(editor, mode) {
  editor.mode = mode === "add" ? "add" : "edit";
  editor.modeEdit.checked = editor.mode === "edit";
  editor.modeAdd.checked = editor.mode === "add";

  editor.selected = null;
  editor.addPoint = null;
  editor.addMarker.classList.add("hidden");

  editor.overlay.querySelectorAll(".ve-text-hitbox").forEach((node) => {
    node.classList.remove("selected");
  });

  editor.newText.disabled = !editor.pageData;
  editor.fontSize.disabled = !editor.pageData;
  editor.addColor.disabled = editor.mode !== "add";

  if (editor.mode === "add") {
    editor.textLabel.textContent = "Text to add";
    editor.newText.placeholder = "Click on the PDF preview, then type text to insert.";
    if (!editor.fontSize.value) {
      editor.fontSize.value = "12";
    }
    editor.selectionLabel.textContent = "Add mode: click anywhere on the page to place new text.";
  } else {
    editor.textLabel.textContent = "Edit selected text";
    editor.newText.placeholder = "Select a highlighted text box above first.";
    editor.selectionLabel.textContent = "Click a highlighted text box to edit it.";
    if (!editor.pageData?.text_items?.length) {
      editor.selectionLabel.textContent = "No editable text found on this page.";
      editor.newText.disabled = true;
      editor.fontSize.disabled = true;
    } else {
      editor.newText.value = "";
      editor.fontSize.value = "";
      editor.newText.disabled = true;
      editor.fontSize.disabled = true;
    }
  }

  updateApplyButton(editor);
}

function selectVisualItem(editor, index) {
  if (editor.mode !== "edit") {
    return;
  }
  if (!editor.pageData?.text_items?.length) {
    return;
  }

  const item = editor.pageData.text_items[index];
  if (!item) {
    return;
  }

  editor.selected = item;
  editor.addPoint = null;
  editor.addMarker.classList.add("hidden");
  editor.newText.value = item.text || "";
  editor.newText.disabled = false;
  editor.fontSize.value = item.font_size ? String(item.font_size) : "";
  editor.fontSize.disabled = false;
  editor.selectionLabel.textContent = `Selected text: "${item.text}" (Page ${editor.pageData.page_number})`;

  editor.overlay.querySelectorAll(".ve-text-hitbox").forEach((node) => {
    const currentIndex = Number(node.dataset.itemIndex || "-1");
    node.classList.toggle("selected", currentIndex === index);
  });
  updateApplyButton(editor);
}

function setAddPoint(editor, pdfX, pdfY) {
  if (editor.mode !== "add" || !editor.pageData) {
    return;
  }

  const x = Math.max(0, Math.min(editor.pageData.page_width, pdfX));
  const y = Math.max(0, Math.min(editor.pageData.page_height, pdfY));
  editor.addPoint = { x, y };
  editor.selected = null;

  editor.overlay.querySelectorAll(".ve-text-hitbox").forEach((node) => {
    node.classList.remove("selected");
  });

  if (editor.renderScale) {
    const markerX = x * editor.renderScale.x;
    const markerY = y * editor.renderScale.y;
    editor.addMarker.style.left = `${markerX}px`;
    editor.addMarker.style.top = `${markerY}px`;
    editor.addMarker.classList.remove("hidden");
  }

  editor.selectionLabel.textContent = `Add position selected on page ${editor.currentPage}.`;
  editor.newText.disabled = false;
  editor.fontSize.disabled = false;
  if (!editor.fontSize.value) {
    editor.fontSize.value = "12";
  }
  updateApplyButton(editor);
}

function renderVisualOverlay(editor) {
  editor.overlay.replaceChildren();
  editor.addMarker.classList.add("hidden");
  editor.renderScale = null;

  if (!editor.pageData) {
    updateApplyButton(editor);
    return;
  }

  const imageWidth = editor.pageImage.clientWidth;
  const imageHeight = editor.pageImage.clientHeight;
  const scaleX = imageWidth / editor.pageData.page_width;
  const scaleY = imageHeight / editor.pageData.page_height;
  editor.renderScale = { x: scaleX, y: scaleY };

  editor.overlay.style.width = `${imageWidth}px`;
  editor.overlay.style.height = `${imageHeight}px`;

  if (!editor.pageData.text_items || editor.pageData.text_items.length === 0) {
    editor.selectionLabel.textContent =
      editor.mode === "add"
        ? "Add mode: click anywhere on the page to place new text."
        : "No editable text found on this page.";
    if (editor.mode === "edit") {
      editor.newText.disabled = true;
      editor.fontSize.disabled = true;
    }
    updateApplyButton(editor);
    return;
  }

  editor.pageData.text_items.forEach((item, index) => {
    const [x0, y0, x1, y1] = item.bbox;
    const left = x0 * scaleX;
    const top = y0 * scaleY;
    const width = Math.max(3, (x1 - x0) * scaleX);
    const height = Math.max(3, (y1 - y0) * scaleY);

    const hitbox = document.createElement("button");
    hitbox.type = "button";
    hitbox.className = "ve-text-hitbox";
    hitbox.style.left = `${left}px`;
    hitbox.style.top = `${top}px`;
    hitbox.style.width = `${width}px`;
    hitbox.style.height = `${height}px`;
    hitbox.dataset.itemIndex = String(index);
    hitbox.title = item.text;
    hitbox.setAttribute("aria-label", `Edit text: ${item.text}`);
    hitbox.addEventListener("click", (event) => {
      event.stopPropagation();
      selectVisualItem(editor, index);
    });
    editor.overlay.appendChild(hitbox);
  });

  if (editor.mode === "edit") {
    editor.selectionLabel.textContent = "Click a highlighted text box to edit it.";
  }
  updateApplyButton(editor);
}

async function loadVisualEditorPage(editor, preferredPage = null) {
  if (!editor.analysis || editor.analysis.is_scanned) {
    return;
  }

  const page = preferredPage || editor.currentPage || 1;
  if (!Number.isFinite(page) || page < 1 || page > editor.analysis.page_count) {
    throw new Error("Invalid page number.");
  }

  const form = new FormData();
  form.set("file", activeVisualPdfFile(editor));
  form.set("page", String(page));
  form.set("zoom", "1.45");

  const response = await fetch("/api/text-editor/page", {
    method: "POST",
    body: form,
  });
  const data = await fetchJsonOrThrow(response);

  editor.pageData = data;
  editor.currentPage = page;
  editor.selected = null;
  editor.addPoint = null;
  editor.newText.value = "";
  editor.fontSize.value = "";

  editor.pageImage.src = data.image_data_url;
  await new Promise((resolve) => {
    if (editor.pageImage.complete) {
      resolve();
      return;
    }
    editor.pageImage.onload = () => resolve();
  });

  updatePageIndicator(editor);
  updatePageNavState(editor);
  renderVisualOverlay(editor);
  setVisualMode(editor, editor.mode);
}

async function analyzeVisualEditor(editor, preferredPage = null) {
  const form = new FormData();
  form.set("file", activeVisualPdfFile(editor));

  const response = await fetch("/api/text-editor/analyze", {
    method: "POST",
    body: form,
  });
  const analysis = await fetchJsonOrThrow(response);
  editor.analysis = analysis;

  editor.scanBadge.classList.remove("ok", "warn");
  if (analysis.is_scanned) {
    editor.scanBadge.classList.add("warn");
    editor.scanBadge.textContent = "Scanned PDF";
    editor.scanMessage.textContent = analysis.message;
    resetVisualEditorState(editor, false);
    editor.analysis = analysis;
    updatePageIndicator(editor);
    setStatus("Visual Text Editor: scanned PDF detected. Direct text editing disabled.", true);
    return;
  }

  editor.scanBadge.classList.add("ok");
  editor.scanBadge.textContent = "Digital PDF";
  editor.scanMessage.textContent = analysis.message;

  editor.currentPage =
    preferredPage && preferredPage >= 1 && preferredPage <= analysis.page_count ? preferredPage : 1;
  updatePageIndicator(editor);
  updatePageNavState(editor);

  await loadVisualEditorPage(editor, editor.currentPage);
  setStatus("Visual Text Editor: PDF analyzed. Use page arrows and click text directly.");
}

async function applyVisualEditorEdit(editor) {
  if (editor.analysis?.is_scanned) {
    throw new Error("Scanned PDF detected. Direct text editing is disabled.");
  }
  if (!editor.pageData) {
    throw new Error("Load a page first.");
  }
  if (editor.mode === "edit" && !editor.selected) {
    throw new Error("Select a text box first.");
  }
  if (editor.mode === "add" && !editor.addPoint) {
    throw new Error("In add mode, click a position on the page first.");
  }

  const text = editor.newText.value ?? "";
  const fontSizeRaw = editor.fontSize.value.trim();
  const paddingRaw = editor.padding.value.trim();
  const fontSize = fontSizeRaw ? Number(fontSizeRaw) : null;
  const padding = paddingRaw ? Number(paddingRaw) : 0;

  if (fontSize !== null && (!Number.isFinite(fontSize) || fontSize <= 0)) {
    throw new Error("Font size must be a positive number.");
  }
  if (!Number.isFinite(padding) || padding < 0) {
    throw new Error("Padding must be zero or a positive number.");
  }

  const form = new FormData();
  form.set("file", activeVisualPdfFile(editor));
  form.set("page", String(editor.currentPage));

  let endpoint = "/api/text-editor/apply";
  if (editor.mode === "add") {
    if (!text.trim()) {
      throw new Error("Type text to add.");
    }
    form.set("x", String(editor.addPoint.x));
    form.set("y", String(editor.addPoint.y));
    form.set("text", text);
    form.set("font_size", String(fontSize ?? 12));
    form.set("color", editor.addColor.value || "#000000");
    endpoint = "/api/text-editor/add";
  } else {
    const [x0, y0, x1, y1] = editor.selected.bbox;
    form.set("x0", String(x0 - padding));
    form.set("y0", String(y0 - padding));
    form.set("x1", String(x1 + padding));
    form.set("y1", String(y1 + padding));
    form.set("new_text", text);
    if (fontSize !== null) {
      form.set("font_size", String(fontSize));
    }
  }

  const response = await fetch(endpoint, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    throw new Error(await parseErrorMessage(response));
  }

  const blob = await response.blob();
  const filename = filenameFromDisposition(
    response.headers.get("Content-Disposition"),
    endpointFallbackNames[endpoint],
  );
  const contentType = response.headers.get("Content-Type") || "application/pdf";

  setResultFromBlob(blob, filename, contentType);
  useResultAsSource();
  editor.fileInput.value = "";

  await analyzeVisualEditor(editor, editor.currentPage);
  setStatus(`Visual Text Editor: change applied and refreshed ${filename}.`);
}

// Build and wire the visual editor popup controls.
function initVisualTextEditor(root) {
  const editor = {
    root,
    fileInput: root.querySelector('[data-ve-role="file-input"]'),
    scanBadge: root.querySelector('[data-ve-role="scan-badge"]'),
    scanMessage: root.querySelector('[data-ve-role="scan-message"]'),
    pageIndicator: root.querySelector('[data-ve-role="page-indicator"]'),
    modeEdit: root.querySelector('[data-ve-role="mode-edit"]'),
    modeAdd: root.querySelector('[data-ve-role="mode-add"]'),
    stage: root.querySelector('[data-ve-role="stage"]'),
    pageImage: root.querySelector('[data-ve-role="page-image"]'),
    overlay: root.querySelector('[data-ve-role="overlay"]'),
    addMarker: root.querySelector('[data-ve-role="add-marker"]'),
    selectionLabel: root.querySelector('[data-ve-role="selection-label"]'),
    textLabel: root.querySelector('[data-ve-role="text-label"]'),
    newText: root.querySelector('[data-ve-role="new-text"]'),
    fontSize: root.querySelector('[data-ve-role="font-size"]'),
    padding: root.querySelector('[data-ve-role="padding"]'),
    addColor: root.querySelector('[data-ve-role="add-color"]'),
    analyzeBtn: root.querySelector('[data-ve-action="analyze"]'),
    prevPageBtn: root.querySelector('[data-ve-action="prev-page"]'),
    nextPageBtn: root.querySelector('[data-ve-action="next-page"]'),
    applyBtn: root.querySelector('[data-ve-action="apply-edit"]'),
    analysis: null,
    pageData: null,
    selected: null,
    currentPage: 1,
    mode: "edit",
    addPoint: null,
    renderScale: null,
  };

  state.modal.editor = editor;
  resetVisualEditorState(editor, true);

  editor.fileInput.addEventListener("change", () => {
    resetVisualEditorState(editor, true);
  });

  editor.modeEdit.addEventListener("change", () => setVisualMode(editor, "edit"));
  editor.modeAdd.addEventListener("change", () => setVisualMode(editor, "add"));

  editor.newText.addEventListener("input", () => {
    updateApplyButton(editor);
  });

  editor.analyzeBtn.addEventListener("click", async () => {
    try {
      editor.analyzeBtn.disabled = true;
      setStatus("Visual Text Editor: analyzing PDF...");
      await analyzeVisualEditor(editor);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unexpected error.";
      setStatus(`Visual Text Editor: ${message}`, true);
    } finally {
      editor.analyzeBtn.disabled = false;
    }
  });

  editor.prevPageBtn.addEventListener("click", async () => {
    try {
      if (!editor.analysis || editor.analysis.is_scanned) {
        return;
      }
      const target = Math.max(1, editor.currentPage - 1);
      if (target === editor.currentPage) {
        return;
      }
      setStatus("Visual Text Editor: loading page...");
      await loadVisualEditorPage(editor, target);
      setStatus("Visual Text Editor: page loaded.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unexpected error.";
      setStatus(`Visual Text Editor: ${message}`, true);
    }
  });

  editor.nextPageBtn.addEventListener("click", async () => {
    try {
      if (!editor.analysis || editor.analysis.is_scanned) {
        return;
      }
      const target = Math.min(editor.analysis.page_count, editor.currentPage + 1);
      if (target === editor.currentPage) {
        return;
      }
      setStatus("Visual Text Editor: loading page...");
      await loadVisualEditorPage(editor, target);
      setStatus("Visual Text Editor: page loaded.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unexpected error.";
      setStatus(`Visual Text Editor: ${message}`, true);
    }
  });

  editor.stage.addEventListener("click", (event) => {
    if (editor.mode !== "add" || !editor.pageData || !editor.renderScale) {
      return;
    }
    const rect = editor.pageImage.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return;
    }
    const xPx = event.clientX - rect.left;
    const yPx = event.clientY - rect.top;
    if (xPx < 0 || yPx < 0 || xPx > rect.width || yPx > rect.height) {
      return;
    }
    const pdfX = xPx / editor.renderScale.x;
    const pdfY = yPx / editor.renderScale.y;
    setAddPoint(editor, pdfX, pdfY);
  });

  editor.applyBtn.addEventListener("click", async () => {
    try {
      editor.applyBtn.disabled = true;
      setStatus("Visual Text Editor: applying edit...");
      await applyVisualEditorEdit(editor);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unexpected error.";
      setStatus(`Visual Text Editor: ${message}`, true);
    } finally {
      editor.applyBtn.disabled = false;
    }
  });

  if (state.sourceBlob) {
    analyzeVisualEditor(editor).catch((error) => {
      const message = error instanceof Error ? error.message : "Unexpected error.";
      setStatus(`Visual Text Editor: ${message}`, true);
    });
  }
}

// -------- Generic modal tools --------

function openToolModal(toolKey, buttonLabel) {
  const template = document.getElementById(`tpl-${toolKey}`);
  if (!template) {
    setStatus(`Tool template not found for ${toolKey}.`, true);
    return;
  }

  modalFormHost.replaceChildren(template.content.cloneNode(true));
  state.modal.activeTool = toolKey;

  if (toolKey === "visual-text-editor") {
    modalPanel.classList.add("editor-mode");
    modalTitle.textContent = "Visual Text Editor";
    setModalDownloadState(false);
    toolModal.classList.remove("hidden");
    toolModal.setAttribute("aria-hidden", "false");

    const root = modalFormHost.querySelector(".visual-editor-shell");
    if (!root) {
      setStatus("Visual Text Editor UI failed to initialize.", true);
      return;
    }

    initVisualTextEditor(root);
    return;
  }

  modalPanel.classList.remove("editor-mode");
  state.modal.editor = null;

  const form = modalFormHost.querySelector("form");
  modalTitle.textContent = form?.dataset.toolName || buttonLabel || "Tool";

  modalAfterMeta.textContent = "Run this tool to preview output.";
  applyModalAfterPreview(null, "", "");
  refreshModalBeforePreview();

  if (form) {
    const fileInputs = form.querySelectorAll('input[type="file"]');
    fileInputs.forEach((input) => {
      input.addEventListener("change", refreshModalBeforePreview);
    });
    form.addEventListener("submit", handleToolSubmit);
  }

  toolModal.classList.remove("hidden");
  toolModal.setAttribute("aria-hidden", "false");
}

function closeToolModal() {
  toolModal.classList.add("hidden");
  toolModal.setAttribute("aria-hidden", "true");
  modalFormHost.replaceChildren();
  state.modal.activeTool = "";
  state.modal.editor = null;
  modalPanel.classList.remove("editor-mode");
  revokeUrl("modalBefore");
  revokeUrl("modalAfter");
  setIframeSource(modalBeforePreview, "");
  setIframeSource(modalAfterPreview, "");
  modalBeforeMeta.textContent = "Load a source file in workspace or this form.";
  modalAfterMeta.textContent = "Run this tool to preview output.";
  setModalDownloadState(false);
}

// Convert tool form inputs into a normalized FormData payload.
function buildSubmissionFormData(form) {
  const formData = new FormData(form);

  form.querySelectorAll('input[type="checkbox"][name]').forEach((checkbox) => {
    formData.set(checkbox.name, checkbox.checked ? "true" : "false");
  });

  const singleFileInput = form.querySelector('input[type="file"][name="file"]');
  const multiFileInput = form.querySelector('input[type="file"][name="files"]');
  const noSourceFallback = form.dataset.noSourceFallback === "true";

  if (singleFileInput) {
    formData.delete("file");

    if (singleFileInput.files.length > 0) {
      formData.set("file", singleFileInput.files[0]);
    } else if (!noSourceFallback && state.sourceBlob) {
      const sourceFile = sourceBlobAsFile();
      if (!sourceFile) {
        throw new Error("No PDF selected.");
      }
      formData.set("file", sourceFile);
    } else {
      throw new Error("No PDF selected. Upload in popup or load source in workspace.");
    }
  }

  if (multiFileInput && multiFileInput.files.length === 0) {
    throw new Error("Select at least one file.");
  }

  for (const [key, value] of Array.from(formData.entries())) {
    if (typeof value === "string" && value.trim() === "") {
      formData.delete(key);
    }
  }

  return formData;
}

async function handleToolSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  const endpoint = form.dataset.endpoint;
  const toolName = form.dataset.toolName || "Operation";
  const submitBtn = form.querySelector('button[type="submit"]');

  try {
    const payload = buildSubmissionFormData(form);
    submitBtn.disabled = true;
    setStatus(`${toolName}: processing...`);

    const response = await fetch(endpoint, {
      method: "POST",
      body: payload,
    });

    if (!response.ok) {
      throw new Error(await parseErrorMessage(response));
    }

    const blob = await response.blob();
    const fallback = endpointFallbackNames[endpoint] || "output.bin";
    const filename = filenameFromDisposition(response.headers.get("Content-Disposition"), fallback);
    const contentType = response.headers.get("Content-Type") || "application/octet-stream";

    const replacements = response.headers.get("X-Replacements");
    const note = replacements !== null ? `Replacements: ${replacements}` : "";

    setResultFromBlob(blob, filename, contentType, note);

    if (replacements !== null) {
      setStatus(`${toolName}: done. ${filename} generated. Replacements: ${replacements}.`);
    } else {
      setStatus(`${toolName}: done. ${filename} generated.`);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unexpected error.";
    setStatus(`${toolName}: ${message}`, true);
  } finally {
    submitBtn.disabled = false;
  }
}

function useResultAsSource() {
  if (!state.resultBlob) return;
  setSourceFromBlob(state.resultBlob, state.resultName || "result.pdf", state.resultType || "application/pdf");
  setStatus(`Source updated to ${state.sourceName}.`);
}

function downloadLatestResult() {
  if (!state.resultBlob) return;
  downloadBlob(state.resultBlob, state.resultName || "output.bin");
}

workspaceFile.addEventListener("change", () => {
  const file = workspaceFile.files?.[0];
  if (!file) return;
  setSourceFromBlob(file, file.name, file.type);
  setStatus(`Source loaded: ${file.name}`);
});

clearSourceBtn.addEventListener("click", () => {
  clearSource();
  setStatus("Source cleared.");
});

useResultBtn.addEventListener("click", useResultAsSource);
downloadResultBtn.addEventListener("click", downloadLatestResult);
modalDownloadBtn.addEventListener("click", downloadLatestResult);
modalUseResultBtn.addEventListener("click", () => {
  useResultAsSource();
  refreshModalBeforePreview();
});

modalCloseBtn.addEventListener("click", closeToolModal);
toolModal.addEventListener("click", (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && target.dataset.closeModal === "true") {
    closeToolModal();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !toolModal.classList.contains("hidden")) {
    closeToolModal();
  }
});

document.querySelectorAll(".tool-btn").forEach((button) => {
  button.addEventListener("click", () => {
    const toolKey = button.dataset.tool;
    if (!toolKey) return;
    openToolModal(toolKey, button.textContent?.trim() || "Tool");
  });
});

setIframeSource(sourcePreview, "");
setIframeSource(resultPreview, "");
setModalDownloadState(false);
