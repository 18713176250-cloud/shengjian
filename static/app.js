"use strict";

const uploadForm = document.querySelector("#upload-form");
const fileInput = document.querySelector("#video-file");
const dropZone = document.querySelector("#drop-zone");
const selectedFile = document.querySelector("#selected-file");
const selectedName = document.querySelector("#selected-name");
const selectedSize = document.querySelector("#selected-size");
const clearFileButton = document.querySelector("#clear-file");
const uploadButton = document.querySelector("#upload-button");
const uploadError = document.querySelector("#upload-error");
const uploadProgress = document.querySelector("#upload-progress");
const uploadProgressBar = document.querySelector("#upload-progress-bar");
const uploadPercent = document.querySelector("#upload-percent");
const uploadProgressLabel = document.querySelector("#upload-progress-label");
const projectList = document.querySelector("#project-list");
const projectCount = document.querySelector("#project-count");
const historyEmpty = document.querySelector("#history-empty");
const historyError = document.querySelector("#history-error");

const statusLabels = {
  ready: "待提取",
  extracting: "提取中",
  audio_ready: "音频已就绪",
  failed: "处理失败"
};

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
  }).format(date);
}

function showError(element, message) {
  element.textContent = message;
  element.classList.remove("hidden");
}

function clearError(element) {
  element.textContent = "";
  element.classList.add("hidden");
}

function createStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `status-badge status-${status}`;
  badge.textContent = statusLabels[status] || status;
  return badge;
}

function chooseFile(file) {
  clearError(uploadError);
  if (!file) {
    clearFile();
    return;
  }
  if (!file.name.toLowerCase().endsWith(".mp4")) {
    clearFile();
    showError(uploadError, "第一版仅支持 MP4 视频（.mp4）。");
    return;
  }
  if (file.size > 100 * 1024 * 1024) {
    clearFile();
    showError(uploadError, "视频大小超过 100 MB 限制，请压缩后重新上传。");
    return;
  }
  if (file.size === 0) {
    clearFile();
    showError(uploadError, "上传的文件为空，请选择有效的 MP4 视频。");
    return;
  }
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  selectedName.textContent = file.name;
  selectedName.title = file.name;
  selectedSize.textContent = formatBytes(file.size);
  selectedFile.classList.remove("hidden");
  uploadButton.disabled = false;
}

function clearFile() {
  fileInput.value = "";
  selectedFile.classList.add("hidden");
  selectedName.textContent = "";
  uploadButton.disabled = true;
}

fileInput.addEventListener("change", () => chooseFile(fileInput.files[0]));
clearFileButton.addEventListener("click", clearFile);

["dragenter", "dragover"].forEach(eventName => {
  dropZone.addEventListener(eventName, event => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach(eventName => {
  dropZone.addEventListener(eventName, event => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
});
dropZone.addEventListener("drop", event => chooseFile(event.dataTransfer.files[0]));

function setUploadProgress(percent) {
  uploadProgress.classList.remove("hidden");
  uploadProgressBar.value = percent;
  uploadProgressBar.textContent = `${percent}%`;
  uploadPercent.textContent = `${percent}%`;
}

uploadForm.addEventListener("submit", event => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) {
    showError(uploadError, "请先选择一个 MP4 视频。");
    return;
  }
  clearError(uploadError);
  uploadButton.disabled = true;
  uploadButton.firstElementChild.textContent = "正在处理…";
  uploadProgressLabel.textContent = "正在上传…";
  setUploadProgress(0);

  const request = new XMLHttpRequest();
  request.open("POST", "/api/projects");
  request.upload.addEventListener("progress", progressEvent => {
    if (progressEvent.lengthComputable) {
      setUploadProgress(Math.round(progressEvent.loaded / progressEvent.total * 100));
    }
  });
  request.upload.addEventListener("load", () => {
    setUploadProgress(100);
    uploadProgressLabel.textContent = "上传完成，正在校验真实格式、时长和音轨…";
  });
  request.addEventListener("load", () => {
    let result = {};
    try {
      result = JSON.parse(request.responseText);
    } catch {
      showError(uploadError, "服务返回了无法识别的结果，请稍后重试。");
    }
    if (request.status >= 200 && request.status < 300 && result.id) {
      uploadProgressLabel.textContent = "校验通过，正在进入项目…";
      window.location.assign(`/projects/${result.id}`);
      return;
    }
    showError(uploadError, result.detail || "上传失败，请稍后重试。");
    uploadButton.disabled = false;
    uploadButton.firstElementChild.textContent = "开始上传";
  });
  request.addEventListener("error", () => {
    showError(uploadError, "无法连接本地服务，请确认服务已启动后重试。");
    uploadButton.disabled = false;
    uploadButton.firstElementChild.textContent = "开始上传";
  });
  const formData = new FormData();
  formData.append("file", file);
  request.send(formData);
});

function renderProject(project) {
  const card = document.createElement("a");
  card.className = "project-card";
  card.href = `/projects/${project.id}`;
  card.setAttribute("aria-label", `打开项目 ${project.original_filename}`);

  const top = document.createElement("div");
  top.className = "project-card-top";
  const type = document.createElement("span");
  type.className = "file-type";
  type.textContent = "MP4";
  top.append(type, createStatusBadge(project.status));

  const title = document.createElement("h3");
  title.textContent = project.original_filename;
  title.title = project.original_filename;
  const meta = document.createElement("p");
  meta.className = "project-card-meta";
  meta.textContent = `${formatDuration(project.duration_seconds)} · ${project.width} × ${project.height} · ${formatBytes(project.file_size)}`;

  const footer = document.createElement("div");
  footer.className = "project-card-footer";
  const date = document.createElement("span");
  date.textContent = formatDate(project.created_at);
  const link = document.createElement("span");
  link.className = "card-link";
  link.textContent = "打开项目 →";
  footer.append(date, link);
  card.append(top, title, meta, footer);
  projectList.append(card);
}

async function loadHistory() {
  clearError(historyError);
  try {
    const response = await fetch("/api/projects", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "历史项目读取失败。");
    projectList.replaceChildren();
    projectCount.textContent = `${result.items.length} 个项目`;
    historyEmpty.classList.toggle("hidden", result.items.length > 0);
    result.items.forEach(renderProject);
  } catch (error) {
    projectCount.textContent = "读取失败";
    historyEmpty.classList.add("hidden");
    showError(historyError, `历史项目读取失败：${error.message}。请刷新页面重试。`);
  }
}

loadHistory();
