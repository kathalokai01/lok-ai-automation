#!/usr/bin/env python3

import base64
import json
import os
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

ACCOUNT_ID = os.environ.get(
    "CLOUDFLARE_ACCOUNT_ID"
)

API_TOKEN = os.environ.get(
    "CLOUDFLARE_API_TOKEN"
)

MODEL = "alibaba/wan-2.6-image"

SCENES_FILE = Path(
    "output/scenes/scenes.json"
)

VISUAL_JOBS_FILE = Path(
    "output/visuals/visual_jobs.json"
)

TOPIC_FILE = Path(
    "Input/topic.txt"
)

MAX_RETRIES = 6
INITIAL_BACKOFF = 20
MAX_BACKOFF = 300
REQUEST_TIMEOUT = 300

BASE_URL = (
    "https://api.cloudflare.com/client/v4/accounts"
)


# ============================================================
# BASIC HELPERS
# ============================================================

def now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def clean_value(value):

    value = value.strip()

    if "#" in value:
        value = value.split(
            "#",
            1
        )[0].strip()

    return (
        value
        .strip()
        .strip('"')
        .strip("'")
    )


def load_config():

    values = {}

    if not TOPIC_FILE.exists():
        return values

    for raw in TOPIC_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split(
            "=",
            1
        )

        values[
            key.strip().upper()
        ] = clean_value(value)

    return values


CONFIG = load_config()

FORMAT = CONFIG.get(
    "FORMAT",
    "full"
).lower()

TOPIC = CONFIG.get(
    "TOPIC",
    ""
)


# ============================================================
# VALIDATION
# ============================================================

if not ACCOUNT_ID:
    raise RuntimeError(
        "CLOUDFLARE_ACCOUNT_ID is not set."
    )

if not API_TOKEN:
    raise RuntimeError(
        "CLOUDFLARE_API_TOKEN is not set."
    )

if FORMAT not in {
    "short",
    "full"
}:
    raise RuntimeError(
        f"Invalid FORMAT: {FORMAT}"
    )


# ============================================================
# FORMAT
# ============================================================

def image_size():

    if FORMAT == "short":
        return "768x1344"

    return "1344x768"


# ============================================================
# JSON
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def save_json(path, data):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp = Path(
        str(path) + ".tmp"
    )

    with temp.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

        f.write("\n")

    os.replace(
        temp,
        path
    )


# ============================================================
# VISUAL PATH
# ============================================================

def visual_path(part, scene):

    return (
        Path("output/visuals")
        / f"part_{int(part):02d}"
        / f"scene_{int(scene):02d}.png"
    )


def is_valid_image(path):

    path = Path(path)

    if not path.exists():
        return False

    if path.stat().st_size < 1000:
        return False

    try:

        with path.open(
            "rb"
        ) as f:

            header = f.read(12)

        return (
            header.startswith(
                b"\x89PNG"
            )
            or header.startswith(
                b"\xff\xd8"
            )
            or header.startswith(
                b"RIFF"
            )
        )

    except Exception:

        return False


# ============================================================
# JOB CREATION
# ============================================================

def create_job(scene, old_job=None):

    part = int(
        scene["part"]
    )

    scene_number = int(
        scene["scene"]
    )

    visual_prompt = str(
        scene.get(
            "visual_prompt",
            ""
        )
    ).strip()

    if not visual_prompt:

        raise RuntimeError(
            f"Empty visual prompt for "
            f"Part {part} Scene {scene_number}"
        )

    job = {
        "part": part,
        "scene": scene_number,
        "status": "pending",
        "asset_type": "photorealistic_visual",
        "visual_prompt": visual_prompt,
        "negative_prompt": str(
            scene.get(
                "negative_prompt",
                ""
            )
        ).strip(),
        "camera_prompt": str(
            scene.get(
                "camera_prompt",
                ""
            )
        ).strip(),
        "lighting_prompt": str(
            scene.get(
                "lighting_prompt",
                ""
            )
        ).strip(),
        "duration": scene.get(
            "duration",
            "auto"
        ),
        "asset_path": None,
        "provider": "cloudflare",
        "model": MODEL,
        "error": None,
    }

    if isinstance(
        old_job,
        dict
    ):

        if old_job.get(
            "model"
        ) == MODEL:

            for key in (
                "error",
                "completed_at"
            ):

                if key in old_job:
                    job[key] = old_job[key]

    return job


# ============================================================
# BUILD JOBS
# ============================================================

def build_jobs():

    if not SCENES_FILE.exists():

        raise RuntimeError(
            "output/scenes/scenes.json not found."
        )

    scenes_data = load_json(
        SCENES_FILE
    )

    if scenes_data.get(
        "status"
    ) != "completed":

        raise RuntimeError(
            "Scene generation is not completed."
        )

    scenes = scenes_data.get(
        "scenes",
        []
    )

    if not scenes:

        raise RuntimeError(
            "No scenes found."
        )

    old_jobs = {}

    if VISUAL_JOBS_FILE.exists():

        try:

            old_data = load_json(
                VISUAL_JOBS_FILE
            )

            for item in old_data.get(
                "jobs",
                []
            ):

                key = (
                    int(item["part"]),
                    int(item["scene"])
                )

                old_jobs[key] = item

        except Exception as exc:

            print(
                "WARNING: Could not read old "
                f"visual manifest: {exc}"
            )

    jobs = []

    for scene in scenes:

        part = int(
            scene["part"]
        )

        scene_number = int(
            scene["scene"]
        )

        key = (
            part,
            scene_number
        )

        path = visual_path(
            part,
            scene_number
        )

        job = create_job(
            scene,
            old_jobs.get(key)
        )

        # Only trust the actual image file.
        if is_valid_image(path):

            job["status"] = "completed"
            job["asset_path"] = str(
                path
            )

        else:

            job["status"] = "pending"
            job["asset_path"] = None

        jobs.append(
            job
        )

    jobs.sort(
        key=lambda x: (
            int(x["part"]),
            int(x["scene"])
        )
    )

    return jobs


# ============================================================
# PHOTOREALISTIC PROMPT
# ============================================================

def build_prompt(job):

    source = job[
        "visual_prompt"
    ]

    camera = job.get(
        "camera_prompt",
        ""
    ).strip()

    lighting = job.get(
        "lighting_prompt",
        ""
    ).strip()

    if FORMAT == "short":

        format_direction = """
Create a strong vertical cinematic frame for a short-form video.

The visual must immediately communicate the situation,
create curiosity, and support suspense.

The frame should contain clear visual storytelling
and should never look like a generic stock image.
"""

    else:

        format_direction = """
Create a cinematic widescreen frame for a long-form story.

The composition should establish the location,
characters, emotion and action clearly.
"""

    prompt = f"""
{format_direction}

STORY TOPIC:
{TOPIC}

SCENE:
{source}

CAMERA DIRECTION:
{camera}

LIGHTING DIRECTION:
{lighting}

Create an extremely photorealistic live-action film frame.

REAL PEOPLE ONLY.

The characters must look like real human actors photographed
with a professional cinema camera.

Use realistic Indian people when the scene calls for Indian
characters.

Natural human skin texture.
Natural pores.
Natural hair.
Natural eyes.
Natural facial anatomy.
Natural hands.
Natural body proportions.
Natural clothing fabric.

REAL-WORLD ENVIRONMENT.

Real buildings.
Real streets.
Real homes.
Real furniture.
Real vehicles.
Real physical objects.

Use physically believable lighting,
natural shadows,
realistic reflections,
realistic depth of field,
realistic lens behavior,
and cinematic exposure.

The image should look like a frame extracted from
a high-budget live-action film.

Preserve character age, gender, face structure,
hair, clothing and identity across scenes.

Do not turn the scene into an illustration.

Do not stylize the characters.

Do not make it look like concept art.

Do not make it look like a poster.

Do not make it look like a painting.

No artificial fantasy appearance.

No exaggerated expressions.

No plastic skin.

No CGI appearance.

No 3D-render appearance.

No comic-book appearance.

No anime appearance.

No cartoon appearance.

No slideshow appearance.

Photographic realism is mandatory.

Composition must leave enough visual information
for a later image-to-video model to animate the scene.

Use natural poses and physically possible positions.

The image must feel like a real camera captured
this exact moment in the real world.
"""

    return prompt.strip()


# ============================================================
# NEGATIVE PROMPT
# ============================================================

def build_negative_prompt(job):

    custom = job.get(
        "negative_prompt",
        ""
    ).strip()

    universal = """
cartoon,
comic,
comic book,
anime,
manga,
illustration,
drawing,
painting,
watercolor,
sketch,
concept art,
poster,
digital art,
3d render,
CGI,
game graphics,
plastic skin,
doll face,
wax figure,
synthetic human,
unrealistic anatomy,
deformed anatomy,
bad hands,
extra fingers,
extra limbs,
missing fingers,
duplicate people,
duplicate objects,
distorted face,
face deformation,
identity change,
age change,
unnatural eyes,
unnatural teeth,
fake skin,
oversaturated colors,
neon,
fantasy environment,
surreal environment,
artificial lighting,
flat lighting,
low detail,
low resolution,
blurry,
out of focus,
text,
caption,
subtitle,
watermark,
logo
"""

    if custom:

        return (
            custom
            + ","
            + universal
        )

    return universal.strip()


# ============================================================
# CLOUDFLARE API
# ============================================================

def api_request(payload):

    url = (
        f"{BASE_URL}/{ACCOUNT_ID}"
        f"/ai/run/{MODEL}"
    )

    request = urllib.request.Request(
        url,
        data=json.dumps(
            payload
        ).encode("utf-8"),
        headers={
            "Authorization":
                f"Bearer {API_TOKEN}",
            "Content-Type":
                "application/json",
        },
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=REQUEST_TIMEOUT
    ) as response:

        return response.read()


# ============================================================
# DOWNLOAD IMAGE URL
# ============================================================

def download_image(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "lok-ai-automation/1.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=REQUEST_TIMEOUT
    ) as response:

        return response.read()


# ============================================================
# EXTRACT IMAGE
# ============================================================

def extract_image(response_bytes):

    if not response_bytes:
        return None

    # Direct PNG/JPEG.
    if response_bytes.startswith(
        b"\x89PNG"
    ):
        return response_bytes

    if response_bytes.startswith(
        b"\xff\xd8"
    ):
        return response_bytes

    try:

        data = json.loads(
            response_bytes.decode(
                "utf-8"
            )
        )

    except Exception as exc:

        raise RuntimeError(
            "Cloudflare returned invalid JSON "
            f"or unsupported binary output: {exc}"
        )

    if data.get(
        "success"
    ) is False:

        raise RuntimeError(
            "Cloudflare API error: "
            + json.dumps(
                data.get(
                    "errors",
                    []
                ),
                ensure_ascii=False
            )
        )

    result = data.get(
        "result"
    )

    if not isinstance(
        result,
        dict
    ):

        raise RuntimeError(
            "Cloudflare response has no result."
        )

    image = result.get(
        "image"
    )

    if isinstance(
        image,
        str
    ):

        if image.startswith(
            "http://"
        ) or image.startswith(
            "https://"
        ):

            return download_image(
                image
            )

        try:

            return base64.b64decode(
                image
            )

        except Exception:

            pass

    raise RuntimeError(
        "Cloudflare response does not contain "
        "a usable image."
    )


# ============================================================
# GENERATE IMAGE
# ============================================================

def generate_image(job):

    prompt = build_prompt(
        job
    )

    negative = build_negative_prompt(
        job
    )

    part = int(
        job["part"]
    )

    scene = int(
        job["scene"]
    )

    seed = (
        part * 10000
        + scene
    )

    payload = {
        "prompt": prompt,
        "negative_prompt": negative,
        "size": image_size(),
        "seed": seed,
    }

    response = api_request(
        payload
    )

    return extract_image(
        response
    )


# ============================================================
# MANIFEST
# ============================================================

def update_manifest(
    jobs,
    status
):

    completed = 0
    failed = 0

    for job in jobs:

        path = visual_path(
            job["part"],
            job["scene"]
        )

        if is_valid_image(path):

            job["status"] = "completed"
            job["asset_path"] = str(
                path
            )

            completed += 1

        elif job.get(
            "status"
        ) == "failed":

            failed += 1

        else:

            job["status"] = "pending"
            job["asset_path"] = None

    total = len(
        jobs
    )

    data = {
        "status": status,
        "topic": TOPIC,
        "format": FORMAT,
        "provider": "cloudflare",
        "model": MODEL,
        "style": "photorealistic_live_action",
        "total_scenes": total,
        "completed_scenes": completed,
        "pending_scenes":
            total - completed - failed,
        "failed_scenes": failed,
        "updated_at": now(),
        "jobs": jobs,
    }

    save_json(
        VISUAL_JOBS_FILE,
        data
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "       PHOTOREALISTIC VISUAL GENERATOR"
    )
    print("=" * 70)

    print(
        f"Model  : {MODEL}"
    )

    print(
        f"Format : {FORMAT}"
    )

    print(
        f"Size   : {image_size()}"
    )

    print(
        "Style  : REAL PEOPLE / REAL WORLD / "
        "LIVE-ACTION PHOTOREALISM"
    )

    jobs = build_jobs()

    total = len(
        jobs
    )

    existing = sum(
        1
        for job in jobs
        if is_valid_image(
            visual_path(
                job["part"],
                job["scene"]
            )
        )
    )

    print()
    print(
        f"Expected visuals : {total}"
    )

    print(
        f"Existing valid   : {existing}"
    )

    print(
        f"To generate      : "
        f"{total - existing}"
    )

    update_manifest(
        jobs,
        "running"
    )

    generated = 0
    skipped = 0

    for index, job in enumerate(
        jobs,
        start=1
    ):

        part = int(
            job["part"]
        )

        scene = int(
            job["scene"]
        )

        output_file = visual_path(
            part,
            scene
        )

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        # ----------------------------------------------------
        # NEVER reuse old comic/old-model image blindly.
        # ----------------------------------------------------

        if (
            job.get("model") == MODEL
            and is_valid_image(
                output_file
            )
        ):

            skipped += 1

            print(
                f"[{index}/{total}] "
                f"Part {part} Scene {scene} "
                "VALID — SKIP"
            )

            continue

        # Remove old visual so the new model definitely
        # creates a fresh source image.
        if output_file.exists():

            try:
                output_file.unlink()
            except Exception:
                pass

        print()
        print(
            "-" * 70
        )

        print(
            f"[{index}/{total}] "
            f"GENERATING REALISTIC "
            f"Part {part} Scene {scene}"
        )

        print(
            f"Model: {MODEL}"
        )

        success = False
        last_error = ""

        for attempt in range(
            1,
            MAX_RETRIES + 1
        ):

            try:

                print(
                    f"Attempt "
                    f"{attempt}/{MAX_RETRIES}"
                )

                image = generate_image(
                    job
                )

                if not image:

                    raise RuntimeError(
                        "Empty image returned."
                    )

                temp = Path(
                    str(output_file)
                    + ".tmp"
                )

                temp.write_bytes(
                    image
                )

                if not is_valid_image(
                    temp
                ):

                    temp.unlink(
                        missing_ok=True
                    )

                    raise RuntimeError(
                        "Generated image failed "
                        "validation."
                    )

                os.replace(
                    temp,
                    output_file
                )

                job["status"] = (
                    "completed"
                )

                job["asset_path"] = (
                    str(output_file)
                )

                job["provider"] = (
                    "cloudflare"
                )

                job["model"] = MODEL

                job["completed_at"] = (
                    now()
                )

                job["error"] = None

                generated += 1
                success = True

                update_manifest(
                    jobs,
                    "running"
                )

                print(
                    f"SUCCESS: {output_file}"
                )

                break

            except urllib.error.HTTPError as e:

                try:

                    body = e.read().decode(
                        "utf-8",
                        errors="replace"
                    )

                except Exception:

                    body = ""

                last_error = (
                    f"HTTP {e.code}: "
                    f"{body[:1000]}"
                )

                print(
                    last_error
                )

                retryable = (
                    e.code == 429
                    or e.code >= 500
                )

                if (
                    not retryable
                    or attempt >= MAX_RETRIES
                ):
                    break

                delay = min(
                    INITIAL_BACKOFF
                    * (
                        2 ** (
                            attempt - 1
                        )
                    )
                    + random.randint(
                        0,
                        10
                    ),
                    MAX_BACKOFF
                )

                print(
                    f"Retrying in {delay}s..."
                )

                time.sleep(
                    delay
                )

            except Exception as e:

                last_error = str(
                    e
                )

                print(
                    f"FAILED: {last_error}"
                )

                if attempt >= MAX_RETRIES:
                    break

                delay = min(
                    INITIAL_BACKOFF
                    * (
                        2 ** (
                            attempt - 1
                        )
                    )
                    + random.randint(
                        0,
                        10
                    ),
                    MAX_BACKOFF
                )

                print(
                    f"Retrying in {delay}s..."
                )

                time.sleep(
                    delay
                )

        if not success:

            job["status"] = "failed"
            job["asset_path"] = None
            job["error"] = last_error

            update_manifest(
                jobs,
                "incomplete"
            )

            raise SystemExit(
                f"ERROR: Part {part} "
                f"Scene {scene} failed."
            )

    # ========================================================
    # FINAL VALIDATION
    # ========================================================

    missing = []

    for job in jobs:

        path = visual_path(
            job["part"],
            job["scene"]
        )

        if not is_valid_image(
            path
        ):

            missing.append(
                f"Part {job['part']} "
                f"Scene {job['scene']}"
            )

    print()
    print("=" * 70)
    print(
        "       FINAL PHOTOREALISTIC VALIDATION"
    )
    print("=" * 70)

    print(
        f"Expected : {total}"
    )

    print(
        f"Generated: {generated}"
    )

    print(
        f"Skipped  : {skipped}"
    )

    print(
        f"Missing  : {len(missing)}"
    )

    if missing:

        for item in missing:
            print(
                f" - {item}"
            )

        update_manifest(
            jobs,
            "incomplete"
        )

        raise SystemExit(
            "ERROR: Visual generation incomplete."
        )

    update_manifest(
        jobs,
        "completed"
    )

    print()
    print(
        "ALL PHOTOREALISTIC SOURCE IMAGES "
        "GENERATED AND VERIFIED."
    )

    print(
        f"Model: {MODEL}"
    )

    print(
        f"Format: {FORMAT}"
    )

    print("=" * 70)


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        print(
            "Interrupted."
        )

        raise SystemExit(130)

    except Exception as exc:

        print(
            f"ERROR: {exc}"
        )

        raise SystemExit(1)
