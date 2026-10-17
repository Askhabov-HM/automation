"""Content-driven PDF layouts, validation and reusable local resources."""
from pathlib import Path
from xml.sax.saxutils import escape
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import uuid


class PdfError(Exception):
    def __init__(self, code, message, stage='input', page=None):
        super().__init__(message)
        self.code, self.stage, self.page = code, stage, page


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def key_for(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def require(ok, code, message):
    if not ok:
        raise PdfError(code, message)


def load_content(path):
    path = Path(path).resolve()
    if path.suffix.lower() == '.md':
        content = {'title': path.stem, 'sections': []}
        section = {'title': 'Содержание', 'blocks': []}
        lines = []
        def flush():
            if lines:
                section['blocks'].append({'type': 'paragraph', 'text': ' '.join(lines)})
                lines.clear()
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.startswith('# '):
                flush(); content['title'] = line[2:].strip()
            elif line.startswith('## '):
                flush()
                if section['blocks']:
                    content['sections'].append(section)
                section = {'title': line[3:].strip(), 'blocks': []}
            elif not line.strip():
                flush()
            elif line.startswith('- '):
                flush(); section['blocks'].append({'type': 'paragraph', 'text': '• ' + line[2:]})
            else:
                lines.append(line.strip())
        flush()
        if section['blocks']:
            content['sections'].append(section)
    else:
        content = json.loads(path.read_text(encoding='utf-8-sig'))
    require(isinstance(content, dict), 'invalid_document', 'Document must be an object.')
    require(isinstance(content.get('title'), str) and content['title'].strip(), 'invalid_title', 'A non-empty title is required.')
    for field in ('subtitle', 'description', 'date', 'author'):
        require(field not in content or isinstance(content[field], str), 'invalid_metadata', f'{field} must be text.')
    require('cover' not in content or type(content['cover']) is bool, 'invalid_metadata', 'cover must be true or false.')
    require(isinstance(content.get('sections'), list) and content['sections'], 'invalid_sections', 'At least one section is required.')
    allowed = {'paragraph', 'heading', 'list', 'callout', 'image', 'chart', 'table', 'link', 'quote'}
    for si, section in enumerate(content['sections'], 1):
        require(isinstance(section, dict) and isinstance(section.get('title'), str), 'invalid_section', f'Section {si} needs a title.')
        require(isinstance(section.get('blocks'), list) and section['blocks'], 'invalid_blocks', f'Section {si} needs content blocks.')
        for field in ('description', 'kicker'):
            require(field not in section or isinstance(section[field], str), 'invalid_metadata', f'Section {field} must be text.')
        for bi, block in enumerate(section['blocks'], 1):
            require(isinstance(block, dict) and block.get('type') in allowed, 'invalid_block', f'Unsupported block in section {si}, position {bi}.')
            kind = block['type']
            if kind in {'paragraph', 'heading', 'quote'}:
                require(isinstance(block.get('text'), str), 'invalid_text', f'Text is required in section {si}, block {bi}.')
            if kind == 'list':
                require(isinstance(block.get('items'), list) and all(isinstance(x, str) for x in block['items']), 'invalid_list', 'List items must be strings.')
            if kind == 'callout':
                require(all(isinstance(block.get(k), str) for k in ('title', 'text')), 'invalid_callout', 'Callout needs title and text.')
            if kind == 'image':
                require(isinstance(block.get('source'), str) and isinstance(block.get('caption'), str), 'invalid_image', 'Image needs a local source and a caption.')
            if kind == 'link':
                require(isinstance(block.get('text'), str) and re.match(r'^https?://[^\s]+$', block.get('url', '')), 'invalid_link', 'Link needs text and an HTTP(S) URL.')
            if kind == 'chart':
                values = block.get('values')
                require(block.get('kind') in {'line', 'bars', 'donut'}, 'invalid_chart', 'Supported charts: line, bars, donut.')
                require(isinstance(values, list) and 1 <= len(values) <= 24 and all(type(x) in (int, float) and math.isfinite(x) for x in values), 'invalid_chart_values', 'Chart needs 1-24 finite numbers.')
                labels = block.get('labels')
                require(isinstance(labels, list) and len(labels) == len(values) and all(isinstance(x, str) for x in labels), 'invalid_chart_labels', 'Provide one text label per chart value.')
                if block['kind'] == 'donut':
                    require(min(values) >= 0 and sum(values) > 0, 'invalid_donut', 'Donut values must be non-negative with a positive sum.')
            if kind == 'table':
                columns, rows = block.get('columns'), block.get('rows')
                require(isinstance(columns, list) and 1 <= len(columns) <= 10 and all(isinstance(x, str) for x in columns), 'invalid_columns', 'Table needs 1-10 column names.')
                require(isinstance(rows, list) and rows and all(isinstance(row, list) and len(row) == len(columns) and all(type(x) in (str, int, float) for x in row) for row in rows), 'invalid_rows', 'All table rows must match the columns.')
                widths = block.get('widths', [1] * len(columns))
                require(isinstance(widths, list) and len(widths) == len(columns) and all(type(x) in (int, float) and math.isfinite(x) and x > 0 for x in widths), 'invalid_widths', 'Table widths must be positive numbers, one per column.')
                require('delta_column' not in block or (type(block['delta_column']) is int and 0 <= block['delta_column'] < len(columns)), 'invalid_delta_column', 'delta_column must be a zero-based column index.')
    return content


def collect_text(content):
    texts = [content['title']]
    if content.get('subtitle'):
        texts.append(content['subtitle'])
    for section in content['sections']:
        texts.append(section['title'])
        for b in section['blocks']:
            for key in ('text', 'caption'):
                if b.get(key): texts.append(b[key])
            if b['type'] == 'callout': texts.append(b['title'])
            if b['type'] == 'list': texts.extend(b['items'])
            if b['type'] == 'table':
                texts.extend(b['columns'])
                texts.extend(str(cell) for row in b['rows'] for cell in row)
    return texts


def fonts(root, supplied=None):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [Path(supplied)] if supplied else [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts', Path('/usr/share/fonts/truetype/dejavu'), root / 'assets/fonts']
    bundles = [
        {'Sans': ['arial.ttf', 'arialbd.ttf', 'ariali.ttf', 'arialbi.ttf'], 'Mono': ['consola.ttf', 'consolab.ttf', 'consolai.ttf', 'consolaz.ttf']},
        {'Sans': ['DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'DejaVuSans-Oblique.ttf', 'DejaVuSans-BoldOblique.ttf'], 'Mono': ['DejaVuSansMono.ttf', 'DejaVuSansMono-Bold.ttf', 'DejaVuSansMono-Oblique.ttf', 'DejaVuSansMono-BoldOblique.ttf']},
    ]
    for folder in candidates:
        for bundle in bundles:
            if all((folder / f).is_file() for names in bundle.values() for f in names):
                hashes = {}; cache = root / '.cache/fonts'; cache.mkdir(parents=True, exist_ok=True)
                for family, names in bundle.items():
                    for suffix, name in zip(['', '-Bold', '-Italic', '-BoldItalic'], names):
                        source = folder / name; sha = digest(source); target = cache / (sha + '.ttf')
                        if not target.exists() or digest(target) != sha: shutil.copy2(source, target)
                        pdfmetrics.registerFont(TTFont(family + suffix, str(target)))
                        hashes[family + suffix] = sha
                    pdfmetrics.registerFontFamily(family, normal=family, bold=family + '-Bold', italic=family + '-Italic', boldItalic=family + '-BoldItalic')
                return hashes
    raise PdfError('fonts_missing', 'Restore the bundled DejaVu fonts, install Arial/Consolas, or use --font-dir.', 'dependencies')


def prepare_image(root, source, input_dir, stats):
    from PIL import Image, ImageOps
    original = (input_dir / source).resolve()
    if not original.is_file():
        raise PdfError('image_missing', 'A referenced local image does not exist.', 'assets')
    sha = digest(original)
    cache = root / '.cache/images'; cache.mkdir(parents=True, exist_ok=True)
    original_cache = cache / (sha + '.source')
    if not original_cache.exists() or digest(original_cache) != sha:
        shutil.copy2(original, original_cache)
    key = key_for({'source': sha, 'max_px': 1600, 'format': 'PNG', 'pillow': importlib.metadata.version('Pillow')})
    target = cache / (key + '.png')
    metadata = cache / (key + '.json')
    try:
        valid = False
        if target.exists() and metadata.exists():
            try: valid = json.loads(metadata.read_text(encoding='utf-8'))['sha256'] == digest(target)
            except (ValueError, KeyError): valid = False
        if valid:
            with Image.open(target) as im: im.verify()
            stats['image_hits'] += 1
        else:
            with Image.open(original_cache) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                if im.mode not in ('RGB', 'RGBA'): im = im.convert('RGB')
                im.save(target)
            write_json(metadata, {'sha256': digest(target), 'source_sha256': sha})
            stats['image_misses'] += 1
    except Exception as error:
        raise PdfError('image_invalid', 'Cannot read or prepare a referenced image.', 'assets') from error
    return target


def make_pdf(root, content, input_dir, mode, target, font_dir, stats):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Flowable, IndexingFlowable,
        Paragraph, Spacer, PageBreak, NextPageTemplate, LongTable, Table, TableStyle, KeepTogether, Image)

    style = json.loads((root / 'templates' / mode / 'style.json').read_text(encoding='utf-8'))
    font_hashes = fonts(root, font_dir)
    for text in collect_text(content):
        for ch in text:
            if not ch.isspace() and ord(ch) not in pdfmetrics.getFont('Sans').face.charToGlyph:
                raise PdfError('unsupported_character', f'Selected font does not support U+{ord(ch):04X}.', 'layout')
    technical = mode == 'technical'; width, height = A4
    margin = style['margin']; cw = width - 2 * margin
    ink = colors.HexColor(style['ink']); accent = colors.HexColor(style.get('accent', '#000000'))
    secondary = colors.HexColor(style.get('secondary', '#000000')); tint = colors.HexColor(style.get('tint', '#FFFFFF'))
    palette = [accent, secondary, colors.HexColor(style.get('warm', '#000000')), ink]
    normal = ParagraphStyle('body', fontName='Sans', fontSize=style['body_size'], leading=style['leading'], textColor=ink, spaceAfter=style['paragraph_gap'])
    head = ParagraphStyle('head', parent=normal, fontName='Sans-Bold', fontSize=14, leading=19, spaceBefore=12, spaceAfter=9, keepWithNext=True)
    small = ParagraphStyle('small', parent=normal, fontSize=9, leading=13)
    def p(text, pstyle=normal): return Paragraph(escape(str(text)).replace('\n', '<br/>'), pstyle)
    prepared = {}
    if technical:
        for section in content['sections']:
            for block in section['blocks']:
                if block['type'] == 'image':
                    prepared[block['source']] = prepare_image(root, block['source'], input_dir, stats)

    class Counter(IndexingFlowable):
        def __init__(self): super().__init__(); self.previous = self.current = 0
        def beforeBuild(self): self.previous, self.current = self.current, 0
        def isSatisfied(self): return self.previous == self.current and self.current > 0
        def wrap(self, a, b): return 0, 0
        def draw(self): pass
    counter = Counter()

    class Marker(Flowable):
        def __init__(self, section, index): super().__init__(); self.section, self.index = section, index
        def wrap(self, a, b): return 0, 0
        def draw(self): pass

    class Doc(BaseDocTemplate):
        def beforeDocument(self): self.current_section = {'title': content['title'], 'kicker': 'Документ'}; self.page_headers = {}
        def afterFlowable(self, flow):
            if isinstance(flow, Marker):
                self.current_section = flow.section
                self.page_headers.setdefault(self.page, flow.section)
                anchor = f'section-{flow.index}'; self.canv.bookmarkPage(anchor)
                self.canv.addOutlineEntry(flow.section['title'], anchor, 0, False)
        def afterPage(self): counter.current = self.page

    def footer(c, doc):
        if technical:
            section = doc.page_headers.get(doc.page, doc.current_section)
            title = section['title']; kicker = section.get('kicker', 'Раздел')
            if doc.pageTemplate.id != 'cover':
                c.setFillColor(tint); c.setStrokeColor(secondary); c.setLineWidth(.5)
                c.rect(margin, height - 47, cw, 22, fill=1, stroke=1)
                c.setFillColor(ink); c.setFont('Mono', 8); c.drawString(margin + 8, height - 40, 'PDF LAB' + (' / ' + content['date'] if content.get('date') else ''))
                c.drawRightString(width - margin - 8, height - 40, f'{doc.page:02d} / {kicker.upper()}')
                c.setFillColor(accent); c.setFont('Mono-Bold', 30); c.drawString(margin, height - 103, f'{doc.page:02d}')
                size = 26
                while size > 16 and pdfmetrics.stringWidth(title, 'Sans-Bold', size) > cw - 58: size -= .5
                title_p = Paragraph(escape(title), ParagraphStyle('page-title', fontName='Sans-Bold', fontSize=size, leading=size * 1.1, textColor=ink))
                _, th = title_p.wrap(cw - 58, 66)
                if th > 66: raise PdfError('title_too_long', 'Shorten the section title.', 'layout', doc.page)
                title_p.drawOn(c, margin + 58, height - 82 - th)
                c.setStrokeColor(ink); c.line(margin, height - 158, width - margin, height - 158)
            c.setStrokeColor(secondary); c.setLineWidth(.4); c.line(margin, 49, width - margin, 49)
            c.setFillColor(secondary); c.setFont('Mono', 7.5); c.drawString(margin, 30, 'PDF / A4' + (' / ' + content['date'] if content.get('date') else ''))
            c.drawRightString(width - margin, 30, f'Страница {doc.page} из {counter.previous or "?"}')
        else:
            c.setFont('Sans', 8); c.setFillColor(colors.black); c.drawRightString(width - margin, 28, str(doc.page))

    class Cover(Flowable):
        def wrap(self, a, b): return width, height
        def draw(self):
            c = self.canv
            c.setFillColor(colors.white); c.rect(0, 0, width, height, fill=1, stroke=0)
            for yy in range(92, 790, 24):
                c.setStrokeColor(tint); c.setLineWidth(.4); c.line(margin, yy, width - margin, yy)
            c.setFillColor(ink); c.rect(margin, 739, cw, 43, fill=1, stroke=0)
            c.setFillColor(colors.white); c.setFont('Mono-Bold', 10); c.drawString(margin + 14, 755, 'ТЕХНИЧЕСКИЙ СТАНДАРТ')
            heading = Paragraph(escape(content['title']), ParagraphStyle('cover-title', fontName='Sans-Bold', fontSize=54, leading=61, textColor=ink))
            _, th = heading.wrap(min(cw, 390), 160)
            if th > 160: raise PdfError('title_too_long', 'Shorten the document title.', 'layout')
            heading.drawOn(c, margin, 678 - th)
            if content.get('subtitle'):
                q = p(content['subtitle']); _, sh = q.wrap(cw, 70)
                if sh > 70: raise PdfError('subtitle_too_long', 'Shorten the document subtitle.', 'layout')
                q.drawOn(c, margin, 528 - sh)
            image = next(iter(prepared.values()), None)
            if image:
                c.setFillColor(colors.black); c.rect(margin, 230, 222, 222, fill=1, stroke=0)
                c.drawImage(ImageReader(str(image)), margin, 230, 222, 222, preserveAspectRatio=True, anchor='c', mask='auto')
            c.setFillColor(accent); c.setFont('Mono-Bold', 38); c.drawString(margin + 250, 411, 'A4')
            q = p('210 × 297 мм\nВертикальная\nориентация', small); _, qh = q.wrap(cw - 250, 120); q.drawOn(c, margin + 250, 382 - qh)
            q = p(content.get('description', 'Согласованный текст, данные и иллюстрации в техническом оформлении.'), normal)
            _, qh = q.wrap(cw, 140)
            if qh > 135: raise PdfError('description_too_long', 'Shorten the cover description.', 'layout')
            q.drawOn(c, margin, 184 - qh)

    class Chart(Flowable):
        def __init__(self, block): super().__init__(); self.b = block; self.width = cw; self.height = max(235, len(block['values']) * 35 + 50) if block['kind'] == 'bars' else max(245, len(block['values']) * 27 + 35) if block['kind'] == 'donut' else 245
        def draw(self):
            c = self.canv; b = self.b; values, labels = b['values'], b['labels']; h = self.height
            def label(s, x, y, size=8, font='Sans', col=ink):
                c.setFont(font, size); c.setFillColor(col); c.drawString(x, y, str(s))
            if b['kind'] == 'line':
                left, bottom, pw, ph = 40, 36, cw - 55, h - 76
                lo, hi = min(values), max(values)
                delta = (hi - lo) or max(1, abs(hi) * .1); lo -= delta * .12; hi += delta * .12
                for i in range(5):
                    yy = bottom + ph * i / 4; value = lo + (hi - lo) * i / 4
                    c.setStrokeColor(secondary); c.setLineWidth(.3); c.line(left, yy, left + pw, yy)
                    label(f'{value:.0f}', 0, yy - 3)
                points = [(left + i * pw / max(1, len(values) - 1), bottom + (v - lo) / (hi - lo) * ph) for i, v in enumerate(values)]
                line = c.beginPath(); line.moveTo(*points[0])
                for point in points[1:]: line.lineTo(*point)
                c.setStrokeColor(accent); c.setLineWidth(2); c.drawPath(line)
                for i, (xx, yy) in enumerate(points):
                    c.setFillColor(accent); c.circle(xx, yy, 2.7, fill=1, stroke=0)
                    q = p(labels[i], ParagraphStyle('axis', parent=small, fontSize=7, leading=8, alignment=1)); _, qh = q.wrap(max(18, pw / len(values)), 22); q.drawOn(c, xx - pw / len(values) / 2, bottom - 8 - qh)
                label(b.get('y_label', ''), 0, h - 15, 9); label(b.get('x_label', ''), left, 0, 8)
            elif b['kind'] == 'bars':
                require(min(values) >= 0, 'negative_bar', 'Bar chart values must be non-negative.')
                max_value = max(values) or 1; x = min(125, cw * .33); ww = cw - x - 35
                for i, (name, value) in enumerate(zip(labels, values)):
                    y = h - 54 - i * 35
                    q = p(name, small); _, qh = q.wrap(x - 12, 32); q.drawOn(c, 0, y + 14 - qh)
                    c.setFillColor(tint); c.rect(x, y, ww, 20, fill=1, stroke=0)
                    c.setFillColor(palette[i % 4]); c.rect(x, y, ww * value / max_value, 20, fill=1, stroke=0)
                    label(f'{value:g}', cw - 28, y + 6, 9, 'Mono')
                label(b.get('x_label', ''), 0, h - 14, 9)
            else:
                cx, cy, radius = 112, h / 2, 100; angle = 90; total = sum(values)
                for i, value in enumerate(values):
                    c.setFillColor(palette[i % 4]); c.wedge(cx - radius, cy - radius, cx + radius, cy + radius, angle, value * 360 / total, fill=1, stroke=0); angle += value * 360 / total
                c.setFillColor(colors.white); c.circle(cx, cy, 65, fill=1, stroke=0); label('100%', cx - 33, cy - 8, 24, 'Sans-Bold')
                for i, (name, value) in enumerate(zip(labels, values)):
                    y = h - 35 - i * 27; c.setFillColor(palette[i % 4]); c.rect(247, y, 8, 8, fill=1, stroke=0)
                    q = p(f'{name}: {value * 100 / total:g}%', small); _, qh = q.wrap(cw - 270, 25); q.drawOn(c, 266, y + 10 - qh)

    doc = Doc(str(target), pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=180 if technical else 40, bottomMargin=95 if technical else 48, title=content['title'], author=content.get('author', 'PDF Documents'), invariant=1, pageCompression=1)
    body = Frame(margin, 95 if technical else 48, cw, height - (180 if technical else 40) - (95 if technical else 48), leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id='cover', frames=Frame(0, 0, width, height, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0), onPageEnd=footer), PageTemplate(id='body', frames=body, onPageEnd=footer)] if technical and content.get('cover', True) else [PageTemplate(id='body', frames=body, onPageEnd=footer)])
    story = [counter]
    if technical and content.get('cover', True): story.extend([Cover(), NextPageTemplate('body'), PageBreak()])
    else:
        story.append(p(content['title'], ParagraphStyle('document-title', parent=head, fontSize=22, leading=28)))
        if content.get('subtitle'): story.append(p(content['subtitle']))
    for index, section in enumerate(content['sections']):
        if technical and index and section.get('page_break', False): story.append(PageBreak())
        story.append(Marker(section, index))
        if not technical or (index and not section.get('page_break', False)):
            story.append(p(section['title'], head))
        if section.get('description'): story.append(p(section['description'], small))
        for block in section['blocks']:
            kind = block['type']
            if kind in {'paragraph', 'heading', 'quote'}:
                ps = head if kind == 'heading' else ParagraphStyle('quote', parent=normal, fontName='Sans-Italic') if kind == 'quote' else normal
                story.append(p(block['text'], ps))
            elif kind == 'list':
                for i, item in enumerate(block['items'], 1): story.append(p(f'{i}. {item}'))
            elif kind == 'callout':
                if technical:
                    box = Table([[p(block['title'], ParagraphStyle('callout-head', parent=small, fontName='Sans-Bold', textColor=accent))], [p(block['text'], small)]], colWidths=[cw])
                    box.setStyle(TableStyle([('BACKGROUND', (0,0),(-1,0), tint), ('BOX',(0,0),(-1,-1),.5,secondary), ('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
                    story.extend([KeepTogether([box]), Spacer(1, 14)])
                else:
                    story.append(p(block['title'] + '. ' + block['text']))
            elif kind == 'image':
                if technical:
                    from PIL import Image as PILImage
                    asset = prepared[block['source']]
                    with PILImage.open(asset) as im: iw, ih = im.size
                    scale = min(cw / iw, min(float(block.get('height', 310)), 360) / ih)
                    picture = Image(str(asset), width=iw * scale, height=ih * scale); picture.hAlign='CENTER'
                    story.extend([KeepTogether([picture, Spacer(1, 12), p(block['caption'], small)]), Spacer(1, 8)])
                else: story.append(p(block['caption']))
                if block.get('credit'): story.append(p(block['credit'], small))
                if block.get('url'):
                    require(re.match(r'^https?://[^\s]+$', block['url']), 'invalid_link', 'Image source URL must use HTTP(S).')
                    story.append(Paragraph(f'<link href="{escape(block["url"], {chr(34): "&quot;"})}" color="{style.get("accent", "#000000")}"><u>{escape(block["url"])}</u></link>', small))
            elif kind == 'chart':
                if technical: story.extend([Chart(block), Spacer(1, 14)])
                else: story.append(p('; '.join(f'{label}: {value:g}' for label, value in zip(block['labels'], block['values']))))
                if block.get('text'): story.append(p(block['text']))
            elif kind == 'table':
                if technical:
                    cellstyle = ParagraphStyle('cell', fontName='Sans', fontSize=8.4, leading=12, textColor=ink)
                    headerstyle = ParagraphStyle('header', parent=cellstyle, fontName='Sans-Bold', textColor=colors.white)
                    numeric = lambda value: bool(re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?', str(value)))
                    numeric_columns = {i for i in range(len(block['columns'])) if all(numeric(row[i]) for row in block['rows'])}
                    mono = ParagraphStyle('numeric-cell', parent=cellstyle, fontName='Mono', alignment=2)
                    data = [[p(x, ParagraphStyle('column-head', parent=headerstyle, alignment=2 if i in numeric_columns and i else 0)) for i,x in enumerate(block['columns'])]]
                    for row in block['rows']:
                        cells = []
                        for i, value in enumerate(row):
                            cs = mono if i in numeric_columns and i else cellstyle
                            if i == block.get('delta_column') and numeric(value):
                                amount = float(str(value).replace(',', '.'))
                                cs = ParagraphStyle('delta', parent=cs, textColor=colors.HexColor('#346C53') if amount < 0 else colors.HexColor('#995332') if amount > 0 else ink)
                            cells.append(p(value, cs))
                        data.append(cells)
                    ratios = block.get('widths', [1] * len(block['columns'])); widths = [cw * x / sum(ratios) for x in ratios]
                    table = LongTable(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
                    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),ink),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,tint]),('GRID',(0,0),(-1,-1),.3,secondary),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
                    story.extend([table, Spacer(1, 12)])
                else:
                    story.append(p(' / '.join(block['columns']), small))
                    for row in block['rows']: story.append(p(' / '.join(str(x) for x in row), ParagraphStyle('draft-row', parent=normal, spaceAfter=3)))
            elif kind == 'link':
                story.append(Paragraph(f'<link href="{escape(block["url"], {chr(34): "&quot;"})}" color="{style.get("accent", "#000000")}"><u>{escape(block["text"])}</u></link>', normal))
                story.append(p(block['url'], small))
    doc.multiBuild(story, maxPasses=3)
    return {'fonts': font_hashes, 'template': digest(root / 'templates' / mode / 'style.json')}


def validate_pdf(path, content, mode):
    from pypdf import PdfReader
    import pdfplumber
    reader = PdfReader(path); details = []; all_text = []; raw_text = []; body_text = []
    if not reader.pages: raise PdfError('empty_pdf', 'PDF has no pages.', 'validation')
    with pdfplumber.open(path) as document:
        for number, (page, extracted) in enumerate(zip(reader.pages, document.pages), 1):
            if abs(float(page.mediabox.width) - 595.2756) > .1 or abs(float(page.mediabox.height) - 841.8898) > .1:
                raise PdfError('page_format', 'Page must be portrait A4.', 'validation', number)
            text = extracted.extract_text() or ''
            if '\ufffd' in text or '\u25a0' in text: raise PdfError('missing_glyph', 'Text contains replacement glyphs.', 'validation', number)
            if not text.strip(): raise PdfError('empty_page', 'Page has no extractable text.', 'validation', number)
            for word in extracted.extract_words():
                if word['x0'] < 18 or word['x1'] > extracted.width - 18 or word['top'] < 14 or word['bottom'] > extracted.height - 14:
                    raise PdfError('text_bounds', 'Text extends outside the allowed page area.', 'validation', number)
            if mode == 'technical' and f'Страница {number} из {len(reader.pages)}' not in text:
                raise PdfError('numbering', 'Page numbering does not match the document.', 'validation', number)
            if mode == 'economy':
                if text.rstrip().splitlines()[-1].strip() != str(number): raise PdfError('numbering', 'Economy page number is missing.', 'validation', number)
                if len(page.images): raise PdfError('draft_image', 'Economy mode must not contain images.', 'validation', number)
                for ch in extracted.chars:
                    if ch.get('non_stroking_color') not in (0, (0,0,0), [0,0,0]): raise PdfError('draft_color', 'Economy text must be black.', 'validation', number)
            for font in page['/Resources'].get('/Font', {}).get_object().values():
                descriptor = font.get_object().get('/FontDescriptor')
                if descriptor and not any(k in descriptor.get_object() for k in ('/FontFile','/FontFile2','/FontFile3')):
                    raise PdfError('font_not_embedded', 'A used font is not embedded.', 'validation', number)
            links = sum(1 for a in page.get('/Annots', []) if a.get_object().get('/Subtype') == '/Link')
            details.append({'page': number, 'characters': len(text), 'images': len(page.images), 'links': links})
            all_text.append(text)
            raw_text.append(page.extract_text() or '')
            body_text.append(extracted.crop((18, 170 if mode == 'technical' else 14, extracted.width - 18, extracted.height - (78 if mode == 'technical' else 42))).extract_text() or '')
    normalized = [re.sub(r'\s+', '', '\n'.join(parts)) for parts in (all_text, raw_text, body_text)]
    for index, expected in enumerate(collect_text(content)):
        if not any(re.sub(r'\s+', '', expected) in candidate for candidate in normalized):
            raise PdfError('missing_text', f'Source text item {index + 1} is absent from the PDF.', 'validation')
    checks = {'a4': True, 'text': True, 'page_bounds': True, 'numbering': True, 'fonts': True}
    if mode == 'economy': checks.update(black_text=True, no_images=True)
    return {'pages': len(reader.pages), 'checks': checks, 'page_details': details}
