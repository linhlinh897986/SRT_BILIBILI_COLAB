#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import subprocess
import requests
import glob
import sys
import base64
import time
from urllib.parse import urlparse
import argparse

# --- PHẦN CẤU HÌNH ---
DEFAULT_REPO_URL = "https://github.com/linhlinh897986/Truyen_SRT"
DEFAULT_LANGUAGE = "vi"

# --- PHẦN 1: TƯƠNG TÁC VỚI GITHUB API ---

def parse_github_url(url):
    parsed = urlparse(url)
    path_parts = parsed.path.strip('/').split('/')
    if len(path_parts) < 2:
        raise ValueError("URL kho lưu trữ không hợp lệ.")
    owner = path_parts[0]
    repo = path_parts[1]
    branch = 'main'
    if len(path_parts) > 3 and path_parts[2] == 'tree':
        branch = path_parts[3]
    return owner, repo, branch

def list_dirs_recursive(owner, repo, path, token):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {'Authorization': f'token {token}'}
    response = requests.get(api_url, headers=headers)
    response.raise_for_status()
    dirs = [path]
    for item in response.json():
        if item['type'] == 'dir':
            dirs.extend(list_dirs_recursive(owner, repo, item['path'], token))
    return dirs

def select_github_srt_dir(owner, repo, branch, token):
    print(f"\nĐang lấy danh sách thư mục trên repo {owner}/{repo} (nhánh {branch}) ...")
    dirs = list_dirs_recursive(owner, repo, "", token)
    for idx, d in enumerate(dirs):
        print(f"{idx}. {d or '/ (gốc)'}")
    while True:
        try:
            choice = int(input("Chọn số thứ tự thư mục chứa file SRT (mặc định 0): ") or "0")
            if 0 <= choice < len(dirs):
                return dirs[choice]
        except Exception:
            pass
        print("Lựa chọn không hợp lệ, thử lại.")

def list_srt_files_in_dir(owner, repo, dir_path, token):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{dir_path}"
    headers = {'Authorization': f'token {token}'}
    response = requests.get(api_url, headers=headers)
    response.raise_for_status()
    srt_files = []
    for item in response.json():
        if item['type'] == 'file' and item['name'].lower().endswith('.srt'):
            srt_files.append(item['path'])
    return srt_files

def download_srt_files_in_dir(owner, repo, dir_path, token):
    """Tải tất cả file .srt trong dir_path về thư mục Truyen_SRT cùng cấp tool."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "Truyen_SRT")
    os.makedirs(output_dir, exist_ok=True)
    srt_files = list_srt_files_in_dir(owner, repo, dir_path, token)
    headers = {'Authorization': f'token {token}'}
    for srt_file in srt_files:
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{srt_file}"
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        item = response.json()
        download_url = item['download_url']
        file_response = requests.get(download_url, headers=headers)
        file_response.raise_for_status()
        local_path = os.path.join(output_dir, os.path.basename(srt_file))
        with open(local_path, 'wb') as f:
            f.write(file_response.content)
        print(f"Đã tải: {local_path}")

def upload_to_github(owner, repo, branch, target_path, file_content_bytes, commit_message, token):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{target_path}"
    headers = {'Authorization': f'token {token}'}
    base64_content = base64.b64encode(file_content_bytes).decode('utf-8')
    get_response = requests.get(api_url, headers=headers)
    sha = None
    if get_response.status_code == 200:
        sha = get_response.json()['sha']
    data = {"message": commit_message, "content": base64_content, "branch": branch}
    if sha:
        data["sha"] = sha
    put_response = requests.put(api_url, headers=headers, json=data)
    put_response.raise_for_status()
    print(f"Đã upload lên GitHub: {target_path}")

# --- PHẦN 2: DỊCH TỆP PHỤ ĐỀ SRT ---

SRT_BLOCK_REGEX = re.compile(
    r'(\d+)\s*\n'
    r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n'
    r'([\s\S]+?)\n\n', re.MULTILINE
)

def parse_srt(content):
    content = content.strip().replace('\r\n', '\n') + '\n\n'
    matches = SRT_BLOCK_REGEX.findall(content)
    return [{'index': m[0], 'start': m[1], 'end': m[2], 'text': m[3].strip()} for m in matches]

def format_for_gemini_prompt(subtitles):
    lines = [f"[{sub['index']}] {sub['text'].replace(os.linesep, ' ')}" for sub in subtitles]
    return "\n".join(lines)

def call_gemini_cli(prompt_text, context_dir):
    command = f'gemini -a --include-directories "{context_dir}"'
    try:
        result = subprocess.run(
            command,
            input=prompt_text,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            shell=True
        )
        return result.stdout
    except FileNotFoundError:
        print("LỖI: Không tìm thấy lệnh 'gemini'.")
        raise
    except subprocess.CalledProcessError as e:
        print(f"Lỗi khi chạy Gemini CLI: {e.stderr}")
        raise

def parse_gemini_output(output):
    lines = output.strip().split('\n')
    translated_texts = {}
    for line in lines:
        match = re.match(r'\[(\d+)\]\s*(.*)', line)
        if match: translated_texts[match.group(1)] = match.group(2)
    return translated_texts

def build_new_srt(subtitles, translated_texts):
    new_content = []
    for sub in subtitles:
        index = sub['index']
        translated_text = translated_texts.get(index, sub['text'])
        new_content.append(f"{index}\n{sub['start']} --> {sub['end']}\n{translated_text}\n")
    return "\n".join(new_content)

# --- PHẦN 3: GIAO DIỆN DÒNG LỆNH (CLI) ---

def main():
    parser = argparse.ArgumentParser(description="CLI tool for translating SRT files and interacting with GitHub.")
    parser.add_argument('--srt-dir', type=str, required=True, help='Thư mục cục bộ chứa các file SRT cần dịch (KHÔNG phải Truyen_SRT).')
    parser.add_argument('--language', type=str, default=DEFAULT_LANGUAGE, help='Ngôn ngữ đích (ví dụ: vi, en).')
    parser.add_argument('--token', type=str, required=False, help='GitHub Personal Access Token (nên truyền qua biến môi trường cho bảo mật).')
    args = parser.parse_args()

    github_token = args.token or os.environ.get("GITHUB_TOKEN")
    if not github_token:
        print("Bạn phải truyền GitHub token qua --token hoặc biến môi trường GITHUB_TOKEN.")
        sys.exit(1)

    owner, repo, branch = parse_github_url(DEFAULT_REPO_URL)

    # --- CHỌN THƯ MỤC CHỨA FILE SRT TRÊN GITHUB ---
    srt_github_dir = select_github_srt_dir(owner, repo, branch, github_token)
    print(f"\nThư mục chứa file SRT trên GitHub: '{srt_github_dir or '/ (gốc)'}'")

    # --- TẢI TẤT CẢ FILE SRT TRONG THƯ MỤC ĐÓ VỀ Truyen_SRT (CHỈ 1 LẦN) ---
    print("Tải tất cả file .srt từ GitHub về thư mục Truyen_SRT (ngữ cảnh cho Gemini CLI)...")
    download_srt_files_in_dir(owner, repo, srt_github_dir, github_token)
    print("Đã tải xong tất cả file .srt.")

    # Đặt thư mục ngữ cảnh cho Gemini CLI
    base_dir = os.path.dirname(os.path.abspath(__file__))
    context_dir = os.path.join(base_dir, "Truyen_SRT")

    processed_files = set()
    print(f"Bắt đầu theo dõi thư mục {args.srt_dir} để dịch và upload file mới...")
    while True:
        srt_files = glob.glob(os.path.join(args.srt_dir, '*.srt'))
        for filepath in srt_files:
            base, ext = os.path.splitext(os.path.basename(filepath))
            output_filename = f"{base}.{args.language}{ext}"
            context_output_path = os.path.join(context_dir, output_filename)
            if context_output_path in processed_files or os.path.exists(context_output_path):
                continue

            print(f"Đang dịch file: {filepath}")
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            subtitles = parse_srt(content)
            if not subtitles: continue

            formatted_text = format_for_gemini_prompt(subtitles)
            prompt = f"Dịch các dòng phụ đề sau sang ngôn ngữ '{args.language}'.\n{formatted_text}"

            gemini_output = call_gemini_cli(prompt, context_dir)
            translated_texts = parse_gemini_output(gemini_output)
            new_srt_content = build_new_srt(subtitles, translated_texts)

            # Lưu file dịch vào Truyen_SRT để làm ngữ cảnh cho các lần sau
            with open(context_output_path, 'w', encoding='utf-8') as f:
                f.write(new_srt_content)
            processed_files.add(context_output_path)
            print(f"Đã dịch và lưu vào Truyen_SRT: {context_output_path}")

            # Upload lên GitHub vào đúng thư mục đã chọn
            target_path_github = f"{srt_github_dir}/{output_filename}".lstrip('/')
            commit_message = f"Dịch tệp {output_filename} sang {args.language}"
            upload_to_github(owner, repo, branch, target_path_github, new_srt_content.encode('utf-8'), commit_message, github_token)

        time.sleep(10)  # Kiểm tra file mới mỗi 10 giây

if __name__ == "__main__":
    main()