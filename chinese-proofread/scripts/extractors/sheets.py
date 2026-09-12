"""XLSX uses the standard library; old XLS optionally uses xlrd."""
import io
import re

import report
from .common import local, paragraph, relations, relation_id

MAX_CELLS = 200000


def cell_text(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    return str(value)


def column_name(index):
    value = ''
    while index:
        index, rem = divmod(index - 1, 26)
        value = chr(65 + rem) + value
    return value


def column_index(name):
    result = 0
    for char in name:
        result = result * 26 + ord(char) - 64
    return result


def add_sheet(blocks, name, rows, max_chars):
    # Do not guess headers. Record the first nonempty row explicitly as context;
    # the text to be checked remains exactly the cell's original text value.
    first_row = None
    for row_number, cells in rows:
        nonempty = [(col, value) for col, value in cells if value.strip()]
        if not nonempty:
            continue
        if first_row is None:
            first_row = dict(nonempty)
            first_number = row_number
        for col, value in nonempty:
            position = '%s!%s%d' % (name, column_name(col), row_number)
            context = first_row.get(col)
            if row_number != first_number and context and context != value:
                position += '（第%d行同列：%s）' % (first_number, context[:100])
            paragraph(blocks, value, position, max_chars)


def rich_text(node):
    if local(node) in ('rPh', 'phoneticPr'):
        return ''
    if local(node) == 't':
        return node.text or ''
    return ''.join(rich_text(child) for child in node)


def extract_xlsx(raw, roots, max_chars):
    workbook = roots.get('xl/workbook.xml')
    report.require(workbook is not None, '缺少 XLSX 工作簿入口')
    rels = relations(roots, 'xl/workbook.xml')
    shared = []
    for target, kind in rels.values():
        if kind == 'sharedStrings':
            report.require(target in roots, '共享字符串部件缺失')
            shared = [rich_text(node) for node in roots[target] if local(node) == 'si']
    blocks, notes, total, formulas, drawings = [], [], 0, 0, 0
    for sheet in (n for n in workbook.iter() if local(n) == 'sheet'):
        name = sheet.get('name', '')
        report.require(name, '工作表缺少名称')
        target = rels.get(relation_id(sheet))
        report.require(target and target[0] in roots, '工作表关系或部件缺失：' + name)
        if target[1] != 'worksheet':
            notes.append('非单元格工作表“%s”未提取。' % name)
            continue
        root = roots[target[0]]
        data = next((n for n in root if local(n) == 'sheetData'), None)
        report.require(data is not None, '工作表缺少 sheetData：' + name)
        rows, seen = [], set()
        previous_row = 0
        for row in data:
            if local(row) != 'row':
                continue
            row_number = int(row.get('r', previous_row + 1))
            report.require(previous_row < row_number <= 1048576, '工作表行号重复、乱序或超出范围')
            previous_row = row_number
            values, previous_column = [], 0
            for cell in row:
                if local(cell) != 'c':
                    continue
                total += 1
                report.require(total <= MAX_CELLS, '工作簿超过 200000 个已存单元格处理上限')
                reference = cell.get('r')
                if reference:
                    match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})', reference)
                    report.require(match is not None and int(match.group(2)) == row_number, '单元格坐标无效')
                    col = column_index(match.group(1))
                else:
                    col = previous_column + 1
                report.require(1 <= col <= 16384 and (row_number, col) not in seen, '单元格重复或列号超出范围')
                seen.add((row_number, col)); previous_column = col
                value_node = next((n for n in cell if local(n) == 'v'), None)
                value = (value_node.text or '') if value_node is not None else ''
                kind = cell.get('t', 'n')
                if any(local(n) == 'f' for n in cell):
                    formulas += 1
                if kind == 's':
                    index = int(value)
                    report.require(0 <= index < len(shared), '共享字符串索引超出范围')
                    value = shared[index]
                elif kind == 'inlineStr':
                    inline = next((n for n in cell if local(n) == 'is'), None)
                    report.require(inline is not None, '内联字符串缺少内容节点')
                    value = rich_text(inline)
                elif kind == 'b':
                    report.require(value in ('0', '1'), '布尔单元格值无效')
                    value = 'TRUE' if value == '1' else 'FALSE'
                elif kind not in ('n', 'str', 'e', 'd'):
                    raise ValueError('未支持的单元格类型：' + kind)
                values.append((col, value))
            rows.append((row_number, sorted(values)))
        add_sheet(blocks, name, rows, max_chars)
        drawings += sum(1 for n in root.iter() if local(n) in ('drawing', 'legacyDrawing'))
        if any(kind in ('comments', 'threadedComment') for _, kind in relations(roots, target[0]).values()):
            notes.append('工作表“%s”的批注未提取。' % name)
    if formulas:
        notes.append('公式使用文件内已保存的结果，未重新计算；缺失的缓存结果未提取。')
    if drawings:
        notes.append('工作表中的绘图、文本框和图片未提取。')
    return blocks, list(dict.fromkeys(notes)), '全部单元格工作表（含隐藏工作表和隐藏行列）；保留坐标；数字和日期使用原始已存值，不还原显示格式'


def extract_xls(raw, max_chars):
    import xlrd
    workbook = xlrd.open_workbook(file_contents=raw, on_demand=True, logfile=io.StringIO())
    blocks, total = [], 0
    try:
        for sheet in workbook.sheets():
            total += sheet.nrows * sheet.ncols
            report.require(total <= MAX_CELLS, '工作簿超过 200000 个单元格处理上限')
            def rows():
                for r in range(sheet.nrows):
                    yield r + 1, [(c + 1, cell_text(sheet.cell_value(r, c))) for c in range(sheet.ncols)]
            add_sheet(blocks, sheet.name, rows(), max_chars)
    finally:
        workbook.release_resources()
    return blocks, ['仅提取单元格值；绘图、文本框、图片和批注未提取，公式未重新计算。'], 'XLS 全部工作表单元格（含隐藏内容）；值为文件已存结果，不还原数字和日期显示格式'
