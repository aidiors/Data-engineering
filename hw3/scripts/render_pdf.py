"""Render every page and build contact sheets for visual inspection."""

import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from frontend_lake.validation import require

    root = Path(__file__).resolve().parents[1]
    pdf = root / "output/pdf/Dubovik_Nikita_variant8_hw3.pdf"
    out = root / "tmp/pdfs"
    out.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    for i, page in enumerate(doc):
        image = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        image.save(str(out / f"page_{i + 1:02}.png"))
        # Text should stay inside the printable page; visual review is still required.
        for block in page.get_text("blocks"):
            require(block[0] >= 20 and block[2] <= page.rect.width - 20, (i + 1, block))
            require(block[1] >= 15 and block[3] <= page.rect.height - 15, (i + 1, block))
    for start in range(0, len(doc), 8):
        sheet = Image.new("RGB", (1200, 870), "#dce5ec")
        draw = ImageDraw.Draw(sheet)
        for j in range(start, min(start + 8, len(doc))):
            img = Image.open(out / f"page_{j + 1:02}.png").convert("RGB")
            # 4 rows; fit page into each 400 px tile for an 8-page overview.
            img.thumbnail((280, 395))
            x = (j - start) % 4 * 300 + 10
            y = (j - start) // 4 * 430 + 30
            sheet.paste(img, (x, y))
            draw.text((x, y - 18), f"Page {j + 1}", fill="black")
        sheet.save(out / f"contact_{start // 8 + 1}.png")
    print(f"Rendered {len(doc)} pages to {out}")


if __name__ == "__main__":
    main()
