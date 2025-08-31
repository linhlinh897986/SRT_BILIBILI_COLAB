import sys
import os
import subprocess
from datetime import datetime
import argparse

# Cố gắng import thư viện GUI, nếu không có thì vẫn chạy được CLI
try:
    from PySide6.QtWidgets import (
        QApplication, QWidget, QLabel, QVBoxLayout, QPushButton,
        QTextEdit, QMessageBox, QProgressBar, QListWidget, QCheckBox
    )
    from PySide6.QtCore import Qt, QThread, Signal
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    print("Cảnh báo: Thư viện PySide6 không được cài đặt. Chỉ có thể sử dụng chế độ dòng lệnh (CLI).")

# ==============================================================================
# SECTION 1: LOGIC TẢI XUỐNG DÙNG CHUNG
# ==============================================================================
def run_download_logic(urls, audio_only, custom_folder_name, download_subs, logger_callback):
    """
    Hàm logic chính để tải xuống, dùng chung cho cả GUI và CLI trực tiếp.
    """
    try:
        if custom_folder_name:
            # Nếu có tên tùy chỉnh, tạo thư mục con trong "Bilibili"
            base_folder = "Bilibili"
            os.makedirs(base_folder, exist_ok=True)
            download_folder = os.path.join(base_folder, custom_folder_name)
        else:
            # Mặc định, tạo thư mục theo ngày tháng trong "Bilibili"
            date_str = datetime.now().strftime("%Y-%m-%d")
            base_folder = "Bilibili"
            os.makedirs(base_folder, exist_ok=True)
            download_folder = os.path.join(base_folder, date_str)

        os.makedirs(download_folder, exist_ok=True)

        for i, url in enumerate(urls, 1):
            logger_callback(f"🔗 [{i}/{len(urls)}] Đang xử lý: {url}")

            cmd = ["yt-dlp"]
            if not audio_only:
                cmd.extend(["-f", "bv*+ba/best", url])
            else:
                cmd.extend(["--extract-audio", "--audio-format", "mp3", url])
            
            cmd.extend(["-o", os.path.join(download_folder, f"%(title)s.%(ext)s")])

            if download_subs:
                cmd.extend(["--write-subs", "--sub-lang", "zh-Hans", "--convert-subs", "srt"])

            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1
            )

            for line in iter(process.stdout.readline, ''):
                if line:
                    logger_callback(line.strip())

            process.wait()
            logger_callback("✅ Hoàn tất link." if process.returncode == 0 else "❌ Lỗi khi tải link.")

        logger_callback("-" * 20)
        logger_callback(f"📂 Tất cả đã được lưu tại: {os.path.abspath(download_folder)}")
    except Exception as e:
        logger_callback(f"❌ Lỗi nghiêm trọng: {e}")

# ==============================================================================
# SECTION 2: CÁC THÀNH PHẦN CỦA GIAO DIỆN ĐỒ HỌA (GUI)
# ==============================================================================
if GUI_AVAILABLE:
    class DownloadWorker(QThread):
        message = Signal(str)
        progress_signal = Signal(int)
        finished = Signal()

        def __init__(self, urls, audio_only, custom_folder_name, download_subs):
            super().__init__()
            self.urls = urls
            self.audio_only = audio_only
            self.custom_folder_name = custom_folder_name
            self.download_subs = download_subs

        def log_message(self, msg):
            self.message.emit(msg)
            if "%" in msg:
                try:
                    percent_str = msg.split("%", 1)[0].split()[-1]
                    percent = int(float(percent_str))
                    if 0 <= percent <= 100: self.progress_signal.emit(percent)
                except: pass

        def run(self):
            run_download_logic(self.urls, self.audio_only, self.custom_folder_name, self.download_subs, self.log_message)
            self.finished.emit()

    class DownloaderApp(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("BiliBili Downloader Tool v2.0")
            self.setMinimumWidth(520)
            self.layout = QVBoxLayout(self)
            self.url_input = QTextEdit(placeholderText="📋 Mỗi dòng 1 link video, playlist hoặc kênh Bilibili...")
            self.url_input.setFixedHeight(100)
            self.folder_name_input = QTextEdit(placeholderText="Tên thư mục (tuỳ chọn, mặc định là ngày tháng)")
            self.folder_name_input.setFixedHeight(30)
            self.audio_only = QCheckBox("🎵 Chỉ tải âm thanh (MP3)")
            self.download_subs = QCheckBox("📄 Tải phụ đề zh-Hans (.srt)")
            self.download_button = QPushButton("🚀 Bắt đầu tải")
            self.progress = QProgressBar()
            self.output_list = QListWidget()
            
            self.layout.addWidget(QLabel("Nhập URL:"))
            self.layout.addWidget(self.url_input)
            self.layout.addWidget(QLabel("Tên thư mục tải (tuỳ chọn):"))
            self.layout.addWidget(self.folder_name_input)
            self.layout.addWidget(self.audio_only)
            self.layout.addWidget(self.download_subs)
            self.layout.addWidget(self.download_button)
            self.layout.addWidget(self.progress)
            self.layout.addWidget(self.output_list)

            self.download_button.clicked.connect(self.start_download)
            self.worker = None

        def start_download(self):
            urls = [u.strip() for u in self.url_input.toPlainText().splitlines() if u.strip()]
            if not urls:
                QMessageBox.warning(self, "Cảnh báo", "Bạn chưa nhập URL nào.")
                return

            self.output_list.clear()
            self.progress.setValue(0)
            self.download_button.setEnabled(False)

            self.worker = DownloadWorker(
                urls, self.audio_only.isChecked(),
                self.folder_name_input.toPlainText().strip(), self.download_subs.isChecked()
            )
            self.worker.message.connect(lambda msg: (self.output_list.addItem(msg), self.output_list.scrollToBottom()))
            self.worker.progress_signal.connect(self.progress.setValue)
            self.worker.finished.connect(lambda: self.download_button.setEnabled(True))
            self.worker.start()

# ==============================================================================
# SECTION 3: CÁC HÀM XỬ LÝ CHO DÒNG LỆNH (CLI)
# ==============================================================================
def handle_cli_download(args):
    """Xử lý cho chế độ CLI trực tiếp"""
    print("--- Chế độ tải trực tiếp (CLI) ---")
    audio_only = args.mp3
    run_download_logic(args.urls, audio_only, args.output, args.subs, print)

def handle_cli_runbg(args):
    """Xử lý cho chế độ chạy nền (background)"""
    print("--- Chế độ chạy nền (CLI Background) ---")
    actual_command = args.command[1:]
    if not actual_command:
        print("Lỗi: Không có lệnh nào được chỉ định sau '--'.")
        sys.exit(1)

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        script_dir = os.getcwd()
        
    output_path = os.path.join(script_dir, args.output)
    os.makedirs(output_path, exist_ok=True)
    
    final_command = [arg.replace('OUTPUT_DIR', output_path) for arg in actual_command]
    log_file_path = os.path.join(script_dir, 'background_task.log')
    
    print(f"🚀 Bắt đầu chạy lệnh trong nền...")
    print(f"📂 Thư mục output: {output_path}")
    print(f"📝 Ghi log vào file: {log_file_path}")
    
    with open(log_file_path, 'w') as log_file:
        subprocess.Popen(final_command, stdout=log_file, stderr=subprocess.STDOUT)
        
    print("✅ Lệnh đã được khởi chạy. Bạn có thể chạy các ô khác.")

def start_gui():
    """Khởi chạy ứng dụng GUI"""
    if not GUI_AVAILABLE:
        print("Lỗi: Không thể khởi chạy GUI vì PySide6 chưa được cài đặt.")
        print("Hãy cài đặt bằng lệnh: pip install PySide6")
        sys.exit(1)
    app = QApplication(sys.argv)
    win = DownloaderApp()
    win.show()
    sys.exit(app.exec())

# ==============================================================================
# SECTION 4: ĐIỂM KHỞI ĐẦU CỦA CHƯƠNG TRÌNH
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="BiliBili Downloader Tool - Một công cụ đa năng.")
    subparsers = parser.add_subparsers(dest='mode', help='Các chế độ hoạt động')

    # --- Parser cho chế độ GUI (tùy chọn, vì nó là mặc định) ---
    subparsers.add_parser('gui', help='Chạy giao diện đồ họa.')

    # --- Parser cho chế độ Tải trực tiếp ---
    p_download = subparsers.add_parser('download', help='Tải trực tiếp từ dòng lệnh và xem tiến trình.')
    p_download.add_argument('urls', nargs='+', help='Một hoặc nhiều URL để tải.')
    format_group = p_download.add_mutually_exclusive_group()
    format_group.add_argument('--mp3', action='store_true', help='Chỉ tải âm thanh (MP3).')
    format_group.add_argument('--mp4', action='store_true', help='Tải video (MP4). (Mặc định)')
    p_download.add_argument('-o', '--output', type=str, default="", help='Tên thư mục tùy chỉnh.')
    p_download.add_argument('--subs', action='store_true', help='Tải xuống phụ đề.')

    # --- Parser cho chế độ Chạy nền ---
    p_runbg = subparsers.add_parser('runbg', help='Chạy một lệnh tải trong nền (cho Colab).')
    p_runbg.add_argument('-o', '--output', required=True, help='Tên thư mục tùy chỉnh để tạo.')
    p_runbg.add_argument('command', nargs=argparse.REMAINDER, help="Lệnh cần chạy, đặt sau dấu '--'.")
    
    # Nếu không có đối số nào được truyền, chạy GUI
    if len(sys.argv) == 1:
        start_gui()
        return

    args = parser.parse_args()
    if args.mode == 'download':
        handle_cli_download(args)
    elif args.mode == 'runbg':
        handle_cli_runbg(args)
    elif args.mode == 'gui':
        start_gui()
    else: # Mặc định nếu không rõ lệnh
        parser.print_help()


if __name__ == "__main__":
    main()