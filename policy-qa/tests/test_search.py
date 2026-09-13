# -*- coding: utf-8 -*-
"""search.py 机械回归：文件遍历、关键词命中、docx 提取、编码兼容、输出契约。

运行：python -m unittest discover -s policy-qa/tests -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)

import search  # noqa: E402


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = search.main(argv)
    return code, out.getvalue()


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def write(self, name, content, encoding="utf-8"):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if encoding == "utf-8" else "w"
        if encoding == "utf-8":
            with open(path, "wb") as f:
                f.write(content.encode("utf-8"))
        else:
            with open(path, "w", encoding=encoding, newline="\n") as f:
                f.write(content)
        return path

    def test_finds_keyword_with_line_number(self):
        self.write("考勤制度.md", "第一条 上班时间。\n第五条 年休假按工龄核定。\n第六条 病假管理。")
        code, out = run_main([self.root, "年休假"])
        self.assertEqual(code, 0)
        self.assertIn("第2行", out)
        self.assertIn("年休假按工龄核定", out)
        self.assertIn("命中 1 个文件、1 处", out)

    def test_multiple_keywords_or_semantics(self):
        self.write("a.md", "差旅费报销标准另文规定。")
        self.write("b.md", "出差审批流程如下。")
        code, out = run_main([self.root, "差旅费", "出差"])
        self.assertEqual(code, 0)
        self.assertIn("a.md", out)
        self.assertIn("b.md", out)

    def test_extension_filter_skips_others(self):
        self.write("制度.doc", "年休假在这里，但doc不支持")
        code, out = run_main([self.root, "年休假", "--ext", "md,txt,docx"])
        self.assertEqual(code, 0)
        self.assertIn("扫描 0 个文件", out)

    def test_gbk_file_readable(self):
        path = os.path.join(self.root, "old.txt")
        with open(path, "w", encoding="gbk", newline="\n") as f:
            f.write("第二条 探亲假报销。")
        code, out = run_main([path, "探亲假"])
        self.assertEqual(code, 0)
        self.assertIn("第1行", out)

    def test_docx_extracted_and_matched(self):
        path = os.path.join(self.root, "办法.docx")
        paras = ["第一条 总则", "第七条 带薪年休假天数为五天。", "第八条 附则"]
        with zipfile.ZipFile(path, "w") as z:
            body = "".join(
                "<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % p for p in paras
            )
            z.writestr("word/document.xml",
                       '<?xml version="1.0"?><w:document xmlns:w="http://schemas.'
                       'openxmlformats.org/wordprocessingml/2006/main"><w:body>%s'
                       "</w:body></w:document>" % body)
        code, out = run_main([path, "年休假"])
        self.assertEqual(code, 0)
        self.assertIn("第2段", out)
        self.assertIn("五天", out)

    def test_json_output_contract(self):
        self.write("m.md", "有条款。")
        code, out = run_main([self.root, "条款", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["total_hits"], 1)
        self.assertEqual(payload["results"][0]["hits"][0]["line"], 1)

    def test_missing_path_exit_code_2(self):
        code, out = run_main([os.path.join(self.root, "none"), "词"])
        self.assertEqual(code, 2)
        self.assertIn("路径不存在", out)

    def test_no_hit_hint(self):
        self.write("x.md", "无关内容。")
        code, out = run_main([self.root, "年休假"])
        self.assertEqual(code, 0)
        self.assertIn("未命中", out)


class DocxUnitTests(unittest.TestCase):
    def test_corrupt_docx_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.docx")
            with open(path, "wb") as f:
                f.write(b"not a zip")
            with self.assertRaises(ValueError):
                search.extract_docx_text(path)


if __name__ == "__main__":
    unittest.main()
