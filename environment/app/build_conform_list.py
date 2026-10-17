#!/usr/bin/env python3
"""套底工位：把剪辑表上的事件算成帧号，写一份套底清单交给回批系统，顺手记一笔流水。

这版是照着最早那条整帧率素材写的，后来陆续加进来的机位还没完全跟上来。
"""

import json
import os
import re
import sys

USAGE = "用法: build_conform_list.py <剪辑表> <素材台账> <清单输出路径> <流水路径>"
TITLE_RE = re.compile(r"^TITLE:\s*(\S.*)$")
TIMELINE_RE = re.compile(r"^TIMELINE\s+(\d+)\s*/\s*(\d+)\s+(DROP-FRAME|NON-DROP-FRAME)$")
TIMECODE_RE = re.compile(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})[:;](\d{1,2})$")


class ConformError(Exception):
    """剪辑表读不出来。"""


def read_editing_table(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    except OSError as exc:
        raise ConformError("剪辑表读不出来: %s" % exc)
    if len(lines) < 2:
        raise ConformError("剪辑表的表头不完整")
    title = TITLE_RE.match(lines[0])
    if title is None:
        raise ConformError("剪辑表第一行不是标题行")
    head = TIMELINE_RE.match(lines[1])
    if head is None:
        raise ConformError("剪辑表第二行读不出来")
    rate = float(head.group(1)) / float(head.group(2))
    events = []
    for line in lines[2:]:
        columns = line.split()
        if len(columns) < 7:
            raise ConformError("事件行读不出来: %s" % line)
        number, reel, transition, src_in, src_out, rec_in, rec_out = columns[:7]
        events.append((int(number), reel, transition, src_in, src_out, rec_in, rec_out))
    return title.group(1), rate, events


def timecode_to_frames(text, rate):
    match = TIMECODE_RE.match(text)
    if match is None:
        raise ConformError("时码读不出来: %s" % text)
    hours, minutes, seconds, frames = (int(item) for item in match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * int(round(rate)) + frames


def build_list(edl_path, ledger_path, journal_path):
    title, rate, events = read_editing_table(edl_path)
    with open(ledger_path, "r", encoding="utf-8") as handle:
        ledger = json.load(handle)
    entries = []
    journal_lines = []
    source_frames = 0
    timeline_frames = 0
    total = 0.0
    for number, reel, transition, src_in, src_out, rec_in, rec_out in events:
        if reel not in ledger:
            continue
        source_begin = timecode_to_frames(src_in, rate)
        source_end = timecode_to_frames(src_out, rate)
        span = source_end - source_begin
        if span < 0:
            span = 0
        record_begin = timecode_to_frames(rec_in, rate)
        record_end = timecode_to_frames(rec_out, rate)
        seconds = span / rate
        entry = {
            "event": number,
            "reel": reel,
            "src_in": src_in,
            "src_out": src_out,
            "src_in_frame": source_begin,
            "src_out_frame": source_end,
            "rec_in": rec_in,
            "rec_out": rec_out,
            "rec_in_frame": record_begin,
            "rec_out_frame": record_end,
            "duration_seconds": "%.6f" % seconds,
        }
        entries.append(entry)
        journal_lines.append("\t".join([
            "%03d" % number, reel, src_in, src_out, rec_in, rec_out, entry["duration_seconds"],
        ]))
        source_frames += span
        timeline_frames += record_end - record_begin
        total += seconds
    payload = {
        "title": title,
        "event_count": len(entries),
        "entries": entries,
        "source_frames": source_frames,
        "timeline_frames": timeline_frames,
        "total_seconds": "%.6f" % total,
    }
    with open(journal_path, "w", encoding="utf-8", newline="\n") as handle:
        for line in journal_lines:
            handle.write(line + "\n")
    return payload


def main(argv):
    if len(argv) != 5:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        payload = build_list(argv[1], argv[2], argv[4])
    except ConformError as exc:
        print("套底清单没能生成: %s" % exc, file=sys.stderr)
        return 1
    output_dir = os.path.dirname(os.path.abspath(argv[3]))
    os.makedirs(output_dir, exist_ok=True)
    with open(argv[3], "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
