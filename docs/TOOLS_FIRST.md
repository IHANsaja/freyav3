# CLI-first Freya

Local file, project, code and system tasks now prefer command-line and direct
file/API tools. A dedicated `cli` agent is available to the planner and to
`dispatch_agent`. It can inspect files, read documents, run commands/code and
verify outputs; it has no screenshot or GUI operator tools. Coding work can
still use the coder, web evidence the researcher, and GUI-only work the operator.
The shared policy is appended after the configured personality so existing
installations receive the new routing guidance without replacing their personas.
Command approval rules, command safety checks and the existing 15-second terminal
timeout remain in place. Terminal commands use the platform shell (cmd.exe on
Windows); PowerShell commands must explicitly invoke PowerShell.

## Document-to-research workflow

1. Locate the actual file using the index/list/search tools. A window title can
   help identify a document but is not a verified path. Ask if matches are ambiguous.
2. Read text/code directly. `read_document` adds local PDF text extraction and
   DOCX body/table text extraction, and also accepts UTF-8/UTF-16 text. `read_file`
   routes PDF/DOCX to this reader instead of decoding binary bytes as text.
3. Follow `next_offset` to finish a selected extraction before moving to `next_page`.
   File stat-keyed caching reuses unchanged extraction across steps. The cache is
   bounded and process-local; there is no cloud model call during extraction.
4. Research extracted facts with search/fetch, or DOM browser reading when a real
   browser was requested or interaction is necessary. Reuse citations and excerpts.
5. For scans, `ocr_document` invokes local Tesseract on one PDF page or PNG/JPEG.
   OCR is approximate, not diagram understanding. It has a 20-second OCR timeout,
   image size limits, and no automatic cloud fallback.

Install the updated Python requirements. PDFs use `pypdf`; scanned PDF rendering
uses `pypdfium2`. Local OCR also needs the separately installed Tesseract executable
on PATH. Missing dependencies produce an actionable error, not a screen capture.
PDFs must be unlocked. Extraction is bounded to 10 MB input, up to 10 PDF pages
per call, 200,000 extracted characters, and 20,000 output characters. Complex PDF
content streams can still consume resources during decompression. DOCX headers,
footnotes, images and visual table layout are not extracted. This is a reader, not
a full Office document renderer or spreadsheet engine.

## Browser vision is on demand

Legacy `browser.vision: true` now means visual inspection is *available*, not
that every action attaches an image. Search, navigation, clicks, typing and page
reading return DOM text and numbered controls without screenshots.

The browser can explicitly call `inspect_visual(reason=...)` for a specific
question unavailable from DOM text (e.g. a canvas chart). It receives one viewport
image; old image payloads are removed after that model turn to avoid repeatedly
sending them. `browser.max_visual_requests` defaults to 2 per browser job, with a
hard maximum of 5. `browser.vision: false` or a zero budget disables the action.
Failed screenshot attempts count toward the budget. Screenshot failure or missing
reason never becomes claimed visual evidence.

Explicit 'look at my screen' requests still work in live voice. Generic 'see what
is in this file' wording no longer encourages desktop capture. CLI routing and
live screen choice use model instructions, not a guarantee that a model will
always choose perfectly. Automatic browser captures, however, are removed in code.
Fewer images reduce input volume; fewer nested model steps also reduce requests.
No specific daily-quota reduction is promised.

## Tests

`python -m unittest test_scripts.test_tools_first test_scripts.test_browser_outcomes`
checks default no-image browsing, explicit/disabled/exhausted visual fallback,
missing image handling, real PDF extraction, DOCX paragraphs/table text, pagination,
cache invalidation, binary refusal and CLI tool separation. OCR tests mock the
Tesseract recognition call; PDF rendering is exercised locally. Existing mission,
quota and trading regression suites are also run. Live Windows voice/desktop
behavior is not validated by these tests.
