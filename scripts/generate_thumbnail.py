#!/usr/bin/env python3

import json
import os
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter


TOPIC_FILE = Path("Input/topic.txt")
VISUAL_MANIFEST = Path("output/visuals/visual_jobs.json")
OUTPUT_DIR = Path("output/thumbnail")

THUMBNAIL_16_9 = OUTPUT_DIR / "thumbnail_1280x720.jpg"
THUMBNAIL_VERTICAL = OUTPUT_DIR / "thumbnail_1080x1920.jpg"
THUMBNAIL_MANIFEST = OUTPUT_DIR / "thumbnail_manifest.json"


def load_topic():
    if not TOPIC_FILE.exists():
        raise SystemExit(
            f"ERROR: Topic file not found: {TOPIC_FILE}"
        )

    for line in TOPIC_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split("=", 1)

        if key.strip() == "TOPIC":
            value = value.strip()

            value = re.sub(
                r"\s+#.*$",
                "",
                value,
            ).strip()

            value = value.strip("\"'")

            if value:
                return value

    raise SystemExit(
        "ERROR: TOPIC not found in Input/topic.txt"
    )


def load_visual():
    if not VISUAL_MANIFEST.exists():
        raise SystemExit(
            "ERROR: visual_jobs.json not found"
        )

    data = json.loads(
        VISUAL_MANIFEST.read_text(
            encoding="utf-8"
        )
    )

    jobs = data.get("jobs", [])

    completed = [
        job
        for job in jobs
        if (
            job.get("status") == "completed"
            and job.get("asset_path")
        )
    ]

    if not completed:
        raise SystemExit(
            "ERROR: No completed visual assets found"
        )

    completed.sort(
        key=lambda job: (
            int(job.get("part", 999)),
            int(job.get("scene", 999)),
        )
    )

    for job in completed:
        path = Path(job["asset_path"])

        if path.exists() and path.stat().st_size > 0:
            return path

    raise SystemExit(
        "ERROR: Completed visual files are missing"
    )


def load_font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]

    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def crop_to_ratio(image, target_ratio):
    width, height = image.size
    current_ratio = width / height

    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2

        return image.crop(
            (
                left,
                0,
                left + new_width,
                height,
            )
        )

    new_height = int(width / target_ratio)
    top = (height - new_height) // 2

    return image.crop(
        (
            0,
            top,
            width,
            top + new_height,
        )
    )


def add_dark_overlay(image):
    overlay = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(overlay)

    width, height = image.size

    for y in range(height):
        alpha = int(
            190 * (y / max(height - 1, 1))
        )

        draw.line(
            [(0, y), (width, y)],
            fill=(0, 0, 0, alpha),
        )

    return Image.alpha_composite(
        image.convert("RGBA"),
        overlay,
    )


def fit_title(draw, text, max_width, start_size):
    size = start_size

    while size >= 28:
        font = load_font(size)

        box = draw.textbbox(
            (0, 0),
            text,
            font=font,
            stroke_width=2,
        )

        if box[2] - box[0] <= max_width:
            return font

        size -= 4

    return load_font(28)


def wrap_text(draw, text, font, max_width):
    words = text.split()

    lines = []
    current = ""

    for word in words:
        test = (
            word
            if not current
            else current + " " + word
        )

        box = draw.textbbox(
            (0, 0),
            test,
            font=font,
            stroke_width=2,
        )

        if box[2] - box[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)

            current = word

    if current:
        lines.append(current)

    return lines


def create_thumbnail(source, topic, width, height):
    image = Image.open(source).convert("RGB")

    image = crop_to_ratio(
        image,
        width / height,
    )

    image = image.resize(
        (width, height),
        Image.Resampling.LANCZOS,
    )

    image = image.filter(
        ImageFilter.SHARPEN
    )

    image = add_dark_overlay(image)

    draw = ImageDraw.Draw(image)

    margin = int(width * 0.07)

    font = fit_title(
        draw,
        topic,
        width - margin * 2,
        int(width * 0.075),
    )

    lines = wrap_text(
        draw,
        topic,
        font,
        width - margin * 2,
    )

    line_boxes = [
        draw.textbbox(
            (0, 0),
            line,
            font=font,
            stroke_width=3,
        )
        for line in lines
    ]

    line_heights = [
        box[3] - box[1]
        for box in line_boxes
    ]

    line_spacing = int(
        font.size * 0.18
    )

    total_height = (
        sum(line_heights)
        + line_spacing * max(
            len(lines) - 1,
            0,
        )
    )

    y = (
        height
        - total_height
        - margin
    )

    for line, line_height in zip(
        lines,
        line_heights,
    ):
        box = draw.textbbox(
            (0, 0),
            line,
            font=font,
            stroke_width=3,
        )

        text_width = (
            box[2] - box[0]
        )

        x = (
            width
            - text_width
        ) // 2

        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )

        y += (
            line_height
            + line_spacing
        )

    return image.convert("RGB")


def main():
    print(
        "======================================"
    )
    print(
        "       GENERATING THUMBNAILS"
    )
    print(
        "======================================"
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    topic = load_topic()
    source = load_visual()

    print(f"Topic: {topic}")
    print(f"Source visual: {source}")

    thumbnail = create_thumbnail(
        source,
        topic,
        1280,
        720,
    )

    thumbnail.save(
        THUMBNAIL_16_9,
        "JPEG",
        quality=92,
        optimize=True,
    )

    vertical = create_thumbnail(
        source,
        topic,
        1080,
        1920,
    )

    vertical.save(
        THUMBNAIL_VERTICAL,
        "JPEG",
        quality=92,
        optimize=True,
    )

    manifest = {
        "status": "completed",
        "topic": topic,
        "source_visual": str(source),
        "thumbnail_16_9": str(
            THUMBNAIL_16_9
        ),
        "thumbnail_vertical": str(
            THUMBNAIL_VERTICAL
        ),
        "width": 1280,
        "height": 720,
        "format": "jpeg",
    }

    THUMBNAIL_MANIFEST.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print()
    print("===== THUMBNAILS CREATED =====")
    print(THUMBNAIL_16_9)
    print(THUMBNAIL_VERTICAL)
    print(THUMBNAIL_MANIFEST)

    for path in [
        THUMBNAIL_16_9,
        THUMBNAIL_VERTICAL,
        THUMBNAIL_MANIFEST,
    ]:
        if not path.exists() or path.stat().st_size == 0:
            raise SystemExit(
                f"ERROR: Invalid output: {path}"
            )

    print()
    print(
        "Thumbnail generation: PASSED"
    )


if __name__ == "__main__":
    main()
