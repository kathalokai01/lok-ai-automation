#!/usr/bin/env python3

import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_FILE = Path("Input/topic.txt")

OUTPUT_DIR = Path("output/scenes")
SCENES_FILE = OUTPUT_DIR / "scenes.json"
CHECKPOINT_FILE = Path("output/checkpoints/scenes_progress.json")

MAX_ATTEMPTS = int(os.getenv("SCENE_MAX_ATTEMPTS", "5"))

# 429 backoff:
# attempt 1 -> 15 sec
# attempt 2 -> 30 sec
# attempt 3 -> 60 sec
# attempt 4 -> 120 sec
# attempt 5 -> 240 sec
INITIAL_BACKOFF = int(os.getenv("SCENE_INITIAL_BACKOFF", "15"))
MAX_BACKOFF = int(os.getenv("SCENE_MAX_BACKOFF", "300"))

# Small delay between normal successful API calls.
REQUEST_DELAY = float(os.getenv("SCENE_REQUEST_DELAY", "2"))

# Gemini API timeout.
REQUEST_TIMEOUT = int(os.getenv("SCENE_REQUEST_TIMEOUT", "120"))


# ============================================================
# HELPERS
# ============================================================

def log(message=""):
    print(message, flush=True)


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
        value = value.strip()

        if (
            len(value) >= 2
            and value.startswith('"')
            and value.endswith('"')
        ):
            value = value[1:-1]

        if (
            len(value) >= 2
            and value.startswith("'")
            and value.endswith("'")
        ):
            value = value[1:-1]

        config[key] = value

    return config


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
        try:
            result.add(int(item))
        except Exception:
            pass

    return result


def scene_key(part_number, scene_number):
    return f"{part_number}:{scene_number}"


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

        part = scene.get("part")
        number = scene.get("scene")

        try:
            if (
                int(part) == part_number
                and int(number) == scene_number
            ):
                return True
        except Exception:
            continue

        # Also support alternative IDs.
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


def extract_retry_after(error):
    """
    Try to extract Retry-After from an HTTP 429 response.
    """

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
    """
    Exponential backoff with small jitter.

    attempt 1 -> 15 sec
    attempt 2 -> 30 sec
    attempt 3 -> 60 sec
    attempt 4 -> 120 sec
    attempt 5 -> 240 sec
    """

    base = INITIAL_BACKOFF * (
        2 ** max(0, attempt - 1)
    )

    base = min(
        base,
        MAX_BACKOFF
    )

    jitter = random.uniform(
        0,
        min(5, base * 0.10)
    )

    return round(
        base + jitter,
        2
    )


# ============================================================
# GEMINI API
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

    # Fallback to known model.
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
    """
    Single Gemini API request.

    Returns:
        generated text

    Raises:
        urllib.error.HTTPError
        urllib.error.URLError
        RuntimeError
    """

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

        # Preserve 429 so retry logic can handle it.
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
# JSON EXTRACTION
# ============================================================

def parse_json_response(text):
    text = text.strip()

    # Direct JSON.
    try:
        return json.loads(text)
    except Exception:
        pass

    # Remove markdown fences.
    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except Exception:
            pass

    # Find first JSON object.
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

    # Find first JSON array.
    start = text.find("[")
    end = text.rfind("]")

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

The scene must contain:

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

Important:
- Keep continuity with the story.
- Keep characters visually consistent.
- Do not invent unrelated characters.
- The narration must be in Hindi.
- The visual prompt should be detailed and production-ready.
- Return JSON only.
""".strip()


# ============================================================
# RETRY LOGIC
# ============================================================

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

            # Force canonical identifiers.
            scene["part"] = part_number
            scene["scene"] = scene_number

            log(
                f"Part {part_number} "
                f"Scene {scene_number} "
                f"completed and saved."
            )

            return scene

        except urllib.error.HTTPError as exc:

            last_error = exc

            if exc.code == 429:

                if attempt >= MAX_ATTEMPTS:
                    break

                retry_after = extract_retry_after(
                    exc
                )

                if retry_after is not None:
                    wait_seconds = max(
                        retry_after,
                        calculate_backoff(attempt)
                    )
                else:
                    wait_seconds = calculate_backoff(
                        attempt
                    )

                log(
                    "Scene generation failed: "
                    "HTTP Error 429: Too Many Requests"
                )

                log(
                    f"Rate limit detected. "
                    f"Waiting {wait_seconds:.1f}s "
                    f"before retry..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            log(
                f"Scene generation failed: "
                f"HTTP Error {exc.code}"
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
                f"Waiting {wait_seconds:.1f}s "
                f"before retry..."
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

    api_key = get_api_key()

    model = get_model()

    log()
    log("===== GEMINI MODEL =====")
    log(f"Selected model: {model}")
    log("========================")

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    CHECKPOINT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Load story
    # --------------------------------------------------------

    story_candidates = [
        Path("output/story/ai_story.json"),
        Path("output/story/story.json"),
    ]

    story = None

    for path in story_candidates:

        candidate = read_json(path)

        if candidate is not None:
            story = candidate
            break

    if story is None:
        raise FileNotFoundError(
            "No story file found. "
            "Expected output/story/ai_story.json "
            "or output/story/story.json"
        )

    # --------------------------------------------------------
    # Determine parts/scenes
    # --------------------------------------------------------

    try:
        parts = int(
            config.get("PARTS", "1")
        )
    except Exception:
        parts = 1

    try:
        scenes_per_part = int(
            config.get("SCENES", "10")
        )
    except Exception:
        scenes_per_part = 10

    total_scenes = (
        parts * scenes_per_part
    )

    log()
    log(
        f"Total parts: {parts}"
    )
    log(
        f"Scenes per part: {scenes_per_part}"
    )
    log(
        f"Total scenes: {total_scenes}"
    )

    # --------------------------------------------------------
    # Load existing scenes
    # --------------------------------------------------------

    existing_data = read_json(
        SCENES_FILE
    )

    if isinstance(
        existing_data,
        dict
    ):
        existing_scenes = existing_data.get(
            "scenes",
            []
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
    # Load checkpoint
    # --------------------------------------------------------

    checkpoint_completed = (
        load_checkpoint()
    )

    # Build completed set from actual scene file too.
    completed = set(
        checkpoint_completed
    )

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
                completed.add(
                    key
                )

    log()
    log(
        f"Checkpoint completed scenes: "
        f"{len(checkpoint_completed)}"
    )

    log(
        f"Existing completed scenes: "
        f"{len(completed)}"
    )

    save_checkpoint(
        total_scenes,
        completed,
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

            # ------------------------------------------------
            # RESUME
            # ------------------------------------------------

            if key in completed:

                log(
                    f"Part {part_number} "
                    f"Scene {scene_number} "
                    f"already completed. "
                    f"Skipping."
                )

                continue

            prompt = build_prompt(
                config,
                story,
                part_number,
                scene_number
            )

            # ------------------------------------------------
            # GENERATE WITH RETRY
            # ------------------------------------------------

            try:

                scene = generate_scene_with_retry(
                    api_key,
                    model,
                    prompt,
                    part_number,
                    scene_number
                )

            except Exception as exc:

                # Save checkpoint BEFORE failing.
                save_checkpoint(
                    total_scenes,
                    completed,
                    failed_scene=key
                )

                log()
                log(
                    f"ERROR: {exc}"
                )

                raise

            # ------------------------------------------------
            # Replace existing duplicate if necessary
            # ------------------------------------------------

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

                    old_scene_number = int(
                        old_scene.get(
                            "scene",
                            -1
                        )
                    )

                except Exception:
                    continue

                if (
                    old_part == part_number
                    and old_scene_number
                    == scene_number
                ):

                    existing_scenes[index] = scene
                    replaced = True
                    break

            if not replaced:
                existing_scenes.append(
                    scene
                )

            # ------------------------------------------------
            # Stable ordering
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Save scene file immediately
            # ------------------------------------------------

            output_data = {
                "status": "in_progress",
                "model": model,
                "total_scenes": total_scenes,
                "completed_scenes": len(
                    completed
                ),
                "scenes": existing_scenes,
            }

            write_json(
                SCENES_FILE,
                output_data
            )

            # ------------------------------------------------
            # Update checkpoint immediately
            # ------------------------------------------------

            completed.add(
                key
            )

            save_checkpoint(
                total_scenes,
                completed,
            )

            log(
                f"Checkpoint saved after "
                f"Part {part_number} "
                f"Scene {scene_number}."
            )

            # ------------------------------------------------
            # Small pacing delay
            # ------------------------------------------------

            if len(completed) < total_scenes:
                time.sleep(
                    REQUEST_DELAY
                )

    # --------------------------------------------------------
    # FINALIZE
    # --------------------------------------------------------

    final_data = {
        "status": "completed",
        "model": model,
        "total_scenes": total_scenes,
        "completed_scenes": len(
            completed
        ),
        "scenes": existing_scenes,
    }

    write_json(
        SCENES_FILE,
        final_data
    )

    save_checkpoint(
        total_scenes,
        completed,
        failed_scene=None
    )

    log()
    log("======================================")
    log("       SCENE GENERATION COMPLETE")
    log("======================================")
    log(
        f"Completed scenes: "
        f"{len(completed)}/{total_scenes}"
    )
    log(
        f"Scenes file: {SCENES_FILE}"
    )
    log(
        f"Checkpoint: {CHECKPOINT_FILE}"
    )


if __name__ == "__main__":
    main()
