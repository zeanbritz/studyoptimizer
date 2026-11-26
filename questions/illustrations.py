from io import BytesIO

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_STORED_BYTES = 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_EDGE = 1800
IMAGE_FORMATS = ("PNG", "JPEG", "WEBP")


def prepare_image(upload):
    """Decode a supported image and store a resized, metadata-free WebP."""
    if upload.size > MAX_IMAGE_BYTES:
        raise ValidationError("Choose an image smaller than 5 MB.")

    try:
        with Image.open(upload, formats=IMAGE_FORMATS) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValidationError("Choose an image with up to 16 megapixels.")
            if getattr(source, "is_animated", False):
                raise ValidationError("Choose a still image.")
            picture = ImageOps.exif_transpose(source)
            picture.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
            transparent = "A" in picture.getbands() or "transparency" in picture.info
            picture = picture.convert("RGBA" if transparent else "RGB")
            for quality in (88, 76, 64):
                output = BytesIO()
                picture.save(output, format="WEBP", quality=quality)
                if output.tell() <= MAX_STORED_BYTES:
                    return output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise ValidationError("Choose a valid PNG, JPEG, or WebP image.") from error

    raise ValidationError("This image is too detailed to store. Try a smaller image.")
