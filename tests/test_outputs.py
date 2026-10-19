"""行为验收：套底机房的剪辑表归算与回批清单契约。"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

APP = Path(os.environ.get("TASK_APP", "/app/build_conform_list.py"))
DATA = Path(os.environ.get("TASK_DATA_DIR", "/data"))
CALL_TIMEOUT_SEC = 60

DROP = "drop-frame"
NON_DROP = "non-drop-frame"

LEDGER_NAME = "shoot-ledger-0707-0709.json"
CUT_A = "0707A-promo-cut2.edl"
ONLINE_B = "0708B-promo-online.edl"
TRAILER_C = "0709C-trailer.edl"
JOURNAL_A = "conform-journal-0707A.tsv"

MAIN = "C012K004_260702_R1A"
LATE = "D088M015_260704_R2B"
NIGHT = "F310H014_260303_R1"
HI = "H004P021_260710_R1C"
DROP_REEL = "A017C012_260712_R1AB"
FLAT_REEL = "B039D017_251122_R2C"
PULL_REEL = "D221F009_260218_R3"
PAL_REEL = "G002K006_260125_R1AC"

DROP_TABLE = "30000/1001"
HI_TABLE = "60000/1001"
FLAT24_TABLE = "24/1"


def _reel(numerator, denominator, basis, start, length):
    return {
        "fps": {"numerator": numerator, "denominator": denominator},
        "timecode_base": basis,
        "start_timecode": start,
        "duration_frames": length,
    }


def _flat_reel(basis, start, length):
    return _reel(24, 1, basis, start, length)


def _drop_reel(start, length):
    return _reel(30000, 1001, DROP, start, length)


def _table(title, rate, basis, rows):
    document = ["TITLE: %s" % title, "TIMELINE %s %s" % (rate, basis)]
    document.extend("%s  %s  %s  %s  %s  %s  %s" % row for row in rows)
    return "\n".join(document) + "\n"


def _place(root, name, text):
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def _case_tag(tag):
    return "case-" + hashlib.sha256(tag.encode("utf-8")).hexdigest()[:12]


def _call(tmp_path, tag, edl_path, ledger_path, journal=None, out=None):
    case = _case_tag(tag)
    out = out if out is not None else tmp_path / (case + "-out") / "conform-list.json"
    journal_path = journal if journal is not None else tmp_path / (case + "-journal.tsv")
    result = subprocess.run(
        [sys.executable, str(APP), str(edl_path), str(ledger_path), str(out), str(journal_path)],
        capture_output=True,
        text=True,
        timeout=CALL_TIMEOUT_SEC,
    )
    return result, out, journal_path


def _run(tmp_path, tag, table, ledger, journal=None, out=None):
    case = _case_tag(tag)
    edl_path = _place(tmp_path, case + ".edl", table)
    ledger_path = _place(tmp_path, case + "-ledger.json", json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
    return _call(tmp_path, case, edl_path, ledger_path, journal, out=out)


def _shipped(tmp_path, tag, table_name, journal=None):
    return _call(tmp_path, tag, DATA / table_name, DATA / LEDGER_NAME, journal)


def _list_of(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _single_row(number, reel, src_in, src_out, rec_in, rec_out):
    return (number, reel, "C", src_in, src_out, rec_in, rec_out)


def test_drop_frame_minute_boundary_skips_two_frame_numbers(tmp_path):
    """题面「台账里的时码是设备按 SMPTE 惯例记的丢帧时码」：整分钟那一跳上被跳过的两格不算帧号。"""
    ledger = {MAIN: _drop_reel("01:00:00;00", 200000)}
    table = _table(
        "EDGE-MINUTE",
        DROP_TABLE,
        "DROP-FRAME",
        [_single_row("001", MAIN, "01:06:59;29", "01:07:00;02", "01:00:00;00", "01:00:00;01")],
    )
    result, out, _journal = _run(tmp_path, "case-01", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["src_in_frame"] == 12587
    assert entry["src_out_frame"] == 12588


def test_drop_frame_tenth_minute_keeps_consecutive_frame_numbers(tmp_path):
    """题面「时码一秒钟走三十格」：每到第十分钟那一跳不跳，帧号仍然连着数。"""
    ledger = {MAIN: _drop_reel("01:00:00;00", 200000)}
    table = _table(
        "EDGE-TENMIN",
        DROP_TABLE,
        "DROP-FRAME",
        [_single_row("001", MAIN, "01:09:59;29", "01:10:00;00", "01:00:00;00", "01:00:00;01")],
    )
    result, out, _journal = _run(tmp_path, "case-02", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["src_in_frame"] == 17981
    assert entry["src_out_frame"] == 17982


def test_sixty_hertz_basis_counts_dropped_frames_for_sixty(tmp_path):
    """题面「丢帧基准是 29.97 与 59.94 两档专用」：59.94 这一档的跳法跟 29.97 不是同一个数。"""
    ledger = {HI: _reel(60000, 1001, DROP, "01:00:00;00", 200000)}
    table = _table(
        "EDGE-5994",
        HI_TABLE,
        "DROP-FRAME",
        [_single_row("001", HI, "01:00:59;59", "01:01:00;04", "01:00:00;00", "01:00:00;01")],
    )
    result, out, _journal = _run(tmp_path, "case-03", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["src_in_frame"] == 3599
    assert entry["src_out_frame"] == 3600
    assert entry["rec_in_frame"] == 215784
    assert entry["rec_out_frame"] == 215785


def test_cross_midnight_event_keeps_counting_source_frames(tmp_path):
    """题面「这种跨夜事件的源出点比源入点小」：跨夜那一条的源侧帧号接着往前数。"""
    ledger = {NIGHT: _drop_reel("23:58:00;02", 12000)}
    table = _table(
        "EDGE-NIGHT",
        DROP_TABLE,
        "DROP-FRAME",
        [_single_row("001", NIGHT, "23:59:58;02", "00:00:12;02", "01:00:00;00", "01:00:14;00")],
    )
    result, out, _journal = _run(tmp_path, "case-04", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["src_in_frame"] == 3538
    assert entry["src_out_frame"] == 3958
    assert entry["duration_seconds"] == "14.014000"


def test_frame_numbers_accumulate_dropped_frames_over_many_minutes(tmp_path):
    """题面「30000/1001 这档素材，时码一秒钟走三十格」：分钟数攒起来以后帧号也要跟着少掉。"""
    ledger = {LATE: _drop_reel("05:00:00;00", 200000)}
    table = _table(
        "EDGE-MINUTES",
        DROP_TABLE,
        "DROP-FRAME",
        [_single_row("001", LATE, "05:12:34;17", "05:13:14;19", "01:00:00;00", "01:00:40;00")],
    )
    result, out, _journal = _run(tmp_path, "case-05", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["src_in_frame"] == 22615
    assert entry["src_out_frame"] == 23815


def test_mixed_basis_list_converts_each_reel_in_its_own_base(tmp_path):
    """题面「素材的时间码按这一卷自己的基准读」：一份清单里丢帧卷与整帧卷各按各的基准数。"""
    ledger = {DROP_REEL: _drop_reel("01:00:00;00", 200000), FLAT_REEL: _drop_reel("04:00:00:00", 200000)}
    table = _table(
        "MIX-BASIS",
        DROP_TABLE,
        "DROP-FRAME",
        [
            _single_row("001", DROP_REEL, "01:10:00;02", "01:10:30;02", "01:00:00;00", "01:00:30;00"),
            _single_row("002", FLAT_REEL, "04:05:00:00", "04:05:30:00", "01:00:30;00", "01:01:00;02"),
        ],
    )
    ledger[FLAT_REEL]["timecode_base"] = NON_DROP
    result, out, _journal = _run(tmp_path, "case-06", table, ledger)
    assert result.returncode == 0, result.stderr
    entries = _list_of(out)["entries"]
    assert [entry["src_in_frame"] for entry in entries] == [17984, 9000]
    assert [entry["src_out_frame"] for entry in entries] == [18884, 9900]
    assert [entry["duration_seconds"] for entry in entries] == ["30.030000", "30.030000"]


def test_pulled_source_duration_follows_its_own_frame_rate(tmp_path):
    """题面「`duration_seconds` 是这条事件的真实时长，拿素材自己的帧率」：拉片素材按它那档帧率折秒。"""
    ledger = {PULL_REEL: _reel(24000, 1001, NON_DROP, "03:00:00:00", 240000)}
    table = _table(
        "PULL-RATE",
        DROP_TABLE,
        "DROP-FRAME",
        [_single_row("001", PULL_REEL, "03:02:30:00", "03:02:40:00", "01:00:00;00", "01:00:10;00")],
    )
    result, out, _journal = _run(tmp_path, "case-07", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["src_in_frame"] == 3600
    assert entry["src_out_frame"] == 3840
    assert entry["rec_out_frame"] - entry["rec_in_frame"] == 300
    assert entry["duration_seconds"] == "10.010000"


def test_twentyfour_source_on_drop_timeline_bridges_through_elapsed_time(tmp_path):
    """题面「源侧按素材帧率折出来的秒数，跟记录侧按时间线帧率折出来的秒数得一样」：24 帧素材落到丢帧时间线。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "09:00:00:00", 180000)}
    table = _table(
        "FLAT-24-ON-29",
        DROP_TABLE,
        "DROP-FRAME",
        [_single_row("001", MAIN, "09:35:00:00", "09:35:41:17", "01:00:00;00", "01:00:41;20")],
    )
    result, out, _journal = _run(tmp_path, "case-08", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["src_in_frame"] == 50400
    assert entry["src_out_frame"] == 51401
    assert entry["rec_out_frame"] - entry["rec_in_frame"] == 1250
    assert entry["duration_seconds"] == "41.708333"


def test_twentyfive_source_on_twentyfour_timeline_bridges_through_elapsed_time(tmp_path):
    """题面「素材侧走过 125 帧，记录侧走过 120 帧」：25 帧素材落到 24 帧时间线上。"""
    ledger = {PAL_REEL: _reel(25, 1, NON_DROP, "02:00:00:00", 90000)}
    table = _table(
        "PAL-25-ON-24",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", PAL_REEL, "02:20:00:00", "02:20:05:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-09", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["src_in_frame"] == 30000
    assert entry["src_out_frame"] == 30125
    assert entry["rec_in_frame"] == 172800
    assert entry["rec_out_frame"] == 172920
    assert entry["duration_seconds"] == "5.000000"


def test_total_seconds_sums_exact_durations_before_rounding(tmp_path):
    """题面「长清单上先把每条时长掐到六位再加，末尾会和账差出来」：合计按没掐位的时长累加。"""
    result, out, _journal = _shipped(tmp_path, "case-10", ONLINE_B)
    assert result.returncode == 0, result.stderr
    payload = _list_of(out)
    assert payload["total_seconds"] == "205.838967"
    assert payload["source_frames"] == 5721
    assert payload["timeline_frames"] == 6169


def test_shipped_online_sample_matches_expected_entries(tmp_path):
    """题面「素材侧走过 125 帧，记录侧走过 120 帧」：随题交付的混合帧率剪辑表整套归算结果逐项对得上。"""
    result, out, _journal = _shipped(tmp_path, "case-11", ONLINE_B)
    assert result.returncode == 0, result.stderr
    payload = _list_of(out)
    assert payload["title"] == "0708B-PROMO-ONLINE"
    assert payload["event_count"] == 8
    assert [
        (entry["reel"], entry["src_in_frame"], entry["src_out_frame"], entry["duration_seconds"])
        for entry in payload["entries"]
    ] == [
        ("A017C012_260712_R1AB", 21510, 23012, "50.116733"),
        ("F310H014_260303_R1", 3538, 3958, "14.014000"),
        ("F310H014_260303_R1", 3958, 4498, "18.018000"),
        ("E008B021_251105_R1AA", 14760, 14880, "2.002000"),
        ("D221F009_260218_R3", 3600, 3840, "10.010000"),
        ("C104E003_260411_R1AD", 50400, 51401, "41.708333"),
        ("A017C012_260712_R1AB", 80100, 80997, "29.929900"),
        ("B039D017_251122_R2C", 18000, 19001, "40.040000"),
    ]


def test_rejects_events_whose_two_sides_disagree_in_elapsed_time(tmp_path):
    """题面「源侧折出来的秒数跟记录侧折出来的秒数对不上」：两侧差一帧的剪辑表整份退回。"""
    ledger = {PAL_REEL: _reel(25, 1, NON_DROP, "02:00:00:00", 90000)}
    table = _table(
        "PAL-25-BAD",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", PAL_REEL, "02:20:00:00", "02:20:05:00", "02:00:00:00", "02:00:05:01")],
    )
    out = tmp_path / "mismatch-out" / "conform-list.json"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"OLD-LIST\n")
    result, out_path, _journal = _run(tmp_path, "case-12", table, ledger, out=out)
    assert result.returncode != 0
    assert out_path.read_bytes() == b"OLD-LIST\n"


def test_shipped_cut_a_sample_matches_expected_entries(tmp_path):
    """题面「`source_frames` 是所有事件源侧帧数的合计」：随题交付的整帧率短片整套归算结果对得上。"""
    result, out, _journal = _shipped(tmp_path, "case-13", CUT_A)
    assert result.returncode == 0, result.stderr
    payload = _list_of(out)
    assert payload["title"] == "0707A-PROMO-CUT2"
    assert [entry["src_out_frame"] - entry["src_in_frame"] for entry in payload["entries"]] == [132, 60, 216, 96, 264]
    assert [entry["rec_out_frame"] - entry["rec_in_frame"] for entry in payload["entries"]] == [132, 60, 216, 96, 264]
    assert payload["total_seconds"] == "32.000000"


def test_list_is_one_compact_line_with_a_trailing_newline(tmp_path):
    """题面「清单是一行紧凑 JSON，分隔符后面不加空格，末尾补一个换行」：清单的写法。"""
    result, out, _journal = _shipped(tmp_path, "case-14", ONLINE_B)
    assert result.returncode == 0, result.stderr
    raw = out.read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":")) + "\n"


def test_list_field_order_is_fixed(tmp_path):
    """题面「顶层键按 `title`、`event_count`、`entries`、`source_frames`、`timeline_frames`、`total_seconds` 的次序排下来」：清单的键序。"""
    result, out, _journal = _shipped(tmp_path, "case-15", ONLINE_B)
    assert result.returncode == 0, result.stderr
    payload = _list_of(out)
    assert list(payload) == ["title", "event_count", "entries", "source_frames", "timeline_frames", "total_seconds"]
    assert list(payload["entries"][0]) == [
        "event",
        "reel",
        "src_in",
        "src_out",
        "src_in_frame",
        "src_out_frame",
        "rec_in",
        "rec_out",
        "rec_in_frame",
        "rec_out_frame",
        "duration_seconds",
    ]


def test_source_timecodes_in_list_carry_drop_frame_separators(tmp_path):
    """题面「`src_in` 与 `src_out` 写在素材自己的基准上」：丢帧卷的源侧时码带分号，整帧卷的用冒号。"""
    result, out, _journal = _shipped(tmp_path, "case-16", ONLINE_B)
    assert result.returncode == 0, result.stderr
    entries = _list_of(out)["entries"]
    assert entries[0]["src_in"] == "01:11:57;20"
    assert entries[0]["src_out"] == "01:12:47;24"
    assert entries[4]["src_in"] == "03:02:30:00"
    assert entries[6]["src_in"] == "01:44:32;20"


def test_record_timecodes_in_list_carry_drop_frame_separators(tmp_path):
    """题面「`rec_in` 与 `rec_out` 写在时间线的基准上」：丢帧时间线的记录侧时码写成带分号的样子。"""
    ledger = {MAIN: _drop_reel("01:00:00;00", 200000)}
    table = _table(
        "MARK-RECORD",
        DROP_TABLE,
        "DROP-FRAME",
        [_single_row("001", MAIN, "01:10:00;02", "01:10:30;02", "01:00:00;00", "01:00:30;00")],
    )
    result, out, _journal = _run(tmp_path, "case-17", table, ledger)
    assert result.returncode == 0, result.stderr
    entry = _list_of(out)["entries"][0]
    assert entry["rec_in"] == "01:00:00;00"
    assert entry["rec_out"] == "01:00:30;00"


def test_list_entries_keep_editing_table_order_and_numbers(tmp_path):
    """题面「`entries` 按剪辑表里的顺序放」：事件号的先后跟剪辑表一致，不重排。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000), PAL_REEL: _flat_reel(NON_DROP, "02:00:00:00", 500000)}
    table = _table(
        "ORDER-KEEP",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [
            _single_row("004", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00"),
            _single_row("009", PAL_REEL, "02:10:00:00", "02:10:03:12", "02:00:05:00", "02:00:08:12"),
            _single_row("002", MAIN, "01:20:00:00", "01:20:07:00", "02:00:08:12", "02:00:15:12"),
        ],
    )
    result, out, _journal = _run(tmp_path, "case-18", table, ledger)
    assert result.returncode == 0, result.stderr
    payload = _list_of(out)
    assert [entry["event"] for entry in payload["entries"]] == [4, 9, 2]
    assert [entry["reel"] for entry in payload["entries"]] == [MAIN, PAL_REEL, MAIN]


def test_list_records_event_count_and_frame_totals(tmp_path):
    """题面「两个都写成整数」：清单里的条数与两侧帧数合计。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000), PAL_REEL: _flat_reel(NON_DROP, "02:00:00:00", 500000)}
    table = _table(
        "TOTALS-KEEP",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [
            _single_row("004", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00"),
            _single_row("009", PAL_REEL, "02:10:00:00", "02:10:03:12", "02:00:05:00", "02:00:08:12"),
            _single_row("002", MAIN, "01:20:00:00", "01:20:07:00", "02:00:08:12", "02:00:15:12"),
        ],
    )
    result, out, _journal = _run(tmp_path, "case-19", table, ledger)
    assert result.returncode == 0, result.stderr
    payload = _list_of(out)
    assert payload["event_count"] == 3
    assert payload["source_frames"] == 372
    assert payload["timeline_frames"] == 372
    assert payload["total_seconds"] == "15.500000"


def test_continuous_timeline_frame_numbers_stay_unchanged(tmp_path):
    """题面「记录侧那对是时间线上的第几帧」：整帧率时间线上的记录侧帧号照旧数。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "SIMPLE-24",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [
            _single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00"),
            _single_row("002", MAIN, "01:10:00:00", "01:10:02:12", "02:00:05:00", "02:00:07:12"),
        ],
    )
    result, out, _journal = _run(tmp_path, "case-20", table, ledger)
    assert result.returncode == 0, result.stderr
    entries = _list_of(out)["entries"]
    assert [entry["rec_in_frame"] for entry in entries] == [172800, 172920]
    assert [entry["rec_out_frame"] for entry in entries] == [172920, 172980]


def test_failed_run_keeps_previous_list_and_journal(tmp_path):
    """题面「退回的时候，清单和流水都一个字都不许动」：退回的那一版不碰上一版。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "KEEP-BOTH",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", "Z999X999_260101_R9Z", "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    out = tmp_path / "keep-out" / "conform-list.json"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"PREVIOUS-LIST\n")
    journal = tmp_path / "keep-journal.tsv"
    journal.write_bytes(b"JOB KEEP-BOTH\n004\tC012K004_260702_R1A\t01:02:30:00\t01:02:35:00\t02:00:00:00\t02:00:05:00\t5.000000\n")
    before = journal.read_bytes()
    result, out_path, journal_path = _run(tmp_path, "case-21", table, ledger, journal=journal, out=out)
    assert result.returncode != 0
    assert out_path.read_bytes() == b"PREVIOUS-LIST\n"
    assert journal_path.read_bytes() == before


def test_unwritable_destination_leaves_no_staging_file(tmp_path):
    """题面「要么完整写出一份，要么一个字节都不写」：清单落不下去的时候旁边不留半截文件。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "BLOCKED-OUT",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    out = tmp_path / "blocked-out" / "conform-list.json"
    out.mkdir(parents=True)
    journal = tmp_path / "blocked-journal.tsv"
    result, out_path, journal_path = _run(tmp_path, "case-22", table, ledger, journal=journal, out=out)
    assert result.returncode != 0
    assert sorted(item.name for item in out_path.parent.iterdir()) == ["conform-list.json"]
    assert out_path.is_dir()
    assert not journal_path.exists()


def test_repeated_runs_write_the_same_list(tmp_path):
    """题面「同一份剪辑表和台账跑两遍，写出来的两份清单逐字节相同」：清单要逐字节可复现。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "REPEAT-LIST",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    first, first_out, _first_journal = _run(tmp_path, "case-23", table, ledger)
    second, second_out, _second_journal = _run(tmp_path, "case-24", table, ledger)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first_out.read_bytes() == second_out.read_bytes()


def test_repeated_runs_do_not_journal_the_same_events_twice(tmp_path):
    """题面「同一份剪辑表连着跑两遍，流水的字节跟第一遍跑完那一模一样」：流水不重复记。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "REPEAT-JOURNAL",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    journal = tmp_path / "repeat-journal.tsv"
    first, _first_out, journal_path = _run(tmp_path, "case-25", table, ledger, journal=journal)
    after_first = journal_path.read_bytes()
    second, _second_out, _journal_path = _run(tmp_path, "case-26", table, ledger, journal=journal)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert journal_path.read_bytes() == after_first


def test_fresh_journal_starts_with_the_job_head_line(tmp_path):
    """题面「头一行是 `JOB` 加片子标题」：流水本来没有的时候先写头行。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "FRESH-JOURNAL",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, _out, journal_path = _run(tmp_path, "case-27", table, ledger)
    assert result.returncode == 0, result.stderr
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "JOB FRESH-JOURNAL"
    assert len(lines) == 2


def test_journal_keeps_existing_lines_and_appends_new_ones(tmp_path):
    """题面「流水只许往后追加，已经写下的字节一个都不许动」：已经记过的行原样留着，新的接在后面。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000), PAL_REEL: _flat_reel(NON_DROP, "02:00:00:00", 500000)}
    table = _table(
        "APPEND-KEEP",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [
            _single_row("004", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00"),
            _single_row("009", PAL_REEL, "02:10:00:00", "02:10:03:12", "02:00:05:00", "02:00:08:12"),
            _single_row("002", MAIN, "01:20:00:00", "01:20:07:00", "02:00:08:12", "02:00:15:12"),
        ],
    )
    journal = tmp_path / "append-journal.tsv"
    journal.write_text(
        "JOB APPEND-KEEP\n"
        "004\tC012K004_260702_R1A\t01:02:30:00\t01:02:35:00\t02:00:00:00\t02:00:05:00\t5.000000\n",
        encoding="utf-8",
    )
    before = journal.read_bytes()
    result, _out, journal_path = _run(tmp_path, "case-28", table, ledger, journal=journal)
    assert result.returncode == 0, result.stderr
    after = journal_path.read_bytes()
    assert after.startswith(before)
    assert [line.split("\t")[0] for line in after.decode("utf-8").splitlines()[1:]] == ["004", "009", "002"]


def test_journal_lines_match_the_list_entries(tmp_path):
    """题面「四个时码也跟清单上写的一样」：流水上的行跟清单里的条目对得上。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "JOURNAL-MATCH",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [
            _single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00"),
            _single_row("002", MAIN, "01:10:00:00", "01:10:02:12", "02:00:05:00", "02:00:07:12"),
        ],
    )
    result, out, journal_path = _run(tmp_path, "case-29", table, ledger)
    assert result.returncode == 0, result.stderr
    entries = _list_of(out)["entries"]
    rows = [line.split("\t") for line in journal_path.read_text(encoding="utf-8").splitlines()[1:]]
    assert rows == [
        [
            "%03d" % entry["event"],
            entry["reel"],
            entry["src_in"],
            entry["src_out"],
            entry["rec_in"],
            entry["rec_out"],
            entry["duration_seconds"],
        ]
        for entry in entries
    ]


def test_rejects_a_journal_kept_for_another_editing_table(tmp_path):
    """题面「流水头行认的片子跟这次要套的片子对不上」：拿错别人的流水就整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "OTHER-FILM",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    journal = tmp_path / "other-journal.tsv"
    journal.write_text("JOB 0707A-PROMO-CUT2\n", encoding="utf-8")
    before = journal.read_bytes()
    result, out, journal_path = _run(tmp_path, "case-30", table, ledger, journal=journal)
    assert result.returncode != 0
    assert not out.exists()
    assert journal_path.read_bytes() == before


def test_rejects_a_journal_line_with_the_wrong_column_count(tmp_path):
    """题面「流水里哪一行不是七列」：流水里形状不对的行让整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "BAD-COLUMNS",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    journal = tmp_path / "case-journal-a.tsv"
    journal.write_text("JOB BAD-COLUMNS\n001\tC012K004_260702_R1A\t01:02:30:00\n", encoding="utf-8")
    before = journal.read_bytes()
    result, out, journal_path = _run(tmp_path, "case-31", table, ledger, journal=journal)
    assert result.returncode != 0
    assert not out.exists()
    assert journal_path.read_bytes() == before


def test_rejects_a_journal_line_with_an_unreadable_timecode(tmp_path):
    """题面「时码按它那一侧的基准读不出来」：流水上的时码对不上基准也让整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "BAD-TIMECODE",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    journal = tmp_path / "case-journal-b.tsv"
    journal.write_text(
        "JOB BAD-TIMECODE\n001\tC012K004_260702_R1A\t01:02:30;00\t01:02:35:00\t02:00:00:00\t02:00:05:00\t5.000000\n",
        encoding="utf-8",
    )
    before = journal.read_bytes()
    result, out, journal_path = _run(tmp_path, "case-32", table, ledger, journal=journal)
    assert result.returncode != 0
    assert not out.exists()
    assert journal_path.read_bytes() == before


def test_rejects_a_journal_line_with_a_broken_duration(tmp_path):
    """题面「时长不是六位小数」：流水上的时长写成别的样子也让整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "BAD-SECONDS",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    journal = tmp_path / "case-journal-c.tsv"
    journal.write_text(
        "JOB BAD-SECONDS\n001\tC012K004_260702_R1A\t01:02:30:00\t01:02:35:00\t02:00:00:00\t02:00:05:00\t5.0\n",
        encoding="utf-8",
    )
    before = journal.read_bytes()
    result, out, journal_path = _run(tmp_path, "case-33", table, ledger, journal=journal)
    assert result.returncode != 0
    assert not out.exists()
    assert journal_path.read_bytes() == before


def test_rejects_event_referencing_unknown_reel(tmp_path):
    """题面「台账里查不到卷号」：卷号不在台账里的剪辑表整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "UNKNOWN-REEL",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", PAL_REEL, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-34", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_ledger_entry_with_an_extra_field(tmp_path):
    """题面「四个字段一个不多一个不少」：台账里多写字段的卷整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    ledger[MAIN]["sound_speed"] = "24"
    table = _table(
        "LEDGER-EXTRA",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-35", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_ledger_entry_missing_a_field(tmp_path):
    """题面「四个字段一个不多一个不少」：台账里少写字段的卷整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    del ledger[MAIN]["duration_frames"]
    table = _table(
        "LEDGER-MISSING",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-36", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_drop_frame_basis_on_an_integer_rate(tmp_path):
    """题面「台账里的帧率跟丢帧基准配不上，比如 25 帧的素材标成丢帧基准」：配不上的组合整份退回。"""
    ledger = {PAL_REEL: _reel(25, 1, DROP, "02:00:00;00", 90000)}
    table = _table(
        "PAL-DROP-BAD",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", PAL_REEL, "02:20:00;00", "02:20:05;00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-37", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_non_drop_reel_whose_start_timecode_has_a_semicolon(tmp_path):
    """题面「素材的起始时码跟它自己的基准对不上，比如整帧素材写成带分号的」：起始时码写错的卷整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00;00", 500000)}
    table = _table(
        "START-MARK-BAD",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-38", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_timecode_column_with_a_semicolon_in_editing_table(tmp_path):
    """题面「四个时码写成 `HH:MM:SS:FF`」：剪辑表里冒号写成别的样子整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "COLON-BAD",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30;00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-39", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_timecode_field_out_of_range(tmp_path):
    """题面「剪辑表里的时间码越界」：秒位写成六十的剪辑表整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "RANGE-BAD",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:60:00", "02:00:00:00", "02:00:30:00")],
    )
    result, out, _journal = _run(tmp_path, "case-40", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_frame_number_equal_to_nominal_rate(tmp_path):
    """帧位正好等于每秒格数时也必须退回，不能当成下一格。"""
    ledger = {FLAT_REEL: _flat_reel(NON_DROP, "01:00:00:00", 1000)}
    table = _table(
        "FRAME-EQ",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", FLAT_REEL, "01:00:00:24", "01:00:01:24", "01:00:00:00", "01:00:01:00")],
    )
    result, out, _journal = _run(tmp_path, "case-41", table, ledger)
    assert result.returncode != 0
    assert result.stderr.startswith("套底清单没能生成: ")
    assert not out.exists()


def test_rejects_zero_timeline_rate(tmp_path):
    """时间线帧率为零时按非法输入退回，不能继续算下去。"""
    ledger = {FLAT_REEL: _flat_reel(NON_DROP, "01:00:00:00", 1000)}
    table = _table(
        "RATE-ZERO",
        "0/1",
        "NON-DROP-FRAME",
        [_single_row("001", FLAT_REEL, "01:00:00:00", "01:00:00:01", "01:00:00:00", "01:00:00:01")],
    )
    result, out, _journal = _run(tmp_path, "case-42", table, ledger)
    assert result.returncode == 1
    assert result.stderr.startswith("套底清单没能生成: 时间线的帧率要是正数")
    assert not out.exists()


def test_rejects_timecode_the_device_never_writes(tmp_path):
    """题面「剪辑表和台账上冒出设备不会写的帧号」：丢帧卷上被跳过的帧号整份退回。"""
    ledger = {MAIN: _drop_reel("01:00:00;00", 200000)}
    table = _table(
        "GHOST-FRAME",
        DROP_TABLE,
        "DROP-FRAME",
        [_single_row("001", MAIN, "01:06:00;01", "01:06:10;01", "01:00:00;00", "01:00:10;00")],
    )
    result, out, _journal = _run(tmp_path, "case-43", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_event_line_with_extra_column(tmp_path):
    """题面「用空白分开七列」：多出一列的剪辑表整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = (
        "TITLE: EXTRA-COLUMN\n"
        "TIMELINE %s NON-DROP-FRAME\n"
        "001  %s  C  01:02:30:00  01:02:35:00  02:00:00:00  02:00:05:00  DISSOLVE\n"
    ) % (FLAT24_TABLE, MAIN)
    result, out, _journal = _run(tmp_path, "case-44", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_duplicate_event_number(tmp_path):
    """题面「事件号在一份剪辑表里不重复」：事件号重号的剪辑表整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "DUP-NUMBER",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [
            _single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00"),
            _single_row("001", MAIN, "01:10:00:00", "01:10:02:12", "02:00:05:00", "02:00:07:12"),
        ],
    )
    result, out, _journal = _run(tmp_path, "case-45", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_transition_other_than_cut(tmp_path):
    """题面「转场这一列都是 `C`」：转场写成别的剪辑表整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "TRANSITION-BAD",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [("001", MAIN, "D", "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-46", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_event_beyond_reel_length(tmp_path):
    """题面「源出点也不能越过 `start_timecode` 再往后数 `duration_frames` 帧」：越过素材长度的整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 3605)}
    table = _table(
        "TOO-LONG",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-47", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_editing_table_without_events(tmp_path):
    """题面「一份剪辑表至少要有一条事件」：只有表头的剪辑表整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table("EMPTY-TABLE", FLAT24_TABLE, "NON-DROP-FRAME", [])
    result, out, _journal = _run(tmp_path, "case-48", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_usage_error_when_arguments_are_missing(tmp_path):
    """题面「多给少给位置参数都不算数」：参数少给的时候按用法错误退出。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    edl = _place(tmp_path, "usage.edl", _table("USAGE", FLAT24_TABLE, "NON-DROP-FRAME", []))
    book = _place(tmp_path, "usage-ledger.json", json.dumps(ledger, ensure_ascii=False) + "\n")
    result = subprocess.run(
        [sys.executable, str(APP), str(edl), str(book)],
        capture_output=True,
        text=True,
        timeout=CALL_TIMEOUT_SEC,
    )
    assert result.returncode != 0
    assert "用法" in result.stderr
    assert not (tmp_path / "usage-list.json").exists()


def test_rejects_unreadable_timecode_text(tmp_path):
    """题面「剪辑表里的时间码越界，或者写法不对」：时码里有字母的剪辑表整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "TEXT-BAD",
        FLAT24_TABLE,
        "NON-DROP-FRAME",
        [_single_row("001", MAIN, "01:02:3a:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-49", table, ledger)
    assert result.returncode != 0
    assert not out.exists()


def test_rejects_unknown_timecode_basis_word(tmp_path):
    """题面「基准那一段只有 `DROP-FRAME` 与 `NON-DROP-FRAME` 两种写法」：别的基准写法整份退回。"""
    ledger = {MAIN: _flat_reel(NON_DROP, "01:00:00:00", 500000)}
    table = _table(
        "BASIS-BAD",
        FLAT24_TABLE,
        "PULL-DOWN",
        [_single_row("001", MAIN, "01:02:30:00", "01:02:35:00", "02:00:00:00", "02:00:05:00")],
    )
    result, out, _journal = _run(tmp_path, "case-50", table, ledger)
    assert result.returncode != 0
    assert not out.exists()
