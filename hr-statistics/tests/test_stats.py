# -*- coding: utf-8 -*-
"""stats.py 机械回归：分组计数、交叉表、年龄段、退休预测、编码兼容。

运行：python -m unittest discover -s hr-statistics/tests -v
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)

import stats  # noqa: E402

CSV = ("姓名,部门,学历,性别,出生日期\n"
       "甲,办公室,本科,男,1990-05-01\n"
       "乙,办公室,硕士,女,1985-03-15\n"
       "丙,财务科,本科,男,1970-12-01\n"
       "丁,财务科,本科,女,1968-02-20\n")


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = stats.main(argv)
    return code, out.getvalue()


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv = os.path.join(self.tmp.name, "r.csv")
        with open(self.csv, "w", encoding="utf-8", newline="\n") as f:
            f.write(CSV)

    def test_count_by(self):
        code, out = run_main(["count-by", self.csv, "--col", "部门"])
        self.assertEqual(code, 0)
        self.assertIn("| 办公室 | 2 | 50.0% |", out)
        self.assertIn("| 合计 | 4 | 100% |", out)

    def test_pivot_cross_table(self):
        code, out = run_main(["pivot", self.csv, "--rows", "部门", "--cols", "学历"])
        self.assertEqual(code, 0)
        self.assertIn("| 办公室 | 1 | 1 | 2 |", out)
        self.assertIn("| 合计 | 3 | 1 | 4 |", out)

    def test_ages_brackets_with_asof(self):
        code, out = run_main(["ages", self.csv, "--col", "出生日期",
                              "--brackets", "35,50", "--asof", "2026-02-15"])
        self.assertEqual(code, 0)
        self.assertIn("| 35岁及以下 | 1 |", out)      # 甲 35岁
        self.assertIn("| 36-50岁 | 1 |", out)         # 乙 40岁
        self.assertIn("| 50岁以上 | 2 |", out)        # 丙 55岁、丁 58岁

    def test_retire_forecast(self):
        code, out = run_main(["retire", self.csv, "--col", "出生日期", "--gender", "性别",
                              "--male-age", "60", "--female-age", "55",
                              "--years", "5", "--asof", "2026-02-15"])
        self.assertEqual(code, 0)
        # 丙 男1970-12-01 → 2030-12 到龄；丁 女1968-02-20 → 2023-02 已超龄
        self.assertIn("2030", out)
        self.assertIn("已超龄未注销", out)
        self.assertIn("男60岁/女55岁", out)

    def test_unknown_column_exit_2(self):
        code, out = run_main(["count-by", self.csv, "--col", "不存在"])
        self.assertEqual(code, 2)
        self.assertIn("找不到列", out)

    def test_gbk_csv(self):
        path = os.path.join(self.tmp.name, "gbk.csv")
        with open(path, "w", encoding="gbk", newline="\n") as f:
            f.write("部门\n办公室\n财务科\n")
        code, out = run_main(["count-by", path, "--col", "部门"])
        self.assertEqual(code, 0)
        self.assertIn("办公室", out)

    def test_missing_file_exit(self):
        code, out = run_main(["count-by", os.path.join(self.tmp.name, "none.csv"), "--col", "部门"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
