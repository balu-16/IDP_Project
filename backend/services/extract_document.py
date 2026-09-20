"""Isolated extraction subprocess; the parent enforces a hard wall-clock timeout."""
import argparse
import json
from pathlib import Path
from pypdf import PdfReader
from config import settings


def ocr_image(image):
    import pytesseract
    if image.width * image.height > settings.MAX_PAGE_PIXELS:
        raise ValueError('Page exceeds pixel limit')
    data = pytesseract.image_to_data(
        image, lang=settings.OCR_LANGUAGE, timeout=30,
        output_type=pytesseract.Output.DICT)
    words, confidences = [], []
    last_line = None
    for i, word in enumerate(data['text']):
        if word.strip():
            line = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
            if last_line is not None and line != last_line:
                words.append('\n')
            words.append(word)
            last_line = line
            confidence = float(data['conf'][i])
            if confidence >= 0:
                confidences.append(confidence)
    return ' '.join(words), (sum(confidences)/len(confidences) if confidences else None)


def extract(path):
    path = Path(path)
    if path.stat().st_size > settings.MAX_FILE_SIZE:
        raise ValueError('File exceeds size limit')
    with path.open('rb') as handle:
        signature = handle.read(8)
    pages, metadata = [], {}
    if signature.startswith(b'%PDF-'):
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('Encrypted PDFs must be decrypted before upload')
        if not 0 < len(reader.pages) <= settings.MAX_DOCUMENT_PAGES:
            raise ValueError('PDF page count outside configured limits')
        metadata = {'title': str((reader.metadata or {}).get('/Title', '')),
                    'author': str((reader.metadata or {}).get('/Author', ''))}
        rendered = None
        try:
            for number, page in enumerate(reader.pages, 1):
                text = (page.extract_text() or '').strip()
                method, confidence = 'native', None
                if not any(c.isalnum() for c in text):
                    import pypdfium2 as pdfium
                    if rendered is None:
                        rendered = pdfium.PdfDocument(str(path))
                    render_page = rendered[number-1]
                    width, height = render_page.get_size()
                    if width * height * 4 > settings.MAX_PAGE_PIXELS:
                        raise ValueError('Rendered page exceeds pixel limit')
                    bitmap = render_page.render(scale=2)
                    image = bitmap.to_pil()
                    try:
                        text, confidence = ocr_image(image)
                    finally:
                        image.close()
                        bitmap.close()
                        render_page.close()
                    method = 'ocr'
                pages.append({'page_number': number, 'text': text,
                              'extraction_method': method, 'ocr_confidence': confidence})
        finally:
            if rendered is not None:
                rendered.close()
    elif signature.startswith(b'\x89PNG\r\n\x1a\n') or signature.startswith(b'\xff\xd8\xff'):
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = settings.MAX_PAGE_PIXELS
        with Image.open(path) as source:
            if source.width * source.height > settings.MAX_PAGE_PIXELS:
                raise ValueError('Image exceeds pixel limit')
            image = ImageOps.exif_transpose(source).convert('RGB')
            try:
                text, confidence = ocr_image(image)
            finally:
                image.close()
        pages.append({'page_number': 1, 'text': text, 'extraction_method': 'ocr',
                      'ocr_confidence': confidence})
    else:
        raise ValueError('Only valid PDF, PNG and JPEG files are supported')
    if not any(any(c.isalnum() for c in page['text']) for page in pages):
        raise ValueError('No usable text was extracted')
    return {'page_texts': pages, 'metadata': {**metadata, 'num_pages': len(pages)}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    args = parser.parse_args()
    try:
        print(json.dumps(extract(args.path), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        raise SystemExit(1)
