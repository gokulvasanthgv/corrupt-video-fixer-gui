# 🎬 Corrupt Video Fixer GUI (GV Video Recovery)

A modern, glassmorphic desktop application for recovering corrupted, unfinalized, or truncated video files (MP4, MOV, MKV, AVI, TS, M4V) caused by abrupt recording interruptions, camera crashes, OBS freezes, or power cuts.

Powered by [`recover_mp4`](https://github.com/ponchio/untrunc) and [`FFmpeg`](https://ffmpeg.org/), wrapped in a sleek **PySide6 (Qt6)** dark glass interface.

---

## ✨ Features

- 🎨 **Glassmorphic Modern UI**: Hardware-accelerated Qt6 interface with interactive glow buttons, dynamic stats cards, and dark theme.
- 📥 **Full-Window Drag & Drop**: Simply drag and drop your corrupted video anywhere onto the window to begin.
- 🔄 **4-Stage Chaptered Progress**: Visual indicators track each step of the pipeline:
  1. **Scan Template**: Analyzes healthy reference video to extract SPS/PPS metadata and audio profiles.
  2. **Recover Streams**: Demuxes and recovers raw video (`.h264`, `.h265`) and audio (`.aac`, `.wav`, etc.) streams.
  3. **Mux Video**: Re-encapsulates the recovered elementary streams into a standard, playable `.mp4`.
  4. **Cleanup**: Automatically deletes intermediate scratch files once the recovery succeeds.
- 🛡️ **Intelligent Disk Space Guard**: Pre-checks internal temporary storage and destination drive space before starting (requires ~2x file size on the same drive).
- 🔁 **Automated Template Fallback**: Supports multi-template candidates (e.g. `good.mp4`, `good-h265.mp4`), automatically switching to alternative templates if one fails.
- ⏱️ **Sliding-Window ETA & Real-Time Stats**: Live byte progress, throughput percentage, and estimated time remaining.
- 📊 **Telemetry Dashboard**: Tracks lifetime recoveries, total duration of restored footage, and daily counts locally.
- 💻 **Collapsible Terminal Panel**: View live diagnostic logs and CLI output from `recover_mp4` and `FFmpeg` without external terminal popups.

---

## 💡 How It Works

When a video recording is cut off unexpectedly (e.g. device power failure or software crash), the container's index metadata (the `moov` atom in MP4/MOV) is never written to disk, rendering the file unplayable.

By providing a **healthy reference video** (recorded on the exact same device and camera settings), this tool extracts the missing header configuration parameters (codec profiles, SPS, PPS, sample rates) and reconstructs the damaged container around the raw streams.

---

## 🚀 Quick Start & Download

### Option 1: Portable Windows Executable (No Python required)

1. Download the latest **`Gv-video-recovery.zip`** from [**Releases (v2)**](https://github.com/gokulvasanthgv/corrupt-video-fixer-gui/releases/tag/v2).
2. Extract the archive to any folder on your computer.
3. Launch `gv-video-recovery.exe`.

### Option 2: Running from Source

#### Prerequisites
- **Python 3.10+**
- **FFmpeg binary** (`ffmpeg.exe`)
- **recover_mp4 binary** (`recover_mp4.exe`)

#### Setup
```bash
# 1. Clone the repository
git clone https://github.com/gokulvasanthgv/corrupt-video-fixer-gui.git
cd corrupt-video-fixer-gui

# 2. Install Python dependencies
pip install PySide6

# 3. Ensure binaries are in the directory
# Place `recover_mp4.exe`, `ffmpeg.exe`, and optional default reference `good.mp4`
# in the same directory or inside an `_internal/` folder.

# 4. Launch the application
python gv-video-recovery.py
```

---

## 📖 How to Use

```
 ┌────────────────────────────────────────────────────────┐
 │ 1. Set Template Video  ─►  2. Drag Corrupted Video    │
 │            │                          │                │
 │            ▼                          ▼                │
 │ 3. Verify Disk Space   ─►  4. Hit 'Recover' Button     │
 └────────────────────────────────────────────────────────┘
```

### Step 1: Select a Reference / Template Video
> [!IMPORTANT]
> The template file **must** be a healthy, playable video recorded on the **same camera, smartphone, or recording software** with the **same resolution, frame rate, and codec** as the damaged file.

- Click **"Change..."** (or **"Select Template..."**) in the upper right header.
- Browse and select your healthy reference video.
- *(If a file named `good.mp4` or `good-h265.mp4` is in the application folder, it will be selected automatically).*

### Step 2: Choose Your Corrupted Video
- **Drag and drop** your broken video directly into the application window.
- Or click **"Choose corrupt file"** to select it manually.

### Step 3: Choose Destination & Verify Space
- The application automatically defaults to saving the output file alongside your original file with the `-recovered.mp4` suffix.
- To specify a custom location, click **"Browse destination"**.
- Check the inline **Space Check Bar**:
  - 🟢 **Green (Space OK)**: You have enough space to perform recovery.
  - 🔴 **Red (Insufficient Space)**: Free up drive space before continuing.

### Step 4: Click Recover
- Click the blue **"Recover"** button.
- Follow the multi-chapter progress bar:
  - Watch live progress percentage and dynamic ETA.
  - Optionally click the **"Terminal"** button to view granular debug output.
- Once finished, your recovered MP4 video will be ready at the chosen destination path!

---

## 📁 Directory Structure (Source / Bundle)

```
app/
├── gv-video-recovery.py       # Main GUI application script
├── README.md                  # Documentation
└── _internal/                 # Required helper binaries & dependencies
    ├── ffmpeg.exe             # Media muxing utility
    ├── recover_mp4.exe        # Stream recovery and parameter analysis tool
    ├── good.mp4               # (Optional) Default fallback template
    └── ...                    # Shared libraries (.dll)
```

---

## 🛠️ Troubleshooting

- **"Analyze failed for template"**: Ensure the template video was recorded with identical encoding profile and resolution as the damaged file.
- **"Insufficient Space on Shared Drive"**: The recovery process requires extracting intermediate elementary streams (`.h264`/`.aac`) before muxing the final `.mp4`. Ensure your drive has at least **2x the size** of the damaged file in free space.
- **Audio is out of sync**: If audio and video are desynchronized after recovery, try opening the Terminal view to check whether the original audio stream uses variable frame rate or non-standard AAC packet headers.

---

## 📜 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
Third-party tools `recover_mp4` and `FFmpeg` are distributed under their respective open-source licenses.
