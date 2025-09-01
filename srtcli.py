import os
import time
import re
import shutil

# ==== Cấu hình ====
INPUT_DIR = r"e:\youtube\tool\input_srt"    # Thay đổi đường dẫn thư mục input tại đây
OUTPUT_DIR = r"e:\youtube\tool\output_srt"  # Thay đổi đường dẫn thư mục output tại đây
GAP_MS = 700                                # Ngưỡng gap giữa các câu (ms)
CHECK_INTERVAL = 5                          # Thời gian kiểm tra lại (giây)

# ==== Regex & Hàm xử lý SRT ====
TIMECODE_RE = re.compile(
    r'^\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}.*$'
)
SENTENCE_TERMINATOR_RE = re.compile(r'[\.,。，?!…]+$')

def _normalize_eol(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")

def _split_blocks(content: str):
    content = _normalize_eol(content).strip()
    if not content:
        return []
    return [b.strip() for b in re.split(r"\n{2,}", content) if b.strip()]

def srt_time_to_ms(time_str: str) -> int:
    try:
        time_str_parts = re.split(r'[:,]', time_str)
        h, m, s, ms = map(int, time_str_parts)
        return h * 3600000 + m * 60000 + s * 1000 + ms
    except Exception:
        return 0

def _parse_for_sentence_merge(content: str):
    entries = []
    blocks = _split_blocks(content)
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 2 and '-->' in lines[1]:
            try:
                time_line = lines[1]
                text = "\n".join(lines[2:])
                start_str, end_str_parts = time_line.split(' --> ')
                end_str = end_str_parts.split(' ')[0]
                entries.append({
                    'start': start_str.strip(),
                    'end': end_str.strip(),
                    'text': text.strip()
                })
            except (ValueError, IndexError):
                pass
    return entries

def merge_sentence_logic(content: str, gap_threshold_ms: int):
    entries = _parse_for_sentence_merge(content)
    if not entries:
        return ""

    merged_blocks = []
    current_fragments = []

    def finalize_block(fragments):
        if not fragments:
            return None
        start_time = fragments[0]['start']
        end_time = fragments[-1]['end']
        first_text = fragments[0]['text']
        speaker_match = re.match(r'(\[SPEAKER_\d+\]:)\s*', first_text)
        speaker_tag = speaker_match.group(1) if speaker_match else ""
        full_text_parts = [re.sub(r'\[SPEAKER_\d+\]:\s*', '', f['text']) for f in fragments]
        full_text = "".join(full_text_parts)
        full_text = re.sub(r'[\.,。，?!…]{2,}', '.', full_text)
        final_text = f"{speaker_tag} {full_text}" if speaker_tag else full_text
        return {'start': start_time, 'end': end_time, 'text': final_text.strip()}

    for i, current_entry in enumerate(entries):
        if not current_fragments:
            current_fragments.append(current_entry)
            continue
        prev_entry = current_fragments[-1]
        clean_prev_text = prev_entry['text'].strip()
        ends_with_punctuation = bool(SENTENCE_TERMINATOR_RE.search(clean_prev_text))
        prev_end_ms = srt_time_to_ms(prev_entry['end'])
        current_start_ms = srt_time_to_ms(current_entry['start'])
        time_gap = current_start_ms - prev_end_ms
        gap_is_too_large = time_gap > gap_threshold_ms
        if ends_with_punctuation or gap_is_too_large:
            block = finalize_block(current_fragments)
            if block: merged_blocks.append(block)
            current_fragments = [current_entry]
        else:
            current_fragments.append(current_entry)
    block = finalize_block(current_fragments)
    if block: merged_blocks.append(block)
    output_blocks = []
    for i, block in enumerate(merged_blocks, 1):
        block_string = f"{i}\n{block['start']} --> {block['end']}\n{block['text']}"
        output_blocks.append(block_string)
    return "\n\n".join(output_blocks)

# ==== Hàm chính: Theo dõi thư mục và xử lý file mới ====
def main():
    print(f"Watching folder: {INPUT_DIR}")
    print(f"Output folder: {OUTPUT_DIR}")
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    processed = set()
    while True:
        try:
            files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith('.srt')]
            for fname in files:
                in_path = os.path.join(INPUT_DIR, fname)
                out_name = os.path.splitext(fname)[0] + "_merged.srt"
                out_path = os.path.join(OUTPUT_DIR, out_name)
                if fname in processed or os.path.exists(out_path):
                    continue
                print(f"Processing: {fname}")
                try:
                    with open(in_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    merged = merge_sentence_logic(content, GAP_MS)
                    if merged.strip():
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(merged)
                        print(f"Saved: {out_path}")
                        processed.add(fname)
                    else:
                        print(f"Skipped (empty after merge): {fname}")
                except Exception as e:
                    print(f"Error processing {fname}: {e}")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print("Stopped by user.")
            break

if __name__ == "__main__":
    main()