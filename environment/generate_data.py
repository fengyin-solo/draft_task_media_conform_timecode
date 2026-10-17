#!/usr/bin/env python3
"""展开这批片子的素材台账与剪辑表。

用法: python3 generate_data.py --out <目录>
"""

import argparse
import json
import os

DROP = "drop-frame"
NON_DROP = "non-drop-frame"

LEDGER = {
    "A017C012_260712_R1AB": {
        "fps": {"numerator": 30000, "denominator": 1001},
        "timecode_base": DROP,
        "start_timecode": "01:00:00;00",
        "duration_frames": 108000,
    },
    "B039D017_251122_R2C": {
        "fps": {"numerator": 25, "denominator": 1},
        "timecode_base": NON_DROP,
        "start_timecode": "02:00:00:00",
        "duration_frames": 90000,
    },
    "C104E003_260411_R1AD": {
        "fps": {"numerator": 24, "denominator": 1},
        "timecode_base": NON_DROP,
        "start_timecode": "09:00:00:00",
        "duration_frames": 180000,
    },
    "D221F009_260218_R3": {
        "fps": {"numerator": 24000, "denominator": 1001},
        "timecode_base": NON_DROP,
        "start_timecode": "03:00:00:00",
        "duration_frames": 240000,
    },
    "E008B021_251105_R1AA": {
        "fps": {"numerator": 60000, "denominator": 1001},
        "timecode_base": DROP,
        "start_timecode": "12:00:00;00",
        "duration_frames": 216000,
    },
    "F310H014_260303_R1": {
        "fps": {"numerator": 30000, "denominator": 1001},
        "timecode_base": DROP,
        "start_timecode": "23:58:00;02",
        "duration_frames": 12000,
    },
    "G002K006_260125_R1AC": {
        "fps": {"numerator": 24, "denominator": 1},
        "timecode_base": NON_DROP,
        "start_timecode": "14:00:00:00",
        "duration_frames": 140000,
    },
}

# 开机时从现场台账与 EDL 导出文件上抄下来的固定表格：
# 事件号、卷号、源入点、源出点、记录入点、记录出点。
# 机房那本流水上已经记过的行：事件号、卷号、源入点、源出点、记录入点、记录出点、时长。
JOURNALS = (
    ("conform-journal-0707A.tsv", "0707A-PROMO-CUT2", [
    (1, "C104E003_260411_R1AD", "09:12:30:00", "09:12:35:12", "01:00:00:00", "01:00:05:12", "5.500000"),
    (2, "C104E003_260411_R1AD", "09:18:25:00", "09:18:27:12", "01:00:05:12", "01:00:08:00", "2.500000"),
]),
)

CONFORM_TABLES = (
    ("0707A-promo-cut2.edl", "0707A-PROMO-CUT2", "24/1", "NON-DROP-FRAME", [
    (1, "C104E003_260411_R1AD", "09:12:30:00", "09:12:35:12", "01:00:00:00", "01:00:05:12"),
    (2, "C104E003_260411_R1AD", "09:18:25:00", "09:18:27:12", "01:00:05:12", "01:00:08:00"),
    (3, "C104E003_260411_R1AD", "09:30:22:12", "09:30:31:12", "01:00:08:00", "01:00:17:00"),
    (4, "C104E003_260411_R1AD", "09:41:00:00", "09:41:04:00", "01:00:17:00", "01:00:21:00"),
    (5, "C104E003_260411_R1AD", "09:50:08:18", "09:50:19:18", "01:00:21:00", "01:00:32:00"),
]),
    ("0708B-promo-online.edl", "0708B-PROMO-ONLINE", "30000/1001", "DROP-FRAME", [
    (1, "A017C012_260712_R1AB", "01:11:57;20", "01:12:47;24", "01:00:00;00", "01:00:50;02"),
    (2, "F310H014_260303_R1", "23:59:58;02", "00:00:12;02", "01:00:50;02", "01:01:04;04"),
    (3, "F310H014_260303_R1", "00:00:12;02", "00:00:30;02", "01:01:04;04", "01:01:22;04"),
    (4, "E008B021_251105_R1AA", "12:04:06;16", "12:04:08;16", "01:01:22;04", "01:01:24;04"),
    (5, "D221F009_260218_R3", "03:02:30:00", "03:02:40:00", "01:01:24;04", "01:01:34;04"),
    (6, "C104E003_260411_R1AD", "09:35:00:00", "09:35:41:17", "01:01:34;04", "01:02:15;26"),
    (7, "A017C012_260712_R1AB", "01:44:32;20", "01:45:02;19", "01:02:15;26", "01:02:45;23"),
    (8, "B039D017_251122_R2C", "02:12:00:00", "02:12:40:01", "01:02:45;23", "01:03:25;25"),
]),
    ("0709C-trailer.edl", "0709C-TRAILER", "24/1", "NON-DROP-FRAME", [
    (1, "B039D017_251122_R2C", "02:20:00:00", "02:20:05:00", "02:00:00:00", "02:00:05:00"),
    (2, "G002K006_260125_R1AC", "14:02:30:00", "14:02:40:00", "02:00:05:00", "02:00:15:00"),
    (3, "B039D017_251122_R2C", "02:23:48:00", "02:23:50:00", "02:00:15:00", "02:00:17:00"),
    (4, "G002K006_260125_R1AC", "14:03:50:00", "14:03:53:00", "02:00:17:00", "02:00:20:00"),
]),
)

SOURCE_NOTE = """这是套底机房这批片子的演练素材：一份素材台账，三份从剪辑软件里导出的剪辑表。
台账里七卷素材的帧率分布覆盖 24、25、29.97、59.94 以及 24/1.001 的拉片几档，
时间码基准有丢帧与整帧两类，其中一卷是傍晚起机、录到第二天凌晨的。
三份剪辑表分别是单机位短片的回批、混合帧率长片的回批、以及预告片的一小段。
台账与剪辑表都由 environment/generate_data.py 这个生成脚本展开，脚本里写的是开机时从
现场台账与 EDL 导出文件上抄下来的固定表格（种子 20261016 只是这批演练数据的批次编号），
全程没有随机抽样，重复运行得到逐字节相同的文件。
数据是按固定字段人工构造的演练数据，不含任何客户素材、成片或真实拍摄参数。
"""


def editing_table(title, rate, basis, rows):
    document = ["TITLE: %s" % title, "TIMELINE %s %s" % (rate, basis)]
    for number, reel, src_in, src_out, rec_in, rec_out in rows:
        document.append(
            "%03d  %s  C  %s  %s  %s  %s" % (number, reel, src_in, src_out, rec_in, rec_out)
        )
    return "\n".join(document) + "\n"


def main():
    parser = argparse.ArgumentParser(description="展开演练用的素材台账与剪辑表")
    parser.add_argument("--out", required=True, help="输出目录")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "shoot-ledger-0707-0709.json"), "w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(LEDGER, ensure_ascii=False, indent=2) + "\n")
    for name, title, rate, basis, rows in CONFORM_TABLES:
        with open(os.path.join(args.out, name), "w", encoding="utf-8", newline="\n") as stream:
            stream.write(editing_table(title, rate, basis, rows))
    for name, title, rows in JOURNALS:
        body = ["JOB %s" % title]
        for number, reel, src_in, src_out, rec_in, rec_out, seconds in rows:
            body.append("%03d	%s	%s	%s	%s	%s	%s" % (number, reel, src_in, src_out, rec_in, rec_out, seconds))
        with open(os.path.join(args.out, name), "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(body) + "\n")
    with open(os.path.join(args.out, "DATA_SOURCE.txt"), "w", encoding="utf-8", newline="\n") as stream:
        stream.write(SOURCE_NOTE)


if __name__ == "__main__":
    main()
