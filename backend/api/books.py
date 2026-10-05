"""A5 photo book: choose and order the album's photos, lay them out as HTML, render a PDF.

Only photos with a story the user wrote are printed, ordered by date with one chapter per
decade (family photos are sparse, so yearly chapters would be mostly empty pages) and undated
photos last. Text is printed exactly as the user saved it.
"""
import datetime
import os
import tempfile

from django.utils import timezone
from django.utils.html import escape, linebreaks

from .language import EN
from .printing import print_quality
from . import thumbnails

# Long side of each embedded photo: about 300 dpi across an A5 page, without bloating the PDF.
PRINT_IMAGE_SIDE = 2000

LABELS = {
    "zh-HK": {
        "title": "{name}嘅故事",
        "undated": "未有日期嘅回憶",
        "colophon": "由 Photolore 整理",
        "chapter": "第 {number} 章",
        "decade": "{decade} 年代",
        "date": "{year}年{month}月{day}日",
    },
    EN: {
        "title": "Stories of {name}",
        "undated": "Undated memories",
        "colophon": "Made with Photolore",
        "chapter": "Chapter {number}",
        "decade": "The {decade}s",
        "date": "{day} {month_name} {year}",
    },
}


def has_story(asset):
    caption = asset.caption.strip()
    return bool(caption) and caption != asset.generated_caption.strip()


def _labels(character):
    return LABELS[EN if character.language == EN else "zh-HK"]


def default_book_title(character):
    return _labels(character)["title"].format(name=character.name)


def book_title(book):
    return book.title.strip() or default_book_title(book.character)


def _sort_key(asset):
    return (asset.captured_at or datetime.date.max, asset.created_at)


def book_outline(book):
    """Photos grouped into chapters, plus what still needs attention before printing."""
    assets = list(book.character.memory_assets.all())
    excluded = {str(asset_id) for asset_id in book.excluded}
    with_story = sorted((a for a in assets if has_story(a)), key=_sort_key)
    included = [a for a in with_story if str(a.id) not in excluded]
    chapters = []
    for asset in included:
        decade = asset.captured_at.year // 10 * 10 if asset.captured_at else None
        if not chapters or chapters[-1]["decade"] != decade:
            chapters.append({"decade": decade, "assets": []})
        chapters[-1]["assets"].append(asset)
    return {
        "chapters": chapters,
        "included": included,
        "excluded": [a for a in with_story if str(a.id) in excluded],
        "missing_story": sorted((a for a in assets if not has_story(a)), key=_sort_key),
        "missing_date": [a for a in included if not a.captured_at],
        "low_resolution": [a for a in included if (print_quality(a.width, a.height) or {}).get("rating") == "low"],
    }


def _format_date(value, labels):
    return labels["date"].format(year=value.year, month=value.month, day=value.day, month_name=value.strftime("%B"))


BOOK_CSS = """
@page { size: 148mm 210mm; margin: 18mm 16mm 20mm;
  @bottom-center { content: counter(page); font: 8.5pt 'Noto Serif CJK TC', serif; color: #8b8674; } }
@page cover { margin: 0; @bottom-center { content: none; } }
@page plain { @bottom-center { content: none; } }
html { font-family: 'Noto Serif CJK TC', 'Noto Serif CJK HK', serif; color: #2a2622; font-size: 10.5pt; }
body { margin: 0; }
section { break-after: page; }
.cover { page: cover; height: 210mm; background: #1f4a42; color: #f3eedf; display: flex; flex-direction: column;
  align-items: center; justify-content: center; text-align: center; padding: 20mm; box-sizing: border-box; }
.cover .frame { background: #fbf8f1; padding: 4mm 4mm 9mm; margin-bottom: 14mm; }
.cover .frame img { display: block; width: 88mm; height: 70mm; object-fit: cover; }
.cover h1 { font-size: 24pt; font-weight: 700; letter-spacing: .06em; margin: 0 0 5mm; }
.cover p { margin: 0; font-size: 10pt; opacity: .8; }
.dedication { page: plain; display: flex; align-items: center; justify-content: center; height: 172mm; text-align: center; }
.dedication div { max-width: 92mm; font-size: 11.5pt; line-height: 2; font-style: italic; }
.chapter { page: plain; height: 172mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.chapter small { font-size: 9pt; letter-spacing: .3em; color: #8b7a55; }
.chapter h2 { font-size: 28pt; font-weight: 700; margin: 4mm 0; }
.chapter hr { width: 20mm; border: 0; border-top: .4pt solid #c9bfa4; margin: 4mm auto; }
.photo-page { min-height: 170mm; display: flex; flex-direction: column; justify-content: center; }
.photo-page .print { background: #fbf8f1; border: .3pt solid #e4dccb; padding: 3mm; margin: 0 auto 6mm; text-align: center; }
.photo-page .print { display: table; }
.photo-page img { display: block; width: auto; height: auto; max-width: 108mm; max-height: 112mm; margin: 0 auto; }
.photo-page .date { font-size: 8.5pt; letter-spacing: .14em; color: #8b7a55; margin: 0 0 2.5mm; }
.photo-page .story { font-size: 11pt; line-height: 2; }
.photo-page .story p { margin: 0 0 2.5mm; }
.colophon { page: plain; height: 172mm; display: flex; align-items: flex-end; justify-content: center; font-size: 8.5pt; color: #8b8674; }
"""


def render_book_html(book, image_paths):
    """HTML for WeasyPrint; image_paths maps asset id to a local JPEG file."""
    character = book.character
    labels = _labels(character)
    outline = book_outline(book)
    included = outline["included"]
    parts = []
    years = [a.captured_at.year for a in included if a.captured_at]
    span = f"{min(years)} – {max(years)}" if years and min(years) != max(years) else (str(years[0]) if years else "")
    cover_photo = image_paths.get(str(included[0].id)) if included else None
    cover_img = f'<div class="frame"><img src="file://{escape(cover_photo)}" alt=""></div>' if cover_photo else ""
    parts.append(f'<section class="cover">{cover_img}<h1>{escape(book_title(book))}</h1><p>{escape(span)}</p></section>')
    if book.dedication.strip():
        parts.append(f'<section class="dedication"><div>{linebreaks(escape(book.dedication.strip()))}</div></section>')
    for number, chapter in enumerate(outline["chapters"], 1):
        heading = labels["decade"].format(decade=chapter["decade"]) if chapter["decade"] else labels["undated"]
        parts.append(f'<section class="chapter"><small>{escape(labels["chapter"].format(number=number))}</small>'
                     f'<h2>{escape(heading)}</h2><hr></section>')
        for asset in chapter["assets"]:
            path = image_paths.get(str(asset.id))
            image = f'<div class="print"><img src="file://{escape(path)}" alt=""></div>' if path else ""
            date = f'<p class="date">{escape(_format_date(asset.captured_at, labels))}</p>' if asset.captured_at else ""
            parts.append(f'<section class="photo-page">{image}{date}<div class="story">{linebreaks(escape(asset.caption.strip()))}</div></section>')
    parts.append(f'<section class="colophon">{escape(labels["colophon"])}</section>')
    lang = "en" if character.language == EN else "zh-HK"
    return f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>{BOOK_CSS}</style></head><body>{"".join(parts)}</body></html>'


def build_book_pdf(book):
    """Render the book to PDF bytes; photos that cannot be read are printed without their image."""
    from weasyprint import HTML  # Imported lazily: it loads native libraries.

    with tempfile.TemporaryDirectory() as workdir:
        image_paths = {}
        for asset in book_outline(book)["included"]:
            try:
                data = thumbnails.jpeg_bytes(asset.image, PRINT_IMAGE_SIDE, 88)
            except (OSError, ValueError):
                continue
            path = os.path.join(workdir, f"{asset.id}.jpg")
            with open(path, "wb") as handle:
                handle.write(data)
            image_paths[str(asset.id)] = path
        html = render_book_html(book, image_paths)
        return HTML(string=html, base_url=workdir).write_pdf()


def export_book(book):
    """Build the PDF and store it, replacing the previous export."""
    from django.core.files.base import ContentFile

    pdf = build_book_pdf(book)
    old_name = book.pdf.name
    book.pdf.save("book.pdf", ContentFile(pdf), save=False)
    book.export_status = book.ExportStatus.READY
    book.export_error = ""
    book.exported_at = timezone.now()
    book.save(update_fields=("pdf", "export_status", "export_error", "exported_at"))
    if old_name:
        book.pdf.storage.delete(old_name)
