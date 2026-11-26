# 声见

面向听障用户的视频无障碍制作平台。第一阶段实现完全本地的媒体基础流程：上传 MP4、预览视频、查看媒体信息、后台提取音频、播放与下载 WAV。

当前版本不登录、不调用云服务，也不生成字幕、说话人或声音事件识别结果。

## 功能与限制

- 仅接受 `.mp4` 文件，并通过 FFprobe 检查真实封装格式，而非只检查扩展名。
- 单文件最大 100 MB，视频最长 180 秒，必须同时包含视频流和音轨。
- 上传文件以 UUID 重命名，用户文件名仅用于界面展示，不参与存储路径或命令拼接。
- FFmpeg 后台提取第一条音轨，输出 16 kHz、单声道、16 位 PCM WAV。
- SQLite 保存项目与任务记录；重启后历史项目仍在。
- 重启时将未完成的提取任务标记为失败，可在项目页重新提取。
- 预留 OBS、SIS、声音事件检测的 Python 接口，当前没有任何云服务实现或调用。

## 项目目录

```text
shengjian/
├─ app/
│  ├─ __init__.py
│  ├─ config.py          # 本地路径、限制和 FFmpeg 配置
│  ├─ database.py        # SQLite 表结构及项目/任务操作
│  ├─ integrations.py    # OBS、SIS、声音事件检测预留接口
│  ├─ main.py            # FastAPI 接口、静态页面和后台任务
│  └─ media.py           # FFprobe 校验与 FFmpeg 音频提取
├─ static/
│  ├─ index.html         # 上传与历史项目首页
│  ├─ project.html       # 视频预览、项目信息与音频页面
│  ├─ styles.css         # 响应式中文界面样式
│  ├─ app.js             # 上传进度、拖放与历史列表
│  └─ project.js         # 项目加载、任务提交与真实状态轮询
├─ tests/
│  └─ test_app.py        # 媒体校验及 API 流程测试
├─ storage/              # 首次运行自动创建，已被 Git 忽略
│  ├─ videos/            # UUID 命名的原始 MP4
│  ├─ audio/             # UUID 命名的 WAV
│  └─ shengjian.db       # 本地 SQLite 数据库
├─ .env.example          # 无密钥的本地配置示例
├─ .gitignore
├─ requirements.txt
└─ README.md
```

## Windows + VS Code 环境准备

### 1. Python

建议使用 Python 3.11.9。安装时勾选 **Add Python to PATH**。在 VS Code 中打开本项目，再打开一个新的 PowerShell 终端：

```powershell
py -3.11 --version
```

### 2. FFmpeg 与 FFprobe

可以使用 Windows 包管理器安装：

```powershell
winget install --id Gyan.FFmpeg -e
```

安装后关闭并重新打开 VS Code 终端，让 PATH 生效，然后检查：

```powershell
ffmpeg -version
ffprobe -version
```

两条命令都应显示版本信息。如果手动安装，请将同时包含 `ffmpeg.exe` 和 `ffprobe.exe` 的 `bin` 目录加入系统 PATH；也可以在 `.env` 中分别设置两个可执行文件的完整路径。

### 3. 创建虚拟环境并安装依赖

在 VS Code 的 PowerShell 终端执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果 PowerShell 禁止激活脚本，可在确认本机执行策略后，仅为当前用户设置：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

也可以不激活虚拟环境，直接使用 `.\.venv\Scripts\python.exe` 执行后续 Python 命令。

### 4. 本地配置

```powershell
Copy-Item .env.example .env
```

默认配置即可运行，不包含任何账号、密码或密钥：

| 配置项 | 默认值 | 用途 |
| --- | --- | --- |
| `APP_HOST` | `127.0.0.1` | 监听地址，仅本机访问 |
| `APP_PORT` | `8000` | 服务端口 |
| `APP_DATA_DIR` | `storage` | 音视频保存目录 |
| `APP_DATABASE_PATH` | `storage/shengjian.db` | SQLite 文件 |
| `APP_MAX_FILE_BYTES` | `104857600` | 100 MB 上传限制 |
| `APP_MAX_DURATION_SECONDS` | `180` | 3 分钟时长限制 |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg 命令或完整路径 |
| `FFPROBE_PATH` | `ffprobe` | FFprobe 命令或完整路径 |

Windows 完整路径示例：

```dotenv
FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe
FFPROBE_PATH=C:\ffmpeg\bin\ffprobe.exe
```

### 5. 启动

```powershell
python -m app.main
```

终端出现启动日志后，用浏览器访问：

```text
http://127.0.0.1:8000
```

停止服务：在终端按 `Ctrl+C`。再次启动后，首页会从同一个 SQLite 数据库读取历史项目。

也可以在虚拟环境已激活时使用：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 使用流程

1. 在首页选择或拖入 MP4，点击“开始上传”。
2. 页面显示实际上传进度；服务端继续检查真实格式、时长、分辨率和音轨。
3. 校验通过后自动进入项目页，可播放原视频并查看媒体信息。
4. 点击“提取音频”，后台任务进入“已排队 / 正在后台提取”状态，页面每 1.5 秒读取一次真实状态。
5. 成功后显示 WAV 播放器和下载按钮；失败时显示中文原因，可重新提取。

## 数据与任务状态

项目状态：

- `ready`：视频已校验，待提取音频。
- `extracting`：音频任务排队或执行中。
- `audio_ready`：音频提取成功。
- `failed`：最近一次提取失败或服务重启导致任务中断。

任务状态：`queued` → `running` → `succeeded` / `failed`。每次点击提取都会新增任务记录，不覆盖历史任务。

如需清空全部本地数据，先停止服务，再删除 `storage` 目录；下次启动会重新创建空目录和数据库。该操作不可恢复。

## 基础检查

```powershell
python -m compileall app tests
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/project.js
```

其中 Python 测试使用临时目录，不读写正式的 `storage/shengjian.db`。测试中的媒体探测与音频生成使用模拟函数，用于验证 API、数据库、文件清理和 WAV 播放/下载流程；它们不能替代本机 FFmpeg 的真实媒体测试。

## API 概览

| 方法 | 地址 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务及 FFmpeg/FFprobe 可用性 |
| `GET` | `/api/projects` | 历史项目列表 |
| `POST` | `/api/projects` | 上传并校验 MP4 |
| `GET` | `/api/projects/{id}` | 项目与最近音频任务状态 |
| `POST` | `/api/projects/{id}/extract-audio` | 创建后台提取任务 |
| `GET` | `/api/projects/{id}/video` | 原视频播放 |
| `GET` | `/api/projects/{id}/audio` | WAV 播放 |
| `GET` | `/api/projects/{id}/audio/download` | WAV 下载 |

FastAPI 自带接口文档位于 `http://127.0.0.1:8000/docs`。

## 常见问题

- **“未检测到 FFprobe / FFmpeg”**：确认两条版本命令均可在启动服务的同一个终端运行，并重新启动服务。
- **“文件的真实格式不是 MP4”**：扩展名改为 `.mp4` 不等于转码，请先用视频工具真正转换为 MP4。
- **“未检测到音轨”**：当前流程要求视频含音轨，无声视频不能进入提取步骤。
- **浏览器不能预览视频**：MP4 只是封装格式，内部编码也可能不受浏览器支持；音频提取仍可按任务结果判断。
- **端口被占用**：修改 `.env` 中的 `APP_PORT`，重新启动并访问对应端口。

## 后续模块

`app/integrations.py` 使用 `Protocol` 定义 OBS 上传、SIS 转写和声音事件检测的边界。后续实现这些接口并接入业务流程时，再添加对应配置；第一阶段不会读取或请求任何云端凭据。
