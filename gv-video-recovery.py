import sys
import os
import re
import shlex
import time
import shutil
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal, QPropertyAnimation, QEasingCurve, QPointF, QTimer
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QLineEdit, QProgressBar, QTextEdit, QFrame,
    QSizePolicy, QGraphicsDropShadowEffect, QGraphicsOpacityEffect
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
    def __init__(self, text="", parent=None, *, bg="#3b82f6", fg="#ffffff", radius=14, pad_v=10, pad_h=20):
        super().__init__(text, parent)
        self._bg = bg
        self._fg = fg
        self._radius = radius
        self._pad_v = pad_v
        self._pad_h = pad_h

        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        # Subtle glow that follows mouse
        self._shadow = QGraphicsDropShadowEffect(self)
        self.setGraphicsEffect(self._shadow)
        self._update_shadow_color()

        # Animate glow intensity on hover
        self._anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._anim.setDuration(180)
        self._anim.setStartValue(12)
        self._anim.setEndValue(26)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

        self._hovered = False
        self._update_style()

    def set_bg_color(self, bg: str):
        self._bg = bg
        self._update_shadow_color()
        self._update_style()

    def _hex_to_rgb(self, hex_str):
        h = hex_str.lstrip("#")
        if len(h) == 3:
            h = "".join(c*2 for c in h)
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def _update_shadow_color(self):
        try:
            r, g, b = self._hex_to_rgb(self._bg)
            self._shadow.setColor(QColor(r, g, b, 140))
            self._shadow.setBlurRadius(16)
            self._shadow.setOffset(0, 0)
        except Exception:
            self._shadow.setColor(QColor(59, 130, 246, 140))

    def _update_style(self):
        try:
            r, g, b = self._hex_to_rgb(self._bg)
            bg_rgba = f"rgba({r}, {g}, {b}, 0.15)"
            border_rgba = f"rgba({r}, {g}, {b}, 0.4)"
            hover_bg_rgba = f"rgba({r}, {g}, {b}, 0.28)"
            hover_border_rgba = f"rgba({r}, {g}, {b}, 0.65)"
            pressed_bg_rgba = f"rgba({r}, {g}, {b}, 0.45)"
        except Exception:
            bg_rgba = "rgba(59, 130, 246, 0.15)"
            border_rgba = "rgba(59, 130, 246, 0.4)"
            hover_bg_rgba = "rgba(59, 130, 246, 0.28)"
            hover_border_rgba = "rgba(59, 130, 246, 0.65)"
            pressed_bg_rgba = "rgba(59, 130, 246, 0.45)"

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_rgba};
                border: 1px solid {border_rgba};
                border-radius: {self._radius}px;
                color: {self._fg};
                padding: {self._pad_v}px {self._pad_h}px;
                font-weight: 600;
                letter-spacing: 0.2px;
            }}
            QPushButton:disabled {{
                background-color: rgba(255, 255, 255, 0.03);
                color: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.05);
            }}
            QPushButton:hover:!disabled {{
                background-color: {hover_bg_rgba};
                border: 1px solid {hover_border_rgba};
            }}
            QPushButton:pressed {{
                background-color: {pressed_bg_rgba};
            }}
        """)

    def enterEvent(self, event):
        self._hovered = True
        self._anim.setDirection(QPropertyAnimation.Forward)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._anim.setDirection(QPropertyAnimation.Backward)
        self._anim.start()
        self._shadow.setOffset(0, 0)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        if self._hovered and self.isEnabled():
            pos: QPointF = event.position()
            cx, cy = self.width() / 2.0, self.height() / 2.0
            dx = (pos.x() - cx) / max(self.width(), 1)
            dy = (pos.y() - cy) / max(self.height(), 1)
            self._shadow.setOffset(dx * 8.0, dy * 8.0)
        super().mouseMoveEvent(event)


# ---------- Watermark Stat Card with Hover Pulse Animation ----------
class StatCard(QFrame):
    def __init__(self, title, color_hex, emoji, parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        
        self.setStyleSheet(f"""
            QFrame#StatCard {{
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 12px;
            }}
        """)
        
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(12)
        self._shadow.setColor(QColor(0, 0, 0, 0))
        self._shadow.setOffset(0, 0)
        self.setGraphicsEffect(self._shadow)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        
        self.lbl_title = QLabel(title.upper())
        self.lbl_title.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.8px; background: transparent; border: none;")
        
        self.lbl_value = QLabel("0")
        self.lbl_value.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {color_hex}; background: transparent; border: none;")
        
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        
        # Large watermark emoji overlaying layout
        self.lbl_emoji = QLabel(emoji, self)
        self.lbl_emoji.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        self.opacity_effect = QGraphicsOpacityEffect(self.lbl_emoji)
        self.opacity_effect.setOpacity(0.12)
        self.lbl_emoji.setGraphicsEffect(self.opacity_effect)
        
        self.base_emoji_size = 54
        self.current_emoji_size = self.base_emoji_size
        self.target_emoji_size = self.base_emoji_size
        
        self.base_opacity = 0.12
        self.current_opacity = self.base_opacity
        self.target_opacity = self.base_opacity
        
        self.lbl_emoji.setStyleSheet(f"font-size: {self.base_emoji_size}px; background: transparent; border: none; padding: 0px;")
        
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._step_animation)
        
    def setValue(self, val):
        self.lbl_value.setText(str(val))
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        ew = 65
        eh = 65
        self.lbl_emoji.setGeometry(self.width() - ew - 5, self.height() - eh + 8, ew, eh)
        
    def enterEvent(self, event):
        self.target_emoji_size = 68
        self.target_opacity = 0.28
        self.timer.start()
        self.setStyleSheet(f"""
            QFrame#StatCard {{
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
            }}
        """)
        self._shadow.setColor(QColor(255, 255, 255, 12))
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self.target_emoji_size = self.base_emoji_size
        self.target_opacity = self.base_opacity
        self.timer.start()
        self.setStyleSheet(f"""
            QFrame#StatCard {{
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 12px;
            }}
        """)
        self._shadow.setColor(QColor(0, 0, 0, 0))
        super().leaveEvent(event)
        
    def _step_animation(self):
        size_diff = self.target_emoji_size - self.current_emoji_size
        op_diff = self.target_opacity - self.current_opacity
        
        if abs(size_diff) < 0.2 and abs(op_diff) < 0.01:
            self.current_emoji_size = self.target_emoji_size
            self.current_opacity = self.target_opacity
            self.timer.stop()
        else:
            self.current_emoji_size += size_diff * 0.18
            self.current_opacity += op_diff * 0.18
            
        self.lbl_emoji.setStyleSheet(f"font-size: {int(self.current_emoji_size)}px; background: transparent; border: none; padding: 0px;")
        self.opacity_effect.setOpacity(self.current_opacity)


# ---------- Background worker (no console windows) ----------
class ProcessWorker(QThread):
    line = Signal(str)
    finished = Signal(int)

    def __init__(self, cmd_args, cwd=None, env=None, parent=None):
        super().__init__(parent)
        self.cmd_args = cmd_args
        self.cwd = cwd
        self.env = env or os.environ.copy()
        self.proc = None
        self.is_killed = False

    def run(self):
        try:
            popen_kwargs = dict(
                cwd=self.cwd,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            # Prevent console windows on Windows
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                popen_kwargs["startupinfo"] = startupinfo
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self.proc = subprocess.Popen(self.cmd_args, **popen_kwargs)
            
            buffer = ""
            while True:
                char = self.proc.stdout.read(1)
                if not char:
                    break
                if char in ("\n", "\r"):
                    if buffer.strip():
                        self.line.emit(buffer)
                    buffer = ""
                else:
                    buffer += char
            if buffer.strip():
                self.line.emit(buffer)

            self.proc.wait()
            self.finished.emit(self.proc.returncode if not self.is_killed else -999)
        except Exception as e:
            self.line.emit(f"[ERROR] {e}")
            self.finished.emit(-1)
        finally:
            self.proc = None

    def kill_process(self):
        self.is_killed = True
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass


# ---------- Main UI ----------
class RecoveryApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gokul's Temp video recovery")
        self.resize(1000, 680)

        # Program directory (supports PyInstaller)
        if hasattr(sys, "_MEIPASS"):
            self.program_dir = Path(sys._MEIPASS).resolve()
        else:
            script_dir = Path(__file__).resolve().parent
            if (script_dir / "_internal").exists():
                self.program_dir = (script_dir / "_internal").resolve()
            else:
                self.program_dir = script_dir

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
        self._workers_history = []
        self._stage_2_temp_files = []
        self._last_monitored_size = -1
        self._last_size_change_time = 0.0
        self._size_poll_ticks = 0
        self._cached_pct = 0
        self._cached_curr_size_str = "0 B"
        self._cached_corrupt_size_str = "0 B"
        self._cached_eta_str = " | ETA: calculating..."

        # Template Auto-Switching State
        self.template_candidates: list[Path] = []
        self.current_template_idx: int = 0

        # Size Polling Timer & History
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(200)  # Check 5 times per second
        self.progress_timer.timeout.connect(self._poll_recovery_progress)
        self._intermediate_video_path = None
        self.current_stage = 1
        self.progress_history = []

        # Log buffering system (prevents UI freeze)
        self.log_queue = []
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(100)  # Flush every 100ms
        self.log_timer.timeout.connect(self._flush_log_queue)
        self.log_timer.start()
        
        # Drag and Drop & Autoscroll initial states
        self.setAcceptDrops(True)
        self._autoscroll = True

        # Build UI
        self.setObjectName("RecoveryApp")
        self._build_ui()
        
        # Try to auto-load 'good.mp4' if it exists in the program folder
        if default_good_mp4.exists():
            self.good_mp4_path = default_good_mp4
        else:
            self.good_mp4_path = None
        self._update_template_display()

        self._apply_glass_theme()
        self._update_controls()
        self._update_telemetry_gui()

    # ----- UI -----
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(14)

        # Header bar: Title left, Controls right
        header = QHBoxLayout()
        title = QLabel("Gokul's Temp video recovery")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: #f1f5f9; letter-spacing: 0.2px; background: transparent;")
        header.addWidget(title, 0, Qt.AlignLeft)
        header.addStretch(1)

        self.template_status_label = QLabel()
        self.template_status_label.setStyleSheet("font-size: 13px; color: #94a3b8; padding-right: 8px; background: transparent;")
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

        # Telemetry Row (Glassmorphic watermarked cards with springy hover animations)
        telemetry_row = QHBoxLayout()
        telemetry_row.setSpacing(14)
        
        self.card_recoveries = StatCard("Recovered Till Date", "#fbbf24", "🏆")
        self.card_duration = StatCard("Hours of Videos Recovered", "#60a5fa", "🕒")
        self.card_runs_today = StatCard("Recovered Today", "#f97316", "🔥")
        
        telemetry_row.addWidget(self.card_recoveries, 1)
        telemetry_row.addWidget(self.card_duration, 1)
        telemetry_row.addWidget(self.card_runs_today, 1)
        
        root.addLayout(telemetry_row)
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

        # Segmented progress chapters layout
        pb_row = QHBoxLayout()
        pb_row.setSpacing(16)
        
        # Chapter 1: Scan
        col1 = QVBoxLayout()
        col1.setSpacing(6)
        lbl1 = QLabel("1. Scan Template")
        lbl1.setStyleSheet("font-size: 11px; font-weight: 700; color: #94a3b8; background: transparent;")
        self.pb_scan = QProgressBar()
        self.pb_scan.setRange(0, 100)
        self.pb_scan.setValue(0)
        self.pb_scan.setTextVisible(False)
        self.pb_scan.setFixedHeight(8)
        self.pb_scan.setProperty("status", "pending")
        col1.addWidget(lbl1)
        col1.addWidget(self.pb_scan)
        pb_row.addLayout(col1)
        
        # Chapter 2: Recover
        col2 = QVBoxLayout()
        col2.setSpacing(6)
        lbl2 = QLabel("2. Recover Streams")
        lbl2.setStyleSheet("font-size: 11px; font-weight: 700; color: #94a3b8; background: transparent;")
        self.pb_recover = QProgressBar()
        self.pb_recover.setRange(0, 100)
        self.pb_recover.setValue(0)
        self.pb_recover.setTextVisible(False)
        self.pb_recover.setFixedHeight(8)
        self.pb_recover.setProperty("status", "pending")
        col2.addWidget(lbl2)
        col2.addWidget(self.pb_recover)
        pb_row.addLayout(col2)
        
        # Chapter 3: Mux
        col3 = QVBoxLayout()
        col3.setSpacing(6)
        lbl3 = QLabel("3. Mux Video")
        lbl3.setStyleSheet("font-size: 11px; font-weight: 700; color: #94a3b8; background: transparent;")
        self.pb_mux = QProgressBar()
        self.pb_mux.setRange(0, 100)
        self.pb_mux.setValue(0)
        self.pb_mux.setTextVisible(False)
        self.pb_mux.setFixedHeight(8)
        self.pb_mux.setProperty("status", "pending")
        col3.addWidget(lbl3)
        col3.addWidget(self.pb_mux)
        pb_row.addLayout(col3)
        
        # Chapter 4: Cleanup
        col4 = QVBoxLayout()
        col4.setSpacing(6)
        lbl4 = QLabel("4. Cleanup")
        lbl4.setStyleSheet("font-size: 11px; font-weight: 700; color: #94a3b8; background: transparent;")
        self.pb_clean = QProgressBar()
        self.pb_clean.setRange(0, 100)
        self.pb_clean.setValue(0)
        self.pb_clean.setTextVisible(False)
        self.pb_clean.setFixedHeight(8)
        self.pb_clean.setProperty("status", "pending")
        col4.addWidget(lbl4)
        col4.addWidget(self.pb_clean)
        pb_row.addLayout(col4)
        
        root.addLayout(pb_row)
        
        # Main Status Label
        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #cbd5e1; font-weight: 500; margin-top: 2px; background: transparent;")
        root.addWidget(self.lbl_status)

        # Logs panel (hidden by default, toggled by "Terminal")
        root.addWidget(self._divider())
        self._log_frame = QFrame()
        self._log_frame.setObjectName("logFrame")
        self._log_frame.setStyleSheet("""
            QFrame#logFrame {
                background-color: rgba(15, 23, 42, 0.45);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
        """)
        v = QVBoxLayout(self._log_frame)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)
        log_header = QLabel("Terminal")
        log_header.setStyleSheet("font-size: 14px; font-weight: 700; color: #94a3b8; background: transparent; border: none;")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.NoWrap)
        self.log.setPlaceholderText("Process output and commands will appear here…")
        self.log.verticalScrollBar().valueChanged.connect(self._on_log_scroll)
        v.addWidget(log_header)
        v.addWidget(self.log, 1)
        root.addWidget(self._log_frame, 1)
        self._log_frame.setVisible(False)  # hidden at start

        # Drag & Drop Full-Window Overlay (Initially hidden)
        self.overlay = QFrame(self)
        self.overlay.setObjectName("dropOverlay")
        self.overlay.setStyleSheet("""
            QFrame#dropOverlay {
                background-color: rgba(8, 13, 22, 0.85);
                border: 3px dashed rgba(59, 130, 246, 0.5);
                border-radius: 16px;
            }
        """)
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        
        overlay_layout = QVBoxLayout(self.overlay)
        overlay_lbl = QLabel("📥 Drop corrupted video file here")
        overlay_lbl.setStyleSheet("font-size: 24px; font-weight: 800; color: #60a5fa; background: transparent; border: none;")
        overlay_lbl.setAlignment(Qt.AlignCenter)
        overlay_layout.addWidget(overlay_lbl)
        self.overlay.hide()

    def _apply_glass_theme(self):
        self.setStyleSheet("""
            QWidget#RecoveryApp {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #080d16, stop:0.5 #0f172a, stop:1 #020617);
            }
            QWidget {
                color: #f1f5f9;
                font-family: "Segoe UI", "Inter", -apple-system, sans-serif;
                font-size: 13px;
            }
            QLabel {
                background: transparent;
            }
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 10px 12px;
                color: #f8fafc;
                font-weight: 500;
            }
            QLineEdit:focus {
                border: 1px solid rgba(59, 130, 246, 0.5);
                background-color: rgba(255, 255, 255, 0.08);
            }
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 4px;
                height: 8px;
            }
            QProgressBar[status="pending"]::chunk {
                background-color: rgba(255, 255, 255, 0.05);
            }
            QProgressBar[status="active"]::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #8b5cf6);
                border-radius: 3px;
            }
            QProgressBar[status="completed"]::chunk {
                background-color: #10b981;
                border-radius: 3px;
            }
            QTextEdit {
                background: transparent;
                color: #e2e8f0;
                border: none;
                font-family: Consolas, 'Cascadia Code', monospace;
                font-size: 12px;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(255, 255, 255, 0.02);
                width: 10px;
                margin: 0px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.25);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                border: none;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

    def _style_line_edit(self, w: QLineEdit):
        pass

    def _style_progressbar(self):
        pass

    def _divider(self):
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setFrameShadow(QFrame.Sunken)
        div.setStyleSheet("color: rgba(255, 255, 255, 0.08); background: transparent;")
        return div

    def _toggle_terminal(self):
        self._log_frame.setVisible(self.btn_terminal.isChecked())

    def _on_log_scroll(self, value):
        sb = self.log.verticalScrollBar()
        at_bottom = (sb.maximum() - value) <= 10
        self._autoscroll = at_bottom

    def _flush_log_queue(self):
        if not self.log_queue:
            return
        text = "\n".join(self.log_queue)
        self.log_queue.clear()
        self.log.append(text)
        if self._autoscroll:
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _vertical_divider(self):
        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setFrameShadow(QFrame.Sunken)
        div.setStyleSheet("color: rgba(255, 255, 255, 0.08); background: transparent; max-width: 1px;")
        return div

    # ----- Drag and Drop -----
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "overlay"):
            self.overlay.setGeometry(self.rect())

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.overlay.show()
            self.overlay.setGeometry(self.rect())
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self.overlay.hide()
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self.overlay.hide()
        urls = event.mimeData().urls()
        if urls:
            file_path = Path(urls[0].toLocalFile()).resolve()
            if file_path.is_file():
                self.selected_file = file_path
                self.edit_path.setText(str(self.selected_file))
                default_out = self.selected_file.with_name(f"{self.selected_file.stem}-recovered.mp4")
                self.dest_path = default_out
                self.edit_dest.setText(str(self.dest_path))
                self._update_space_check()
                self._update_controls()
                self._set_chapter_progress(1, 0, "Ready to recover")
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    # ----- Telemetry Probing & Loading -----
    def _get_video_duration(self, file_path: Path) -> float:
        cmd = [str(self.ffmpeg_exe), "-i", str(file_path)]
        try:
            popen_kwargs = {}
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                popen_kwargs["startupinfo"] = startupinfo
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **popen_kwargs)
            stdout, stderr = proc.communicate(timeout=5)
            m = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d{2})", stderr)
            if m:
                h, mins, s, ms = map(int, m.groups())
                return h * 3600 + mins * 60 + s + ms / 100.0
        except Exception as e:
            self._append_log(f"[WARN] Failed to get video duration: {e}")
        return 0.0

    def _update_telemetry_gui(self):
        today_str = datetime.now().strftime("%Y-%m-%d")
        total_recoveries = 0
        count_path = self.program_dir / "recovery_count.txt"
        if count_path.exists():
            try:
                total_recoveries = int(count_path.read_text().strip())
            except Exception:
                pass

        telemetry_path = self.program_dir / "recovery_telemetry.txt"
        total_seconds = 0.0
        daily_runs = 0
        if telemetry_path.exists():
            try:
                lines = telemetry_path.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    parts = line.split(" | ")
                    if len(parts) >= 3:
                        if len(parts) >= 4:
                            try:
                                total_seconds += float(parts[2])
                            except ValueError:
                                pass
                        timestamp = parts[0]
                        if timestamp.startswith(today_str):
                            daily_runs += 1
            except Exception as e:
                self._append_log(f"[TELEMETRY] Warning: Could not read telemetry logs: {e}")

        s = int(total_seconds)
        hours = s // 3600
        minutes = (s % 3600) // 60
        secs = s % 60
        if hours > 0:
            duration_str = f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            duration_str = f"{minutes}m {secs}s"
        else:
            duration_str = f"{secs}s"

        self.card_recoveries.setValue(total_recoveries)
        self.card_duration.setValue(duration_str)
        self.card_runs_today.setValue(daily_runs)

    def _set_chapter_progress(self, chapter_idx: int, value: int, status_text: str):
        self.lbl_status.setText(status_text)
        chapters = [
            (1, self.pb_scan),
            (2, self.pb_recover),
            (3, self.pb_mux),
            (4, self.pb_clean)
        ]
        for idx, pb in chapters:
            if idx < chapter_idx:
                pb.setValue(100)
                pb.setProperty("status", "completed")
            elif idx == chapter_idx:
                pb.setValue(value)
                pb.setProperty("status", "active")
            else:
                pb.setValue(0)
                pb.setProperty("status", "pending")
            pb.style().unpolish(pb)
            pb.style().polish(pb)

    def _poll_recovery_progress(self):
        # Initialize idle timer states if needed
        if not hasattr(self, "_size_poll_ticks"):
            self._size_poll_ticks = 4
        if not hasattr(self, "_cached_pct"):
            self._cached_pct = 0
        if not hasattr(self, "_cached_curr_size_str"):
            self._cached_curr_size_str = "0 B"
        if not hasattr(self, "_cached_corrupt_size_str"):
            self._cached_corrupt_size_str = "0 B"
        if not hasattr(self, "_cached_eta_str"):
            self._cached_eta_str = " | ETA: calculating..."
        if not hasattr(self, "_last_monitored_size"):
            self._last_monitored_size = -1
        if not hasattr(self, "_last_size_change_time"):
            self._last_size_change_time = time.time()

        # Check for size-change idle timeout (no timeout for Stage 1)
        if self.current_stage in (2, 3):
            self._size_poll_ticks += 1
            if self._size_poll_ticks >= 5:  # Every 1 second (5 * 200ms)
                self._size_poll_ticks = 0
                
                curr_size = 0
                if self.current_stage == 2:
                    if hasattr(self, "_stage_2_temp_files"):
                        for p in self._stage_2_temp_files:
                            if p.exists():
                                try:
                                    curr_size += p.stat().st_size
                                except Exception:
                                    pass
                elif self.current_stage == 3:
                    if self.dest_path and self.dest_path.exists():
                        try:
                            curr_size = self.dest_path.stat().st_size
                        except Exception:
                            pass

                if self._last_monitored_size == -1:
                    self._last_monitored_size = curr_size
                    self._last_size_change_time = time.time()
                elif curr_size != self._last_monitored_size:
                    self._last_monitored_size = curr_size
                    self._last_size_change_time = time.time()
                else:
                    idle_time = time.time() - self._last_size_change_time
                    if idle_time > 25.0:
                        self._append_log(f"[TIMEOUT] Stage {self.current_stage} file size has not changed for {idle_time:.1f} seconds. Terminating process.")
                        if self._current_worker:
                            self._current_worker.kill_process()
                        return

                if self.selected_file:
                    try:
                        corrupt_size = self.selected_file.stat().st_size
                        if corrupt_size > 0:
                            self._cached_pct = min(99, int((curr_size / corrupt_size) * 100))
                            self._cached_curr_size_str = human_size(curr_size)
                            self._cached_corrupt_size_str = human_size(corrupt_size)
                            
                            # Sliding-window ETA calculation (last 10 seconds)
                            now = time.time()
                            self.progress_history.append((now, self._cached_pct))
                            self.progress_history = [(t, p) for (t, p) in self.progress_history if now - t <= 10.0]
                            
                            if len(self.progress_history) >= 2:
                                t0, p0 = self.progress_history[0]
                                tN, pN = self.progress_history[-1]
                                dt = tN - t0
                                dp = pN - p0
                                if dt >= 1.0 and dp > 0:
                                    pct_per_sec = dp / dt
                                    remaining_pct = 100.0 - self._cached_pct
                                    eta_seconds = remaining_pct / pct_per_sec
                                    s = int(eta_seconds)
                                    hours = s // 3600
                                    minutes = (s % 3600) // 60
                                    secs = s % 60
                                    if hours > 0:
                                        self._cached_eta_str = f" | ETA: {hours}h {minutes}m {secs}s"
                                    elif minutes > 0:
                                        self._cached_eta_str = f" | ETA: {minutes}m {secs}s"
                                    else:
                                        self._cached_eta_str = f" | ETA: {secs}s"
                                else:
                                    self._cached_eta_str = " | ETA: calculating..."
                            else:
                                self._cached_eta_str = " | ETA: calculating..."
                    except Exception:
                        pass

        # Advance spinner
        if not hasattr(self, "spinner_idx"):
            self.spinner_idx = 0
            self._spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            
        self.spinner_idx = (self.spinner_idx + 1) % len(self._spinner_frames)
        spinner = self._spinner_frames[self.spinner_idx]
        wait_text = f" | Please wait {spinner}"

        if self.current_stage == 1:
            self._set_chapter_progress(
                1,
                5,
                f"Analyzing {self.good_mp4_path.name}… [Please wait {spinner}]"
            )
            return

        if self.current_stage == 2:
            self._set_chapter_progress(
                2, 
                self._cached_pct, 
                f"Extracting streams: {self._cached_curr_size_str} / {self._cached_corrupt_size_str} ({self._cached_pct}%){wait_text}{self._cached_eta_str}"
            )
        elif self.current_stage == 3:
            self._set_chapter_progress(
                3, 
                self._cached_pct, 
                f"Muxing streams into final MP4: {self._cached_curr_size_str} / {self._cached_corrupt_size_str} ({self._cached_pct}%){wait_text}{self._cached_eta_str}"
            )

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
        self._set_chapter_progress(1, 0, "Ready to recover")

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
            self._set_space_bar("ℹ️", "Waiting for file and destination...", "rgba(255, 255, 255, 0.03)", "#94a3b8", border="rgba(255, 255, 255, 0.08)")
            return
        try:
            size = self.selected_file.stat().st_size
        except FileNotFoundError:
            self._set_space_bar("⚠️", "Selected file no longer exists. Please reselect.", "rgba(239, 68, 68, 0.06)", "#f87171", border="rgba(239, 68, 68, 0.35)")
            return

        internal_dir = self.program_dir
        dest_dir = self.dest_path.parent

        try:
            d1 = Path(internal_dir).drive.upper()
            free_internal = shutil.disk_usage(internal_dir).free
        except Exception:
            self._set_space_bar("⚠️", "Internals folder drive check failed.", "rgba(239, 68, 68, 0.06)", "#f87171", border="rgba(239, 68, 68, 0.35)")
            return

        try:
            d2 = Path(dest_dir).drive.upper()
            free_dest = shutil.disk_usage(dest_dir).free
        except Exception:
            self._set_space_bar("⚠️", "Destination folder drive check failed.", "rgba(239, 68, 68, 0.06)", "#f87171", border="rgba(239, 68, 68, 0.35)")
            return

        if d1 == d2:
            required = size * 2
            if free_internal >= required:
                msg = f"Space OK on Shared Drive ({d1}) | Required: {human_size(required)} (2x file size) | Available: {human_size(free_internal)}"
                self._set_space_bar("✅", msg, "rgba(16, 185, 129, 0.06)", "#34d399", border="rgba(16, 185, 129, 0.35)")
            else:
                need = required - free_internal
                msg = f"Insufficient Space on Shared Drive ({d1}) | Need to free: {human_size(need)} | Req: {human_size(required)} | Avail: {human_size(free_internal)}"
                self._set_space_bar("⛔", msg, "rgba(239, 68, 68, 0.06)", "#f87171", border="rgba(239, 68, 68, 0.35)")
        else:
            ok_internal = free_internal >= size
            ok_dest = free_dest >= size
            internal_status = f"Internals ({d1}): Req {human_size(size)} / Avail {human_size(free_internal)}"
            dest_status = f"Destination ({d2}): Req {human_size(size)} / Avail {human_size(free_dest)}"
            
            if ok_internal and ok_dest:
                msg = f"Space OK | {internal_status} | {dest_status}"
                self._set_space_bar("✅", msg, "rgba(16, 185, 129, 0.06)", "#34d399", border="rgba(16, 185, 129, 0.35)")
            else:
                msg = f"Insufficient Space | {internal_status} | {dest_status}"
                self._set_space_bar("⛔", msg, "rgba(239, 68, 68, 0.06)", "#f87171", border="rgba(239, 68, 68, 0.35)")

    def _set_space_bar(self, icon: str, text: str, bg: str, fg: str, *, border="rgba(255, 255, 255, 0.08)"):
        self.space_icon.setText(icon)
        self.space_msg.setText(text)
        self.space_bar.setStyleSheet(f"""
            QFrame#spaceBar {{
                border: 1px solid {border};
                background: {bg};
                border-radius: 12px;
            }}
        """)
        self.space_msg.setStyleSheet(f"font-size: 13px; color: {fg}; background: transparent; border: none;")

    def _space_ok(self) -> bool:
        if not (self.selected_file and self.dest_path):
            return False
        try:
            size = self.selected_file.stat().st_size
            internal_dir = self.program_dir
            dest_dir = self.dest_path.parent
            d1 = Path(internal_dir).drive.upper()
            d2 = Path(dest_dir).drive.upper()
            free_internal = shutil.disk_usage(internal_dir).free
            free_dest = shutil.disk_usage(dest_dir).free
            if d1 == d2:
                return free_internal >= size * 2
            else:
                return free_internal >= size and free_dest >= size
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
        if not (self.selected_file and self.dest_path):
            return
        if not self._space_ok():
            self._update_space_check()
            return
        if not self._verify_prereqs():
            return

        self.log.clear()
        self.log_queue.clear()
        self.btn_recover.setEnabled(False)
        self._workers_history = []
        
        # Build template candidates
        self.template_candidates = []
        if self.good_mp4_path and self.good_mp4_path.exists():
            self.template_candidates.append(self.good_mp4_path.resolve())
            
        p_good = (self.program_dir / "good.mp4").resolve()
        if p_good.exists() and p_good not in self.template_candidates:
            self.template_candidates.append(p_good)
            
        p_h265 = (self.program_dir / "good-h265.mp4").resolve()
        if p_h265.exists() and p_h265 not in self.template_candidates:
            self.template_candidates.append(p_h265)

        if not self.template_candidates:
            self._append_log("[ERROR] No template files found in internals folder. Please select a template video.")
            self._set_chapter_progress(1, 0, "No templates found")
            self.btn_recover.setEnabled(True)
            return

        self.current_template_idx = 0
        self._start_recovery_with_current_template()

    def _start_recovery_with_current_template(self):
        self.good_mp4_path = self.template_candidates[self.current_template_idx]
        self._update_template_display()
        
        self.command_1_line = None
        self.command_2_line = None
        self._mux_inputs = []
        
        self._set_chapter_progress(1, 5, f"Analyzing {self.good_mp4_path.name}…")
        self._append_log("=" * 60)
        self._append_log(f"[INFO] Trying Template {self.current_template_idx + 1}/{len(self.template_candidates)}: {self.good_mp4_path.name}")
        self._append_log("=" * 60)

        self.current_stage = 1
        self._last_monitored_size = -1
        self._last_size_change_time = time.time()
        self._size_poll_ticks = 4
        self.progress_timer.start()

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
            self._set_chapter_progress(1, 50, f"Template analysis suggestions found…")
        ffm_match = re.match(r"^\s*(ffmpeg\.exe\s+.+)$", line, flags=re.IGNORECASE)
        if ffm_match:
            self.command_2_line = ffm_match.group(1).strip()
            self._set_chapter_progress(1, 80, f"FFmpeg muxing command found…")

    def _after_analyze(self, code: int):
        self.progress_timer.stop()
        self._current_worker = None
        if code != 0 or not (self.command_1_line and self.command_2_line):
            self._append_log(f"[TEMPLATE ERROR] Analyze failed for template: {self.good_mp4_path.name}")
            self._try_next_template()
            return

        self._set_chapter_progress(1, 100, "Template scanning completed.")

        # Build command_1 (replace corrupted_file)
        recover_cmd = self._build_recover_cmd()
        
        # Detect intermediate file path
        self._intermediate_video_path = None
        for token in recover_cmd:
            t_lower = token.lower()
            if t_lower.endswith(".h264") or t_lower.endswith(".h265") or t_lower.endswith(".hevc"):
                self._intermediate_video_path = (self.program_dir / token).resolve()
                break
        if not self._intermediate_video_path:
            self._intermediate_video_path = (self.program_dir / "result.h264").resolve()

        # Delete any output files in the recovery command to prevent overwrite prompts
        self._stage_2_temp_files = []
        for token in recover_cmd:
            t_lower = token.lower()
            if any(t_lower.endswith(ext) for ext in [".h264", ".h265", ".hevc", ".aac", ".wav", ".mp3", ".m4a"]):
                temp_file = (self.program_dir / token).resolve()
                self._stage_2_temp_files.append(temp_file)
                try:
                    temp_file.unlink(missing_ok=True)
                except Exception:
                    pass

        self.current_stage = 2
        self.progress_history = []
        self._last_monitored_size = -1
        self._last_size_change_time = time.time()
        self._size_poll_ticks = 4
        self._set_chapter_progress(2, 0, "Initializing recovery streams…")
        self.progress_timer.start()

        self._append_log(f"[RUN] {self._pretty_cmd(recover_cmd)}")
        self._run_process(
            recover_cmd,
            on_line=self._on_recover_line,
            on_finish=self._after_recover
        )

    def _on_recover_line(self, line: str):
        self._append_log(line)

    def _after_recover(self, code: int):
        self.progress_timer.stop()
        self._current_worker = None
        if code != 0:
            self._append_log(f"[TEMPLATE ERROR] Recovery step failed for template: {self.good_mp4_path.name}")
            self._try_next_template()
            return

        # Move to mux stage
        self._set_chapter_progress(2, 100, "Recovery stream extraction completed.")
        self._set_chapter_progress(3, 0, "Muxing video/audio streams into final MP4…")

        # Delete any existing destination file so progress starts from 0%
        try:
            self.dest_path.unlink(missing_ok=True)
        except Exception:
            pass

        self.current_stage = 3
        self.progress_history = []
        self._last_monitored_size = -1
        self._last_size_change_time = time.time()
        self._size_poll_ticks = 4
        self.progress_timer.start()

        mux_cmd = self._build_mux_cmd_and_inputs()
        self._append_log(f"[RUN] {self._pretty_cmd(mux_cmd)}")
        self._run_process(
            mux_cmd,
            on_line=self._append_log,
            on_finish=self._after_mux
        )

    def _cleanup_intermediates_only(self):
        for p in self._mux_inputs:
            try:
                Path(self.program_dir / p).unlink(missing_ok=True)
                self._append_log(f"[CLEAN] Deleted {p}")
            except Exception as e:
                self._append_log(f"[CLEAN] Could not delete {p}: {e}")

    def _cleanup_failed_attempt(self):
        for p in self._mux_inputs:
            try:
                Path(self.program_dir / p).unlink(missing_ok=True)
            except Exception:
                pass
        if self._intermediate_video_path:
            try:
                self._intermediate_video_path.unlink(missing_ok=True)
            except Exception:
                pass
        if self.current_stage >= 3:
            try:
                if self.dest_path and self.dest_path.exists():
                    self.dest_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _after_mux(self, code: int):
        self.progress_timer.stop()
        self._current_worker = None
        if code == 0:
            self._set_chapter_progress(3, 100, "Muxing completed successfully.")
            self._set_chapter_progress(4, 10, "Cleaning up intermediate temporary files…")
            self._append_log("[INFO] Finished.")
            self._append_log(f"[INFO] Saved: {self.dest_path}")
            
            # Cleanup intermediates (e.g., result.h264, result.aac)
            self._cleanup_intermediates_only()
            
            self._set_chapter_progress(4, 100, f"Done. Saved: {self.dest_path.name}")
            
            # Local Telemetry Logging
            self._log_telemetry()
            self.btn_recover.setEnabled(True)
        else:
            self._set_chapter_progress(3, 100, "Mux failed")
            self._append_log(f"[TEMPLATE ERROR] Muxing failed (FFmpeg exit code {code}) for template: {self.good_mp4_path.name}")
            self._cleanup_failed_attempt()
            self._try_next_template()

    def _try_next_template(self):
        self.progress_timer.stop()
        self.current_template_idx += 1
        if self.current_template_idx < len(self.template_candidates):
            self._append_log(f"[AUTO-SWITCH] Switching template to: {self.template_candidates[self.current_template_idx].name}")
            self._start_recovery_with_current_template()
        else:
            self._append_log("[ERROR] All available template candidates failed. Unable to recover video.")
            self._set_chapter_progress(1, 0, "Recovery failed (All templates failed)")
            
            # Reset all chapter progress bars to pending style
            self.pb_scan.setValue(0)
            self.pb_scan.setProperty("status", "pending")
            self.pb_scan.style().unpolish(self.pb_scan)
            self.pb_scan.style().polish(self.pb_scan)
            
            self.pb_recover.setValue(0)
            self.pb_recover.setProperty("status", "pending")
            self.pb_recover.style().unpolish(self.pb_recover)
            self.pb_recover.style().polish(self.pb_recover)
            
            self.pb_mux.setValue(0)
            self.pb_mux.setProperty("status", "pending")
            self.pb_mux.style().unpolish(self.pb_mux)
            self.pb_mux.style().polish(self.pb_mux)
            
            self.pb_clean.setValue(0)
            self.pb_clean.setProperty("status", "pending")
            self.pb_clean.style().unpolish(self.pb_clean)
            self.pb_clean.style().polish(self.pb_clean)
            
            self.btn_recover.setEnabled(True)

    def _log_telemetry(self):
        try:
            recovered_size = self.dest_path.stat().st_size
        except Exception:
            recovered_size = 0

        # Calculate duration of the newly recovered video
        duration = self._get_video_duration(self.dest_path)

        # 1. Update recovery_count.txt (total recoveries count)
        count_path = self.program_dir / "recovery_count.txt"
        total_recoveries = 1
        if count_path.exists():
            try:
                total_recoveries = int(count_path.read_text().strip()) + 1
            except Exception:
                pass
        try:
            count_path.write_text(str(total_recoveries))
        except Exception as e:
            self._append_log(f"[TELEMETRY] Warning: Could not update recovery_count.txt: {e}")

        # 2. Append history log to recovery_telemetry.txt
        telemetry_path = self.program_dir / "recovery_telemetry.txt"
        now_iso = datetime.now().isoformat()
        dest_str = str(self.dest_path)
        try:
            with open(telemetry_path, "a", encoding="utf-8") as f:
                f.write(f"{now_iso} | {recovered_size} | {duration:.2f} | {dest_str}\n")
        except Exception as e:
            self._append_log(f"[TELEMETRY] Warning: Could not write recovery_telemetry.txt: {e}")

        # Update stats dashboard in GUI
        self._update_telemetry_gui()

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
        self.stage_start_time = time.time()
        
        # Convert all arguments to string format
        str_cmd = [str(arg) for arg in cmd_args]
                
        worker = ProcessWorker(str_cmd, cwd=str(self.program_dir))
        self._current_worker = worker
        self._workers_history.append(worker)  # Keep reference to prevent GC crash during stage transition
        worker.line.connect(on_line)
        worker.finished.connect(on_finish)
        worker.start()

    def closeEvent(self, event):
        try:
            self.progress_timer.stop()
            self.log_timer.stop()
        except Exception:
            pass

        workers_to_kill = []
        if hasattr(self, "_current_worker") and self._current_worker:
            workers_to_kill.append(self._current_worker)
        if hasattr(self, "_workers_history"):
            for w in self._workers_history:
                if w not in workers_to_kill:
                    workers_to_kill.append(w)

        for w in workers_to_kill:
            try:
                w.kill_process()
            except Exception:
                pass
            try:
                w.quit()
                w.wait(2000)
            except Exception:
                pass

        event.accept()

    # ----- Helpers -----
    def _append_log(self, text: str):
        self.log_queue.append(text)

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
