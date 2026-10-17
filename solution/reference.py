#!/usr/bin/env python3
"""按素材台账把定剪的剪辑表归算成回批给转码系统的套底清单。"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from fractions import Fraction

USAGE = "用法: build_conform_list.py <剪辑表> <素材台账> <清单输出路径> <流水路径>"
DROP = "drop-frame"
NON_DROP = "non-drop-frame"
BASES = (DROP, NON_DROP)
LEDGER_KEYS = ("fps", "timecode_base", "start_timecode", "duration_frames")
FPS_KEYS = ("numerator", "denominator")
DECLARED_RATES = (Fraction(30000, 1001), Fraction(60000, 1001))
TIMECODE_BODY = r"^(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})$"
TITLE_LINE = re.compile(r"^TITLE:\s*(\S.*)$")
TIMELINE_LINE = re.compile(r"^TIMELINE\s+(\d{1,9})\s*/\s*(\d{1,9})\s+(\S+)$")
EVENT_COLUMNS = ("事件号", "卷号", "转场", "源入点", "源出点", "记录入点", "记录出点")
JOURNAL_HEAD = "JOB"
JOURNAL_COLUMNS = 7
SECONDS_TEXT = re.compile(r"^\d+\.\d{6}$")
MICRO = 10 ** 6
DAY_HOURS = 24


class ConformError(Exception):
    """剪辑表、素材台账或套底流水不符合公开契约。"""


def nominal_rate(rate):
    """时码每秒走的整格数。"""
    return -(-rate.numerator // rate.denominator)


def drop_per_minute(nominal):
    return nominal // 15


def day_frames(nominal, basis):
    count = DAY_HOURS * 3600 * nominal
    if basis == DROP:
        count -= drop_per_minute(nominal) * (DAY_HOURS * 60 - DAY_HOURS * 6)
    return count


def read_timecode(text, basis, nominal, label, separator=None):
    match = re.match(TIMECODE_BODY, text)
    if match is None:
        raise ConformError("%s 的时码写法不对: %s" % (label, text))
    hours, minutes, seconds, mark, frames = match.groups()
    if separator is None:
        separator = ";" if basis == DROP else ":"
    if mark != separator:
        raise ConformError("%s 的时码分隔符跟基准对不上: %s" % (label, text))
    hour, minute, second, frame = (int(item) for item in (hours, minutes, seconds, frames))
    if hour > 23 or minute > 59 or second > 59:
        raise ConformError("%s 的时码越界: %s" % (label, text))
    if frame >= nominal:
        raise ConformError("%s 的帧位超出这一档的每秒格数: %s" % (label, text))
    if basis == DROP and second == 0 and minute % 10 != 0 and frame < drop_per_minute(nominal):
        raise ConformError("%s 写的是设备不会记的帧号: %s" % (label, text))
    return hour, minute, second, frame


def frames_of(text, basis, nominal, label, separator=None):
    hour, minute, second, frame = read_timecode(text, basis, nominal, label, separator)
    total = ((hour * 60 + minute) * 60 + second) * nominal + frame
    if basis == DROP:
        minutes = 60 * hour + minute
        total -= drop_per_minute(nominal) * (minutes - minutes // 10)
    return total


def timecode_of(frames, basis, nominal):
    per_minute = drop_per_minute(nominal)
    if basis == DROP:
        per_ten = 10 * 60 * nominal - 9 * per_minute
        ten, rest = divmod(frames, per_ten)
        minute = ten * 10
        if rest >= 60 * nominal:
            rest -= 60 * nominal
            minute += 1
            step = 60 * nominal - per_minute
            minute += rest // step
            rest %= step
        if minute % 10 == 0:
            second, frame = divmod(rest, nominal)
        elif rest < nominal - per_minute:
            second, frame = 0, rest + per_minute
        else:
            rest -= nominal - per_minute
            second, frame = 1 + rest // nominal, rest % nominal
        hour, minute = divmod(minute, 60)
        hour %= DAY_HOURS
    else:
        hour, rest = divmod(frames, 3600 * nominal)
        hour %= DAY_HOURS
        minute, rest = divmod(rest, 60 * nominal)
        second, frame = divmod(rest, nominal)
    mark = ";" if basis == DROP else ":"
    return "%02d:%02d:%02d%s%02d" % (hour, minute, second, mark, frame)


def seconds_text(value):
    scaled = value * MICRO
    rounded = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    digits = str(rounded).rjust(7, "0")
    return digits[:-6] + "." + digits[-6:]


def read_editing_table(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        raise ConformError("剪辑表读不出来: %s" % exc) from exc
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise ConformError("剪辑表里什么都没有")
    title_line = TITLE_LINE.match(lines[0])
    if title_line is None:
        raise ConformError("剪辑表第一行不是标题行")
    if len(lines) < 2:
        raise ConformError("剪辑表少了时间线声明那一行")
    timeline_line = TIMELINE_LINE.match(lines[1])
    if timeline_line is None:
        raise ConformError("剪辑表的时间线声明读不出来")
    top, bottom, word = timeline_line.groups()
    if word not in ("DROP-FRAME", "NON-DROP-FRAME"):
        raise ConformError("时间线的时码基准不认: %s" % word)
    basis = DROP if word == "DROP-FRAME" else NON_DROP
    rate = Fraction(int(top), int(bottom))
    if rate <= 0:
        raise ConformError("时间线的帧率要是正数")
    events = []
    seen = set()
    for line in lines[2:]:
        columns = line.split()
        if len(columns) != len(EVENT_COLUMNS):
            raise ConformError("事件行的列数不对: %s" % line)
        number, reel, transition, src_in, src_out, rec_in, rec_out = columns
        if not re.fullmatch(r"\d{3}", number) or int(number) < 1:
            raise ConformError("事件号不是三位数字: %s" % number)
        if int(number) in seen:
            raise ConformError("事件号重复: %s" % number)
        seen.add(int(number))
        if transition != "C":
            raise ConformError("事件 %s 的转场不是剪切: %s" % (number, transition))
        events.append((int(number), reel, src_in, src_out, rec_in, rec_out))
    if not events:
        raise ConformError("剪辑表里没有事件")
    return title_line.group(1), basis, rate, events


def read_reel(reel, entry):
    if not isinstance(entry, dict) or set(entry) != set(LEDGER_KEYS):
        raise ConformError("%s 的字段跟台账格式对不上" % reel)
    fps = entry["fps"]
    if not isinstance(fps, dict) or set(fps) != set(FPS_KEYS):
        raise ConformError("%s 的帧率要写成分子与分母两个字段" % reel)
    top, bottom = fps["numerator"], fps["denominator"]
    for value in (top, bottom):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConformError("%s 的帧率分子分母都是正整数" % reel)
    rate = Fraction(top, bottom)
    basis = entry["timecode_base"]
    if basis not in BASES:
        raise ConformError("%s 的时码基准不认" % reel)
    nominal = nominal_rate(rate)
    if basis == DROP and rate not in DECLARED_RATES:
        raise ConformError("%s 的帧率跟丢帧基准配不上" % reel)
    start = frames_of(entry["start_timecode"], basis, nominal, "%s 的起始时码" % reel)
    length = entry["duration_frames"]
    if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
        raise ConformError("%s 的帧数是正整数" % reel)
    return {"rate": rate, "basis": basis, "nominal": nominal, "start": start, "length": length}


def read_ledger(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ConformError("素材台账读不出来: %s" % exc) from exc
    if not isinstance(raw, dict):
        raise ConformError("素材台账顶层要是卷号到素材的对照")
    table = {}
    for reel, entry in raw.items():
        if not isinstance(reel, str) or not reel.strip():
            raise ConformError("素材台账里有空卷号")
        table[reel] = read_reel(reel, entry)
    return table


def reel_offsets(card, begin_text, end_text, number):
    total = day_frames(card["nominal"], card["basis"])
    begin = (frames_of(begin_text, card["basis"], card["nominal"], "事件 %d 的源入点" % number) - card["start"]) % total
    end = (frames_of(end_text, card["basis"], card["nominal"], "事件 %d 的源出点" % number) - card["start"]) % total
    if end <= begin:
        end += total
    return begin, end


def record_offsets(basis, nominal, begin_text, end_text, number):
    total = day_frames(nominal, basis)
    begin = frames_of(begin_text, basis, nominal, "事件 %d 的记录入点" % number)
    end = frames_of(end_text, basis, nominal, "事件 %d 的记录出点" % number)
    if end <= begin:
        end += total
    return begin, end


def read_journal(path, title, basis, nominal, ledger):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConformError("套底流水读不出来: %s" % exc) from exc
    lines = raw.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return None
    head = lines[0].split()
    if len(head) != 2 or head[0] != JOURNAL_HEAD:
        raise ConformError("套底流水的头行读不出来")
    if head[1] != title:
        raise ConformError("这本流水记的是 %s，不是这次要套的片子" % head[1])
    known = set()
    for line in lines[1:]:
        columns = line.split("\t")
        if len(columns) != JOURNAL_COLUMNS:
            raise ConformError("套底流水里有不是七列的行: %s" % line)
        number, reel, src_in, src_out, rec_in, rec_out, seconds = columns
        if not re.fullmatch(r"\d{3}", number):
            raise ConformError("套底流水里的事件号不是三位数字: %s" % line)
        card = ledger.get(reel)
        if card is None:
            raise ConformError("套底流水里的卷号在台账里查不到: %s" % reel)
        for text, side_basis, side_nominal, label in (
            (src_in, card["basis"], card["nominal"], "源入点"),
            (src_out, card["basis"], card["nominal"], "源出点"),
            (rec_in, basis, nominal, "记录入点"),
            (rec_out, basis, nominal, "记录出点"),
        ):
            frames_of(text, side_basis, side_nominal, "套底流水的%s" % label)
        if not SECONDS_TEXT.match(seconds):
            raise ConformError("套底流水里的时长不是六位小数: %s" % seconds)
        known.add(line)
    return known


def build_document(edl_path, ledger_path, journal_path):
    title, basis, rate, events = read_editing_table(edl_path)
    ledger = read_ledger(ledger_path)
    nominal = nominal_rate(rate)
    known = read_journal(journal_path, title, basis, nominal, ledger)
    entries = []
    journal_lines = []
    source_frames = 0
    timeline_frames = 0
    total = Fraction(0)
    for number, reel, src_in, src_out, rec_in, rec_out in events:
        card = ledger.get(reel)
        if card is None:
            raise ConformError("素材台账里查不到卷号 %s" % reel)
        start, end = reel_offsets(card, src_in, src_out, number)
        if end > card["length"]:
            raise ConformError("事件 %d 落在 %s 这卷素材的范围之外" % (number, reel))
        record_start, record_end = record_offsets(basis, nominal, rec_in, rec_out, number)
        source_seconds = Fraction(end - start) / card["rate"]
        record_seconds = Fraction(record_end - record_start) / rate
        if source_seconds != record_seconds:
            raise ConformError("事件 %d 的源侧与记录侧时长对不上" % number)
        entry = {
            "event": number,
            "reel": reel,
            "src_in": timecode_of(start + card["start"], card["basis"], card["nominal"]),
            "src_out": timecode_of(end + card["start"], card["basis"], card["nominal"]),
            "src_in_frame": start,
            "src_out_frame": end,
            "rec_in": timecode_of(record_start, basis, nominal),
            "rec_out": timecode_of(record_end, basis, nominal),
            "rec_in_frame": record_start,
            "rec_out_frame": record_end,
            "duration_seconds": seconds_text(source_seconds),
        }
        entries.append(entry)
        journal_lines.append("\t".join([
            "%03d" % entry["event"], entry["reel"], entry["src_in"], entry["src_out"],
            entry["rec_in"], entry["rec_out"], entry["duration_seconds"],
        ]))
        source_frames += end - start
        timeline_frames += record_end - record_start
        total += source_seconds
    payload = {
        "title": title,
        "event_count": len(entries),
        "entries": entries,
        "source_frames": source_frames,
        "timeline_frames": timeline_frames,
        "total_seconds": seconds_text(total),
    }
    document = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    pending = [line for line in journal_lines if known is None or line not in known]
    return document, pending


def publish(path, document):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, staged = tempfile.mkstemp(dir=directory, prefix=".staged-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(document)
        os.replace(staged, path)
    except OSError:
        try:
            os.unlink(staged)
        except OSError:
            pass
        raise


def record_journal(path, title, pending):
    if not pending:
        return
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        if handle.tell() == 0:
            handle.write("%s %s\n" % (JOURNAL_HEAD, title))
        for line in pending:
            handle.write(line + "\n")


def main(argv):
    if len(argv) != 5:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        document, pending = build_document(argv[1], argv[2], argv[4])
    except ConformError as exc:
        print("套底清单没能生成: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("套底清单没能生成: %s" % exc, file=sys.stderr)
        return 1
    try:
        publish(argv[3], document)
    except OSError as exc:
        print("套底清单没能写出: %s" % exc, file=sys.stderr)
        return 1
    if pending:
        title = json.loads(document)["title"]
        try:
            record_journal(argv[4], title, pending)
        except OSError as exc:
            print("套底流水没能记上: %s" % exc, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
