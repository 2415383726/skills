# -*- coding: utf-8 -*-
"""table.py 机械回归：xlsx 解析、类型推断、日期转换、聚合、CLI 契约。

运行：python -m unittest discover -s excel-analysis/tests -v
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)

import table  # noqa: E402


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = table.main(argv)
    return code, out.getvalue()


def make_csv(tmp, name, content, encoding="utf-8"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(content)
    return path


def make_xlsx(tmp, name, sheets):
    """构造最小 xlsx：sheets = [ (名称, [[r1c1, r1c2], ...]) ]，均视为内联文本/数字。"""
    path = os.path.join(tmp, name)
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    sheet_xmls, names, targets = [], [], []
    for i, (name_, rows) in enumerate(sheets, start=1):
        body = ""
        for r, row in enumerate(rows, start=1):
            cells = ""
            for c, val in enumerate(row, start=1):
                col = table.column_name(c) if hasattr(table, "column_name") else chr(64 + c)
                cells += '<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' % (col, r, val)
            body += '<row r="%d">%s</row>' % (r, cells)
        sheet_xmls.append(
            '<?xml version="1.0"?><worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>'
            % (ns, body))
        names.append(name_)
        targets.append("worksheets/sheet%d.xml" % i)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>'
                   % (ns, rel_ns,
                      "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (n, i, i)
                              for i, n in enumerate(names, start=1))))
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
                   % "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="%s"/>' % (i, t)
                             for i, t in enumerate(targets, start=1)))
        for i, xml in enumerate(sheet_xmls, start=1):
            z.writestr("xl/worksheets/sheet%d.xml" % i, xml)
    return path


class ReaderTests(unittest.TestCase):
    def test_read_xlsx_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_xlsx(tmp, "t.xlsx", [("台账", [["部门", "人数"], ["综合科", "12"], ["财务科", "8"]])])
            rows = table.load_rows(path, None)
            self.assertEqual(rows[0], ["部门", "人数"])
            self.assertEqual(rows[2], ["财务科", "8"])

    def test_read_csv_gbk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_csv(tmp, "t.csv", "部门,人数\n综合科,12\n", encoding="gbk")
            rows = table.load_rows(path, None)
            self.assertEqual(rows[1], ["综合科", "12"])

    def test_to_number_variants(self):
        self.assertEqual(table.to_number("1,234"), 1234)
        self.assertEqual(table.to_number("23.5%"), 0.235)
        self.assertEqual(table.to_number("12"), 12)
        self.assertIsNone(table.to_number("综合科"))
        self.assertIsNone(table.to_number(""))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv = make_csv(self.tmp.name, "d.csv",
                            "科室,性别,基本工资\n综合科,女,5000\n综合科,男,6000\n财务科,男,5500\n")

    def test_profile_reports_columns(self):
        code, out = run_main(["profile", self.csv])
        self.assertEqual(code, 0)
        self.assertIn("3 行 × 3 列", out)
        self.assertIn("基本工资[数值]", out)
        self.assertIn("合计 16500", out)
        self.assertIn("科室[文本]", out)

    def test_header_option_skips_title_row(self):
        path = make_csv(self.tmp.name, "t.csv", "2025年人员台账\n科室,人数\n综合科,12\n")
        code, out = run_main(["profile", path, "--header", "1"])
        self.assertEqual(code, 0)
        self.assertIn("人数[数值]", out)

    def test_groupby_sum_and_count(self):
        code, out = run_main(["groupby", self.csv, "--by", "科室", "--agg", "count", "--agg", "sum:基本工资"])
        self.assertEqual(code, 0)
        self.assertIn("| 综合科 | 2 | 11000 |", out)
        self.assertIn("| 财务科 | 1 | 5500 |", out)

    def test_groupby_unknown_column_exits(self):
        code, out = run_main(["groupby", self.csv, "--by", "不存在", "--agg", "count"])
        self.assertEqual(code, 2)
        self.assertIn("找不到列", out)

    def test_xlsx_profile_via_cli(self):
        path = make_xlsx(self.tmp.name, "t.xlsx",
                         [("Sheet1", [["部门", "月份", "金额"], ["甲", "202501", "100"], ["乙", "202502", "200"]])])
        code, out = run_main(["profile", path])
        self.assertEqual(code, 0)
        self.assertIn("金额[数值]", out)

    def test_missing_file_exit(self):
        code, out = run_main(["profile", os.path.join(self.tmp.name, "none.csv")])
        self.assertEqual(code, 2)

    def test_preview_shows_rows(self):
        code, out = run_main(["preview", self.csv, "--rows", "2"])
        self.assertEqual(code, 0)
        self.assertIn("表头", out)
        self.assertIn("综合科", out)


if __name__ == "__main__":
    unittest.main()
