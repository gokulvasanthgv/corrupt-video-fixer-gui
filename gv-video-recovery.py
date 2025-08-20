import sys
import os
import re
import shlex
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QPropertyAnimation, QEasingCurve, QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QLineEdit, QProgressBar, QTextEdit, QFrame,
    QSizePolicy, QGraphicsDropShadowEffect
)
import subprocess


# ---------- Utils ----------
def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    s = float(n)
    for u in units:
        if s < 1024.0 or u == units[-1]:
            return f"{s:.2f} {u}"
        s /= 1024.0


# ---------- Mouse-follow glow "squircle" button ----------
class GlowButton(QPushButton):
    def __init__(self, text="", parent=None, *, bg="#3b82f6", fg="#ffffff", radius=18, pad_v=12, pad_h=20):
        super().__init__(text, parent)
        self._bg = bg
        self._fg = fg
        self._radius = radius
        self._pad_v = pad_v
        self._pad_h = pad_h

        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._update_style()

        # Subtle glow that follows mouse
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setColor(QColor(59, 130, 246, 180))  # blue glow
        self._shadow.setBlurRadius(16)
        self._shadow.setOffset(0, 0)
        self.setGraphicsEffect(self._shadow)

        # Animate glow intensity on hover
        self._anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._anim.setDuration(180)
        self._anim.setStartValue(12)
        self._anim.setEndValue(26)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

        self._hovered = False

    def set_bg_color(self, bg: str):
        """Allows dynamically changing the background color of the button."""
        self._bg = bg
        self._update_style()

    def _update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._bg};
                color: {self._fg};
                border: none;
                border-radius: {self._radius}px;
                padding: {self._pad_v}px {self._pad_h}px;
                font-weight: 600;
                letter-spacing: 0.2px;
            }}
            QPushButton:disabled {{
                background-color: #cdd5e1;
                color: #f8fafc;
            }}
            QPushButton:hover:!disabled {{
                background-color: {self._mix(self._bg, "#ffffff", 0.08)};
            }}
            QPushButton:checked {{
                background-color: {self._mix(self._bg, "#000000", 0.1)};
            }}
        """)

    def _mix(self, c1: str, c2: str, t: float) -> str:
        def hex_to_rgb(h):
            h = h.lstrip("#")
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
        def rgb_to_hex(rgb):
            return "#{:02x}{:02x}{:02x}".format(*rgb)
        a = hex_to_rgb(c1)
        b = hex_to_rgb(c2)
        m = tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))
        return rgb_to_hex(m)

    def enterEvent(self, event):
        self._hovered = True
        self._anim.setDirection(QPropertyAnimation.Forward)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._anim.setDirection(QPropertyAnimation.Backward)
        self._anim.start()
        # Center the glow back
        self._shadow.setOffset(0, 0)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        if self._hovered and self.isEnabled():
            # Move glow offset relative to cursor position
            pos: QPointF = event.position()
            cx, cy = self.width() / 2.0, self.height() / 2.0
            dx = (pos.x() - cx) / max(self.width(), 1)
            dy = (pos.y() - cy) / max(self.height(), 1)
            # Scale to a subtle offset
            self._shadow.setOffset(dx * 10.0, dy * 10.0)
        super().mouseMoveEvent(event)


# ---------- Background worker (no console windows) ----------
class ProcessWorker(QThread):
    line = Signal(str)
    finished = Signal(int)

    def __init__(self, cmd_args, cwd=None, env=None, parent=None):
        super().__init__(parent)
        self.cmd_args = cmd_args
        self.cwd = cwd
        self.env = env or os.environ.copy()

    def run(self):
        try:
            popen_kwargs = dict(
                cwd=self.cwd,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            # Prevent console windows on Windows
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                popen_kwargs["startupinfo"] = startupinfo
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            proc = subprocess.Popen(self.cmd_args, **popen_kwargs)
            for line in proc.stdout:
                self.line.emit(line.rstrip("\r\n"))
            proc.wait()
            self.finished.emit(proc.returncode)
        except Exception as e:
            self.line.emit(f"[ERROR] {e}")
            self.finished.emit(-1)


# ---------- Main UI ----------
class RecoveryApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gokul's Temp video recovery")
        self.resize(1000, 680)

        # Program directory (supports PyInstaller)
        self.program_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        self.recover_exe = (self.program_dir / "recover_mp4.exe").resolve()
        self.ffmpeg_exe = (self.program_dir / "ffmpeg.exe").resolve()
        default_good_mp4 = (self.program_dir / "good.mp4").resolve()

        # State
        self.selected_file: Path | None = None
        self.dest_path: Path | None = None
        self.good_mp4_path: Path | None = None
        self.command_1_line: str | None = None
        self.command_2_line: str | None = None
        self._mux_inputs = []
        self._current_worker: ProcessWorker | None = None

        # Build UI
        self._build_ui()
        
        # Try to auto-load 'good.mp4' if it exists in the program folder
        if default_good_mp4.exists():
            self.good_mp4_path = default_good_mp4
        else:
            self.good_mp4_path = None
        self._update_template_display()

        self._apply_light_theme()
        self._update_controls()

    # ----- UI -----
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(14)

        # Header bar: Title left, Controls right
        header = QHBoxLayout()
        title = QLabel("Gokul's Temp video recovery")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: #0f172a; letter-spacing: 0.2px;")
        header.addWidget(title, 0, Qt.AlignLeft)
        header.addStretch(1)

        self.template_status_label = QLabel()
        self.template_status_label.setStyleSheet("font-size: 13px; color: #475569; padding-right: 8px;")
        header.addWidget(self.template_status_label, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.btn_change_template = GlowButton("Change...", bg="#64748b", pad_v=8, pad_h=16)  # slate color
        self.btn_change_template.clicked.connect(self.change_template_file)
        header.addWidget(self.btn_change_template, 0, Qt.AlignRight)
        header.addSpacing(15)

        self.btn_terminal = GlowButton("Terminal", pad_v=8, pad_h=16)
        self.btn_terminal.setCheckable(True)
        self.btn_terminal.clicked.connect(self._toggle_terminal)
        header.addWidget(self.btn_terminal, 0, Qt.AlignRight)
        root.addLayout(header)

        root.addWidget(self._divider())

        # File chooser row
        file_row = QHBoxLayout()
        self.btn_choose = GlowButton("Choose corrupt file", bg="#10b981")  # green
        self.btn_choose.clicked.connect(self.choose_file)
        self.edit_path = QLineEdit()
        self.edit_path.setReadOnly(True)
        self.edit_path.setPlaceholderText("No file selected")
        self._style_line_edit(self.edit_path)
        file_row.addWidget(self.btn_choose, 0)
        file_row.addSpacing(10)
        file_row.addWidget(self.edit_path, 1)
        root.addLayout(file_row)

        # Destination row (Save As)
        dest_row = QHBoxLayout()
        self.btn_dest = GlowButton("Browse destination", bg="#8b5cf6")  # violet
        self.btn_dest.clicked.connect(self.choose_dest)
        self.edit_dest = QLineEdit()
        self.edit_dest.setReadOnly(True)
        self.edit_dest.setPlaceholderText("Choose where to save the recovered video")
        self._style_line_edit(self.edit_dest)
        dest_row.addWidget(self.btn_dest, 0)
        dest_row.addSpacing(10)
        dest_row.addWidget(self.edit_dest, 1)
        root.addLayout(dest_row)

        # Inline space check bar (no popups)
        self.space_bar = QFrame()
        self.space_bar.setObjectName("spaceBar")
        self.space_bar.setStyleSheet("""
            QFrame#spaceBar {
                border: 1px solid #e5e7eb;
                background: #f8fafc;
                border-radius: 12px;
            }
        """)
        sb_layout = QHBoxLayout(self.space_bar)
        sb_layout.setContentsMargins(12, 10, 12, 10)
        sb_layout.setSpacing(10)
        self.space_icon = QLabel("ℹ️")
        self.space_icon.setStyleSheet("font-size: 16px;")
        self.space_msg = QLabel("Waiting for file and destination...")
        self.space_msg.setStyleSheet("font-size: 13px; color: #334155;")
        sb_layout.addWidget(self.space_icon, 0, Qt.AlignVCenter)
        sb_layout.addWidget(self.space_msg, 1, Qt.AlignVCenter)
        root.addWidget(self.space_bar)

        # Action row: single Recover button centered
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.btn_recover = GlowButton("Recover", bg="#3b82f6")  # blue
        self.btn_recover.setEnabled(False)
        self.btn_recover.clicked.connect(self.run_all_sequence)
        action_row.addWidget(self.btn_recover, 0)
        action_row.addStretch(1)
        root.addLayout(action_row)

        # Combined progress bar + status
        pb_row = QHBoxLayout()
        self.pb = QProgressBar()
        self.pb.setRange(0, 100)
        self.pb.setValue(0)
        self.pb.setFormat("Waiting…")
        self.pb.setTextVisible(True)
        self.pb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._style_progressbar()
        pb_row.addWidget(self.pb)
        root.addLayout(pb_row)

        # Logs panel (hidden by default, toggled by "Terminal")
        root.addWidget(self._divider())
        self._log_frame = QFrame()
        self._log_frame.setFrameShape(QFrame.NoFrame)
        v = QVBoxLayout(self._log_frame)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        log_header = QLabel("Terminal")
        log_header.setStyleSheet("font-size: 14px; font-weight: 700; color: #475569;")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.NoWrap)
        self.log.setPlaceholderText("Process output and commands will appear here…")
        self.log.setStyleSheet("""
            QTextEdit {
                background: #0b1220;
                color: #e5edf6;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 10px 10px;
                font-family: Consolas, 'Cascadia Code', monospace;
                font-size: 12px;
            }
        """)
        v.addWidget(log_header)
        v.addWidget(self.log, 1)
        root.addWidget(self._log_frame, 1)
        self._log_frame.setVisible(False)  # hidden at start

    def _apply_light_theme(self):
        self.setStyleSheet("""
            QWidget {
                background: #f6f7fb;
                color: #0f172a;
                font-size: 14px;
            }
            QLabel {
                color: #0f172a;
            }
        """)

    def _style_line_edit(self, w: QLineEdit):
        w.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 10px 12px;
                color: #0f172a;
                font-weight: 500;
            }
        """)

    def _style_progressbar(self):
        self.pb.setStyleSheet("""
            QProgressBar {
                background-color: #e5e7eb;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 2px;
                text-align: center;
                color: #0f172a;
                height: 22px;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
                border-radius: 10px;
            }
        """)

    def _divider(self):
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setFrameShadow(QFrame.Sunken)
        div.setStyleSheet("color: #e5e7eb;")
        return div

    def _toggle_terminal(self):
        self._log_frame.setVisible(self.btn_terminal.isChecked())

    # ----- File and destination selection -----
    def choose_file(self):
        file, _ = QFileDialog.getOpenFileName(
            self,
            "Choose corrupted video file",
            str(Path.home()),
            "Video files (*.mp4 *.mov *.mkv *.avi *.ts *.m4v *.*)"
        )
        if not file:
            return
        self.selected_file = Path(file).resolve()
        self.edit_path.setText(str(self.selected_file))
        # Default destination next to source, with -recovered.mp4
        default_out = self.selected_file.with_name(f"{self.selected_file.stem}-recovered.mp4")
        self.dest_path = default_out
        self.edit_dest.setText(str(self.dest_path))
        self._update_space_check()
        self._update_controls()
        self.pb.setValue(0)
        self.pb.setFormat("Ready to recover")

    def change_template_file(self):
        file, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a non-corrupt template video file",
            str(self.program_dir),
            "Video files (*.mp4 *.mov *.mkv *.avi *.ts *.m4v *.*)"
        )
        if not file:
            return
        self.good_mp4_path = Path(file).resolve()
        self._update_template_display()
        self._update_controls()

    def choose_dest(self):
        if self.selected_file:
            suggested = str(self.selected_file.with_name(f"{self.selected_file.stem}-recovered.mp4"))
        else:
            suggested = str(Path.home() / "recovered.mp4")
        out, _ = QFileDialog.getSaveFileName(
            self,
            "Save recovered video as",
            suggested,
            "MP4 Video (*.mp4)"
        )
        if not out:
            return
        self.dest_path = Path(out).resolve()
        self.edit_dest.setText(str(self.dest_path))
        self._update_space_check()
        self._update_controls()

    def _update_template_display(self):
        if self.good_mp4_path and self.good_mp4_path.exists():
            self.template_status_label.setText(f"Template: <b>{self.good_mp4_path.name}</b>")
            self.btn_change_template.setText("Change...")
            self.btn_change_template.set_bg_color("#64748b")  # slate
        else:
            self.template_status_label.setText("Template: <b>⚠️ None selected</b>")
            self.btn_change_template.setText("Select Template...")
            self.btn_change_template.set_bg_color("#f97316")  # orange

    # ----- Space check (inline message, no popups) -----
    def _update_space_check(self):
        if not (self.selected_file and self.dest_path):
            self._set_space_bar("ℹ️", "Waiting for file and destination...", "#f8fafc", "#334155", border="#e5e7eb")
            return
        try:
            size = self.selected_file.stat().st_size
        except FileNotFoundError:
            self._set_space_bar("⚠️", "Selected file no longer exists. Please reselect.", "#fff7ed", "#9a3412", border="#fdba74")
            return

        dest_dir = self.dest_path.parent
        try:
            usage = shutil.disk_usage(dest_dir)
            free = usage.free
        except FileNotFoundError:
            self._set_space_bar("⚠️", "Destination folder does not exist. Choose another location.", "#fff7ed", "#9a3412", border="#fdba74")
            return

        required = size * 4
        if free >= required:
            msg = f"Space OK on {dest_dir}. Required: {human_size(required)} | Available: {human_size(free)}"
            self._set_space_bar("✅", msg, "#ecfdf5", "#065f46", border="#6ee7b7")
        else:
            need = required - free
            msg = (f"Not enough space on {dest_dir}. Need to free {human_size(need)}.\n"
                   f"Required: {human_size(required)} | Available: {human_size(free)}")
            self._set_space_bar("⛔", msg, "#fef2f2", "#991b1b", border="#fecaca")

    def _set_space_bar(self, icon: str, text: str, bg: str, fg: str, *, border="#e5e7eb"):
        self.space_icon.setText(icon)
        self.space_msg.setText(text)
        self.space_bar.setStyleSheet(f"""
            QFrame#spaceBar {{
                border: 1px solid {border};
                background: {bg};
                border-radius: 12px;
            }}
        """)
        self.space_msg.setStyleSheet(f"font-size: 13px; color: {fg};")

    def _space_ok(self) -> bool:
        if not (self.selected_file and self.dest_path):
            return False
        try:
            size = self.selected_file.stat().st_size
            free = shutil.disk_usage(self.dest_path.parent).free
            return free >= size * 4
        except Exception:
            return False

    def _update_controls(self):
        enabled = (
            self.selected_file is not None and
            self.dest_path is not None and
            self.good_mp4_path is not None and
            self._space_ok()
        )
        self.btn_recover.setEnabled(enabled)

    # ----- Prereq check (executables, reference file) -----
    def _verify_prereqs(self) -> bool:
        missing = []
        if not self.recover_exe.exists():
            missing.append(self.recover_exe.name)
        if not self.ffmpeg_exe.exists():
            missing.append(self.ffmpeg_exe.name)
        if missing:
            self._append_log("=== Missing required files in the program folder ===")
            for m in missing:
                self._append_log(f" - {m}")
            self._append_log("Please add them and try again.")
            return False
        return True

    # ----- Flow: Analyze → Recover → Mux -----
    def run_all_sequence(self):
        if not (self.selected_file and self.dest_path and self.good_mp4_path):
            return
        if not self._space_ok():
            # Make sure user sees the reason inline
            self._update_space_check()
            return
        if not self._verify_prereqs():
            return

        # Reset state
        self.log.clear()
        self.command_1_line = None
        self.command_2_line = None
        self._mux_inputs = []
        self.btn_recover.setEnabled(False)
        self.pb.setValue(2)
        self.pb.setFormat("Analyzing…")

        # Start analyze
        analyze_cmd = [str(self.recover_exe), str(self.good_mp4_path), "--analyze"]
        self._append_log(f"[RUN] {self._pretty_cmd(analyze_cmd)}")
        self._run_process(
            analyze_cmd,
            on_line=self._parse_analyze_output,
            on_finish=self._after_analyze
        )

    def _parse_analyze_output(self, line: str):
        self._append_log(line)
        # Capture suggested commands
        rec_match = re.match(r"^\s*(recover_mp4\.exe\s+.+)$", line, flags=re.IGNORECASE)
        if rec_match:
            self.command_1_line = rec_match.group(1).strip()
        ffm_match = re.match(r"^\s*(ffmpeg\.exe\s+.+)$", line, flags=re.IGNORECASE)
        if ffm_match:
            self.command_2_line = ffm_match.group(1).strip()

    def _after_analyze(self, code: int):
        if code != 0 or not (self.command_1_line and self.command_2_line):
            self.pb.setFormat("Analyze failed (see Terminal)")
            self.pb.setValue(100)
            self.btn_recover.setEnabled(True)
            return

        # Mark analyze as 10%
        self.pb.setValue(10)
        self.pb.setFormat("Recovering…")

        # Build and run command_1 (replace corrupted_file)
        recover_cmd = self._build_recover_cmd()
        self._append_log(f"[RUN] {self._pretty_cmd(recover_cmd)}")
        self._run_process(
            recover_cmd,
            on_line=self._on_recover_line,
            on_finish=self._after_recover
        )

    def _on_recover_line(self, line: str):
        self._append_log(line)
        # Extract percentage if present, e.g., "42%" anywhere in the line
        m = re.search(r"(\d{1,3})\s*%", line)
        if m:
            pct = max(0, min(100, int(m.group(1))))
            combined = 10 + int(pct * 0.8)  # 10% analyze + 80% recover
            self.pb.setValue(min(combined, 95))
            self.pb.setFormat(f"Recovering… {pct}%")

    def _after_recover(self, code: int):
        if code != 0:
            self.pb.setValue(100)
            self.pb.setFormat("Recover failed (see Terminal)")
            self.btn_recover.setEnabled(True)
            return

        # Move to mux stage
        self.pb.setValue(max(self.pb.value(), 90))
        self.pb.setFormat("Muxing…")

        mux_cmd = self._build_mux_cmd_and_inputs()
        self._append_log(f"[RUN] {self._pretty_cmd(mux_cmd)}")
        self._run_process(
            mux_cmd,
            on_line=self._append_log,
            on_finish=self._after_mux
        )

    def _after_mux(self, code: int):
        if code == 0:
            self.pb.setValue(100)
            self.pb.setFormat("Done")
            self._append_log("[INFO] Finished.")
            self._append_log(f"[INFO] Saved: {self.dest_path}")
            # Cleanup intermediates (e.g., result.h264, result.aac)
            for p in self._mux_inputs:
                try:
                    Path(self.program_dir / p).unlink(missing_ok=True)
                    self._append_log(f"[CLEAN] Deleted {p}")
                except Exception as e:
                    self._append_log(f"[CLEAN] Could not delete {p}: {e}")
        else:
            self.pb.setValue(100)
            self.pb.setFormat("Mux failed (see Terminal)")
        self.btn_recover.setEnabled(True)

    # ----- Command builders -----
    def _build_recover_cmd(self):
        tokens = shlex.split(self.command_1_line, posix=False)
        tokens[0] = str(self.recover_exe)

        # Replace placeholder 'corrupted_file' if present; else replace second token
        replaced = False
        for i, t in enumerate(tokens[1:], start=1):
            if t.lower() == "corrupted_file":
                tokens[i] = str(self.selected_file)
                replaced = True
                break
        if not replaced and len(tokens) > 1:
            tokens[1] = str(self.selected_file)
        return tokens

    def _build_mux_cmd_and_inputs(self):
        tokens = shlex.split(self.command_2_line, posix=False)
        tokens[0] = str(self.ffmpeg_exe)

        # Force overwrite
        if "-y" not in [t.lower() for t in tokens]:
            tokens.insert(1, "-y")

        # Track inputs after -i that look like elementary streams
        inputs = []
        i = 0
        while i < len(tokens) - 1:
            if tokens[i].lower() == "-i":
                inputs.append(tokens[i + 1])
                i += 2
            else:
                i += 1
        # Filter likely intermediate streams
        exts = {".h264", ".h265", ".hevc", ".aac", ".ac3", ".mp3", ".m4a"}
        self._mux_inputs = [p for p in inputs if Path(p).suffix.lower() in exts]

        # Replace output file with chosen destination
        out_idx = None
        # Heuristic: last token that looks like a path with extension .mp4
        for j in range(len(tokens) - 1, -1, -1):
            if tokens[j].lower().endswith(".mp4"):
                out_idx = j
                break
        if out_idx is not None:
            tokens[out_idx] = str(self.dest_path)
        else:
            tokens.append(str(self.dest_path))

        return tokens

    # ----- Process runner -----
    def _run_process(self, cmd_args, on_line, on_finish):
        worker = ProcessWorker(cmd_args, cwd=str(self.program_dir))
        self._current_worker = worker
        worker.line.connect(on_line)
        worker.finished.connect(on_finish)
        worker.start()

    # ----- Helpers -----
    def _append_log(self, text: str):
        self.log.append(text)

    def _pretty_cmd(self, args):
        def q(a):
            s = str(a)
            if " " in s and not s.startswith("\""):
                return f"\"{s}\""
            return s
        return " ".join(q(a) for a in args)


def main():
    app = QApplication(sys.argv)
    w = RecoveryApp()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
