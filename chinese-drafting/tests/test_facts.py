# -*- coding: utf-8 -*-
"""facts.py 机械回归：占位符扫描、类别判断、定稿检查、骨架生成、编码兼容。

运行：python -m unittest discover -s chinese-drafting/tests -v
测试只验证脚本行为，不代表起草语言质量；语言质量见 evals/。
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
TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "assets", "templates"))
sys.path.insert(0, SCRIPTS)

import facts  # noqa: E402


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = facts.main(argv)
    return code, out.getvalue()


class MarkerTests(unittest.TestCase):
    def test_find_markers_counts_and_lines(self):
        text = "第一行\n全年培训【待补：数字－全年培训期数】期。\n由【待补：人名－分管副局长姓名】带队。"
        items = facts.find_markers(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["line"], 2)
        self.assertEqual(items[1]["line"], 3)
        self.assertEqual(items[0]["category"], "数字")
        self.assertEqual(items[1]["category"], "人名")

    def test_marker_without_space_after_dash(self):
        items = facts.find_markers("【待补：文号－上级通知文号】")
        self.assertEqual(items[0]["category"], "文号")

    def test_category_defaults_to_other(self):
        items = facts.find_markers("关于【待补：具体事由】的请示")
        self.assertEqual(items[0]["category"], "其他")

    def test_clean_text_has_no_markers(self):
        self.assertEqual(facts.find_markers("特此通知。\n妥否，请批示。"), [])

    def test_unclosed_marker_warning(self):
        text = "正常句。【待补：缺右括号的一处"
        warnings = facts.find_warnings(text)
        self.assertTrue(any("未闭合" in w for w in warnings))

    def test_anonymous_placeholder_warning(self):
        warnings = facts.find_warnings("由某某同志负责。")
        self.assertTrue(any("×××/某某" in w for w in warnings))

    def test_english_placeholders(self):
        self.assertEqual(facts.find_english_placeholders("ok line"), [])
        self.assertEqual(facts.find_english_placeholders("TODO fill me"), [1])


class CheckTests(unittest.TestCase):
    def test_check_clean_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clean.md")
            facts.write_text(path, "# 标题\n正文没有占位符。\n")
            code, out = run_main(["check", path])
            self.assertEqual(code, 0)
            self.assertIn("可申请定稿", out)

    def test_check_dirty_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dirty.md")
            facts.write_text(path, "金额【待补：数字－总额】万元。")
            code, out = run_main(["check", path])
            self.assertEqual(code, 1)
            self.assertIn("数字－总额", out)

    def test_check_english_placeholder_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "todo.md")
            facts.write_text(path, "next: TODO 补数据")
            code, out = run_main(["check", path])
            self.assertEqual(code, 1)


class ScanTests(unittest.TestCase):
    def test_scan_markdown_output_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft = os.path.join(tmp, "d.md")
            listing = os.path.join(tmp, "list.md")
            facts.write_text(draft, "依据【待补：文号－通知文号】要求。")
            code, out = run_main(["scan", draft, "--out", listing])
            self.assertEqual(code, 0)
            self.assertIn("已写入", out)
            content = facts.read_text(listing)
            self.assertIn("# 待补事实清单", content)
            self.assertIn("文号", content)

    def test_scan_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft = os.path.join(tmp, "d.md")
            facts.write_text(draft, "【待补：时间－完工节点】前完成。")
            code, out = run_main(["scan", draft, "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["items"][0]["category"], "时间")

    def test_scan_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            run_main(["scan", os.path.join("no", "such.md")])


class EncodingTests(unittest.TestCase):
    def test_read_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bom.md")
            with open(path, "wb") as f:
                f.write("【待补：数字－人数】".encode("utf-8-sig"))
            items = facts.find_markers(facts.read_text(path))
            self.assertEqual(len(items), 1)

    def test_read_gbk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gbk.md")
            with open(path, "wb") as f:
                f.write("【待补：部门－牵头科室】".encode("gbk"))
            items = facts.find_markers(facts.read_text(path))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["category"], "部门")


class NewTests(unittest.TestCase):
    def test_every_template_type_scaffolds(self):
        for name in facts.list_types():
            self.assertTrue(os.path.isfile(os.path.join(TEMPLATES, name + ".md")), name)
            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, name + "-draft.md")
                code, msg = run_main(["new", name, "-o", out])
                self.assertEqual(code, 0, name)
                text = facts.read_text(out)
                self.assertIn("【待补", text, name)
                self.assertIn(str(len(facts.MARKER_RE.findall(text))), msg, name)

    def test_new_replaces_first_heading_with_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "t.md")
            code, _ = run_main(["new", "work-summary", "--title", "××单位2025年工作总结", "-o", out])
            self.assertEqual(code, 0)
            self.assertTrue(facts.read_text(out).startswith("# ××单位2025年工作总结\n"))

    def test_new_unknown_type_exits(self):
        with self.assertRaises(SystemExit):
            run_main(["new", "no-such-type"])

    def test_new_list_prints_types(self):
        code, out = run_main(["new", "--list"])
        self.assertEqual(code, 0)
        self.assertIn("work-summary", out)
        self.assertIn("speech", out)

    def test_templates_count_is_nine(self):
        self.assertEqual(len(facts.list_types()), 9)


if __name__ == "__main__":
    unittest.main()
