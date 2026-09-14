import base64
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from core.browser.agent import BrowserAgent, _tools
from core.document_reader import read_document, _extract, ocr_document
from core.registry import ToolContext


class BrowserVisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent=BrowserAgent.__new__(BrowserAgent)
        self.agent.use_vision=True;self.agent.visual_requests=0;self.agent.max_visual_requests=1;self.agent.visited=[]
        self.browser=NS(view=NS(url='https://example.com',render=lambda:'Article text and [1] link'),screenshot=AsyncMock(return_value=base64.b64encode(b'image').decode()))
    async def test_normal_steps_never_capture_even_with_legacy_vision_true(self):
        for action in ['search','read','click','type']:
            parts=await self.agent._observe(self.browser,action)
            self.assertTrue(all(p.inline_data is None for p in parts))
        self.browser.screenshot.assert_not_awaited()
    async def test_explicit_visual_question_captures_once(self):
        parts=await self.agent._observe(self.browser,'inspect',visual_reason='Explain the unlabeled canvas diagram')
        self.assertEqual(parts[-1].inline_data.data,b'image')
        again=await self.agent._observe(self.browser,'inspect',visual_reason='Explain diagram again')
        self.assertTrue(all(p.inline_data is None for p in again))
        self.assertEqual(self.browser.screenshot.await_count,1)
    async def test_disabled_and_missing_reason_do_not_capture(self):
        await self.agent._observe(self.browser,'inspect',visual_reason='')
        self.agent.use_vision=False
        await self.agent._observe(self.browser,'inspect',visual_reason='Explain canvas diagram')
        self.browser.screenshot.assert_not_awaited()
        self.assertNotIn('inspect_visual',[d.name for t in _tools(False) for d in t.function_declarations])
    async def test_unavailable_image_is_not_claimed(self):
        self.browser.screenshot.return_value=None
        parts=await self.agent._observe(self.browser,'inspect',visual_reason='Explain canvas diagram')
        self.assertIn('no visual evidence',parts[-1].text)


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);_extract.cache_clear()
    def tearDown(self):self.tmp.cleanup()
    def read(self,path,**kwargs):return read_document({'path':str(path),**kwargs},ToolContext({}))
    def test_text_continuation_and_cache_invalidation(self):
        p=self.root/'notes.txt';p.write_text('hello '*100)
        first=json.loads(self.read(p,max_chars=100));second=json.loads(self.read(p,max_chars=100,offset=100))
        self.assertEqual(first['next_offset'],100);self.assertEqual(second['offset'],100)
        self.assertGreater(_extract.cache_info().hits,0)
        p.write_text('new evidence')
        self.assertEqual(json.loads(self.read(p))['text'],'new evidence')
    def test_docx_body_and_table(self):
        p=self.root/'notes.docx'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Research question</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table evidence</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        result=json.loads(self.read(p));self.assertIn('Table evidence',result['text']);self.assertIn('Research question',result['text'])
    def test_binary_missing_and_invalid_bounds(self):
        p=self.root/'binary.dat';p.write_bytes(b'\x00\x01')
        self.assertIn('Binary file',self.read(p))
        self.assertIn('Could not extract',self.read(self.root/'missing'))
        self.assertIn('Invalid page range',self.read(p,page_count=100))
    def test_actual_pdf_page_evidence_and_empty_scan_hint(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        p=self.root/'test.pdf';writer=PdfWriter();page=writer.add_blank_page(width=200,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 100 Td (File research evidence) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream);writer.add_blank_page(width=200,height=200)
        with p.open('wb') as out:writer.write(out)
        first=json.loads(self.read(p,page_count=1));self.assertIn('File research evidence',first['text']);self.assertEqual(first['next_page'],2)
        second=json.loads(self.read(p,page_start=2));self.assertTrue(any('no text layer' in n for n in second['notes']))
    def test_read_file_routes_documents(self):
        from core.system_tools import read_file
        with patch('core.document_reader.read_document',return_value='extracted') as reader:
            self.assertEqual(read_file({'path':str(self.root/'test.pdf')},ToolContext({})),'extracted')
            reader.assert_called_once()
    def test_cli_agent_has_no_gui_or_screen_tools(self):
        from core.agents import DEFAULT_AGENTS
        tools=DEFAULT_AGENTS['cli']['tools']
        self.assertIn('run_terminal_command',tools);self.assertIn('read_document',tools)
        self.assertFalse({'capture_screen','browser_task','click_element'}.intersection(tools))

    def test_local_ocr_image_without_cloud(self):
        from PIL import Image
        p=self.root/'scan.png';Image.new('RGB',(20,20),'white').save(p)
        engine=NS(image_to_string=lambda image,timeout:'Scanned evidence')
        with patch.dict('sys.modules',{'pytesseract':engine}):
            result=json.loads(ocr_document({'path':str(p)},ToolContext({})))
        self.assertEqual(result['method'],'local_ocr');self.assertEqual(result['text'],'Scanned evidence')

    def test_selected_pdf_page_local_render_for_ocr(self):
        from pypdf import PdfWriter
        p=self.root/'scan.pdf';writer=PdfWriter();writer.add_blank_page(width=200,height=200)
        with p.open('wb') as out:writer.write(out)
        engine=NS(image_to_string=lambda image,timeout:'Local PDF OCR')
        with patch.dict('sys.modules',{'pytesseract':engine}):
            result=json.loads(ocr_document({'path':str(p),'page':1},ToolContext({})))
        self.assertEqual(result['text'],'Local PDF OCR')
