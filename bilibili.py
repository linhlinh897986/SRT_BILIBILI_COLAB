import sys
import os
import subprocess
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QPushButton,
    QTextEdit, QMessageBox, QProgressBar, QListWidget, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal


# ------------------- Worker -------------------
class DownloadWorker(QThread):
    message = Signal(str)
    progress_signal = Signal(int)
    finished = Signal(str)

    def __init__(self, urls, audio_only=False, custom_folder_name="", download_subs=False):
        super().__init__()
        self.urls = urls
        self.audio_only = audio_only
        self.custom_folder_name = custom_folder_name.strip()
        self.download_subs = download_subs
        self.stop_flag = False
        self.process = None

    def stop(self):
        self.stop_flag = True
        if self.process:
            self.process.terminate()
            self.message.emit("⏹ Dừng tải...")

    def run(self):
        try:
            # --------- Tạo thư mục ---------
            base_folder = "Bilibili"
            os.makedirs(base_folder, exist_ok=True)

            if self.custom_folder_name:
                download_folder = os.path.join(base_folder, self.custom_folder_name)
            else:
                date_str = datetime.now().strftime("%Y-%m-%d")
                download_folder = os.path.join(base_folder, date_str)

            os.makedirs(download_folder, exist_ok=True)
            # -------------------------------

            for i, url in enumerate(self.urls, 1):
                if self.stop_flag:
                    self.message.emit("⏹ Đã dừng tải.")
                    break

                self.message.emit(f"🔗 [{i}] Đang tải: {url}")

                # Lệnh yt-dlp cho Bilibili
                if not self.audio_only:
                    cmd = [
                        "yt-dlp", url,
                        "-f", "bv*+ba/best",   # chọn best video+audio
                        "-o", os.path.join(download_folder, f"%(title)s.%(ext)s")
                    ]
                else:
                    cmd = [
                        "yt-dlp", url,
                        "--extract-audio",
                        "--audio-format", "mp3",
                        "-o", os.path.join(download_folder, f"%(title)s.%(ext)s")
                    ]

                # Nếu bật tải phụ đề
                if self.download_subs:
                    cmd += [
                        "--write-subs",        # tải phụ đề
                        "--sub-lang", "zh-Hans",  # chỉ lấy zh-Hans
                        "--convert-subs", "srt"   # chuyển thành .srt
                    ]

                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
                )

                for line in self.process.stdout:
                    if self.stop_flag:
                        self.process.terminate()
                        break

                    line = line.strip()
                    if line:
                        self.message.emit(line)
                        if "%" in line:
                            try:
                                percent_str = line.split("%", 1)[0].split()[-1].replace(".", "").strip()
                                percent = int(percent_str)
                                if 0 <= percent <= 100:
                                    self.progress_signal.emit(percent)
                            except:
                                pass
                self.process.wait()

                if self.process.returncode == 0:
                    self.message.emit(f"✅ Hoàn tất link {i}")
                else:
                    self.message.emit(f"❌ Lỗi khi tải link {i}")

                self.progress_signal.emit(int(i / len(self.urls) * 100))

            self.finished.emit(f"📂 Video được lưu tại: {download_folder}")

        except Exception as e:
            self.message.emit(f"❌ Lỗi: {e}")


# ------------------- App -------------------
class DownloaderApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bilibili Downloader v1.1")
        self.setMinimumWidth(520)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # URL input
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("📋 Mỗi dòng 1 link video hoặc playlist Bilibili...")
        self.url_input.setFixedHeight(100)
        self.layout.addWidget(QLabel("Nhập URL video:"))
        self.layout.addWidget(self.url_input)

        # Folder name input
        self.folder_name_input = QTextEdit()
        self.folder_name_input.setPlaceholderText("Tên thư mục (tuỳ chọn)")
        self.folder_name_input.setFixedHeight(30)
        self.layout.addWidget(QLabel("Tên thư mục tải (tuỳ chọn):"))
        self.layout.addWidget(self.folder_name_input)

        # Options
        self.audio_only = QCheckBox("🎵 Chỉ tải âm thanh (MP3)")
        self.download_subs = QCheckBox("📄 Tải phụ đề zh-Hans (.srt)")
        self.layout.addWidget(self.audio_only)
        self.layout.addWidget(self.download_subs)

        # Buttons
        self.download_button = QPushButton("🚀 Bắt đầu tải")
        self.download_button.clicked.connect(self.start_download)
        self.stop_button = QPushButton("⏹ Dừng tải")
        self.stop_button.clicked.connect(self.stop_download)

        self.layout.addWidget(self.download_button)
        self.layout.addWidget(self.stop_button)

        # Progress and log
        self.progress = QProgressBar()
        self.layout.addWidget(self.progress)

        self.output_list = QListWidget()
        self.layout.addWidget(self.output_list)

        self.worker = None

    def start_download(self):
        urls = [u.strip() for u in self.url_input.toPlainText().splitlines() if u.strip()]
        if not urls:
            QMessageBox.warning(self, "Cảnh báo", "Bạn chưa nhập URL nào.")
            return

        self.output_list.clear()
        self.progress.setValue(0)

        self.worker = DownloadWorker(
            urls,
            audio_only=self.audio_only.isChecked(),
            custom_folder_name=self.folder_name_input.toPlainText(),
            download_subs=self.download_subs.isChecked()
        )

        self.worker.message.connect(self.output_list.addItem)
        self.worker.progress_signal.connect(self.progress.setValue)
        self.worker.finished.connect(self.output_list.addItem)

        self.worker.start()

    def stop_download(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.output_list.addItem("⏹ Đang dừng tiến trình...")
        else:
            QMessageBox.information(self, "Thông báo", "Hiện không có tác vụ nào đang chạy.")


# ------------------- MAIN -------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DownloaderApp()
    win.show()
    sys.exit(app.exec())
