#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
CÔNG CỤ TỰ ĐỘNG HÓA BILIBILI - SRT - GEMINI

Phiên bản hợp nhất, một lần chạy, thực thi hai luồng song song:
- Luồng 1: Tải file audio từ Bilibili.
- Luồng 2: Theo dõi, hợp nhất, dịch và upload file SRT.
"""

import os
import sys
import subprocess
import re
import requests
import glob
import base64
import time
import threading
import getpass
from urllib.parse import urlparse

# ==============================================================================
# SECTION 1: CẤU HÌNH TOÀN CỤC
# ==============================================================================
UPLOAD_DIR = "colab_upload"
INPUT_SRT_DIR = "colab_input_srt"
OUTPUT_SRT_DIR = "colab_output_srt"
FINAL_VI_DIR = "colab_final_vi_srt"
CONTEXT_DIR = "colab_context_srt"

DEFAULT_REPO_URL = "https://github.com/linhlinh897986/Truyen_SRT"
TARGET_LANGUAGE = "vi"
SRT_MERGE_GAP_MS = 700
CHECK_INTERVAL_SECONDS = 10

# ==============================================================================
# SECTION 2: CÁC HÀM LOGIC
# ==============================================================================

def run_bilibili_download(urls, download_folder):
    try:
        os.makedirs(download_folder, exist_ok=True)
        print("-" * 20)
        print(f"Bắt đầu tải audio vào thư mục: {download_folder}")
        for i, url in enumerate(urls, 1):
            print(f"🔗 [{i}/{len(urls)}] Đang xử lý: {url}")
            cmd = ["yt-dlp", "--extract-audio", "--audio-format", "mp3", "-o", os.path.join(download_folder, f"%(title)s.%(ext)s"), url]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
            for line in iter(process.stdout.readline, ''):
                if line: print(line.strip())
            process.wait()
            print("✅ Hoàn tất link." if process.returncode == 0 else "❌ Lỗi khi tải link.")
        print(f"📂 Tất cả audio đã được lưu tại: {os.path.abspath(download_folder)}")
    except Exception as e:
        print(f"❌ Lỗi nghiêm trọng khi tải xuống: {e}")

def srt_time_to_ms(time_str: str) -> int:
    try:
        h, m, s_ms = time_str.replace(",", ".").split(':')
        s, ms = s_ms.split('.')
        return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)
    except Exception:
        return 0

def merge_sentence_logic(content: str, gap_threshold_ms: int):
    blocks = [b.strip() for b in re.split(r"\n{2,}", content.replace('\r\n', '\n').strip()) if b.strip()]
    entries = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 2 and '-->' in lines[1]:
            try:
                start_str, end_str_parts = lines[1].split(' --> ')
                entries.append({'start': start_str.strip(), 'end': end_str_parts.split(' ')[0].strip(), 'text': "\n".join(lines[2:]).strip()})
            except (ValueError, IndexError): pass
    if not entries: return ""
    merged_blocks, current_fragments = [], []
    sentence_terminator_re = re.compile(r'[\.,。，?!…]+$')
    def finalize_block(fragments):
        if not fragments: return None
        full_text = "".join([f['text'] for f in fragments])
        return {'start': fragments[0]['start'], 'end': fragments[-1]['end'], 'text': full_text.strip()}
    for entry in entries:
        if not current_fragments: current_fragments.append(entry); continue
        prev_entry = current_fragments[-1]
        gap = srt_time_to_ms(entry['start']) - srt_time_to_ms(prev_entry['end'])
        if sentence_terminator_re.search(prev_entry['text']) or gap > gap_threshold_ms:
            block = finalize_block(current_fragments)
            if block: merged_blocks.append(block)
            current_fragments = [entry]
        else: current_fragments.append(entry)
    block = finalize_block(current_fragments)
    if block: merged_blocks.append(block)
    output_blocks = [f"{i}\n{b['start']} --> {b['end']}\n{b['text']}" for i, b in enumerate(merged_blocks, 1)]
    return "\n\n".join(output_blocks)

def parse_github_url(url):
    parsed = urlparse(url)
    path_parts = parsed.path.strip('/').split('/')
    if len(path_parts) < 2: raise ValueError("URL không hợp lệ.")
    return path_parts[0], path_parts[1], 'main'

def upload_to_github(owner, repo, branch, target_path, file_content_bytes, commit_message, token):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{target_path}"
    headers = {'Authorization': f'token {token}'}
    base64_content = base64.b64encode(file_content_bytes).decode('utf-8')
    get_response = requests.get(api_url, headers=headers)
    sha = get_response.json()['sha'] if get_response.status_code == 200 else None
    data = {"message": commit_message, "content": base64_content, "branch": branch}
    if sha: data["sha"] = sha
    put_response = requests.put(api_url, headers=headers, json=data)
    put_response.raise_for_status()
    print(f"✅ Đã upload thành công lên GitHub: {target_path}")

def parse_srt(content):
    content = content.strip().replace('\r\n', '\n') + '\n\n'
    matches = re.findall(r'(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n([\s\S]+?)\n\n', content, re.MULTILINE)
    return [{'index': m[0], 'start': m[1], 'end': m[2], 'text': m[3].strip()} for m in matches]

def call_gemini_cli(prompt_text, context_dir):
    command = f'gemini -a --include-directories "{context_dir}"'
    try:
        result = subprocess.run(command, input=prompt_text, capture_output=True, text=True, check=True, encoding='utf-8', shell=True)
        return result.stdout
    except FileNotFoundError: print("LỖI: Không tìm thấy lệnh 'gemini'."); raise
    except subprocess.CalledProcessError as e: print(f"Lỗi khi chạy Gemini CLI: {e.stderr}"); raise

def build_new_srt(subtitles, translated_texts):
    new_content = []
    for sub in subtitles:
        index = sub['index']
        translated_text = translated_texts.get(index, sub['text'])
        new_content.append(f"{index}\n{sub['start']} --> {sub['end']}\n{translated_text}\n")
    return "\n".join(new_content)

def parse_gemini_output(output):
    translated_texts = {}
    for line in output.strip().split('\n'):
        match = re.match(r'\[(\d+)\]\s*(.*)', line)
        if match: translated_texts[match.group(1)] = match.group(2)
    return translated_texts

def list_github_dirs_recursive(owner, repo, path, headers):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        time.sleep(0.2)
    except requests.exceptions.RequestException:
        return []
    all_dirs = []
    items = response.json()
    if not isinstance(items, list): return []
    for item in items:
        if item['type'] == 'dir':
            all_dirs.append(item['path'])
            all_dirs.extend(list_github_dirs_recursive(owner, repo, item['path'], headers))
    return all_dirs

# ==============================================================================
# SECTION 3: CÁC LUỒNG VÀ HÀM MAIN
# ==============================================================================

def select_github_dir_interactive(owner, repo, token):
    print("\nĐang lấy danh sách thư mục từ kho GitHub...")
    headers = {'Authorization': f'token {token}'}
    try:
        root_dirs = list_github_dirs_recursive(owner, repo, "", headers)
        all_dirs = ["/ (Thư mục gốc)"] + sorted(list(set(root_dirs)))
    except Exception as e:
        print(f"❌ Không thể lấy danh sách thư mục: {e}")
        return input("Vui lòng nhập thủ công tên thư mục: ")

    print("Chọn một thư mục để lưu file SRT đã dịch:")
    for i, dir_name in enumerate(all_dirs):
        print(f"  {i}: {dir_name}")
    print(f"  {len(all_dirs)}: **Tạo thư mục mới**")

    while True:
        try:
            choice = int(input(f"Lựa chọn của bạn [0-{len(all_dirs)}]: "))
            if 0 <= choice < len(all_dirs):
                selected_dir = all_dirs[choice]
                return "" if selected_dir == "/ (Thư mục gốc)" else selected_dir
            elif choice == len(all_dirs):
                new_dir = input("Nhập đường dẫn cho thư mục mới: ")
                return new_dir.strip("/")
            else:
                print("Lựa chọn không hợp lệ.")
        except ValueError:
            print("Vui lòng nhập một số.")

def downloader_thread_func(urls, download_folder):
    print("🚀 [Luồng 1] Bắt đầu tải xuống...")
    run_bilibili_download(urls, download_folder)
    print("✅ [Luồng 1] Đã tải xong tất cả các link.")

def processing_thread_func(stop_event, github_details):
    print(f"🚀 [Luồng 2] Bắt đầu theo dõi thư mục '{INPUT_SRT_DIR}'...")
    processed_files = set()
    while not stop_event.is_set():
        try:
            srt_files = glob.glob(os.path.join(INPUT_SRT_DIR, '*.srt'))
            new_files = [f for f in srt_files if os.path.basename(f) not in processed_files]
            for filepath in new_files:
                filename = os.path.basename(filepath)
                print(f"⚡ [Luồng 2] Phát hiện file mới: {filename}")
                try:
                    with open(filepath, "r", encoding="utf-8") as f: content = f.read()
                    merged_content = merge_sentence_logic(content, SRT_MERGE_GAP_MS)
                    if not merged_content.strip():
                        print(f"⚠️ [Luồng 2] Bỏ qua file rỗng: {filename}"); processed_files.add(filename); continue
                    merged_filename = os.path.splitext(filename)[0] + "_merged.srt"
                    merged_filepath = os.path.join(OUTPUT_SRT_DIR, merged_filename)
                    with open(merged_filepath, "w", encoding="utf-8") as f: f.write(merged_content)
                    print(f"👍 [Luồng 2] Đã hợp nhất câu: {merged_filename}")
                    subtitles = parse_srt(merged_content)
                    if not subtitles: print(f"⚠️ [Luồng 2] Không có khối SRT: {merged_filename}"); processed_files.add(filename); continue
                    prompt_text = "\n".join([f"[{sub['index']}] {sub['text'].replace(os.linesep, ' ')}" for sub in subtitles])
                    full_prompt = f"Dịch các dòng phụ đề sau sang ngôn ngữ '{TARGET_LANGUAGE}'. Giữ nguyên định dạng [số]:\n{prompt_text}"
                    gemini_output = call_gemini_cli(full_prompt, CONTEXT_DIR)
                    translated_texts = parse_gemini_output(gemini_output)
                    new_srt_content = build_new_srt(subtitles, translated_texts)
                    translated_filename = f"{os.path.splitext(filename)[0]}.{TARGET_LANGUAGE}.srt"
                    final_filepath = os.path.join(FINAL_VI_DIR, translated_filename)
                    context_filepath = os.path.join(CONTEXT_DIR, translated_filename)
                    with open(final_filepath, 'w', encoding='utf-8') as f: f.write(new_srt_content)
                    with open(context_filepath, 'w', encoding='utf-8') as f: f.write(new_srt_content)
                    print(f"🌐 [Luồng 2] Đã dịch xong: {translated_filename}")
                    target_path_github = f"{github_details['dir']}/{translated_filename}".lstrip('/')
                    commit_message = f"Dịch tự động: {translated_filename}"
                    upload_to_github(github_details['owner'], github_details['repo'], github_details['branch'], target_path_github, new_srt_content.encode('utf-8'), commit_message, github_details['token'])
                except Exception as e:
                    print(f"❌ [Luồng 2] Lỗi xử lý file {filename}: {e}")
                finally:
                    processed_files.add(filename)
                    print("-" * 10)
            time.sleep(CHECK_INTERVAL_SECONDS)
        except Exception as e:
            print(f"❌ [Luồng 2] Lỗi nghiêm trọng: {e}")
            time.sleep(CHECK_INTERVAL_SECONDS)
    print("🛑 [Luồng 2] Đã dừng.")

def main():
    print("=======================================================")
    print("== TOOL TỰ ĐỘNG HÓA BILIBILI - DỊCH SRT (1 LẦN CHẠY) == ")
    print("=======================================================")

    # 1. Cài đặt & tạo thư mục
    print("\n--- Bước 1: Thiết lập môi trường ---")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp", "google-generativeai"], check=True)
        for dirname in [UPLOAD_DIR, INPUT_SRT_DIR, OUTPUT_SRT_DIR, FINAL_VI_DIR, CONTEXT_DIR]:
            os.makedirs(dirname, exist_ok=True)
        print("✅ Môi trường đã sẵn sàng.")
    except Exception as e:
        print(f"❌ Lỗi khi thiết lập: {e}"); return

    # 2. Nhập thông tin
    print("\n--- Bước 2: Nhập thông tin cần thiết ---")
    bili_urls = []
    print("Nhập link video/playlist Bilibili (nhập 'done' khi xong):")
    while True:
        url = input("> ")
        if url.lower() == 'done': break
        if url.strip(): bili_urls.append(url.strip())

    github_token = getpass.getpass("Nhập GitHub Personal Access Token: ")
    repo_url = input(f"Nhập URL repo GitHub (mặc định: {DEFAULT_REPO_URL}): ") or DEFAULT_REPO_URL
    try:
        owner, repo, branch = parse_github_url(repo_url)
        github_srt_dir = select_github_dir_interactive(owner, repo, github_token)
        github_details = {
            "owner": owner, "repo": repo, "branch": branch,
            "token": github_token, "dir": github_srt_dir
        }
    except Exception as e:
        print(f"❌ Lỗi khi xử lý thông tin GitHub: {e}"); return

    # 3. Khởi chạy các luồng
    print("\n--- Bước 3: Khởi chạy các luồng ---")
    stop_event = threading.Event()
    threads = []
    if bili_urls:
        downloader = threading.Thread(target=downloader_thread_func, args=(bili_urls, UPLOAD_DIR))
        threads.append(downloader)
        downloader.start()
    processor = threading.Thread(target=processing_thread_func, args=(stop_event, github_details))
    threads.append(processor)
    processor.start()

    # 4. Chờ đợi và kết thúc
    print("\n--- Bước 4: Chương trình đang chạy ---")
    print("Nhấn CTRL+C trong terminal hoặc nút STOP trong Colab để dừng.")
    try:
        # Chờ luồng tải xuống hoàn tất (nếu nó được khởi chạy)
        if 'downloader' in locals() and downloader.is_alive():
            downloader.join()
        # Giữ chương trình chính sống trong khi luồng xử lý hoạt động
        while processor.is_alive():
            processor.join(timeout=1)
    except KeyboardInterrupt:
        print("\n🛑 Đã nhận tín hiệu dừng. Đang đóng các luồng...")
        stop_event.set()
        for t in threads:
            if t.is_alive(): t.join()
        print("✅ Tất cả các luồng đã được đóng.")

if __name__ == "__main__":
    main()
