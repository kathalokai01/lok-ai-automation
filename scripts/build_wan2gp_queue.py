#!/usr/bin/env python3

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from PIL import Image


BASE = Path(__file__).resolve().parents[1]

SCENES_FILE = BASE / "output" / "scenes" / "scenes.json"
VISUALS_DIR = BASE / "output" / "visuals"
OUTPUT_DIR = BASE / "output" / "i2v"
OUTPUT_ZIP = OUTPUT_DIR / "wan2gp_queue.zip"

# Wan 2.2 TI2V-5B FastWan
MODEL_TYPE = "ti2v_2_2"

# Free-T4 friendly target.
# Actual Wan2GP model/profile may adjust this further at runtime.
RESOLUTION = "480x832"

# 5 seconds ~= 81 frames at 16 FPS.
VIDEO_LENGTH = 81
FPS = 16

# FastWan is designed for low-step generation.
NUM_INFERENCE_STEPS = 6
GUIDANCE_SCALE = 1.0
FLOW_SHIFT = 3

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def fail(message):
    print(f"ERROR: {message}")
    raise SystemExit(1)


def load_scenes():
    if not SCENES_FILE.exists():
        fail(f"Scenes file not found: {SCENES_FILE}")

    try:
        data = json.loads(SCENES_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Could not parse scenes.json: {exc}")

    if isinstance(data, dict):
        scenes = data.get("scenes")

        if scenes is None:
            fail("scenes.json does not contain a 'scenes' array.")

    elif isinstance(data, list):
        scenes = data

    else:
        fail("Unsupported scenes.json structure.")

    if not isinstance(scenes, list) or not scenes:
        fail("No scenes found in scenes.json.")

    return scenes


def find_visual(part, scene):
    part_dir = VISUALS_DIR / f"part_{part:02d}"

    for ext in IMAGE_EXTENSIONS:
        candidate = part_dir / f"scene_{scene:02d}{ext}"
        if candidate.exists():
            return candidate

    # Fallback: tolerate alternate generated image names.
    if part_dir.exists():
        matches = sorted(
            p
            for p in part_dir.glob(f"scene_{scene:02d}.*")
            if p.suffix.lower() in IMAGE_EXTENSIONS
        )

        if matches:
            return matches[0]

    return None


def validate_image(path):
    try:
        with Image.open(path) as img:
            img.verify()

        with Image.open(path) as img:
            image = img.convert("RGB")
            width, height = image.size

        if width < 64 or height < 64:
            raise ValueError(f"image too small: {width}x{height}")

        return width, height

    except Exception as exc:
        fail(f"Invalid visual image '{path}': {exc}")


def build_prompt(scene):
    visual = str(scene.get("visual_prompt") or "").strip()
    camera = str(scene.get("camera_prompt") or "").strip()
    lighting = str(scene.get("lighting_prompt") or "").strip()

    if not visual:
        fail(
            f"Part {scene.get('part')} Scene {scene.get('scene')} "
            "has no visual_prompt."
        )

    sections = [
        visual,
        "Generate real natural movement and continuous temporal motion.",
        "The subject must move naturally rather than remaining a static photograph.",
        "Preserve the character identity, clothing, environment and composition from the input image.",
    ]

    if camera:
        sections.append(f"Camera movement: {camera}")

    if lighting:
        sections.append(f"Lighting: {lighting}")

    return "\n".join(sections)


def build_negative_prompt(scene):
    negative = str(scene.get("negative_prompt") or "").strip()

    extra = [
        "static image",
        "frozen frame",
        "slideshow",
        "photo montage",
        "cartoon",
        "anime",
        "illustration",
        "painting",
        "text",
        "watermark",
        "logo",
        "glitch",
        "distorted anatomy",
        "extra limbs",
    ]

    parts = []

    if negative:
        parts.append(negative)

    parts.extend(extra)

    # Remove duplicates while preserving order.
    seen = set()
    result = []

    for item in parts:
        key = item.lower().strip()

        if key and key not in seen:
            seen.add(key)
            result.append(item.strip())

    return ", ".join(result)


def make_task(scene, embedded_image_name):
    part = int(scene["part"])
    scene_no = int(scene["scene"])

    duration = scene.get("duration")

    try:
        duration = float(duration)
    except Exception:
        duration = 5.0

    # Keep the queue deterministic and T4-friendly.
    frames = max(49, min(81, round(duration * FPS)))

    # Wan video lengths are normally frame-count based.
    # Round to 4n+1 style values where practical.
    frames = ((frames - 1) // 4) * 4 + 1

    if frames < 49:
        frames = 49

    if frames > 81:
        frames = 81

    return {
        "id": f"part_{part:02d}_scene_{scene_no:02d}",
        "params": {
            "model_type": MODEL_TYPE,
            "prompt": build_prompt(scene),
            "negative_prompt": build_negative_prompt(scene),

            # Image-to-video.
            "image_start": embedded_image_name,
            "image_prompt_type": "S",

            # T4-oriented generation settings.
            "resolution": RESOLUTION,
            "video_length": frames,
            "force_fps": str(FPS),
            "num_inference_steps": NUM_INFERENCE_STEPS,
            "guidance_scale": GUIDANCE_SCALE,
            "flow_shift": FLOW_SHIFT,

            "batch_size": 1,
            "repeat_generation": 1,
            "seed": -1,

            # Avoid accidental multi-prompt expansion.
            "multi_prompts_gen_type": "FG",
            "multi_images_gen_type": 0,

            # Keep motion natural.
            "motion_amplitude": 1.0,

            # Output naming.
            "output_filename": (
                f"part_{part:02d}_scene_{scene_no:02d}.mp4"
            ),
        },
    }


def main():
    print("=" * 60)
    print("       BUILDING WAN2GP I2V QUEUE")
    print("=" * 60)

    print(f"Scenes file : {SCENES_FILE}")
    print(f"Visuals dir : {VISUALS_DIR}")
    print(f"Output ZIP  : {OUTPUT_ZIP}")
    print(f"Model       : {MODEL_TYPE}")
    print(f"Resolution  : {RESOLUTION}")
    print(f"FPS         : {FPS}")
    print(f"Steps       : {NUM_INFERENCE_STEPS}")
    print()

    scenes = load_scenes()

    # Stable ordering.
    scenes = sorted(
        scenes,
        key=lambda x: (
            int(x.get("part", 0)),
            int(x.get("scene", 0)),
        ),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    tasks = []
    missing = []

    with tempfile.TemporaryDirectory(
        prefix="wan2gp_queue_"
    ) as temp_dir:

        temp_root = Path(temp_dir)

        for index, scene in enumerate(scenes, start=1):
            try:
                part = int(scene["part"])
                scene_no = int(scene["scene"])
            except Exception:
                fail(
                    f"Scene #{index} has invalid part/scene values."
                )

            visual = find_visual(part, scene_no)

            if visual is None:
                missing.append(
                    f"part_{part:02d}/scene_{scene_no:02d}"
                )
                continue

            width, height = validate_image(visual)

            embedded_name = (
                f"task{index}_image_start_0.png"
            )

            embedded_path = temp_root / embedded_name

            # Convert every source image to PNG so the queue has
            # one deterministic image format.
            with Image.open(visual) as img:
                img.convert("RGB").save(
                    embedded_path,
                    format="PNG",
                    optimize=True,
                )

            task = make_task(
                scene,
                embedded_name,
            )

            tasks.append(task)

            print(
                f"[{len(tasks):03d}] "
                f"Part {part:02d} Scene {scene_no:02d} "
                f"| {width}x{height} "
                f"| {embedded_name}"
            )

        if missing:
            print()
            print("Missing visual assets:")
            for item in missing:
                print(f"  - {item}")

            fail(
                f"{len(missing)} scene visual(s) are missing. "
                "Queue was NOT created."
            )

        if not tasks:
            fail("No valid scenes were converted into queue tasks.")

        queue_json = temp_root / "queue.json"

        queue_json.write_text(
            json.dumps(
                tasks,
                ensure_ascii=False,
                indent=4,
            ),
            encoding="utf-8",
        )

        # Validate queue.json before creating ZIP.
        loaded = json.loads(
            queue_json.read_text(encoding="utf-8")
        )

        if not isinstance(loaded, list):
            fail("Generated queue.json is not a list.")

        if len(loaded) != len(tasks):
            fail("Queue task count validation failed.")

        # Validate every referenced image exists.
        for task in loaded:
            params = task.get("params", {})
            image_name = params.get("image_start")

            if not image_name:
                fail(
                    f"Task {task.get('id')} has no image_start."
                )

            image_path = temp_root / image_name

            if not image_path.exists():
                fail(
                    f"Embedded image missing: {image_name}"
                )

        # Build ZIP exactly in the Wan2GP-compatible pattern:
        # queue.json + embedded media files.
        with zipfile.ZipFile(
            OUTPUT_ZIP,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:

            zf.write(
                queue_json,
                arcname="queue.json",
            )

            for image_file in sorted(
                temp_root.glob("task*_image_start_0.png")
            ):
                zf.write(
                    image_file,
                    arcname=image_file.name,
                )

    # Final ZIP validation.
    if not OUTPUT_ZIP.exists():
        fail("Queue ZIP was not created.")

    with zipfile.ZipFile(
        OUTPUT_ZIP,
        "r",
    ) as zf:

        names = zf.namelist()

        if "queue.json" not in names:
            fail("ZIP does not contain queue.json.")

        image_count = len(
            [
                name
                for name in names
                if name.endswith(".png")
            ]
        )

        if image_count != len(tasks):
            fail(
                "ZIP image count mismatch: "
                f"{image_count} images for {len(tasks)} tasks."
            )

        bad = zf.testzip()

        if bad is not None:
            fail(
                f"ZIP integrity check failed at: {bad}"
            )

    zip_size_mb = OUTPUT_ZIP.stat().st_size / (
        1024 * 1024
    )

    print()
    print("=" * 60)
    print("              QUEUE READY")
    print("=" * 60)
    print(f"Tasks       : {len(tasks)}")
    print(f"Images      : {image_count}")
    print(f"ZIP size    : {zip_size_mb:.2f} MB")
    print(f"Queue file  : {OUTPUT_ZIP}")
    print()
    print("Wan2GP dry-run command:")
    print(
        "python wgp.py "
        "--process output/i2v/wan2gp_queue.zip "
        "--dry-run"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
