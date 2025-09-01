import os
import re
import subprocess
import requests
import glob
import sys
import base64
import time
import argparse
from urllib.parse import urlparse

# --- PHẦN 1: CẤU HÌNH ---
# Dán GitHub Personal Access Token của bạn vào đây.
# Token cần quyền 'repo' để đọc và ghi vào kho lưu trữ.
GITHUB_TOKEN = "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"

# URL mặc định của kho lưu trữ GitHub.
DEFAULT_REPO_URL = "https://github.com/linhlinh897986/Truyen_SRT"

# --- PHẦN 2: TƯƠNG TÁC VỚI GITHUB API ---

def parse_repo_url(url):
    """Phân tích URL kho lưu trữ để lấy owner và repo."""
    parsed = urlparse(url)
    path_parts = parsed.path.strip('/').split('/')
    if len(path_parts) < 2:
        raise ValueError("URL kho lưu trữ không hợp lệ.")
    owner, repo = path_parts[0], path_parts[1]
    branch = 'main'
    if len(path_parts) > 3 and path_parts[2] == 'tree':
        branch = path_parts[3]
    return owner, repo, branch

def get_all_dirs_from_repo(owner, repo, branch, token, path=''):
    """Lấy đệ quy tất cả các thư mục từ một kho lưu trữ."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    headers = {'Authorization': f'token {token}'}
    response = requests.get(api_url, headers=headers)
    response.raise_for_status()
    
    dirs = []
    for item in response.json():
        if item['type'] == 'dir':
            dirs.append(item['path'])
            dirs.extend(get_all_dirs_from_repo(owner, repo, branch, token, item['path']))
    return dirs

def upload_to_github(owner, repo, branch, target_path, file_content_bytes, commit_message, token):
    """Tải một tệp lên GitHub."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{target_path}"
    headers = {'Authorization': f'token {token}'}
    base64_content = base64.b64encode(file_content_bytes).decode('utf-8')
    
    get_response = requests.get(api_url, headers=headers, params={'ref': branch})
    sha = None
    if get_response.status_code == 200:
        sha = get_response.json()['sha']
        print(f"INFO: Tệp '{target_path}' đã tồn tại. Chuẩn bị cập nhật.")

    data = {"message": commit_message, "content": base64_content, "branch": branch}
    if sha: data["sha"] = sha
        
    put_response = requests.put(api_url, headers=headers, json=data)
    put_response.raise_for_status()
    print(f"SUCCESS: Đã tải tệp lên GitHub thành công: {target_path}")

def download_github_dir(owner, repo, branch, dir_path, output_dir, token):
    """Tải xuống nội dung của một thư mục cụ thể từ kho GitHub."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{dir_path}?ref={branch}"
    print(f"INFO: Đang lấy nội dung từ API: {api_url}")
    _download_recursive(api_url, output_dir, token)

def _download_recursive(api_url, local_path, token):
    """Hàm đệ quy để tải tệp và thư mục."""
    headers = {'Authorization': f'token {token}'}
    response = requests.get(api_url, headers=headers)
    response.raise_for_status()
    items = response.json()

    for item in items:
        item_path = os.path.join(local_path, item['name'])
        if item['type'] == 'dir':
            os.makedirs(item_path, exist_ok=True)
            _download_recursive(item['url'], item_path, token)
        elif item['type'] == 'file':
            print(f"INFO: Đang tải tệp: {item['name']}")
            file_response = requests.get(item['download_url'], headers=headers)
            file_response.raise_for_status()
            with open(item_path, 'wb') as f: f.write(file_response.content)

# --- PHẦN 3: DỊCH TỆP PHỤ ĐỀ SRT ---

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

def call_gemini_cli(prompt_text, working_dir):
    """Thực thi Gemini CLI trong một thư mục làm việc cụ thể để sử dụng ngữ cảnh."""
    command = ["gemini", "-a"]
    print(f"INFO: Đang thực thi lệnh 'gemini -a' trong thư mục '{working_dir}'...")
    try:
        result = subprocess.run(
            command, input=prompt_text, capture_output=True, text=True, 
            check=True, encoding='utf-8', shell=True, cwd=working_dir
        )
        return result.stdout
    except FileNotFoundError:
        print("\nERROR: Lệnh 'gemini' không được tìm thấy."); raise
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Lỗi khi thực thi Gemini CLI:\nStderr: {e.stderr}\nStdout: {e.stdout}"); raise

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
        translated_text = translated_texts.get(index, f"!!!LỖI DỊCH!!! {sub['text']}")
        new_content.append(f"{index}\n{sub['start']} --> {sub['end']}\n{translated_text}\n")
    return "\n".join(new_content)

# --- PHẦN 4: LOGIC CHÍNH - THIẾT LẬP TƯƠNG TÁC VÀ CHẠY NỀN ---

def select_github_directory_interactively(owner, repo, branch, token):
    """Hiển thị menu để người dùng chọn một thư mục làm việc trên GitHub."""
    print(f"Đang lấy danh sách thư mục từ kho lưu trữ '{owner}/{repo}'...")
    try:
        all_dirs = get_all_dirs_from_repo(owner, repo, branch, token)
        if not all_dirs:
            print("Không tìm thấy thư mục nào trong kho lưu trữ.")
            return None
        
        print("\nVui lòng chọn thư mục trên GitHub để làm việc (tải ngữ cảnh và lưu kết quả):")
        for i, dir_name in enumerate(all_dirs, 1):
            print(f"  [{i}] {dir_name}")
        
        while True:
            try:
                choice = int(input("Nhập lựa chọn của bạn: "))
                if 1 <= choice <= len(all_dirs):
                    return all_dirs[choice - 1]
                else:
                    print("Lựa chọn không hợp lệ, vui lòng thử lại.")
            except ValueError:
                print("Vui lòng nhập một số.")
    except Exception as e:
        print(f"Lỗi khi lấy danh sách thư mục: {e}", file=sys.stderr)
        return None

def main():
    """Hàm chính điều khiển quy trình."""
    if GITHUB_TOKEN == "YOUR_GITHUB_TOKEN_HERE":
        print("FATAL: Vui lòng dán GitHub Token của bạn vào biến GITHUB_TOKEN trong tệp script.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Chạy nền để theo dõi, dịch và tải tệp SRT. Sẽ yêu cầu chọn thư mục GitHub khi khởi động.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--work-dir', 
        required=True, 
        help="Thư mục cục bộ trên Colab để tải ngữ cảnh về và theo dõi các tệp .srt mới."
    )
    parser.add_argument(
        '--output-dir', 
        required=True, 
        help="Thư mục cục bộ trên Colab để lưu các tệp .srt đã dịch."
    )
    # Các đối số khác vẫn giữ nguyên
    args, unknown = parser.parse_known_args()

    # --- BƯỚC 1: THIẾT LẬP TƯƠNG TÁC ---
    owner, repo, branch = parse_repo_url(DEFAULT_REPO_URL)
    github_work_dir = select_github_directory_interactively(owner, repo, branch, GITHUB_TOKEN)
    if not github_work_dir:
        print("Không có thư mục nào được chọn. Kết thúc chương trình.", file=sys.stderr)
        sys.exit(1)

    # --- BƯỚC 2: CHUẨN BỊ CHẠY NỀN ---
    os.makedirs(args.work_dir, exist_ok=True)
    os.makedirs(args.output_dir, exist_ok=True)
    
    print(f"\n--- Đang tải các tệp ngữ cảnh từ GitHub: {github_work_dir} ---")
    try:
        download_github_dir(owner, repo, branch, github_work_dir, args.work_dir, GITHUB_TOKEN)
        print("--- Tải ngữ cảnh hoàn tất ---")
    except Exception as e:
        print(f"WARNING: Không thể tải tệp ngữ cảnh: {e}", file=sys.stderr)

    processed_files = set(os.path.basename(f) for f in glob.glob(os.path.join(args.work_dir, '*.srt')))
    if processed_files:
        print(f"\nINFO: Đã bỏ qua {len(processed_files)} tệp hiện có trong thư mục làm việc.")

    print("\n" + "="*50)
    print("--- BẮT ĐẦU CHẾ ĐỘ THEO DÕI NỀN ---")
    print(f"Thư mục làm việc (ngữ cảnh & file mới): {os.path.abspath(args.work_dir)}")
    print(f"Lưu bản dịch cục bộ tại:              {os.path.abspath(args.output_dir)}")
    print(f"Tải lên GitHub tại:                     '{github_work_dir}'")
    print("Nhấn Ctrl+C để dừng.")
    print("="*50 + "\n")
    
    # --- BƯỚC 3: VÒNG LẶP CHẠY NỀN ---
    try:
        while True:
            srt_files = glob.glob(os.path.join(args.work_dir, '*.srt'))
            
            for filepath in srt_files:
                filename = os.path.basename(filepath)
                
                if filename not in processed_files:
                    print(f"\n{'='*20}\nPhát hiện tệp mới: {filename}\n{'='*20}")
                    
                    try:
                        processed_files.add(filename)
                        with open(filepath, 'r', encoding='utf-8') as f: content = f.read()
                        
                        subtitles = parse_srt(content)
                        if not subtitles:
                            print(f"WARNING: Không tìm thấy phụ đề trong {filename}. Bỏ qua."); continue
                        
                        prompt = f"Dịch các dòng phụ đề sau sang ngôn ngữ 'vi'.\nChỉ trả về văn bản đã dịch. Giữ nguyên định dạng '[số] nội dung'.\n\n{format_for_gemini_prompt(subtitles)}"
                        
                        gemini_output = call_gemini_cli(prompt, working_dir=args.work_dir)
                        if not gemini_output:
                            print(f"WARNING: Gemini không trả về kết quả cho {filename}. Bỏ qua."); continue

                        translated_texts = parse_gemini_output(gemini_output)
                        if not translated_texts:
                            print(f"WARNING: Không thể phân tích kết quả từ Gemini. Bỏ qua."); continue
                        
                        new_srt_content = build_new_srt(subtitles, translated_texts)
                        base, ext = os.path.splitext(filename)
                        output_filename = f"{base}.vi{ext}"

                        local_output_path = os.path.join(args.output_dir, output_filename)
                        with open(local_output_path, 'w', encoding='utf-8') as f:
                            f.write(new_srt_content)
                        print(f"SUCCESS: Đã lưu bản dịch cục bộ tại: {local_output_path}")

                        target_path_github = f"{github_work_dir}/{output_filename}".lstrip('/')
                        commit_message = f"Dịch tệp {filename} sang vi"
                        upload_to_github(
                            owner, repo, branch, target_path_github,
                            new_srt_content.encode('utf-8'), commit_message, GITHUB_TOKEN
                        )

                    except Exception as e:
                        print(f"ERROR: Đã xảy ra lỗi khi xử lý tệp {filename}: {e}", file=sys.stderr)
            
            time.sleep(10) # Khoảng thời gian quét
            
    except KeyboardInterrupt:
        print("\n--- Đã nhận tín hiệu dừng. Kết thúc chương trình. ---")
    except Exception as e:
        print(f"\nFATAL ERROR: Đã xảy ra lỗi không mong muốn: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
