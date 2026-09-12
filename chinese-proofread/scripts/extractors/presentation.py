"""Extract explicit slide text in presentation order, including notes."""
import report
from .common import local, paragraph, relations, relation_id


def text(node):
    if local(node) == 't':
        return node.text or ''
    if local(node) in ('br', 'tab'):
        return '\n' if local(node) == 'br' else '\t'
    return ''.join(text(child) for child in node)


def extract(raw, roots, max_chars):
    presentation = roots.get('ppt/presentation.xml')
    report.require(presentation is not None, '缺少 PPTX 演示文稿入口')
    rels = relations(roots, 'ppt/presentation.xml')
    blocks, limitations = [], []
    slide_ids = [node for node in presentation.iter() if local(node) == 'sldId']
    report.require(slide_ids, '演示文稿没有幻灯片')
    for number, sid in enumerate(slide_ids, 1):
        target = rels.get(relation_id(sid))
        report.require(target and target[1] == 'slide' and target[0] in roots, '幻灯片关系缺失')
        part = target[0]
        slide = roots[part]
        tree = next((n for n in slide.iter() if local(n) == 'spTree'), None)
        report.require(tree is not None, '幻灯片缺少形状树')
        shape_index = [0]
        def walk(node):
            tag = local(node)
            if tag == 'AlternateContent':
                limitations.append('第%d张幻灯片的兼容分支内容未提取。' % number)
                return
            if tag in ('sp', 'graphicFrame'):
                shape_index[0] += 1
                position = '第%d张幻灯片／对象%d' % (number, shape_index[0])
                table = next((n for n in node.iter() if local(n) == 'tbl'), None)
                if table is not None:
                    for r, row in enumerate((n for n in table if local(n) == 'tr'), 1):
                        for c, cell in enumerate((n for n in row if local(n) == 'tc'), 1):
                            value = '\n'.join(text(n) for n in cell.iter() if local(n) == 'p')
                            paragraph(blocks, value, position + '／表格 R%dC%d' % (r, c), max_chars)
                else:
                    values = [text(n) for n in node.iter() if local(n) == 'p']
                    for index, value in enumerate(values, 1):
                        paragraph(blocks, value, position + '／段落%d' % index, max_chars)
                    if any(local(n) in ('chart', 'relIds', 'oleObj') for n in node.iter()):
                        limitations.append('第%d张幻灯片的图表、SmartArt 或嵌入对象文字未提取。' % number)
                return
            if tag == 'pic':
                limitations.append('第%d张幻灯片的图片文字未识别。' % number)
                return
            for child in node:
                walk(child)
        walk(tree)
        for target_part, kind in relations(roots, part).values():
            if kind != 'notesSlide':
                continue
            report.require(target_part in roots, '幻灯片备注部件缺失')
            for shape in roots[target_part].iter():
                if local(shape) != 'sp':
                    continue
                placeholder = next((n for n in shape.iter() if local(n) == 'ph'), None)
                if placeholder is not None and placeholder.get('type') in ('sldImg', 'sldNum', 'hdr', 'ftr', 'dt'):
                    continue
                for index, value in enumerate((text(n) for n in shape.iter() if local(n) == 'p'), 1):
                    paragraph(blocks, value, '第%d张幻灯片／备注段落%d' % (number, index), max_chars)
    # Master/layout content is not duplicated onto every slide. State this
    # extraction boundary rather than implying reconstruction of rendered pages.
    limitations.append('仅提取幻灯片显式文字和备注；母版、版式继承文字及批注未提取，不还原视觉阅读顺序。')
    return blocks, list(dict.fromkeys(limitations)), '按演示文稿顺序提取全部幻灯片（含隐藏页）的文本框、组合形状、表格和备注；页内按文件对象顺序'
