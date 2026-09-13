# -*- coding: utf-8 -*-
"""actions.py 机械回归：台账生成、待确认规则、日期归一、逾期检查。

运行：python -m unittest discover -s meeting-minutes/tests -v
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

import actions  # noqa: E402


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = actions.main(argv)
    return code, out.getvalue()


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write_json(self, items):
        path = os.path.join(self.tmp.name, "a.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        return path

    def out_path(self):
        return os.path.join(self.tmp.name, "ledger.csv")

    def test_missing_owner_and_deadline_become_pending(self):
        src = self.write_json([{"事项": "提交报价单", "责任人": "", "截止日期": ""},
                               {"事项": "签订合同", "责任人": "张三", "截止日期": "2026/9/20"}])
        out = self.out_path()
        code, msg = run_main(["build", "--from", src, "--out", out])
        self.assertEqual(code, 0)
        self.assertIn("待确认", msg)
        content = open(out, encoding="utf-8-sig").read()
        self.assertIn("待确认,中,待办", content.replace(",,", ",待确认,"))
        self.assertIn("2026-09-20", content)

    def test_date_formats_normalized(self):
        src = self.write_json([{"事项": "甲", "责任人": "张", "截止日期": "2026年10月1日"},
                               {"事项": "乙", "责任人": "李", "截止日期": "20261015"}])
        out = self.out_path()
        code, _ = run_main(["build", "--from", src, "--out", out])
        self.assertEqual(code, 0)
        content = open(out, encoding="utf-8-sig").read()
        self.assertIn("2026-10-01", content)
        self.assertIn("2026-10-15", content)

    def test_items_without_task_skipped(self):
        src = self.write_json([{"责任人": "张三"}, {"事项": "有效项", "责任人": "李四", "截止日期": "2026-10-01"}])
        out = self.out_path()
        code, msg = run_main(["build", "--from", src, "--out", out])
        self.assertEqual(code, 0)
        self.assertIn("已跳过", msg)
        self.assertIn("有效项", open(out, encoding="utf-8-sig").read())

    def test_no_fabrication_of_defaults(self):
        """缺日期时不得自行补一个具体日期。"""
        src = self.write_json([{"事项": "只有事项的条目"}])
        out = self.out_path()
        run_main(["build", "--from", src, "--out", out])
        content = open(out, encoding="utf-8-sig").read()
        row = [line for line in content.splitlines() if "只有事项" in line][0]
        self.assertIn("待确认", row)
        self.assertNotIn("202", row.replace("待确认", ""))


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write_csv(self, content):
        path = os.path.join(self.tmp.name, "l.csv")
        with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write(content)
        return path

    def test_overdue_detected(self):
        path = self.write_csv("序号,事项,责任人,协办,截止日期,优先级,状态,来源,备注\n"
                              "1,甲,张三,,2026-08-01,高,待办,,\n")
        code, out = run_main(["check", path, "--asof", "2026-09-13"])
        self.assertEqual(code, 1)
        self.assertIn("逾期", out)
        self.assertIn("甲", out)

    def test_missing_owner_flagged(self):
        path = self.write_csv("序号,事项,责任人,协办,截止日期,优先级,状态,来源,备注\n"
                              "1,甲,,待确认,2026-12-01,中,待办,,\n")
        code, out = run_main(["check", path])
        self.assertEqual(code, 1)
        self.assertIn("缺责任人", out)

    def test_clean_ledger_passes(self):
        path = self.write_csv("序号,事项,责任人,协办,截止日期,优先级,状态,来源,备注\n"
                              "1,甲,张三,,2026-12-01,中,待办,,\n"
                              "2,乙,李四,,2026-01-01,低,完成,,\n")
        code, out = run_main(["check", path, "--asof", "2026-09-13"])
        self.assertEqual(code, 0)
        self.assertIn("无逾期", out)

    def test_missing_required_columns(self):
        path = self.write_csv("事项,责任人\n甲,张三\n")
        code, out = run_main(["check", path])
        self.assertEqual(code, 1)
        self.assertIn("缺少必需列", out)


if __name__ == "__main__":
    unittest.main()
