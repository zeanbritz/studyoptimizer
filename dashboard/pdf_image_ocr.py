"""Bounded, local OCR for raster images embedded in PDF pages."""

from io import BytesIO
import subprocess

from PIL import Image
from pypdf.errors import PdfReadError


MAX_OCR_IMAGES_PER_SCAN = 8
MAX_OCR_IMAGES_PER_PAGE = 2
MAX_INSPECTED_IMAGES_PER_PAGE = 8
MIN_OCR_PIXELS = 60_000
MAX_DECODE_PIXELS = 30_000_000
MAX_OCR_PIXELS = 3_000_000
OCR_TIMEOUT_SECONDS = 6


def _png_for_ocr(image):
    """Shrink an image before handing it to the OCR process."""
    width, height = image.size
    if not MIN_OCR_PIXELS <= width * height <= MAX_DECODE_PIXELS:
        return None
    image = image.copy()
    if width * height > MAX_OCR_PIXELS:
        scale = (MAX_OCR_PIXELS / (width * height)) ** 0.5
        image.thumbnail((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def _run_ocr(png_bytes):
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "6"],
        input=png_bytes,
        capture_output=True,
        check=False,
        timeout=OCR_TIMEOUT_SECONDS,
    )
    if result.returncode:
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()[:100_000]


def scan_page_images(page, remaining):
    """Only start OCR when an embedded image is present; bound work per scan."""
    result = {"image_found": False, "checked": 0, "texts": [], "unavailable": False,
              "limit_reached": False}
    try:
        image_keys = page.images.keys()
    except (PdfReadError, ValueError, TypeError, KeyError, OSError):
        return result
    if not image_keys:
        return result
    result["image_found"] = True
    if remaining <= 0:
        result["limit_reached"] = True
        return result

    possible = []
    for key in image_keys[:MAX_INSPECTED_IMAGES_PER_PAGE]:
        try:
            image = page.images[key].image
            pixels = image.width * image.height
            if MIN_OCR_PIXELS <= pixels <= MAX_DECODE_PIXELS:
                possible.append((pixels, image))
        except (PdfReadError, ValueError, TypeError, KeyError, OSError):
            continue
    possible.sort(key=lambda entry: entry[0], reverse=True)
    selected = possible[:min(remaining, MAX_OCR_IMAGES_PER_PAGE)]
    if len(possible) > len(selected) or len(image_keys) > MAX_INSPECTED_IMAGES_PER_PAGE:
        result["limit_reached"] = True
    for _, image in selected:
        try:
            png_bytes = _png_for_ocr(image)
            if not png_bytes:
                continue
            text = _run_ocr(png_bytes)
            result["checked"] += 1
            if text:
                result["texts"].append(text)
        except FileNotFoundError:
            result["unavailable"] = True
            break
        except subprocess.TimeoutExpired:
            result["checked"] += 1
            continue
        except (ValueError, OSError):
            continue
    return result
