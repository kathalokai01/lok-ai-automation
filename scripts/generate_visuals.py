#!/usr/bin/env python3

import os
import sys
import json
import time
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from input_config import (
    load_input_config,
    cfg_bool,
    cfg_text,
    get_parts,
    get_scenes,
    get_max_retries,
    normalize_format,
    resolve_topic,
)

# ============================================================
# PATHS
# ============================================================

ROOT = Path(".")
CONFIG_FILE = Path("Input/topic.txt")

SCENES_FILE = Path("output/scenes/scenes.json")
CHARACTER_BIBLE_FILE = Path("output/character_bible/character_bible.json")

VISUAL_ROOT = Path("output/visuals")
MANIFEST_FILE = VISUAL_ROOT / "visual_jobs.json"

API_URL = (
    "https://api.cloudflare.com/client/v4/accounts/"
    "{account_id}/ai/run/{model}"
)

MODEL = "alibaba/wan-2.6-image"


# ============================================================
# CONFIG
# ============================================================

CONFIG = load_input_config()

FORMAT = normalize_format(CONFIG)

TOPIC = resolve_topic(CONFIG)

PARTS = get_parts(CONFIG)
SCENES_PER_PART = get_scenes(CONFIG)

MAX_RETRIES = max(1, get_max_retries(CONFIG))

RESUME_ENABLED = cfg_bool(CONFIG, "RESUME_ENABLED", True)
SKIP_COMPLETED_SCENES = cfg_bool(
    CONFIG,
    "SKIP_COMPLETED_SCENES",
    True,
)

SAVE_CHECKPOINT_AFTER_EACH_SCENE = cfg_bool(
    CONFIG,
    "SAVE_CHECKPOINT_AFTER_EACH_SCENE",
    True,
)

VISUAL_STYLE = cfg_text(
    CONFIG,
    "VISUAL_STYLE",
    "cinematic_realistic",
)

REALISM = cfg_text(
    CONFIG,
    "REALISM",
    "high",
)

CHARACTER_BIBLE_ENABLED = cfg_bool(
    CONFIG,
    "CHARACTER_BIBLE",
    True,
)

CHARACTER_CONSISTENCY = cfg_bool(
    CONFIG,
    "CHARACTER_CONSISTENCY",
    True,
)

WORLD_CONSISTENCY = cfg_bool(
    CONFIG,
    "WORLD_CONSISTENCY",
    True,
)

SCENE_CONTINUITY = cfg_bool(
    CONFIG,
    "SCENE_CONTINUITY",
    True,
)

CINEMATIC_CAMERA = cfg_bool(
    CONFIG,
    "CINEMATIC_CAMERA",
    True,
)

CAMERA_STYLE = cfg_text(
    CONFIG,
    "CAMERA_STYLE",
    "cinematic",
)

LIGHTING = cfg_text(
    CONFIG,
    "LIGHTING",
    "cinematic",
)

MOOD = cfg_text(
    CONFIG,
    "MOOD",
    "dramatic",
)

QUALITY = cfg_text(
    CONFIG,
    "QUALITY",
    "high",
)

NEGATIVE_PROMPT_ENABLED = cfg_bool(
    CONFIG,
    "NEGATIVE_PROMPT",
    True,
)

AVOID_CARTOON_LOOK = cfg_bool(
    CONFIG,
    "AVOID_CARTOON_LOOK",
    True,
)

AVOID_NEON = cfg_bool(
    CONFIG,
    "AVOID_NEON",
    True,
)

AVOID_GLITCH_EFFECTS = cfg_bool(
    CONFIG,
    "AVOID_GLITCH_EFFECTS",
    True,
)

NATURAL_MOTION = cfg_bool(
    CONFIG,
    "NATURAL_MOTION",
    True,
)

REALISTIC_LIGHTING = cfg_bool(
    CONFIG,
    "REALISTIC_LIGHTING",
    True,
)

TRANSITIONS = cfg_text(
    CONFIG,
    "TRANSITIONS",
    "cinematic",
)

CAPTIONS = cfg_text(
    CONFIG,
    "CAPTIONS",
    "hindi",
)

MUSIC = cfg_bool(
    CONFIG,
    "MUSIC",
    True,
)

MUSIC_STYLE = cfg_text(
    CONFIG,
    "MUSIC_STYLE",
    "cinematic",
)

SFX = cfg_bool(
    CONFIG,
    "SFX",
    True,
)

AMBIENT_SOUND = cfg_bool(
    CONFIG,
    "AMBIENT_SOUND",
    True,
)


# ============================================================
# FORMAT
# ============================================================

if FORMAT == "short":
    IMAGE_WIDTH = 768
    IMAGE_HEIGHT = 1344
else:
    IMAGE_WIDTH = 1344
    IMAGE_HEIGHT = 768


# ============================================================
# HELPERS
# ============================================================

def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def safe_text(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def scene_key(part, scene):
    return f"part_{int(part):02d}_scene_{int(scene):02d}"


def visual_path(part, scene):
    return (
        VISUAL_ROOT
        / f"part_{int(part):02d}"
        / f"scene_{int(scene):02d}.png"
    )


def is_valid_image(path):
    try:
        return (
            path.exists()
            and path.is_file()
            and path.stat().st_size > 1000
        )
    except Exception:
        return False


def load_json(path):
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    tmp.replace(path)


def normalize_scene_list(data):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in (
        "scenes",
        "items",
        "scene_list",
        "data",
    ):
        value = data.get(key)

        if isinstance(value, list):
            return value

    return []


# ============================================================
# VISUAL CONFIG SIGNATURE
# ============================================================

VISUAL_CONFIG = {
    "format": FORMAT,
    "model": MODEL,
    "visual_style": VISUAL_STYLE,
    "realism": REALISM,
    "character_bible": CHARACTER_BIBLE_ENABLED,
    "character_consistency": CHARACTER_CONSISTENCY,
    "world_consistency": WORLD_CONSISTENCY,
    "scene_continuity": SCENE_CONTINUITY,
    "cinematic_camera": CINEMATIC_CAMERA,
    "camera_style": CAMERA_STYLE,
    "lighting": LIGHTING,
    "mood": MOOD,
    "quality": QUALITY,
    "negative_prompt": NEGATIVE_PROMPT_ENABLED,
    "avoid_cartoon": AVOID_CARTOON_LOOK,
    "avoid_neon": AVOID_NEON,
    "avoid_glitch": AVOID_GLITCH_EFFECTS,
    "natural_motion": NATURAL_MOTION,
    "realistic_lighting": REALISTIC_LIGHTING,
    "transitions": TRANSITIONS,
}

VISUAL_CONFIG_SIGNATURE = hashlib.sha256(
    json.dumps(
        VISUAL_CONFIG,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


# ============================================================
# CHARACTER BIBLE
# ============================================================

def load_character_bible():
    if not CHARACTER_BIBLE_ENABLED:
        return {}

    if not CHARACTER_BIBLE_FILE.exists():
        die(
            "CHARACTER_BIBLE=true but "
            "output/character_bible/character_bible.json "
            "was not found."
        )

    data = load_json(CHARACTER_BIBLE_FILE)

    if not data:
        die("Character bible exists but could not be read.")

    return data


CHARACTER_BIBLE = load_character_bible()


# ============================================================
# CHARACTER LOOKUP
# ============================================================

def get_character_map():
    result = {}

    if not isinstance(CHARACTER_BIBLE, dict):
        return result

    characters = CHARACTER_BIBLE.get("characters", [])

    if not isinstance(characters, list):
        return result

    for character in characters:
        if not isinstance(character, dict):
            continue

        cid = safe_text(
            character.get("id")
            or character.get("character_id")
            or character.get("name")
        )

        if cid:
            result[cid] = character

    return result


CHARACTER_MAP = get_character_map()


def character_description(character_id):
    character = CHARACTER_MAP.get(character_id)

    if not character:
        return ""

    parts = []

    for key in (
        "name",
        "identity",
        "age",
        "gender",
        "appearance",
        "face",
        "hair",
        "skin",
        "body",
        "clothing",
        "accessories",
        "distinctive_features",
        "consistency_rules",
    ):
        value = character.get(key)

        if isinstance(value, list):
            value = ", ".join(
                safe_text(x)
                for x in value
                if safe_text(x)
            )

        value = safe_text(value)

        if value:
            parts.append(f"{key}: {value}")

    return "; ".join(parts)


# ============================================================
# SCENE DATA
# ============================================================

if not SCENES_FILE.exists():
    die(
        "Missing scenes file: "
        f"{SCENES_FILE}"
    )

SCENES_DATA = load_json(SCENES_FILE)
SCENES = normalize_scene_list(SCENES_DATA)

EXPECTED_TOTAL = PARTS * SCENES_PER_PART

if len(SCENES) != EXPECTED_TOTAL:
    die(
        f"Scene count mismatch. "
        f"Expected {EXPECTED_TOTAL}, "
        f"found {len(SCENES)}."
    )


# ============================================================
# NEGATIVE PROMPT
# ============================================================

def build_negative_prompt(scene):
    if not NEGATIVE_PROMPT_ENABLED:
        return ""

    negatives = [
        "low quality",
        "blurry",
        "deformed",
        "bad anatomy",
        "extra fingers",
        "extra limbs",
        "duplicate person",
        "duplicate objects",
        "distorted face",
        "unnatural face",
        "text",
        "subtitles",
        "captions",
        "watermark",
        "logo",
    ]

    if AVOID_CARTOON_LOOK:
        negatives.extend([
            "cartoon",
            "comic",
            "anime",
            "manga",
            "illustration",
            "storybook",
            "2D art",
            "3D cartoon",
            "animated character",
        ])

    if AVOID_NEON:
        negatives.extend([
            "neon colors",
            "oversaturated neon lighting",
        ])

    if AVOID_GLITCH_EFFECTS:
        negatives.extend([
            "glitch",
            "digital artifacts",
            "visual distortion",
            "cyber glitch effects",
        ])

    negatives.extend([
        "plastic skin",
        "CGI look",
        "game render",
        "synthetic human",
        "slideshow",
        "static poster",
    ])

    return ", ".join(negatives)


# ============================================================
# VISUAL PROMPT
# ============================================================

def build_visual_prompt(scene):
    visual_prompt = safe_text(
        scene.get("visual_prompt")
        or scene.get("visual")
        or scene.get("image_prompt")
    )

    narration = safe_text(
        scene.get("narration")
        or scene.get("voiceover")
    )

    world_context = safe_text(
        scene.get("world_context")
        or scene.get("world")
        or scene.get("setting")
    )

    mood = safe_text(
        scene.get("mood")
        or MOOD
    )

    camera = safe_text(
        scene.get("camera")
        or scene.get("camera_direction")
    )

    lighting = safe_text(
        scene.get("lighting")
        or LIGHTING
    )

    character_ids = scene.get("character_ids", [])

    if isinstance(character_ids, str):
        character_ids = [character_ids]

    if not isinstance(character_ids, list):
        character_ids = []

    characters = []

    for cid in character_ids:
        cid = safe_text(cid)

        if not cid:
            continue

        description = character_description(cid)

        if description:
            characters.append(
                f"Character {cid}: {description}"
            )

    sections = []

    sections.append(
        "Create a single cinematic live-action photograph "
        "for an AI image-to-video pipeline."
    )

    if TOPIC:
        sections.append(
            f"Story topic: {TOPIC}"
        )

    if visual_prompt:
        sections.append(
            f"Scene visual description: {visual_prompt}"
        )

    if narration:
        sections.append(
            f"Scene meaning/narration context: {narration}"
        )

    if world_context and WORLD_CONSISTENCY:
        sections.append(
            "Maintain the established world and location: "
            + world_context
        )

    if characters and CHARACTER_CONSISTENCY:
        sections.append(
            "Maintain exact recurring character identity, "
            "face, body, clothing and appearance consistency:\n"
            + "\n".join(characters)
        )

    if SCENE_CONTINUITY:
        sections.append(
            "Maintain continuity with previous and following scenes. "
            "Preserve location, time, wardrobe, character appearance, "
            "objects and environmental conditions."
        )

    if VISUAL_STYLE:
        sections.append(
            f"Visual style: {VISUAL_STYLE}."
        )

    if REALISM:
        sections.append(
            f"Realism level: {REALISM}."
        )

    if CINEMATIC_CAMERA:
        sections.append(
            f"Cinematic camera direction: {CAMERA_STYLE}. "
            + (camera if camera else "")
        )

    if lighting:
        sections.append(
            f"Lighting: {lighting}."
        )

    if REALISTIC_LIGHTING:
        sections.append(
            "Use physically believable natural lighting, "
            "realistic shadows, realistic skin tones and realistic "
            "light interaction with the environment."
        )

    if mood:
        sections.append(
            f"Emotional atmosphere: {mood}."
        )

    if QUALITY:
        sections.append(
            f"Image quality target: {QUALITY}."
        )

    if NATURAL_MOTION:
        sections.append(
            "Pose, body language, facial expression and object placement "
            "must look physically natural and suitable for realistic "
            "image-to-video animation."
        )

    if FORMAT == "short":
        sections.append(
            "Vertical composition for short-form video. "
            "Keep the important subject clearly visible and centered "
            "within a vertical 9:16 safe area."
        )
    else:
        sections.append(
            "Landscape cinematic composition for long-form video. "
            "Use a 16:9 cinematic frame."
        )

    sections.extend([
        "Real human beings and real-world environments.",
        "Photorealistic skin, natural facial details, "
        "physically believable materials and textures.",
        "Natural depth of field and realistic perspective.",
        "No poster-like composition.",
        "No slideshow appearance.",
        "The frame must look like a real film still captured "
        "with a professional cinema camera.",
    ])

    return "\n".join(
        section
        for section in sections
        if safe_text(section)
    )


# ============================================================
# CLOUDFLARE
# ============================================================

ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()

if not ACCOUNT_ID:
    die("CLOUDFLARE_ACCOUNT_ID is not set.")

if not API_TOKEN:
    die("CLOUDFLARE_API_TOKEN is not set.")


def cloudflare_generate(prompt, negative_prompt):
    url = API_URL.format(
        account_id=ACCOUNT_ID,
        model=MODEL,
    )

    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": IMAGE_WIDTH,
        "height": IMAGE_HEIGHT,
    }

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(request, timeout=300) as response:
        return response.read()


def extract_image_bytes(raw):
    if not raw:
        return None

    try:
        data = json.loads(raw.decode("utf-8"))

        if isinstance(data, dict):
            result = data.get("result")

            if isinstance(result, dict):
                for key in (
                    "image",
                    "image_base64",
                    "base64",
                ):
                    value = result.get(key)

                    if isinstance(value, str):
                        import base64

                        return base64.b64decode(value)

            for key in (
                "image",
                "image_base64",
                "base64",
            ):
                value = data.get(key)

                if isinstance(value, str):
                    import base64

                    return base64.b64decode(value)

    except Exception:
        pass

    # Some Cloudflare image responses can be returned directly.
    if raw.startswith(b"\x89PNG"):
        return raw

    if raw.startswith(b"\xff\xd8"):
        return raw

    return None


# ============================================================
# MANIFEST
# ============================================================

def load_manifest():
    if not RESUME_ENABLED:
        return {
            "version": 3,
            "model": MODEL,
            "visual_config": VISUAL_CONFIG,
            "visual_config_signature": VISUAL_CONFIG_SIGNATURE,
            "jobs": {},
        }

    data = load_json(MANIFEST_FILE)

    if not isinstance(data, dict):
        data = {}

    jobs = data.get("jobs")

    if not isinstance(jobs, dict):
        jobs = {}

    return {
        "version": 3,
        "model": MODEL,
        "visual_config": VISUAL_CONFIG,
        "visual_config_signature": VISUAL_CONFIG_SIGNATURE,
        "jobs": jobs,
    }


MANIFEST = load_manifest()
OLD_JOBS = dict(MANIFEST.get("jobs", {}))


def save_manifest():
    MANIFEST["version"] = 3
    MANIFEST["model"] = MODEL
    MANIFEST["visual_config"] = VISUAL_CONFIG
    MANIFEST["visual_config_signature"] = VISUAL_CONFIG_SIGNATURE

    save_json(
        MANIFEST_FILE,
        MANIFEST,
    )


# ============================================================
# JOB CREATION
# ============================================================

def build_job(scene):
    part = int(
        scene.get("part")
        or scene.get("part_number")
        or 0
    )

    scene_number = int(
        scene.get("scene")
        or scene.get("scene_number")
        or 0
    )

    if part < 1 or scene_number < 1:
        die(
            f"Invalid part/scene in scene data: {scene}"
        )

    key = scene_key(
        part,
        scene_number,
    )

    output = visual_path(
        part,
        scene_number,
    )

    old_job = OLD_JOBS.get(key, {})

    old_model = safe_text(
        old_job.get("model")
    )

    old_signature = safe_text(
        old_job.get("visual_config_signature")
    )

    reusable = (
        SKIP_COMPLETED_SCENES
        and is_valid_image(output)
        and old_model == MODEL
        and old_signature == VISUAL_CONFIG_SIGNATURE
    )

    if not reusable and output.exists():
        try:
            output.unlink()
        except Exception:
            pass

    job = {
        "key": key,
        "part": part,
        "scene": scene_number,
        "model": MODEL,
        "status": "completed" if reusable else "pending",
        "output": str(output),
        "visual_config_signature": VISUAL_CONFIG_SIGNATURE,
        "prompt": build_visual_prompt(scene),
        "negative_prompt": build_negative_prompt(scene),
        "reused": reusable,
        "attempts": 0,
    }

    return job


# ============================================================
# BUILD ALL JOBS
# ============================================================

JOBS = {}

for scene in SCENES:
    job = build_job(scene)

    key = job["key"]

    if key in JOBS:
        die(f"Duplicate scene detected: {key}")

    JOBS[key] = job


MANIFEST["jobs"] = JOBS
save_manifest()


# ============================================================
# GENERATION
# ============================================================

pending_jobs = [
    job
    for job in JOBS.values()
    if job["status"] != "completed"
]

print("==============================================")
print("        GENERATING VISUAL ASSETS")
print("==============================================")
print(f"Format                 : {FORMAT}")
print(f"Topic                  : {TOPIC}")
print(f"Parts                  : {PARTS}")
print(f"Scenes per part       : {SCENES_PER_PART}")
print(f"Expected visuals      : {EXPECTED_TOTAL}")
print(f"Existing valid        : {EXPECTED_TOTAL - len(pending_jobs)}")
print(f"Pending visuals       : {len(pending_jobs)}")
print(f"Model                 : {MODEL}")
print(f"Visual style          : {VISUAL_STYLE}")
print(f"Realism               : {REALISM}")
print(f"Character consistency : {CHARACTER_CONSISTENCY}")
print(f"World consistency     : {WORLD_CONSISTENCY}")
print(f"Scene continuity      : {SCENE_CONTINUITY}")
print(f"Camera                : {CAMERA_STYLE}")
print(f"Lighting              : {LIGHTING}")
print(f"Mood                  : {MOOD}")
print(f"Quality               : {QUALITY}")
print("==============================================")


for job in pending_jobs:
    key = job["key"]

    print()
    print("----------------------------------------------")
    print(f"Generating {key}")
    print("----------------------------------------------")

    success = False
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        job["attempts"] = attempt

        try:
            print(
                f"Attempt {attempt}/{MAX_RETRIES}"
            )

            raw = cloudflare_generate(
                job["prompt"],
                job["negative_prompt"],
            )

            image_bytes = extract_image_bytes(raw)

            if not image_bytes:
                raise RuntimeError(
                    "Cloudflare response did not contain "
                    "a usable image."
                )

            output = Path(job["output"])

            output.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with output.open("wb") as f:
                f.write(image_bytes)

            if not is_valid_image(output):
                raise RuntimeError(
                    "Generated image is missing or too small."
                )

            job["status"] = "completed"
            job["reused"] = False

            save_manifest()

            print(
                f"SUCCESS: {key}"
            )

            success = True
            break

        except HTTPError as exc:
            last_error = (
                f"HTTP {exc.code}: "
                f"{exc.reason}"
            )

            print(
                f"WARNING: {last_error}"
            )

            if exc.code not in (
                408,
                425,
                429,
                500,
                502,
                503,
                504,
            ):
                break

            if attempt < MAX_RETRIES:
                delay = min(
                    60,
                    15 * (2 ** (attempt - 1)),
                )

                print(
                    f"Retrying in {delay}s..."
                )

                time.sleep(delay)

        except (URLError, TimeoutError) as exc:
            last_error = str(exc)

            print(
                f"WARNING: Network error: {last_error}"
            )

            if attempt < MAX_RETRIES:
                delay = min(
                    60,
                    15 * (2 ** (attempt - 1)),
                )

                print(
                    f"Retrying in {delay}s..."
                )

                time.sleep(delay)

        except Exception as exc:
            last_error = str(exc)

            print(
                f"WARNING: {last_error}"
            )

            if attempt < MAX_RETRIES:
                delay = min(
                    60,
                    15 * (2 ** (attempt - 1)),
                )

                print(
                    f"Retrying in {delay}s..."
                )

                time.sleep(delay)

    if not success:
        job["status"] = "failed"
        job["error"] = last_error

        save_manifest()

        die(
            f"{key} failed after "
            f"{MAX_RETRIES} attempts: "
            f"{last_error}"
        )

    if SAVE_CHECKPOINT_AFTER_EACH_SCENE:
        save_manifest()


# ============================================================
# FINAL VALIDATION
# ============================================================

print()
print("==============================================")
print("        FINAL VISUAL VALIDATION")
print("==============================================")

missing = []
invalid = []

for part in range(1, PARTS + 1):
    for scene in range(1, SCENES_PER_PART + 1):
        path = visual_path(part, scene)

        if not path.exists():
            missing.append(
                scene_key(part, scene)
            )
            continue

        if not is_valid_image(path):
            invalid.append(
                scene_key(part, scene)
            )


if missing:
    print(
        "Missing visuals:"
    )

    for item in missing:
        print(f"  - {item}")

    die(
        f"Missing visual count: {len(missing)}"
    )


if invalid:
    print(
        "Invalid visuals:"
    )

    for item in invalid:
        print(f"  - {item}")

    die(
        f"Invalid visual count: {len(invalid)}"
    )


completed_count = sum(
    1
    for job in JOBS.values()
    if job.get("status") == "completed"
    and is_valid_image(
        Path(job["output"])
    )
)

if completed_count != EXPECTED_TOTAL:
    die(
        f"Final visual count mismatch. "
        f"Expected {EXPECTED_TOTAL}, "
        f"found {completed_count}."
    )


MANIFEST["status"] = "completed"
MANIFEST["expected_total"] = EXPECTED_TOTAL
MANIFEST["completed_total"] = completed_count
MANIFEST["format"] = FORMAT
MANIFEST["topic"] = TOPIC
MANIFEST["visual_config"] = VISUAL_CONFIG
MANIFEST["visual_config_signature"] = (
    VISUAL_CONFIG_SIGNATURE
)

save_manifest()

print(
    f"Visual assets: "
    f"{completed_count}/{EXPECTED_TOTAL}"
)

print(
    "Visual generation completed successfully."
)

print("==============================================")
