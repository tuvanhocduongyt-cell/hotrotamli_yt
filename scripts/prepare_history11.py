"""Build a search index for scanned books. Images remain the authoritative source.

Windows preparation only: pip install PyMuPDF winrt-runtime
winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams
winrt-Windows.Globalization winrt-Windows.Foundation winrt-Windows.Foundation.Collections
Run: python scripts/prepare_history11.py [--upload]
"""
import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def prepare(upload=False):
    import pymupdf
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
    from winrt.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
    from winrt.windows.graphics.imaging import BitmapDecoder
    from utils.data_store import DataStore

    dest = ROOT / 'data/history11'
    dest.mkdir(parents=True, exist_ok=True)
    index_path = dest / 'index.json'
    old = json.loads(index_path.read_text('utf-8')) if index_path.exists() else {'books': []}
    engine = OcrEngine.try_create_from_language(Language('vi-VN'))
    language = 'vi-VN'
    if engine is None:
        engine = OcrEngine.try_create_from_language(Language('en-US'))
        language = 'en-US'
    if engine is None:
        raise RuntimeError('No Windows OCR recognizer is installed.')
    books = []
    for pattern, key, title in [('SGK*.pdf', 'sgk', 'SGK Lịch sử 11 – Kết nối tri thức'),
                                 ('Chuyên*.pdf', 'chuyende', 'Chuyên đề Lịch sử 11 – Kết nối tri thức')]:
        source = next((ROOT / 'capnhat').glob(pattern))
        target = dest / (key + '.pdf')
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copyfile(source, target)
        previous = next((b for b in old['books'] if b['id'] == key and b.get('sha256') == checksum), {})
        pages = previous.get('pages', [])
        doc = pymupdf.open(target)
        for i in range(len(pages), len(doc)):
            page = doc[i]
            text = page.get_text().strip()
            if not text:
                stream = InMemoryRandomAccessStream()
                writer = DataWriter(stream)
                writer.write_bytes(page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes('png'))
                await writer.store_async()
                stream.seek(0)
                decoder = await BitmapDecoder.create_async(stream)
                bitmap = await decoder.get_software_bitmap_async()
                result = await engine.recognize_async(bitmap)
                text = result.text
                writer.close()
                stream.close()
            pages.append({'page': i + 1, 'text': text})
            book = {'id': key, 'title': title, 'asset': 'data/history11/' + key + '.pdf',
                    'sha256': checksum, 'ocr_language': language, 'pages': pages}
            index_path.write_text(json.dumps({'books': books + [book]}, ensure_ascii=False), 'utf-8')
            if (i + 1) % 10 == 0:
                print(key, i + 1, '/', len(doc), flush=True)
        books.append({'id': key, 'title': title, 'asset': 'data/history11/' + key + '.pdf',
                      'sha256': checksum, 'ocr_language': language, 'pages': pages})
        doc.close()
    index_path.write_text(json.dumps({'books': books}, ensure_ascii=False), 'utf-8')
    if upload:
        store = DataStore()
        for path in sorted(dest.iterdir()):
            if path.suffix in ('.pdf', '.json'):
                store.write_asset(path, path.read_bytes())
                print('Uploaded', path.name, flush=True)
    print('Prepared', sum(len(b['pages']) for b in books), 'pages. OCR is for search; use page images for evidence.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--upload', action='store_true')
    asyncio.run(prepare(parser.parse_args().upload))
