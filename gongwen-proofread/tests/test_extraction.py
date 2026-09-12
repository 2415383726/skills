"""Real file/parser and host-handoff regression tests; no model calls."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / 'scripts'))
try:
    import openpyxl
except ImportError:
    openpyxl = None

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
TYPES = 'http://schemas.openxmlformats.org/package/2006/content-types'


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gongwen-extract-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.output = self.work / 'document.json'

    def call(self, *args, ok=True, no_dependencies=False):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if no_dependencies:
            env.pop('PYTHONPATH', None)
        result = subprocess.run([sys.executable, *(['-S'] if no_dependencies else []),
                                 str(SKILL / 'scripts/extract_file.py'), *map(str,args)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0 if ok else 2, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def extract(self, source, *extra):
        return self.call('--input', source, '--output', self.output, *extra)

    def doc(self):
        return json.loads(self.output.read_text())

    def package(self, filename, parts):
        path = self.work / filename
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            for name,value in parts.items():
                z.writestr(name,value)
        return path

    def test_txt_text_and_markdown_are_preserved(self):
        original = '# 工作安排\n\n请尽快部暑。\n```python\nf(x, y)\n```\n[资料](https://example.invalid/a?x=1)\n'
        for suffix in ('.txt','.text','.md','.markdown'):
            with self.subTest(suffix=suffix):
                source=self.work/('source'+suffix); source.write_text(original,encoding='utf-8-sig')
                result=self.extract(source,'--overwrite')
                self.assertEqual(result['action'],'ready')
                self.assertEqual([b['text'] for b in self.doc()['blocks']], [s for s in original.splitlines() if s.strip()])
                self.assertEqual(result['suggested_delivery'],'chat')
                self.assertEqual(self.doc()['provenance']['source_path'],str(source.resolve()))

    def test_utf16_and_explicit_legacy_encoding(self):
        source=self.work/'通知.txt'; source.write_bytes('工作安排。'.encode('utf-16'))
        self.assertEqual(self.extract(source)['action'],'ready')
        source.write_bytes('工作安排。'.encode('gb18030'))
        self.assertEqual(self.extract(source,'--overwrite')['action'],'host_extract')
        self.assertEqual(self.extract(source,'--overwrite','--encoding','gb18030')['action'],'ready')
        self.assertEqual(self.doc()['blocks'][0]['text'],'工作安排。')

    def test_docx_sniffing_handles_standard_content_with_wps_extension(self):
        source=self.package('材料.wps',{
            '[Content_Types].xml':f'<Types xmlns="{TYPES}"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            'word/document.xml':f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>请尽快</w:t></w:r><w:r><w:t>部暑。</w:t></w:r></w:p></w:body></w:document>'})
        result=self.extract(source)
        self.assertEqual(result['detected_format'],'docx')
        self.assertEqual(self.doc()['blocks'][0]['text'],'请尽快部暑。')

    @unittest.skipIf(openpyxl is None, "openpyxl is needed to generate this XLSX fixture")
    def test_xlsx_multiple_sheets_sparse_cells_and_context(self):
        workbook=openpyxl.Workbook(); sheet=workbook.active; sheet.title='工作计划'
        sheet.append(['部门','任务']); sheet.append(['综合处','工作部暑'])
        sheet['D5']='保留空列'; sheet['E6']='=1+1'
        hidden=workbook.create_sheet('内部记录');hidden.sheet_state='hidden';hidden['B2']='归档内容'
        source=self.work/'计划.xlsx';workbook.save(source)
        result=self.extract(source)
        self.assertEqual(result['detected_format'],'xlsx')
        blocks=self.doc()['blocks'];self.assertTrue(any(b['text']=='工作部暑' and '工作计划!B2' in b['location'] and '任务' in b['location'] for b in blocks))
        self.assertTrue(any(b['text']=='归档内容' and '内部记录!B2' in b['location'] for b in blocks))
        self.assertFalse(any(b['text']=='=1+1' for b in blocks))
        self.assertTrue(any('缓存' in note for note in self.doc()['limitations']))

    def test_pptx_slide_order_group_text_table_notes_and_locations(self):
        def shape(value):
            return f'<p:sp><p:txBody><a:p><a:r><a:t>{value}</a:t></a:r></a:p></p:txBody></p:sp>'
        def slide(value):
            return f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree><p:grpSp>{shape(value)}</p:grpSp></p:spTree></p:cSld></p:sld>'
        source=self.package('演示.pptx',{
            '[Content_Types].xml':f'<Types xmlns="{TYPES}"><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/></Types>',
            'ppt/presentation.xml':f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst><p:sldId id="2" r:id="r2"/><p:sldId id="1" r:id="r1"/></p:sldIdLst></p:presentation>',
            'ppt/_rels/presentation.xml.rels':f'<Relationships xmlns="{PKG}"><Relationship Id="r1" Type="{R}/slide" Target="slides/slide1.xml"/><Relationship Id="r2" Type="{R}/slide" Target="slides/slide2.xml"/></Relationships>',
            'ppt/slides/slide1.xml':slide('第二页文字'),
            'ppt/slides/slide2.xml':slide('第一页文字'),
            'ppt/slides/_rels/slide2.xml.rels':f'<Relationships xmlns="{PKG}"><Relationship Id="n1" Type="{R}/notesSlide" Target="../notesSlides/notesSlide1.xml"/></Relationships>',
            'ppt/notesSlides/notesSlide1.xml':f'<p:notes xmlns:p="{P}" xmlns:a="{A}">{shape("讲解备注")}</p:notes>'})
        self.assertEqual(self.extract(source)['detected_format'],'pptx')
        blocks=self.doc()['blocks'];self.assertEqual([b['text'] for b in blocks],['第一页文字','讲解备注','第二页文字'])
        self.assertIn('第1张幻灯片',blocks[0]['location']);self.assertIn('第2张幻灯片',blocks[2]['location'])

    def test_unsupported_host_text_resume_then_pipeline_dispatch(self):
        source=self.work/'old.doc';source.write_bytes(b'unsupported legacy fixture')
        result=self.extract(source)
        self.assertEqual(result['action'],'host_extract');self.assertFalse(self.output.exists())
        host=Path(result['host_output_path']);host.write_text('宿主提取的原文。',encoding='utf-8')
        resumed=self.call('--resume',result['request_path'],'--scope','宿主读取的正文')
        self.assertEqual(resumed['action'],'ready')
        self.assertEqual(self.doc()['source_name'],'old.doc')
        self.assertEqual(self.doc()['provenance']['source_path'],str(source.resolve()))
        result=subprocess.run([sys.executable,str(SKILL/'scripts/tasks.py'),'step','--work',str(self.work),'--coordinator','fixture'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['action'],'dispatch')

    def test_source_changes_block_host_resume(self):
        source=self.work/'材料.dps';source.write_bytes(b'version1')
        result=self.extract(source)
        Path(result['host_output_path']).write_text('旧内容',encoding='utf-8')
        source.write_bytes(b'version2')
        failed=self.call('--resume',result['request_path'],ok=False)
        self.assertEqual(failed['action'],'blocked');self.assertIn('源文件已变化',failed['reason'])
        self.assertFalse(self.output.exists())

    def test_structured_host_result_preserves_locations(self):
        source=self.work/'材料.ppt';source.write_bytes(b'legacy')
        result=self.extract(source)
        host=self.work/'host.json';host.write_text(json.dumps({'title':'ignored','source_name':'ignored','scope':'宿主读取全部幻灯片','limitations':[],
            'blocks':[{'id':'s1','kind':'paragraph','text':'工作安排','location':'第3张幻灯片／标题'}]},ensure_ascii=False))
        self.call('--resume',result['request_path'],'--host-document',host)
        self.assertEqual(self.doc()['blocks'][0]['location'],'第3张幻灯片／标题')
        self.assertEqual(self.doc()['source_name'],'材料.ppt')

    def test_invalid_host_result_does_not_loop_or_create_document(self):
        source=self.work/'材料.wps';source.write_bytes(b'legacy')
        result=self.extract(source)
        Path(result['host_output_path']).write_text('',encoding='utf-8')
        failed=self.call('--resume',result['request_path'],ok=False)
        self.assertEqual(failed['action'],'blocked');self.assertNotIn('resume_command',failed)
        self.assertFalse(self.output.exists())

    def test_output_cannot_overwrite_source(self):
        source=self.work/'原文.txt';source.write_text('原文')
        result=self.call('--input',source,'--output',source,'--overwrite',ok=False)
        self.assertEqual(result['action'],'blocked');self.assertEqual(source.read_text(),'原文')

    def test_xml_entity_package_is_not_read(self):
        source=self.package('坏文件.docx',{'[Content_Types].xml':'<!DOCTYPE Types [<!ENTITY x "text">]><Types>&x;</Types>'})
        result=self.extract(source)
        self.assertEqual(result['action'],'host_extract');self.assertIn('DTD',result['reason'])
        self.assertFalse(self.output.exists())

    def test_missing_xls_dependency_is_actionable_and_can_use_host(self):
        source = self.work/'legacy.xls'
        source.write_bytes((SKILL/'tests/fixtures/legacy.xls').read_bytes())
        result = self.call('--input', source, '--output', self.output, no_dependencies=True)
        self.assertEqual(result['action'], 'install_dependency')
        self.assertEqual(result['requirement'], 'xlrd')
        self.assertIn('--host-fallback', result['fallback_command'])
        self.assertFalse(self.output.exists())
        fallback = self.call('--input', source, '--output', self.output,
                             '--host-fallback', no_dependencies=True)
        self.assertEqual(fallback['action'], 'host_extract')

    def test_real_xls_when_dependency_available(self):
        try:
            import xlrd
        except ImportError:
            self.skipTest('Install xlrd to test legacy XLS parsing')
        result = self.extract(SKILL/'tests/fixtures/legacy.xls')
        self.assertEqual(result['action'], 'ready')
        self.assertTrue(any(b['text']=='工作部暑' and '工作计划!B2' in b['location'] for b in self.doc()['blocks']))

    def test_xlsx_stdlib_fallback_without_site_packages(self):
        source = self.package('标准表格.xlsx', {
            '[Content_Types].xml': f'<Types xmlns="{TYPES}"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
            'xl/workbook.xml': f'<workbook xmlns:r="{R}"><sheets><sheet name="计划" sheetId="1" r:id="r1"/></sheets></workbook>',
            'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{PKG}"><Relationship Id="r1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Type="{R}/sharedStrings" Target="sharedStrings.xml"/></Relationships>',
            'xl/sharedStrings.xml': '<sst><si><r><t>工作</t></r><r><t>部暑</t></r><rPh><t>phonetic</t></rPh></si></sst>',
            'xl/worksheets/sheet1.xml': '<worksheet><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>任务</t></is></c></row><row r="1000000"><c r="A1000000" t="s"><v>0</v></c></row></sheetData></worksheet>'})
        result = self.call('--input',source,'--output',self.output,no_dependencies=True)
        self.assertEqual(result['action'],'ready')
        self.assertEqual(self.doc()['extraction_backend'],'xlsx stdlib')
        self.assertEqual([b['text'] for b in self.doc()['blocks']],['任务','工作部暑'])
        self.assertIn('A1000000',self.doc()['blocks'][1]['location'])


if __name__=='__main__':
    unittest.main()
