# -*- coding: utf-8 -*-
"""clauses.py 机械回归：中文条号解析、条款拆分、对齐类型、输出契约。

运行：python -m unittest discover -s policy-diff/tests -v
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

import clauses  # noqa: E402


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = clauses.main(argv)
    return code, out.getvalue()


class NumeralTests(unittest.TestCase):
    def test_common_numerals(self):
        cases = {"一": 1, "五": 5, "十": 10, "十三": 13, "二十": 20, "二十五": 25,
                 "一百": 100, "一百零五": 105, "一百二十": 120, "两": 2,
                 "一千二百": 1200, "三十九": 39}
        for s, v in cases.items():
            self.assertEqual(clauses.chinese_to_int(s), v, s)

    def test_clause_number_supports_arabic(self):
        self.assertEqual(clauses.clause_number("42"), 42)
        self.assertEqual(clauses.clause_number("十三"), 13)


class ParseTests(unittest.TestCase):
    def test_split_md_clauses(self):
        text = "第一章 总则\n第一条 为规范××，制定本办法。\n第二条 本办法适用于各科室。\n\n第二章 附则\n第三条 本办法自发布之日起施行。"
        parsed = clauses.parse_clauses(text)
        self.assertEqual([n for n, _ in parsed], [1, 2, 3])
        self.assertIn("制定本办法", parsed[0][1])
        self.assertIn("适用于各科室", parsed[1][1])

    def test_multiline_clause_body(self):
        text = "第一条 总则要求。\n具体措施如下：\n（一）加强领导。\n第二条 附则。"
        parsed = clauses.parse_clauses(text)
        self.assertEqual(len(parsed), 2)
        self.assertIn("（一）加强领导", parsed[0][1])


class AlignTests(unittest.TestCase):
    def old_new(self, old_text, new_text):
        return clauses.align(clauses.parse_clauses(old_text),
                             clauses.parse_clauses(new_text))

    def test_modified_detected(self):
        recs = self.old_new("第一条 每年休假五天。", "第一条 每年休假十天。")
        self.assertEqual(recs[0]["type"], "modified")

    def test_same_detected(self):
        recs = self.old_new("第一条 依据上级规定执行。", "第一条 依据上级规定执行。")
        self.assertEqual(recs[0]["type"], "same")

    def test_added_and_deleted(self):
        recs = self.old_new("第一条 甲。\n第二条 乙。", "第一条 甲。\n第三条 丙。")
        types = {r["type"] for r in recs}
        self.assertIn("added", types)
        self.assertIn("deleted", types)

    def test_renumber_same_text(self):
        recs = self.old_new("第一条 甲。\n第二条 乙。", "第一条 甲。\n第五条 乙。")
        renum = [r for r in recs if r["type"] == "renumbered"]
        self.assertEqual(len(renum), 1)
        self.assertEqual((renum[0]["old_no"], renum[0]["new_no"]), (2, 5))

    def test_whitespace_only_counts_as_same(self):
        recs = self.old_new("第一条  甲，乙。", "第一条 甲，乙。 ")
        self.assertEqual(recs[0]["type"], "same")


class CliTests(unittest.TestCase):
    def test_align_report_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "old.md")
            new = os.path.join(tmp, "new.md")
            out = os.path.join(tmp, "report.md")
            with open(old, "w", encoding="utf-8") as f:
                f.write("第一条 休假五天。")
            with open(new, "w", encoding="utf-8") as f:
                f.write("第一条 休假十天。\n第二条 新增考核。")
            code, msg = run_main(["align", old, new, "--out", out])
            self.assertEqual(code, 0)
            self.assertIn("已写入", msg)
            report = open(out, encoding="utf-8-sig").read()
            self.assertIn("文字有差异", report)
            self.assertIn("新增", report)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "old.md")
            new = os.path.join(tmp, "new.md")
            with open(old, "w", encoding="utf-8") as f:
                f.write("第一条 甲。")
            with open(new, "w", encoding="utf-8") as f:
                f.write("第一条 乙。")
            code, out = run_main(["align", old, new, "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["records"][0]["type"], "modified")

    def test_no_clause_structure_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "old.md")
            with open(old, "w", encoding="utf-8") as f:
                f.write("这是一段没有条款结构的文字。")
            new = os.path.join(tmp, "new.md")
            with open(new, "w", encoding="utf-8") as f:
                f.write("第一条 有条款。")
            code, out = run_main(["align", old, new])
            self.assertEqual(code, 2)
            self.assertIn("未识别到", out)

    def test_missing_file_exit_2(self):
        code, out = run_main(["align", "no-such-old.md", "no-such-new.md"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
