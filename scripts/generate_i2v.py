#!/usr/bin/env python3

import base64
import json
import mimetypes
import os
import random
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ============================================================
# CONFIG
# ============================================================

CONFIG_FILE = Path("Input/topic.txt")
SCENES_FILE = Path("output/scenes/scenes.json")

VISUAL_DIR = Path("output/visuals")
AUDIO_DIR = Path("output/narration/audio")
I2V_DIR = Path("output/i2v")

JOBS_FILE = I2V_DIR / "i2v_jobs.json"

ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()

MODEL = "alibaba/hh1.1-i2v"

API_URL = (
    "https://api.cloudflare.com/client/v4/accounts/"
    "{account_id}/ai/run/{model}"
)

MAX_RETRIES = 6
INITIAL_BACKOFF = 20
MAX_BACKOFF = 300
REQUEST_TIMEOUT = 300


# ============================================================
# CONFIG HELPERS
# ============================================================

def clean_config_value(value):

    value = value.strip()

    if "#" in value:
        value = value.split("#", 1)[0].strip()

    return value.strip().strip('"').strip("'")


def load_config():

    if not CONFIG_FILE.exists():
        raise RuntimeError(
            "Input/topic.txt not found."
        )

    config = {}

    for raw in CONFIG_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        config[key.strip().upper()] = (
            clean_config_value(value)
        )

    return config


CONFIG = load_config()

FORMAT = CONFIG.get(
    "FORMAT",
    "full"
).lower()

if FORMAT not in {"short", "full"}:
    raise RuntimeError(
        f"Invalid FORMAT: {FORMAT}"
    )


# ============================================================
# VALIDATE API
# ============================================================

if not ACCOUNT_ID:
    raise RuntimeError(
        "CLOUDFLARE_ACCOUNT_ID is not set."
    )

if not API_TOKEN:
    raise RuntimeError(
        "CLOUDFLARE_API_TOKEN is not set."
    )


# ============================================================
# DIRECTORIES
# ============================================================

I2V_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path, default):

    if not path.exists():
        return default

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return default


def save_json(path, data):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


jobs = load_json(
    JOBS_FILE,
    {
        "status": "running",
        "format": FORMAT,
        "model": MODEL,
        "jobs": []
    }
)


# ============================================================
# FILE HELPERS
# ============================================================

def find_visual(part, scene):

    directory = (
        VISUAL_DIR /
        f"part_{part:02d}"
    )

    candidates = [
        directory / f"scene_{scene:02d}.png",
        directory / f"scene_{scene:02d}.jpg",
        directory / f"scene_{scene:02d}.jpeg",
        directory / f"scene_{scene}.png",
        directory / f"scene_{scene}.jpg",
        directory / f"scene_{scene}.jpeg",
    ]

    for path in candidates:

        if (
            path.exists()
            and path.stat().st_size > 1000
        ):
            return path

    return None


def find_audio(part, scene):

    directory = (
        AUDIO_DIR /
        f"part_{part:02d}"
    )

    candidates = [
        directory / f"scene_{scene:02d}.mp3",
        directory / f"scene_{scene}.mp3",
        directory / f"scene_{scene:02d}.wav",
        directory / f"scene_{scene}.wav",
    ]

    for path in candidates:

        if (
            path.exists()
            and path.stat().st_size > 1000
        ):
            return path

    return None


def get_audio_duration(path):

    import subprocess

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Unable to read audio duration: {path}"
        )

    try:

        return float(
            result.stdout.strip()
        )

    except Exception:

        raise RuntimeError(
            f"Invalid audio duration: {path}"
        )


# ============================================================
# I2V DURATION
# ============================================================

def choose_duration(audio_duration):

    """
    Cloudflare HH 1.1 I2V supports approximately
    3-15 seconds.

    We request enough time for the narration while
    avoiding unnecessary looping during rendering.
    """

    if FORMAT == "short":

        # Short scenes should remain fast.
        # Give the scene enough motion time for narration.
        target = audio_duration + 0.5

    else:

        target = audio_duration + 0.5

    # Model limits.
    target = max(
        3.0,
        min(15.0, target)
    )

    # API expects an integer duration.
    duration = int(
        round(target)
    )

    duration = max(
        3,
        min(15, duration)
    )

    return duration


# ============================================================
# IMAGE -> DATA URI
# ============================================================

def image_to_data_uri(path):

    mime_type, _ = mimetypes.guess_type(
        str(path)
    )

    if not mime_type:

        if path.suffix.lower() == ".png":
            mime_type = "image/png"

        else:
            mime_type = "image/jpeg"

    encoded = base64.b64encode(
        path.read_bytes()
    ).decode("ascii")

    return (
        f"data:{mime_type};base64,{encoded}"
    )


# ============================================================
# MOTION PROMPT
# ============================================================

def build_prompt(
    scene,
    part,
    scene_number,
    duration
):

    base = str(
        scene.get(
            "visual_prompt",
            scene.get(
                "prompt",
                ""
            )
        )
    ).strip()

    scene_description = str(
        scene.get(
            "description",
            ""
        )
    ).strip()

    action = str(
        scene.get(
            "action",
            ""
        )
    ).strip()

    if FORMAT == "short":

        format_instruction = """
This is an ORIGINAL short-form video scene.

Motion must begin immediately in the first moment.
Do not make the opening feel like a still photograph.

Create immediate visual curiosity and tension.
Use purposeful human movement, environmental movement,
camera movement, or a combination.

The scene must feel designed specifically for a short video,
not like a clipped section from a longer movie.

Maintain momentum throughout the shot.
Avoid a static opening.
Avoid a static ending.
"""

    else:

        format_instruction = """
This is a cinematic long-form video scene.

Create continuous natural motion throughout the shot.
Use subtle human movement, environmental movement,
and purposeful cinematic camera movement.

Do not make the scene feel like a photograph.
"""

    return f"""
Create a REALISTIC AI IMAGE-TO-VIDEO shot.

PART: {part}
SCENE: {scene_number}
TARGET DURATION: {duration} seconds

SOURCE IMAGE IS THE VISUAL REFERENCE.

{format_instruction}

SOURCE SCENE DESCRIPTION:
{scene_description}

SOURCE ACTION:
{action}

SOURCE VISUAL PROMPT:
{base}

ANIMATION REQUIREMENTS:

- Real human beings.
- Real-world environment.
- Photorealistic appearance.
- Natural human anatomy.
- Natural skin texture.
- Natural facial movement.
- Natural eye movement.
- Natural blinking when appropriate.
- Natural breathing.
- Realistic body movement.
- Realistic clothing movement.
- Realistic environmental motion.
- Physically believable lighting.
- Realistic shadows.
- Natural depth of field.
- Cinematic but believable camera movement.
- Preserve the identity of every person.
- Preserve age, face, hairstyle, clothing and body proportions.
- Preserve the location and important objects.
- Preserve continuity with the source image.
- Do not change the characters into different people.
- Do not change the scene into a different location.

CAMERA:

Use subtle real camera movement such as:
slow handheld movement,
controlled dolly movement,
slow push-in,
gentle tracking,
or realistic documentary-style movement.

The camera must not move randomly.

IMPORTANT:

The generated result must look like footage captured
with a real camera in the real world.

It must NOT look like:
a comic,
a cartoon,
an illustration,
anime,
3D animation,
CGI,
game graphics,
a slideshow,
a moving photograph,
or a painted image.

Do not freeze the subjects.

Do not simply zoom a still image.

Create genuine temporal motion between frames.

NEGATIVE PROMPT:

cartoon, comic, anime, manga, illustration,
painting, drawing, sketch, 3d render, CGI,
game graphics, plastic skin, doll face,
unrealistic anatomy, distorted face,
extra fingers, extra limbs, duplicate person,
face deformation, identity change,
age change, clothing change,
location change, object morphing,
frozen pose, static image, slideshow,
moving photograph, artificial camera motion,
warping, flickering, jitter,
frame interpolation artifacts,
ghosting, duplicated body parts,
neon colors, fantasy environment,
surreal environment, low detail,
blurry face, deformed hands,
watermark, text, logo
""".strip()


# ============================================================
# HTTP REQUEST
# ============================================================

def call_cloudflare(payload):

    url = API_URL.format(
        account_id=ACCOUNT_ID,
        model=MODEL
    )

    body = json.dumps(
        payload
    ).encode("utf-8")

    request = Request(
        url,
        data=body,
        headers={
            "Authorization":
                f"Bearer {API_TOKEN}",
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    try:

        with urlopen(
            request,
            timeout=REQUEST_TIMEOUT
        ) as response:

            raw = response.read()

            return json.loads(
                raw.decode("utf-8")
            )

    except HTTPError as error:

        response_body = ""

        try:
            response_body = (
                error.read()
                .decode("utf-8", errors="replace")
            )
        except Exception:
            pass

        raise RuntimeError(
            f"HTTP {error.code}: "
            f"{response_body[:2000]}"
        )

    except URLError as error:

        raise RuntimeError(
            f"Network error: {error}"
        )


# ============================================================
# VIDEO RESPONSE
# ============================================================

def extract_video_bytes(result):

    if not isinstance(result, dict):
        raise RuntimeError(
            "Invalid Cloudflare response."
        )

    if result.get("success") is False:

        errors = result.get(
            "errors",
            []
        )

        raise RuntimeError(
            f"Cloudflare AI error: "
            f"{errors}"
        )

    result_data = result.get(
        "result"
    )

    if isinstance(
        result_data,
        dict
    ):

        video = result_data.get(
            "video"
        )

        if isinstance(
            video,
            str
        ):

            # Some responses may return a URL.
            if video.startswith(
                "http://"
            ) or video.startswith(
                "https://"
            ):

                request = Request(
                    video,
                    headers={
                        "Authorization":
                            f"Bearer {API_TOKEN}"
                    }
                )

                with urlopen(
                    request,
                    timeout=REQUEST_TIMEOUT
                ) as response:

                    return response.read()

            # Otherwise treat as base64.
            try:

                return base64.b64decode(
                    video
                )

            except Exception:
                pass

        if isinstance(
            video,
            dict
        ):

            data = video.get(
                "data"
            )

            if data:

                return base64.b64decode(
                    data
                )

    raise RuntimeError(
        "Cloudflare response does not contain "
        "a usable video result."
    )


# ============================================================
# GENERATE ONE CLIP
# ============================================================

def generate_clip(
    part,
    scene_number,
    scene,
    visual_path,
    audio_path,
    output_path
):

    audio_duration = get_audio_duration(
        audio_path
    )

    duration = choose_duration(
        audio_duration
    )

    prompt = build_prompt(
        scene=scene,
        part=part,
        scene_number=scene_number,
        duration=duration
    )

    print()
    print("=" * 70)
    print(
        f"GENERATING I2V "
        f"Part {part} Scene {scene_number}"
    )
    print("=" * 70)

    print(
        f"Audio duration : "
        f"{audio_duration:.2f}s"
    )

    print(
        f"I2V duration   : "
        f"{duration}s"
    )

    print(
        f"Model          : "
        f"{MODEL}"
    )

    image_uri = image_to_data_uri(
        visual_path
    )

    payload = {
        "input": {
            "image": image_uri,
            "prompt": prompt,
            "negative_prompt": (
                "cartoon, comic, anime, illustration, "
                "painting, CGI, 3D render, slideshow, "
                "static image, distorted face, "
                "identity change, body deformation, "
                "warping, flicker, jitter"
            ),
            "resolution": "720P",
            "duration": duration,
            "watermark": False,
        }
    }

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            print(
                f"Attempt {attempt}/"
                f"{MAX_RETRIES}"
            )

            result = call_cloudflare(
                payload
            )

            video_bytes = extract_video_bytes(
                result
            )

            if not video_bytes:
                raise RuntimeError(
                    "Cloudflare returned empty video."
                )

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            output_path.write_bytes(
                video_bytes
            )

            if output_path.stat().st_size < 1000:

                output_path.unlink(
                    missing_ok=True
                )

                raise RuntimeError(
                    "Generated video is too small."
                )

            print(
                f"SUCCESS: {output_path}"
            )

            return duration

        except Exception as exc:

            last_error = exc

            print(
                f"Attempt {attempt} failed: "
                f"{exc}"
            )

            if attempt >= MAX_RETRIES:
                break

            delay = min(
                MAX_BACKOFF,
                INITIAL_BACKOFF
                * (2 ** (attempt - 1))
            )

            delay += random.randint(
                0,
                10
            )

            print(
                f"Waiting {delay}s before retry..."
            )

            time.sleep(
                delay
            )

    raise RuntimeError(
        f"Part {part} Scene {scene_number} "
        f"failed after {MAX_RETRIES} attempts: "
        f"{last_error}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("       REAL AI IMAGE-TO-VIDEO GENERATION")
    print("=" * 70)

    print(
        f"Format : {FORMAT}"
    )

    print(
        f"Model  : {MODEL}"
    )

    if not SCENES_FILE.exists():
        raise RuntimeError(
            "output/scenes/scenes.json not found."
        )

    scenes_data = json.loads(
        SCENES_FILE.read_text(
            encoding="utf-8"
        )
    )

    if scenes_data.get("status") != "completed":
        raise RuntimeError(
            "Scenes are not marked completed."
        )

    scenes = scenes_data.get(
        "scenes",
        []
    )

    if not scenes:
        raise RuntimeError(
            "No scenes found."
        )

    print(
        f"Scenes: {len(scenes)}"
    )

    # --------------------------------------------------------
    # Existing jobs
    # --------------------------------------------------------

    old_jobs = {}

    for job in jobs.get(
        "jobs",
        []
    ):

        key = (
            int(job["part"]),
            int(job["scene"])
        )

        old_jobs[key] = job

    final_jobs = []

    # --------------------------------------------------------
    # Process scenes
    # --------------------------------------------------------

    for scene in scenes:

        part = int(
            scene.get("part", 0)
        )

        scene_number = int(
            scene.get("scene", 0)
        )

        if part <= 0:
            raise RuntimeError(
                f"Invalid part: {part}"
            )

        if scene_number <= 0:
            raise RuntimeError(
                f"Invalid scene: {scene_number}"
            )

        visual_path = find_visual(
            part,
            scene_number
        )

        if visual_path is None:
            raise RuntimeError(
                f"Missing visual for "
                f"Part {part} Scene {scene_number}"
            )

        audio_path = find_audio(
            part,
            scene_number
        )

        if audio_path is None:
            raise RuntimeError(
                f"Missing narration for "
                f"Part {part} Scene {scene_number}"
            )

        output_path = (
            I2V_DIR /
            f"part_{part:02d}" /
            f"scene_{scene_number:02d}.mp4"
        )

        key = (
            part,
            scene_number
        )

        # ----------------------------------------------------
        # Resume valid completed clip
        # ----------------------------------------------------

        if (
            output_path.exists()
            and output_path.stat().st_size > 1000
        ):

            print()
            print(
                f"SKIP existing I2V: "
                f"Part {part} Scene {scene_number}"
            )

            duration = 0

            try:
                duration = get_audio_duration(
                    audio_path
                )
            except Exception:
                pass

            final_jobs.append(
                {
                    "part": part,
                    "scene": scene_number,
                    "status": "completed",
                    "model": MODEL,
                    "format": FORMAT,
                    "visual": str(
                        visual_path
                    ),
                    "audio": str(
                        audio_path
                    ),
                    "output": str(
                        output_path
                    ),
                    "audio_duration":
                        duration,
                }
            )

            continue

        # ----------------------------------------------------
        # Generate new clip
        # ----------------------------------------------------

        generated_duration = generate_clip(
            part=part,
            scene_number=scene_number,
            scene=scene,
            visual_path=visual_path,
            audio_path=audio_path,
            output_path=output_path,
        )

        audio_duration = get_audio_duration(
            audio_path
        )

        final_jobs.append(
            {
                "part": part,
                "scene": scene_number,
                "status": "completed",
                "model": MODEL,
                "format": FORMAT,
                "visual": str(
                    visual_path
                ),
                "audio": str(
                    audio_path
                ),
                "output": str(
                    output_path
                ),
                "audio_duration":
                    audio_duration,
                "requested_duration":
                    generated_duration,
            }
        )

        jobs["jobs"] = final_jobs
        jobs["status"] = "running"

        save_json(
            JOBS_FILE,
            jobs
        )

    # --------------------------------------------------------
    # Final validation
    # --------------------------------------------------------

    expected = len(scenes)

    completed = 0

    for job in final_jobs:

        output = Path(
            job["output"]
        )

        if (
            output.exists()
            and output.stat().st_size > 1000
        ):

            completed += 1

    print()
    print("=" * 70)
    print("             I2V VALIDATION")
    print("=" * 70)

    print(
        f"Completed: {completed}/{expected}"
    )

    if completed != expected:
        raise RuntimeError(
            "I2V clip count mismatch."
        )

    jobs["jobs"] = final_jobs
    jobs["status"] = "completed"
    jobs["format"] = FORMAT
    jobs["model"] = MODEL
    jobs["total"] = expected

    save_json(
        JOBS_FILE,
        jobs
    )

    print()
    print(
        "REAL AI IMAGE-TO-VIDEO GENERATION COMPLETE."
    )

    print(
        f"Output directory: {I2V_DIR}"
    )


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "Interrupted."
        )

        sys.exit(130)

    except Exception as exc:

        print()
        print(
            f"ERROR: {exc}"
        )

        sys.exit(1)
