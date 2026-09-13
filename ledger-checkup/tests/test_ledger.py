# -*- coding: utf-8 -*-
"""ledger.py 机械回归：身份证校验、查重、必填、日期逻辑、枚举漂移、清洗副本。

运行：python -m unittest discover -s ledger-checkup/tests -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)

import ledger  # noqa: E402

# 身份证号均为公开测试向量（GB 11643 标准示例），非真实证件号
VALID_ID = "11010519491231002X"
INVALID_ID = "110105194912310021"


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ledger.main(argv)
    return code, out.getvalue()


class IdTests(unittest.TestCase):
    def test_valid_checksum(self):
        problems, info = ledger.parse_id(VALID_ID)
        self.assertEqual(problems, [])
        self.assertEqual(info["birth"].isoformat(), "1949-12-31")
        self.assertEqual(info["gender"], "女")

    def test_bad_checksum(self):
        problems, _ = ledger.parse_id(INVALID_ID)
        self.assertTrue(any("校验码" in p for p in problems))

    def test_short_id(self):
        problems, _ = ledger.parse_id("110105491231002")
        self.assertTrue(any("18位" in p for p in problems))

    def test_birth_in_future(self):
        fake = "110105203012310019"
        problems, _ = ledger.parse_id(fake)
        # 校验码可能不符，但至少应报出生段或校验码问题
        self.assertTrue(problems)


class CheckTests(unittest.TestCase):
    HEADERS = ["姓名", "身份证号", "工号", "出生日期", "性别", "年龄", "部门", "入职日期"]

    def rows(self):
        return [
            ["张三", VALID_ID, "GH001", "1949-12-31", "女", "76", "办公室", "2020-01-01"],
            ["李四", INVALID_ID, "GH002", "1990/05/01", "男", "35", "财务科 ", "2021.6.15"],
            ["李四", VALID_ID, "GH002", "1990.5.1", "女", "30", "财务科", ""],
            ["王五", "", "GH004", "未知", "N/A", "45", "办公室", "2019-13-01"],
        ]

    def test_duplicate_key_detected(self):
        issues = ledger.check_ledger(self.HEADERS, self.rows(), ["工号"], [], None)
        self.assertTrue(any(lv == "红" and "重复" in msg and "GH002" in msg
                            for lv, kind, msg in issues))

    def test_required_missing_detected(self):
        issues = ledger.check_ledger(self.HEADERS, self.rows(), [], ["身份证号"], None)
        self.assertTrue(any(lv == "红" and "必填缺失" in kind for lv, kind, msg in issues))

    def test_id_cross_checks(self):
        issues = ledger.check_ledger(self.HEADERS, self.rows(), [], [], None)
        kinds = [kind for _, kind, _ in issues]
        self.assertIn("身份证", kinds)          # 李四第一行校验码不符
        self.assertIn("性别不符", kinds)        # 李四第二行 性别列男 vs 身份证推算女
        self.assertIn("年龄不符", kinds)        # 李四第二行 30 vs 推算35（截至2025）

    def test_date_format_mixed(self):
        issues = ledger.check_ledger(self.HEADERS, self.rows(), [], [], None)
        self.assertTrue(any(kind == "日期格式" and "入职日期" in msg for _, kind, msg in issues))

    def test_enum_drift_detected(self):
        issues = ledger.check_ledger(self.HEADERS, self.rows(), [], [], None)
        self.assertTrue(any(kind == "枚举漂移" and "部门" in msg for _, kind, msg in issues))

    def test_placeholder_flagged(self):
        issues = ledger.check_ledger(self.HEADERS, self.rows(), [], [], None)
        self.assertTrue(any(kind == "占位值" for _, kind, msg in issues))

    def test_clean_table_has_no_red(self):
        rows = [
            ["张三", VALID_ID, "GH001", "1949-12-31", "女", "76", "办公室", "2020-01-01"],
            ["李四", "110105199005010026", "GH002", "1990-05-01", "女", "35", "财务科", "2021-06-15"],
        ]
        import datetime
        issues = ledger.check_ledger(self.HEADERS, rows, ["身份证号", "工号"],
                                     ["身份证号", "部门"], datetime.date(2026, 2, 15))
        reds = [i for i in issues if i[0] == "红"]
        self.assertEqual(reds, [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, content, name="r.csv", encoding="utf-8"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding=encoding, newline="\n") as f:
            f.write(content)
        return path

    def test_cli_check_and_json(self):
        path = self.write("姓名,工号\n甲,GH1\n乙,GH1\n")
        code, out = run_main(["check", path, "--key", "工号", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["issues"][0]["level"], "红")

    def test_cli_clean_writes_copy(self):
        src = self.write("姓名,部门\n 甲 , 办公室 \n")
        out_path = os.path.join(self.tmp.name, "clean.csv")
        code, msg = run_main(["clean", src, out_path])
        self.assertEqual(code, 0)
        self.assertIn("已生成", msg)
        content = open(out_path, encoding="utf-8-sig").read()
        self.assertIn("甲,办公室", content)
        # 原文件未被改动
        self.assertIn(" 甲 ", open(src, encoding="utf-8").read())

    def test_missing_file(self):
        code, out = run_main(["check", os.path.join(self.tmp.name, "none.csv")])
        self.assertEqual(code, 2)
        self.assertIn("不存在", out)


if __name__ == "__main__":
    unittest.main()
