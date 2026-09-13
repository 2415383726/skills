# -*- coding: utf-8 -*-
"""check.py 机械回归：合计校验、负值、可疑比率、跳变、空值、输出契约。

运行：python -m unittest discover -s report-check/tests -v
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

import check  # noqa: E402


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = check.main(argv)
    return code, out.getvalue()


class UnitTests(unittest.TestCase):
    def test_to_number(self):
        self.assertEqual(check.to_number("1,234"), (1234, "ok"))
        self.assertEqual(check.to_number("50%"), (0.5, "ok"))
        self.assertEqual(check.to_number(""), (None, "empty"))
        n, s = check.to_number("１２３。")
        self.assertEqual(s, "unparsable")

    def test_subtotal_mismatch_is_red(self):
        rows = [["综合科", "100"], ["财务科", "200"], ["合计", "350"]]
        issues, _ = check.check_table(rows, ["科室", "金额"])
        self.assertTrue(any(lv == "红" and kind == "合计行校验" and "350" in msg
                            for lv, kind, msg in issues))

    def test_subtotal_group_boundary(self):
        rows = [["A", "10"], ["小计", "10"], ["B", "20"], ["合计", "30"]]
        issues, _ = check.check_table(rows, ["科室", "金额"])
        self.assertFalse(any("合计行校验" in msg for _, kind, msg in issues))

    def test_negative_count_is_red(self):
        rows = [["甲", "-5"]]
        issues, _ = check.check_table(rows, ["单位", "人数"])
        self.assertTrue(any(lv == "红" and kind == "负值检查" for lv, kind, msg in issues))

    def test_zero_and_100_percent_suspicious(self):
        rows = [["甲", "0%"], ["乙", "100%"], ["丙", "50%"], ["丁", "60%"]]
        issues, _ = check.check_table(rows, ["单位", "完成率"])
        kinds = [msg for lv, kind, msg in issues if kind == "可疑比率"]
        self.assertEqual(len(kinds), 2)

    def test_jump_detected(self):
        rows = [["1月", "12"], ["2月", "11"], ["3月", "13"], ["4月", "90"]]
        issues, _ = check.check_table(rows, ["月份", "金额"])
        self.assertTrue(any(kind == "跳变检查" for _, kind, msg in issues))

    def test_empty_and_unparsable(self):
        rows = [["甲", ""], ["乙", "12。5"], ["丙", "10"], ["丁", "11"]]
        issues, _ = check.check_table(rows, ["单位", "数量"])
        kinds = [kind for _, kind, _ in issues]
        self.assertIn("空值", kinds)
        self.assertIn("解析失败", kinds)

    def test_clean_table_no_issues(self):
        rows = [["甲", "10"], ["乙", "20"], ["合计", "30"]]
        issues, _ = check.check_table(rows, ["科室", "金额"])
        self.assertEqual(issues, [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, content):
        path = os.path.join(self.tmp.name, "r.csv")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return path

    def test_cli_report_and_out(self):
        path = self.write("科室,金额\n甲,100\n乙,200\n合计,350\n")
        out_path = os.path.join(self.tmp.name, "report.md")
        code, msg = run_main([path, "--out", out_path])
        self.assertEqual(code, 0)
        self.assertIn("已写入", msg)
        report = open(out_path, encoding="utf-8-sig").read()
        self.assertIn("红色 1 项", report)
        self.assertIn("350", report)

    def test_json_output(self):
        path = self.write("单位,人数\n甲,-3\n")
        code, out = run_main([path, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["issues"][0]["level"], "红")

    def test_missing_file(self):
        code, out = run_main([os.path.join(self.tmp.name, "none.csv")])
        self.assertEqual(code, 2)
        self.assertIn("不存在", out)


if __name__ == "__main__":
    unittest.main()
