#!/usr/bin/env python3

import copy
import json
import tempfile
import zipfile
from pathlib import Path

from PIL import Image


BASE = Path(__file__).resolve().parents[1]

SCENES_FILE = BASE / "output" / "scenes" / "scenes.json"
VISUALS_DIR = BASE / "output" / "visuals"
OUTPUT_DIR = BASE / "output" / "i2v"
OUTPUT_ZIP = OUTPUT_DIR / "wan2gp_queue.zip"

# Exported from Wan2GP "Export Settings".
# This prevents us from guessing model-specific settings.
TEMPLATE_FILE = BASE / "Input" / "wan2gp_template.json"

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def fail(message):
    print(f"ERROR: {message}")
    raise SystemExit(1)


def load_json(path, description):
    if not path.exists():
        fail(f"{description} not found: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Could not parse {description}: {exc}")


def load_scenes():
    data = load_json(SCENES_FILE, "scenes.json")

    if isinstance(data, dict):
        scenes = data.get("scenes")
    elif isinstance(data, list):
        scenes = data
    else:
        scenes = None

    if not isinstance(scenes, list) or not scenes:
        fail("scenes.json does not contain a valid non-empty 'scenes' array.")

    return scenes


def load_template():
    """
    Load a real Wan2GP exported settings file.

    We intentionally do NOT manufacture model-specific fields here.
    Wan2GP documentation recommends exported settings as the safest
    template for a particular model.
    """

    template = load_json(TEMPLATE_FILE, "Wan2GP template")

    if not isinstance(template, dict):
        fail("Wan2GP template must contain a JSON object.")

    model_type = str(template.get("model_type") or "").strip()

    if not model_type:
        fail(
            "Wan2GP template does not contain 'model_type'. "
            "Export the settings from a real Wan2GP I2V configuration."
        )

    print(f"Template model : {model_type}")

    if "settings_version" in template:
        print(f"Settings ver.  : {template['settings_version']}")

    return template


def find_visual(part, scene):
    part_dir = VISUALS_DIR / f"part_{part:02d}"

    for ext in IMAGE_EXTENSIONS:
        candidate = part_dir / f"scene_{scene:02d}{ext}"

        if candidate.exists():
            return candidate

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
            raise ValueError(
                f"image too small: {width}x{height}"
            )

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
        "Generate real natural temporal movement.",
        "The subject must move naturally and continuously, not remain a static photograph.",
        "Preserve character identity, clothing, environment and composition.",
        "Create realistic cinematic motion rather than a slideshow, photo montage, "
        "zoom-only effect or pan-only effect.",
    ]

    if camera:
        sections.append(f"Camera movement: {camera}")

    if lighting:
        sections.append(f"Lighting: {lighting}")

    return "\n".join(sections)


def build_negative_prompt(scene, template):
    original = str(
        scene.get("negative_prompt")
        or template.get("negative_prompt")
        or ""
    ).strip()

    extra = [
        "static image",
        "frozen frame",
        "slideshow",
        "photo montage",
        "zoom-only",
        "pan-only",
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

    if original:
        parts.append(original)

    parts.extend(extra)

    result = []
    seen = set()

    for item in parts:
        value = item.strip()
        key = value.lower()

        if value and key not in seen:
            seen.add(key)
            result.append(value)

    return ", ".join(result)


def scene_duration(scene):
    value = scene.get("duration")

    try:
        duration = float(value)
    except Exception:
        duration = 5.0

    if duration <= 0:
        duration = 5.0

    return duration


def calculate_frames(duration, template):
    """
    Only modify video length when the exported template already tells us
    enough information to do it safely.

    Otherwise preserve the template's model-specific value.
    """

    existing = template.get("video_length")

    if existing is None:
        return None

    # Wan2GP accepts numeric frame counts.
    if isinstance(existing, int):
        fps_value = template.get("force_fps", 16)

        try:
            fps = float(fps_value)
        except Exception:
            fps = 16.0

        frames = max(1, round(duration * fps))

        # Common Wan-family temporal alignment.
        if frames > 1:
            frames = ((frames - 1) // 4) * 4 + 1

        return frames

    # If the template uses a duration string, leave it untouched.
    if isinstance(existing, str):
        return existing

    return None


def make_task(scene, embedded_image_name, template):
    try:
        part = int(scene["part"])
        scene_no = int(scene["scene"])
    except Exception:
        fail("Scene has invalid part/scene values.")

    params = copy.deepcopy(template)

    # Remove fields that belong to exported UI/session state rather than
    # an individual queue task.
    transient_keys = [
        "state",
        "start_image_labels",
        "end_image_labels",
        "start_image_data_base64",
        "end_image_data_base64",
        "start_image_data",
        "end_image_data",
        "profile_priority",
        "lset_name",
    ]

    for key in transient_keys:
        params.pop(key, None)

    # Scene-specific prompt.
    params["prompt"] = build_prompt(scene)

    # Negative prompt only if the template/model supports the field.
    if "negative_prompt" in params:
        params["negative_prompt"] = build_negative_prompt(
            scene,
            template,
        )
    elif scene.get("negative_prompt"):
        params["negative_prompt"] = build_negative_prompt(
            scene,
            template,
        )

    # Start image.
    params["image_start"] = embedded_image_name

    # Explicitly tell Wan2GP to treat the image as a start image when the
    # template already uses this mode.
    if "image_prompt_type" in params:
        params["image_prompt_type"] = "S"


    # Preserve model-specific resolution, sampling, guidance, acceleration,
    # profiles, etc. from the exported template.
    #
    # We intentionally DO NOT hard-code:
    # model_type
    # resolution
    # steps
    # guidance_scale
    # flow_shift
    # fps
    #
    # Those belong to the actual Wan2GP model/template.

    frames = calculate_frames(
        scene_duration(scene),
        template,
    )

    if frames is not None:
        params["video_length"] = frames

    output_name = f"part_{part:02d}_scene_{scene_no:02d}.mp4"

    params["output_filename"] = output_name

    # Keep these sane if the exported template contains them.
    if "batch_size" in params:
        params["batch_size"] = 1

    if "repeat_generation" in params:
        params["repeat_generation"] = 1

    return {
        "id": f"part_{part:02d}_scene_{scene_no:02d}",
        "params": params,
    }


def validate_queue(tasks, root):
    if not isinstance(tasks, list) or not tasks:
        fail("Generated queue is empty or is not a list.")

    for task in tasks:
        if not isinstance(task, dict):
            fail("Queue contains a non-object task.")

        task_id = task.get("id")

        if not task_id:
            fail("Queue task has no id.")

        params = task.get("params")

        if not isinstance(params, dict):
            fail(f"Task {task_id} has invalid params.")

        if not params.get("model_type"):
            fail(
                f"Task {task_id} has no model_type. "
                "The template must come from Wan2GP Export Settings."
            )

        image_name = params.get("image_start")

        if not image_name:
            fail(f"Task {task_id} has no image_start.")

        image_path = root / image_name

        if not image_path.exists():
            fail(
                f"Task {task_id} references missing embedded image: "
                f"{image_name}"
            )


def main():
    print("=" * 64)
    print("          BUILDING WAN2GP I2V QUEUE")
    print("=" * 64)
    print(f"Scenes file : {SCENES_FILE}")
    print(f"Visuals dir : {VISUALS_DIR}")
    print(f"Template    : {TEMPLATE_FILE}")
    print(f"Output ZIP  : {OUTPUT_ZIP}")
    print()

    scenes = load_scenes()
    template = load_template()

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

            try:
                with Image.open(visual) as img:
                    img.convert("RGB").save(
                        embedded_path,
                        format="PNG",
                        optimize=True,
                    )
            except Exception as exc:
                fail(
                    f"Could not embed image '{visual}': {exc}"
                )

            task = make_task(
                scene,
                embedded_name,
                template,
            )

            tasks.append(task)

            print(
                f"[{len(tasks):03d}] "
                f"Part {part:02d} Scene {scene_no:02d} | "
                f"{width}x{height} | "
                f"{embedded_name}"
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
            fail(
                "No valid scenes were converted into queue tasks."
            )

        validate_queue(tasks, temp_root)

        queue_json = temp_root / "queue.json"

        queue_json.write_text(
            json.dumps(
                tasks,
                ensure_ascii=False,
                indent=4,
            ),
            encoding="utf-8",
        )

        # Reload and validate the actual JSON that will be zipped.
        try:
            loaded = json.loads(
                queue_json.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as exc:
            fail(
                f"Generated queue.json cannot be reloaded: {exc}"
            )

        validate_queue(loaded, temp_root)

        if len(loaded) != len(tasks):
            fail(
                "Queue task count validation failed."
            )

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
                temp_root.glob(
                    "task*_image_start_0.png"
                )
            ):
                zf.write(
                    image_file,
                    arcname=image_file.name,
                )

    if not OUTPUT_ZIP.exists():
        fail(
            "Queue ZIP was not created."
        )

    # Final ZIP integrity validation.
    try:
        with zipfile.ZipFile(
            OUTPUT_ZIP,
            "r",
        ) as zf:

            names = zf.namelist()

            if "queue.json" not in names:
                fail(
                    "ZIP does not contain queue.json."
                )

            image_count = len(
                [
                    name
                    for name in names
                    if name.lower().endswith(
                        (".png", ".jpg", ".jpeg", ".webp")
                    )
                ]
            )

            if image_count != len(tasks):
                fail(
                    "ZIP image count mismatch: "
                    f"{image_count} images for "
                    f"{len(tasks)} tasks."
                )

            bad = zf.testzip()

            if bad is not None:
                fail(
                    f"ZIP integrity check failed at: {bad}"
                )

    except zipfile.BadZipFile as exc:
        fail(
            f"Generated queue ZIP is corrupt: {exc}"
        )

    zip_size_mb = (
        OUTPUT_ZIP.stat().st_size
        / (1024 * 1024)
    )

    print()
    print("=" * 64)
    print("                 QUEUE READY")
    print("=" * 64)
    print(f"Tasks       : {len(tasks)}")
    print(f"Images      : {image_count}")
    print(f"ZIP size    : {zip_size_mb:.2f} MB")
    print(f"Queue file  : {OUTPUT_ZIP}")
    print()
    print("Wan2GP validation command:")
    print(
        "python wgp.py "
        "--process output/i2v/wan2gp_queue.zip "
        "--dry-run"
    )
    print()
    print(
        "IMPORTANT: This queue uses the model/settings "
        "from Input/wan2gp_template.json."
    )
    print("=" * 64)


if __name__ == "__main__":
    main()
