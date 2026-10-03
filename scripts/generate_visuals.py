#!/usr/bin/env python3

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

from input_config import (
    load_input_config,
    normalize_format,
)


BASE = Path("output")

SCENES_FILE = (
    BASE / "scenes" / "scenes.json"
)

CHARACTER_BIBLE_FILE = (
    BASE
    / "character_bible"
    / "character_bible.json"
)

MODEL_FILE = (
    BASE
    / "config"
    / "selected_visual_model.json"
)

VISUALS_DIR = (
    BASE / "visuals"
)

MANIFEST_FILE = (
    VISUALS_DIR / "visual_jobs.json"
)

DEFAULT_MODEL = (
    "alibaba/wan-2.6-image"
)

API_BASE = (
    "https://api.cloudflare.com/client/v4/accounts"
)

REQUEST_TIMEOUT = 180


# ============================================================
# INPUT CONFIG COMPATIBILITY HELPERS
# ============================================================

def cfg_text(config, key, default=""):
    value = config.get(key, default)

    if value is None:
        return str(default)

    return str(value).strip()


def cfg_bool(config, key, default=False):
    value = config.get(key, default)

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"true", "yes", "on", "1"}:
        return True

    if text in {"false", "no", "off", "0"}:
        return False

    return bool(default)


def cfg_int(config, key, default=0):
    value = config.get(key, default)

    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


# ============================================================
# BASIC HELPERS
# ============================================================

def fail(message):
    print(f"ERROR: {message}")
    sys.exit(1)


def load_json(path, default=None):

    if not path.exists():
        return default

    try:

        with path.open(
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as exc:

        print(
            f"WARNING: Failed to read "
            f"{path}: {exc}"
        )

        return default


def save_json(path, data):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    with tmp.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    tmp.replace(path)


def valid_image(path):

    if not path.exists():
        return False

    if not path.is_file():
        return False

    try:
        return path.stat().st_size > 1000

    except Exception:
        return False


# ============================================================
# FORMAT / IMAGE SIZE
# ============================================================

def get_image_size(format_name):

    """
    Cloudflare Wan 2.6 Image supports custom WxH size.

    SHORT:
        Portrait source image.

    FULL:
        Landscape source image.

    Final render:
        SHORT -> 720x1280
        FULL  -> 1920x1080
    """

    if format_name == "short":
        return "768x1024"

    return "1024x768"


# ============================================================
# MODEL
# ============================================================

def get_model():

    data = load_json(
        MODEL_FILE,
        {}
    )

    if isinstance(
        data,
        dict
    ):

        model = str(
            data.get(
                "model",
                ""
            )
        ).strip()

        status = str(
            data.get(
                "status",
                ""
            )
        ).strip().lower()

        if (
            model
            and status == "selected"
        ):

            print(
                f"Selected visual model: "
                f"{model}"
            )

            return model

    print(
        "WARNING: No valid selected "
        "visual model found."
    )

    print(
        f"Using fallback model: "
        f"{DEFAULT_MODEL}"
    )

    return DEFAULT_MODEL


# ============================================================
# CREDENTIALS
# ============================================================

def get_credentials():

    account_id = os.getenv(
        "CLOUDFLARE_ACCOUNT_ID",
        ""
    ).strip()

    api_token = os.getenv(
        "CLOUDFLARE_API_TOKEN",
        ""
    ).strip()

    if not account_id:

        fail(
            "CLOUDFLARE_ACCOUNT_ID "
            "is not set."
        )

    if not api_token:

        fail(
            "CLOUDFLARE_API_TOKEN "
            "is not set."
        )

    return (
        account_id,
        api_token
    )


# ============================================================
# NEGATIVE PROMPT
# ============================================================

def build_negative_prompt(config):

    negative = []

    if cfg_bool(
        config,
        "AVOID_CARTOON_LOOK",
        True
    ):

        negative.extend([
            "cartoon",
            "comic",
            "anime",
            "illustration",
            "drawing",
            "2D art",
        ])

    if cfg_bool(
        config,
        "AVOID_NEON",
        True
    ):

        negative.append(
            "neon colors"
        )

    if cfg_bool(
        config,
        "AVOID_GLITCH_EFFECTS",
        True
    ):

        negative.extend([
            "glitch",
            "digital distortion",
        ])

    negative.extend([
        "CGI look",
        "plastic skin",
        "artificial face",
        "deformed anatomy",
        "extra fingers",
        "extra limbs",
        "duplicate person",
        "watermark",
        "logo",
        "text",
    ])

    return ", ".join(
        negative
    )


# ============================================================
# VISUAL PROMPT
# ============================================================

def build_visual_prompt(
    config,
    scene,
    character_bible
):

    visual_style = cfg_text(
        config,
        "VISUAL_STYLE",
        "cinematic_realistic"
    )

    realism = cfg_text(
        config,
        "REALISM",
        "high"
    )

    camera_style = cfg_text(
        config,
        "CAMERA_STYLE",
        "cinematic"
    )

    lighting = cfg_text(
        config,
        "LIGHTING",
        "cinematic"
    )

    mood = cfg_text(
        config,
        "MOOD",
        "dramatic"
    )

    quality = cfg_text(
        config,
        "QUALITY",
        "high"
    )

    natural_motion = cfg_bool(
        config,
        "NATURAL_MOTION",
        True
    )

    realistic_lighting = cfg_bool(
        config,
        "REALISTIC_LIGHTING",
        True
    )

    scene_prompt = str(
        scene.get(
            "visual_prompt",
            scene.get(
                "visual",
                scene.get(
                    "description",
                    ""
                )
            )
        )
    ).strip()

    characters = scene.get(
        "characters",
        scene.get(
            "character_ids",
            []
        )
    )

    world_context = scene.get(
        "world_context",
        scene.get(
            "world",
            ""
        )
    )

    character_context = ""

    if (
        isinstance(
            character_bible,
            dict
        )
        and characters
    ):

        bible_characters = (
            character_bible.get(
                "characters",
                []
            )
        )

        if isinstance(
            bible_characters,
            list
        ):

            wanted = set(
                str(x)
                for x in characters
            )

            selected = []

            for character in (
                bible_characters
            ):

                if not isinstance(
                    character,
                    dict
                ):
                    continue

                char_id = str(
                    character.get(
                        "id",
                        ""
                    )
                )

                if char_id in wanted:

                    selected.append(
                        character
                    )

            if selected:

                character_context = (
                    json.dumps(
                        selected,
                        ensure_ascii=False
                    )
                )

    prompt_parts = [

        "Photorealistic live-action "
        "cinematic frame.",

        "Real human beings and "
        "real-world physical environments.",

        f"Visual style: {visual_style}.",

        f"Realism level: {realism}.",

        f"Camera style: {camera_style}.",

        f"Lighting: {lighting}.",

        f"Mood: {mood}.",

        f"Quality: {quality}.",
    ]

    if natural_motion:

        prompt_parts.append(
            "Natural human posture and "
            "physically believable movement."
        )

    if realistic_lighting:

        prompt_parts.append(
            "Physically realistic natural "
            "lighting and shadows."
        )

    if scene_prompt:

        prompt_parts.append(
            f"Scene description: "
            f"{scene_prompt}"
        )

    if world_context:

        prompt_parts.append(
            f"World continuity: "
            f"{world_context}"
        )

    if character_context:

        prompt_parts.append(
            "Character continuity reference: "
            + character_context
        )

    prompt_parts.append(
        "Maintain identity, clothing, "
        "location, time, environment and "
        "visual continuity with surrounding scenes."
    )

    return " ".join(
        prompt_parts
    )


# ============================================================
# CONFIG SIGNATURE
# ============================================================

def config_signature(
    config,
    model,
    image_size
):

    relevant = {

        "model": model,

        "format": normalize_format(
            config
        ),

        "image_size": image_size,

        "visual_style": cfg_text(
            config,
            "VISUAL_STYLE",
            ""
        ),

        "realism": cfg_text(
            config,
            "REALISM",
            ""
        ),

        "character_bible": cfg_bool(
            config,
            "CHARACTER_BIBLE",
            True
        ),

        "character_consistency": cfg_bool(
            config,
            "CHARACTER_CONSISTENCY",
            True
        ),

        "world_consistency": cfg_bool(
            config,
            "WORLD_CONSISTENCY",
            True
        ),

        "scene_continuity": cfg_bool(
            config,
            "SCENE_CONTINUITY",
            True
        ),

        "cinematic_camera": cfg_bool(
            config,
            "CINEMATIC_CAMERA",
            True
        ),

        "camera_style": cfg_text(
            config,
            "CAMERA_STYLE",
            ""
        ),

        "lighting": cfg_text(
            config,
            "LIGHTING",
            ""
        ),

        "mood": cfg_text(
            config,
            "MOOD",
            ""
        ),

        "quality": cfg_text(
            config,
            "QUALITY",
            ""
        ),

        "negative_prompt": cfg_bool(
            config,
            "NEGATIVE_PROMPT",
            True
        ),

        "avoid_cartoon": cfg_bool(
            config,
            "AVOID_CARTOON_LOOK",
            True
        ),

        "avoid_neon": cfg_bool(
            config,
            "AVOID_NEON",
            True
        ),

        "avoid_glitch": cfg_bool(
            config,
            "AVOID_GLITCH_EFFECTS",
            True
        ),

        "natural_motion": cfg_bool(
            config,
            "NATURAL_MOTION",
            True
        ),

        "realistic_lighting": cfg_bool(
            config,
            "REALISTIC_LIGHTING",
            True
        ),

        "transitions": cfg_text(
            config,
            "TRANSITIONS",
            ""
        ),
    }

    raw = json.dumps(
        relevant,
        ensure_ascii=False,
        sort_keys=True
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# EXTRACT / DOWNLOAD IMAGE
# ============================================================

def download_image_url(url):

    try:

        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        content = response.content

        if (
            content
            and len(content) > 1000
        ):

            return content

    except requests.RequestException as exc:

        print(
            "    Failed to download "
            f"generated image URL: {exc}"
        )

    return None


def decode_image_string(value):

    if not isinstance(
        value,
        str
    ):
        return None

    value = value.strip()

    if not value:
        return None

    if (
        value.startswith("http://")
        or value.startswith("https://")
    ):

        return download_image_url(
            value
        )

    if value.startswith(
        "data:image"
    ):

        try:

            encoded = value.split(
                ",",
                1
            )[1]

            decoded = base64.b64decode(
                encoded
            )

            if len(decoded) > 1000:
                return decoded

        except Exception:
            return None

    try:

        decoded = base64.b64decode(
            value,
            validate=True
        )

        if len(decoded) > 1000:
            return decoded

    except Exception:
        pass

    return None


def extract_image_bytes(data):

    if not isinstance(
        data,
        dict
    ):
        return None

    result = data.get(
        "result"
    )

    if not isinstance(
        result,
        dict
    ):
        return None

    candidates = [

        result.get("image"),

        result.get("image_data"),

        result.get("output"),

        result.get("data"),
    ]

    for item in candidates:

        if isinstance(
            item,
            str
        ):

            image_bytes = (
                decode_image_string(
                    item
                )
            )

            if image_bytes:
                return image_bytes

        if isinstance(
            item,
            dict
        ):

            nested_candidates = [

                item.get("image"),

                item.get("image_data"),

                item.get("data"),

                item.get("url"),
            ]

            for value in (
                nested_candidates
            ):

                image_bytes = (
                    decode_image_string(
                        value
                    )
                )

                if image_bytes:
                    return image_bytes

    return None


# ============================================================
# IMAGE GENERATION
# ============================================================

def generate_image(
    account_id,
    api_token,
    model,
    prompt,
    negative_prompt,
    image_size,
    retries
):

    url = (
        f"{API_BASE}/"
        f"{account_id}"
        f"/ai/run/@{model}"
    )

    headers = {

        "Authorization":
            f"Bearer {api_token}",

        "Content-Type":
            "application/json",
    }

    payload = {

        "prompt": prompt,

        "size": image_size,
    }

    if negative_prompt:

        payload[
            "negative_prompt"
        ] = negative_prompt

    print(
        f"    Image size: "
        f"{image_size}"
    )

    total_attempts = max(
        1,
        retries
    )

    for attempt in range(
        1,
        total_attempts + 1
    ):

        print(
            f"    Generation attempt "
            f"{attempt}/"
            f"{total_attempts}"
        )

        try:

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

        except requests.RequestException as exc:

            print(
                f"    Request error: "
                f"{exc}"
            )

            if attempt < total_attempts:

                time.sleep(
                    min(
                        5 * attempt,
                        30
                    )
                )

                continue

            return None

        if response.status_code in (
            200,
            201,
            202
        ):

            try:

                data = response.json()

            except Exception as exc:

                print(
                    "    Invalid JSON response: "
                    f"{exc}"
                )

                data = {}

            image_bytes = (
                extract_image_bytes(
                    data
                )
            )

            if image_bytes:
                return image_bytes

            print(
                "    Model returned no "
                "usable image data."
            )

            print(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2
                )[:3000]
            )

        elif response.status_code in (
            429,
            500,
            502,
            503,
            504
        ):

            print(
                f"    Temporary Cloudflare "
                f"error {response.status_code}"
            )

        else:

            print(
                f"    Cloudflare error "
                f"{response.status_code}"
            )

            print(
                response.text[:3000]
            )

            if response.status_code in (
                400,
                401,
                403,
                404
            ):

                return None

        if attempt < total_attempts:

            wait = min(
                5 * attempt,
                30
            )

            time.sleep(
                wait
            )

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "          GENERATING VISUALS"
    )

    print(
        "=" * 60
    )

    config = load_input_config()

    format_name = normalize_format(
        config
    )

    image_size = get_image_size(
        format_name
    )

    parts = cfg_int(
        config,
        "PARTS",
        1
    )

    scenes_per_part = cfg_int(
        config,
        "SCENES",
        1
    )

    max_retries = cfg_int(
        config,
        "MAX_RETRIES",
        3
    )

    resume_enabled = cfg_bool(
        config,
        "RESUME_ENABLED",
        True
    )

    skip_completed = cfg_bool(
        config,
        "SKIP_COMPLETED_SCENES",
        True
    )

    save_checkpoint = cfg_bool(
        config,
        "SAVE_CHECKPOINT_AFTER_EACH_SCENE",
        True
    )

    character_bible_enabled = cfg_bool(
        config,
        "CHARACTER_BIBLE",
        True
    )

    model = get_model()

    print(
        f"FORMAT          : "
        f"{format_name}"
    )

    print(
        f"IMAGE SIZE      : "
        f"{image_size}"
    )

    print(
        f"MODEL           : "
        f"{model}"
    )

    print(
        f"PARTS           : "
        f"{parts}"
    )

    print(
        f"SCENES/PART     : "
        f"{scenes_per_part}"
    )

    print(
        f"MAX_RETRIES     : "
        f"{max_retries}"
    )

    if not SCENES_FILE.exists():

        fail(
            f"Missing scenes file: "
            f"{SCENES_FILE}"
        )

    scenes_data = load_json(
        SCENES_FILE,
        {}
    )

    scenes = scenes_data.get(
        "scenes",
        []
    )

    expected_total = (
        parts
        * scenes_per_part
    )

    if len(scenes) != expected_total:

        fail(
            "Scene count mismatch: "
            f"expected {expected_total}, "
            f"got {len(scenes)}"
        )

    character_bible = {}

    if character_bible_enabled:

        if not CHARACTER_BIBLE_FILE.exists():

            fail(
                "CHARACTER_BIBLE=true "
                "but file is missing: "
                f"{CHARACTER_BIBLE_FILE}"
            )

        character_bible = load_json(
            CHARACTER_BIBLE_FILE,
            {}
        )

    account_id, api_token = (
        get_credentials()
    )

    VISUALS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    old_manifest = load_json(
        MANIFEST_FILE,
        {}
    )

    old_jobs = {}

    if (
        isinstance(
            old_manifest,
            dict
        )
        and isinstance(
            old_manifest.get("jobs"),
            dict
        )
    ):

        old_jobs = (
            old_manifest["jobs"]
        )

    signature = config_signature(
        config,
        model,
        image_size
    )

    jobs = {}

    completed = 0

    negative_prompt = ""

    if cfg_bool(
        config,
        "NEGATIVE_PROMPT",
        True
    ):

        negative_prompt = (
            build_negative_prompt(
                config
            )
        )

    for index, scene in enumerate(
        scenes,
        start=1
    ):

        part = int(
            scene.get(
                "part",
                (
                    (
                        index - 1
                    )
                    // scenes_per_part
                )
                + 1
            )
        )

        scene_number = int(
            scene.get(
                "scene",
                (
                    (
                        index - 1
                    )
                    % scenes_per_part
                )
                + 1
            )
        )

        key = (
            f"part_{part:02d}/"
            f"scene_{scene_number:02d}"
        )

        output_path = (
            VISUALS_DIR
            / f"part_{part:02d}"
            / f"scene_{scene_number:02d}.png"
        )

        old_job = old_jobs.get(
            key,
            {}
        )

        old_signature = (
            old_job.get(
                "config_signature"
            )
            if isinstance(
                old_job,
                dict
            )
            else None
        )

        old_model = (
            old_job.get(
                "model"
            )
            if isinstance(
                old_job,
                dict
            )
            else None
        )

        old_image_size = (
            old_job.get(
                "image_size"
            )
            if isinstance(
                old_job,
                dict
            )
            else None
        )

        physical_valid = (
            valid_image(
                output_path
            )
        )

        reusable = (

            resume_enabled

            and skip_completed

            and physical_valid

            and old_model == model

            and old_image_size == image_size

            and old_signature == signature
        )

        if reusable:

            print(
                f"[{index}/"
                f"{expected_total}] "
                f"SKIP {key} "
                f"(valid existing visual)"
            )

            jobs[key] = {

                "part": part,

                "scene": scene_number,

                "status": "completed",

                "model": model,

                "image_size": image_size,

                "config_signature": signature,

                "visual_path": str(
                    output_path
                ),
            }

            completed += 1

            continue

        print()

        print(
            f"[{index}/"
            f"{expected_total}] "
            f"GENERATE {key}"
        )

        prompt = build_visual_prompt(
            config,
            scene,
            character_bible
        )

        image_bytes = generate_image(
            account_id,
            api_token,
            model,
            prompt,
            negative_prompt,
            image_size,
            max_retries
        )

        if not image_bytes:

            jobs[key] = {

                "part": part,

                "scene": scene_number,

                "status": "failed",

                "model": model,

                "image_size": image_size,

                "config_signature": signature,

                "visual_path": str(
                    output_path
                ),
            }

            save_json(
                MANIFEST_FILE,
                {

                    "status": "failed",

                    "format": format_name,

                    "model": model,

                    "image_size": image_size,

                    "config_signature": signature,

                    "expected_total":
                        expected_total,

                    "completed":
                        completed,

                    "jobs": jobs,
                }
            )

            fail(
                "Visual generation failed "
                f"for {key}"
            )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with output_path.open(
            "wb"
        ) as f:

            f.write(
                image_bytes
            )

        if not valid_image(
            output_path
        ):

            fail(
                "Generated visual is invalid: "
                f"{output_path}"
            )

        jobs[key] = {

            "part": part,

            "scene": scene_number,

            "status": "completed",

            "model": model,

            "image_size": image_size,

            "config_signature": signature,

            "visual_path": str(
                output_path
            ),
        }

        completed += 1

        if save_checkpoint:

            save_json(
                MANIFEST_FILE,
                {

                    "status": "pending",

                    "format": format_name,

                    "model": model,

                    "image_size": image_size,

                    "config_signature": signature,

                    "expected_total":
                        expected_total,

                    "completed":
                        completed,

                    "pending":
                        expected_total
                        - completed,

                    "jobs": jobs,
                }
            )

    # ========================================================
    # FINAL VALIDATION
    # ========================================================

    missing = []

    for part in range(
        1,
        parts + 1
    ):

        for scene_number in range(
            1,
            scenes_per_part + 1
        ):

            path = (
                VISUALS_DIR
                / f"part_{part:02d}"
                / f"scene_{scene_number:02d}.png"
            )

            if not valid_image(
                path
            ):

                missing.append(
                    f"Part {part} "
                    f"Scene {scene_number}"
                )

    if missing:

        save_json(
            MANIFEST_FILE,
            {

                "status": "failed",

                "format": format_name,

                "model": model,

                "image_size": image_size,

                "config_signature":
                    signature,

                "expected_total":
                    expected_total,

                "completed":
                    expected_total
                    - len(missing),

                "missing": missing,

                "jobs": jobs,
            }
        )

        fail(
            "Missing visual(s): "
            + ", ".join(
                missing
            )
        )

    save_json(
        MANIFEST_FILE,
        {

            "status": "completed",

            "format": format_name,

            "model": model,

            "image_size": image_size,

            "config_signature":
                signature,

            "expected_total":
                expected_total,

            "completed":
                expected_total,

            "pending": 0,

            "jobs": jobs,
        }
    )

    print()

    print(
        "=" * 60
    )

    print(
        "          VISUAL GENERATION COMPLETE"
    )

    print(
        "=" * 60
    )

    print(
        f"Model           : "
        f"{model}"
    )

    print(
        f"Format          : "
        f"{format_name}"
    )

    print(
        f"Image size      : "
        f"{image_size}"
    )

    print(
        f"Visuals         : "
        f"{completed}/"
        f"{expected_total}"
    )

    print(
        f"Manifest        : "
        f"{MANIFEST_FILE}"
    )

    print(
        "=" * 60
    )

    return 0


if __name__ == "__main__":

    sys.exit(
        main()
    )
