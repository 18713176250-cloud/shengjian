"use strict";

const projectId = window.location.pathname.split("/").filter(Boolean).pop();
const loading = document.querySelector("#page-loading");
const pageError = document.querySelector("#page-error");
const content = document.querySelector("#project-content");
const projectName = document.querySelector("#project-name");
const projectStatus = document.querySelector("#project-status");
const videoPlayer = document.querySelector("#video-player");
const videoError = document.querySelector("#video-error");
const extractButton = document.querySelector("#extract-button");
const taskError = document.querySelector("#task-error");
const taskStatus = document.querySelector("#task-status");
const audioCard = document.querySelector("#audio-card");
const audioPlayer = document.querySelector("#audio-player");
const audioDownload = document.querySelector("#audio-download");

const projectStatusLabels = {
  ready: "待提取音频",
  extracting: "正在提取音频",
  audio_ready: "音频已就绪",
  failed: "处理失败"
};
const taskStatusLabels = {
  queued: "已排队，等待执行",
  running: "正在后台提取",
  succeeded: "提取完成",
  failed: "提取失败，可重试"
};

let pollTimer = null;
let requestInProgress = false;

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)} 分 ${String(total % 60).padStart(2, "0")} 秒`;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
  }).format(date);
}

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

function showError(element, message) {
  element.textContent = message;
  element.classList.remove("hidden");
}

function clearError(element) {
  element.textContent = "";
  element.classList.add("hidden");
}

function schedulePoll(project) {
  if (pollTimer) window.clearTimeout(pollTimer);
  const activeTask = project.latest_audio_task && ["queued", "running"].includes(project.latest_audio_task.status);
  if (project.status === "extracting" || activeTask) {
    pollTimer = window.setTimeout(loadProject, 1500);
  }
}

function renderProject(project) {
  document.title = `${project.original_filename} · 声见`;
  projectName.textContent = project.original_filename;
  projectStatus.className = `status-badge status-${project.status}`;
  projectStatus.textContent = projectStatusLabels[project.status] || project.status;
  setText("#video-duration", formatDuration(project.duration_seconds));
  setText("#video-resolution", `${project.width} × ${project.height}`);
  setText("#video-size", formatBytes(project.file_size));
  setText("#video-created", formatDate(project.created_at));

  if (!videoPlayer.getAttribute("src")) videoPlayer.src = project.video_url;
  const task = project.latest_audio_task;
  taskStatus.textContent = task ? taskStatusLabels[task.status] || task.status : "尚未创建任务";
  taskStatus.title = task ? `任务编号：${task.id}` : "";

  clearError(taskError);
  if (project.error_message) showError(taskError, project.error_message);
  const isProcessing = project.status === "extracting" || (task && ["queued", "running"].includes(task.status));
  extractButton.disabled = Boolean(isProcessing);
  extractButton.classList.toggle("hidden", project.has_audio);
  extractButton.firstChild.textContent = project.status === "failed" ? "重新提取音频 " : isProcessing ? "正在提取… " : "提取音频 ";

  audioCard.classList.toggle("hidden", !project.has_audio);
  if (project.has_audio) {
    if (audioPlayer.getAttribute("src") !== project.audio_url) audioPlayer.src = project.audio_url;
    audioDownload.href = project.audio_download_url;
  } else {
    audioPlayer.removeAttribute("src");
    audioPlayer.load();
  }
  schedulePoll(project);
}

async function loadProject() {
  if (requestInProgress) return;
  requestInProgress = true;
  try {
    const response = await fetch(`/api/projects/${projectId}`, { cache: "no-store" });
    const project = await response.json();
    if (!response.ok) throw new Error(project.detail || "项目读取失败。");
    clearError(pageError);
    loading.classList.add("hidden");
    content.classList.remove("hidden");
    renderProject(project);
  } catch (error) {
    loading.classList.add("hidden");
    showError(pageError, `无法读取项目：${error.message}。请检查本地服务后刷新页面。`);
  } finally {
    requestInProgress = false;
  }
}

extractButton.addEventListener("click", async () => {
  clearError(taskError);
  extractButton.disabled = true;
  extractButton.firstChild.textContent = "正在提交任务… ";
  try {
    const response = await fetch(`/api/projects/${projectId}/extract-audio`, { method: "POST" });
    const project = await response.json();
    if (!response.ok) throw new Error(project.detail || "任务提交失败。");
    renderProject(project);
  } catch (error) {
    showError(taskError, error.message);
    extractButton.disabled = false;
    extractButton.firstChild.textContent = "重新提取音频 ";
  }
});

videoPlayer.addEventListener("error", () => {
  showError(videoError, "视频无法播放，文件可能不存在或浏览器不支持其编码。请重新上传有效的 MP4 视频。");
});
videoPlayer.addEventListener("loadedmetadata", () => clearError(videoError));

loadProject();
