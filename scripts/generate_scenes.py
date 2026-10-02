#!/usr/bin/env python3

import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path


CONFIG_FILE = Path("Input/topic.txt")
OUTPUT_DIR = Path("output/scenes")
SCENES_FILE = OUTPUT_DIR / "scenes.json"
CHECKPOINT_FILE = Path("output/checkpoints/scenes_progress.json")

MAX_ATTEMPTS = int(os.getenv("SCENE_MAX_ATTEMPTS", "5"))
INITIAL_BACKOFF = int(os.getenv("SCENE_INITIAL_BACKOFF", "15"))
MAX_BACKOFF = int(os.getenv("SCENE_MAX_BACKOFF", "300"))
REQUEST_DELAY = float(os.getenv("SCENE_REQUEST_DELAY", "2"))
REQUEST_TIMEOUT = int(os.getenv("SCENE_REQUEST_TIMEOUT", "120"))


def log(message=""):
    print(message, flush=True)


# ============================================================
# CONFIG PARSER
# ============================================================

def clean_config_value(value):
    """
    Remove inline comments safely.

    Example:
        4   # number of parts
    becomes:
        4

    Quoted strings are preserved.
    """

    value = value.strip()

    if not value:
        return ""

    # Remove inline comment.
    if "#" in value:
        value = value.split("#", 1)[0].strip()

    # Remove surrounding quotes.
    if len(value) >= 2:
        if (
            value.startswith('"')
            and value.endswith('"')
        ):
            value = value[1:-1]

        elif (
            value.startswith("'")
            and value.endswith("'")
        ):
            value = value[1:-1]

    return value.strip()


def load_config():
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_FILE}"
        )

    config = {}

    for raw_line in CONFIG_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        key = key.strip()
        value = clean_config_value(value)

        config[key] = value

    return config


def read_int_config(config, key, default):
    value = config.get(key, "")

    try:
        number = int(str(value).strip())

        if number < 1:
            raise ValueError

        return number

    except Exception:
        raise ValueError(
            f"Invalid {key} value: {value!r}. "
            f"Expected a positive integer."
        )


# ============================================================
# JSON
# ============================================================

def read_json(path):
    if not path.exists():
        return None

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        log(
            f"WARNING: Could not read JSON "
            f"{path}: {exc}"
        )
        return None


def write_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    temp_path.replace(path)


# ============================================================
# CHECKPOINT
# ============================================================

def scene_key(part_number, scene_number):
    return f"{part_number}:{scene_number}"


def save_checkpoint(
    total_scenes,
    completed_scenes,
    failed_scene=None,
):
    completed = sorted(
        list(completed_scenes)
    )

    checkpoint = {
        "status": (
            "completed"
            if len(completed) >= total_scenes
            else "in_progress"
        ),
        "total_scenes": total_scenes,
        "completed_scenes": completed,
        "completed_count": len(completed),
        "remaining_scenes": max(
            0,
            total_scenes - len(completed)
        ),
        "failed_scene": failed_scene,
        "updated_at": int(time.time()),
    }

    write_json(
        CHECKPOINT_FILE,
        checkpoint
    )


def load_checkpoint():
    data = read_json(CHECKPOINT_FILE)

    if not isinstance(data, dict):
        return set()

    completed = data.get(
        "completed_scenes",
        []
    )

    if not isinstance(completed, list):
        return set()

    result = set()

    for item in completed:

        if isinstance(item, str) and ":" in item:
            result.add(item)
            continue

        try:
            result.add(str(int(item)))
        except Exception:
            pass

    return result


# ============================================================
# EXISTING SCENES
# ============================================================

def scene_already_saved(
    existing_scenes,
    part_number,
    scene_number,
):
    key = scene_key(
        part_number,
        scene_number
    )

    for scene in existing_scenes:

        if not isinstance(scene, dict):
            continue

        try:
            part = int(
                scene.get("part", -1)
            )

            number = int(
                scene.get("scene", -1)
            )

            if (
                part == part_number
                and number == scene_number
            ):
                return True

        except Exception:
            pass

        scene_id = str(
            scene.get("id", "")
        ).strip()

        if scene_id in {
            key,
            f"scene_{part_number}_{scene_number}",
            f"part_{part_number}_scene_{scene_number}",
        }:
            return True

    return False


# ============================================================
# GEMINI
# ============================================================

def get_model():

    selected_model_file = Path(
        "output/config/selected_model.json"
    )

    data = read_json(
        selected_model_file
    )

    if isinstance(data, dict):

        for key in (
            "model",
            "selected_model",
            "name",
        ):

            value = data.get(key)

            if value:
                return str(value).strip()

    return "gemini-3.5-flash-lite"


def get_api_key():

    key = os.getenv(
        "GEMINI_API_KEY",
        ""
    ).strip()

    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured."
        )

    return key


def call_gemini(
    api_key,
    model,
    prompt,
):

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "responseMimeType": "application/json"
        }
    }

    body = json.dumps(
        payload,
        ensure_ascii=False
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT
        ) as response:

            raw = response.read().decode(
                "utf-8"
            )

            data = json.loads(raw)

    except urllib.error.HTTPError as exc:

        if exc.code == 429:
            raise

        try:
            error_body = exc.read().decode(
                "utf-8",
                errors="replace"
            )
        except Exception:
            error_body = str(exc)

        raise RuntimeError(
            f"Gemini HTTP {exc.code}: "
            f"{error_body[:1000]}"
        ) from exc

    except urllib.error.URLError as exc:

        raise RuntimeError(
            f"Gemini network error: {exc}"
        ) from exc

    candidates = data.get(
        "candidates",
        []
    )

    if not candidates:
        raise RuntimeError(
            "Gemini returned no candidates."
        )

    content = candidates[0].get(
        "content",
        {}
    )

    parts = content.get(
        "parts",
        []
    )

    if not parts:
        raise RuntimeError(
            "Gemini returned empty content."
        )

    text = parts[0].get(
        "text",
        ""
    ).strip()

    if not text:
        raise RuntimeError(
            "Gemini returned empty text."
        )

    return text


# ============================================================
# JSON RESPONSE
# ============================================================

def parse_json_response(text):

    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    if text.startswith("```"):

        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip() == "```"
        ):
            lines = lines[:-1]

        cleaned = "\n".join(
            lines
        ).strip()

        try:
            return json.loads(cleaned)
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:

        candidate = text[
            start:end + 1
        ]

        try:
            return json.loads(candidate)
        except Exception:
            pass

    raise ValueError(
        "Gemini response was not valid JSON."
    )


# ============================================================
# PROMPT
# ============================================================

def build_prompt(
    config,
    story,
    part_number,
    scene_number,
):

    story_text = json.dumps(
        story,
        ensure_ascii=False,
        indent=2
    )

    style = config.get(
        "VISUAL_STYLE",
        "cinematic"
    )

    realism = config.get(
        "REALISM",
        "high"
    )

    return f"""
You are generating ONE scene for an AI-generated Hindi
story video.

Return ONLY valid JSON.

PROJECT:
{story_text}

VIDEO CONFIGURATION:
Visual style: {style}
Realism: {realism}
Audience: {config.get("AUDIENCE", "")}
Format: {config.get("FORMAT", "vertical")}
Scene duration: {config.get("SCENE_DURATION", "")}

CURRENT SCENE:
Part: {part_number}
Scene: {scene_number}

Create a detailed scene suitable for downstream
visual generation.

Return exactly this structure:

{{
  "part": {part_number},
  "scene": {scene_number},
  "title": "short scene title",
  "narration": "Hindi narration for this scene",
  "visual_prompt": "detailed cinematic visual prompt",
  "negative_prompt": "things that must not appear",
  "duration": "scene duration",
  "transition": "appropriate transition"
}}

Rules:
- Keep continuity with the story.
- Keep characters visually consistent.
- Do not invent unrelated characters.
- Narration must be Hindi.
- Visual prompt must be detailed.
- Return JSON only.
""".strip()


# ============================================================
# RETRY
# ============================================================

def extract_retry_after(error):

    if not error:
        return None

    try:

        value = error.headers.get(
            "Retry-After"
        )

        if value:

            seconds = float(value)

            if seconds >= 0:
                return seconds

    except Exception:
        pass

    return None


def calculate_backoff(attempt):

    base = INITIAL_BACKOFF * (
        2 ** max(
            0,
            attempt - 1
        )
    )

    base = min(
        base,
        MAX_BACKOFF
    )

    jitter = random.uniform(
        0,
        min(
            5,
            base * 0.10
        )
    )

    return round(
        base + jitter,
        2
    )


def generate_scene_with_retry(
    api_key,
    model,
    prompt,
    part_number,
    scene_number,
):

    last_error = None

    for attempt in range(
        1,
        MAX_ATTEMPTS + 1
    ):

        log(
            f"Generating Part {part_number} "
            f"Scene {scene_number} "
            f"(attempt {attempt}/{MAX_ATTEMPTS}) "
            f"using model {model}..."
        )

        try:

            response = call_gemini(
                api_key,
                model,
                prompt
            )

            scene = parse_json_response(
                response
            )

            if not isinstance(
                scene,
                dict
            ):
                raise ValueError(
                    "Scene response must be a JSON object."
                )

            scene["part"] = part_number
            scene["scene"] = scene_number

            return scene

        except urllib.error.HTTPError as exc:

            last_error = exc

            if exc.code == 429:

                if attempt >= MAX_ATTEMPTS:
                    break

                retry_after = extract_retry_after(
                    exc
                )

                wait_seconds = (
                    max(
                        retry_after,
                        calculate_backoff(attempt)
                    )
                    if retry_after is not None
                    else calculate_backoff(attempt)
                )

                log(
                    "HTTP 429 rate limit."
                )

                log(
                    f"Waiting {wait_seconds:.1f}s..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            log(
                f"Gemini HTTP Error {exc.code}"
            )

        except Exception as exc:

            last_error = exc

            log(
                f"Scene generation failed: {exc}"
            )

        if attempt < MAX_ATTEMPTS:

            wait_seconds = calculate_backoff(
                attempt
            )

            log(
                f"Waiting {wait_seconds:.1f}s..."
            )

            time.sleep(
                wait_seconds
            )

    raise RuntimeError(
        f"Part {part_number} "
        f"Scene {scene_number} "
        f"failed after {MAX_ATTEMPTS} attempts: "
        f"{last_error}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    log("======================================")
    log("       GENERATING STORY SCENES")
    log("======================================")

    config = load_config()

    # --------------------------------------------------------
    # IMPORTANT: Parse numeric config safely.
    # --------------------------------------------------------

    parts = read_int_config(
        config,
        "PARTS",
        1
    )

    scenes_per_part = read_int_config(
        config,
        "SCENES",
        10
    )

    total_scenes = (
        parts * scenes_per_part
    )

    log()
    log("===== CONFIGURATION =====")
    log(f"PARTS            : {parts}")
    log(f"SCENES PER PART  : {scenes_per_part}")
    log(f"TOTAL SCENES     : {total_scenes}")
    log("=========================")

    api_key = get_api_key()
    model = get_model()

    log(
        f"Selected model: {model}"
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    CHECKPOINT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Story
    # --------------------------------------------------------

    story = None

    for path in [
        Path("output/story/ai_story.json"),
        Path("output/story/story.json"),
    ]:

        candidate = read_json(path)

        if candidate is not None:
            story = candidate
            break

    if story is None:

        raise FileNotFoundError(
            "No story file found."
        )

    # --------------------------------------------------------
    # Existing scenes
    # --------------------------------------------------------

    existing_data = read_json(
        SCENES_FILE
    )

    if isinstance(
        existing_data,
        dict
    ):

        existing_scenes = (
            existing_data.get(
                "scenes",
                []
            )
        )

    elif isinstance(
        existing_data,
        list
    ):

        existing_scenes = existing_data

    else:

        existing_scenes = []

    if not isinstance(
        existing_scenes,
        list
    ):

        existing_scenes = []

    # --------------------------------------------------------
    # Checkpoint
    # --------------------------------------------------------

    completed = load_checkpoint()

    # Add scenes that physically exist in scenes.json.
    for part_number in range(
        1,
        parts + 1
    ):

        for scene_number in range(
            1,
            scenes_per_part + 1
        ):

            key = scene_key(
                part_number,
                scene_number
            )

            if scene_already_saved(
                existing_scenes,
                part_number,
                scene_number
            ):

                completed.add(key)

    # IMPORTANT:
    # Remove invalid/out-of-range checkpoint entries.
    valid_completed = set()

    for item in completed:

        if ":" not in item:
            continue

        try:

            p, s = item.split(
                ":",
                1
            )

            p = int(p)
            s = int(s)

            if (
                1 <= p <= parts
                and 1 <= s <= scenes_per_part
            ):
                valid_completed.add(
                    scene_key(p, s)
                )

        except Exception:
            pass

    completed = valid_completed

    log(
        f"Existing completed scenes: "
        f"{len(completed)}/{total_scenes}"
    )

    save_checkpoint(
        total_scenes,
        completed
    )

    # --------------------------------------------------------
    # Generate missing scenes
    # --------------------------------------------------------

    for part_number in range(
        1,
        parts + 1
    ):

        for scene_number in range(
            1,
            scenes_per_part + 1
        ):

            key = scene_key(
                part_number,
                scene_number
            )

            if key in completed:

                log(
                    f"Part {part_number} "
                    f"Scene {scene_number} "
                    f"already completed. Skipping."
                )

                continue

            prompt = build_prompt(
                config,
                story,
                part_number,
                scene_number
            )

            try:

                scene = generate_scene_with_retry(
                    api_key,
                    model,
                    prompt,
                    part_number,
                    scene_number
                )

            except Exception as exc:

                save_checkpoint(
                    total_scenes,
                    completed,
                    failed_scene=key
                )

                log(
                    f"ERROR: {exc}"
                )

                raise

            # Replace existing scene.
            replaced = False

            for index, old_scene in enumerate(
                existing_scenes
            ):

                if not isinstance(
                    old_scene,
                    dict
                ):
                    continue

                try:

                    old_part = int(
                        old_scene.get(
                            "part",
                            -1
                        )
                    )

                    old_number = int(
                        old_scene.get(
                            "scene",
                            -1
                        )
                    )

                except Exception:

                    continue

                if (
                    old_part == part_number
                    and old_number == scene_number
                ):

                    existing_scenes[index] = scene
                    replaced = True
                    break

            if not replaced:

                existing_scenes.append(
                    scene
                )

            def sort_key(item):

                try:

                    return (
                        int(
                            item.get(
                                "part",
                                999999
                            )
                        ),
                        int(
                            item.get(
                                "scene",
                                999999
                            )
                        ),
                    )

                except Exception:

                    return (
                        999999,
                        999999
                    )

            existing_scenes.sort(
                key=sort_key
            )

            completed.add(key)

            write_json(
                SCENES_FILE,
                {
                    "status": "in_progress",
                    "model": model,
                    "total_scenes": total_scenes,
                    "completed_scenes": len(completed),
                    "scenes": existing_scenes,
                }
            )

            save_checkpoint(
                total_scenes,
                completed
            )

            log(
                f"Saved Part {part_number} "
                f"Scene {scene_number} "
                f"({len(completed)}/{total_scenes})"
            )

            if len(completed) < total_scenes:

                time.sleep(
                    REQUEST_DELAY
                )

    # --------------------------------------------------------
    # Final validation
    # --------------------------------------------------------

    expected_keys = {
        scene_key(p, s)
        for p in range(1, parts + 1)
        for s in range(1, scenes_per_part + 1)
    }

    actual_keys = set()

    for scene in existing_scenes:

        if not isinstance(scene, dict):
            continue

        try:

            p = int(scene["part"])
            s = int(scene["scene"])

            actual_keys.add(
                scene_key(p, s)
            )

        except Exception:
            pass

    missing = sorted(
        expected_keys - actual_keys
    )

    if missing:

        raise RuntimeError(
            f"Scene generation incomplete. "
            f"Missing {len(missing)} scenes: "
            f"{', '.join(missing[:20])}"
        )

    final_data = {
        "status": "completed",
        "model": model,
        "total_scenes": total_scenes,
        "completed_scenes": len(actual_keys),
        "scenes": existing_scenes,
    }

    write_json(
        SCENES_FILE,
        final_data
    )

    save_checkpoint(
        total_scenes,
        actual_keys,
        failed_scene=None
    )

    log()
    log("======================================")
    log("       SCENE GENERATION COMPLETE")
    log("======================================")
    log(
        f"Completed scenes: "
        f"{len(actual_keys)}/{total_scenes}"
    )


if __name__ == "__main__":
    main()
