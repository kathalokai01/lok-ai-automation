#!/usr/bin/env python3

import base64
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


VISUAL_DIR = Path("output/visuals")
VIDEO_DIR = Path("output/i2v")
SCENES_FILE = Path("output/scenes/scenes.json")
CONFIG_FILE = Path("Input/topic.txt")

ACCOUNT_ID = os.environ.get(
    "CLOUDFLARE_ACCOUNT_ID",
    ""
).strip()

API_TOKEN = os.environ.get(
    "CLOUDFLARE_API_TOKEN",
    ""
).strip()

MODEL = "alibaba/hh1.1-i2v"

MAX_RETRIES = 5
INITIAL_BACKOFF = 15
MAX_BACKOFF = 180

REQUEST_TIMEOUT = 300


def clean_value(value):
    value = value.strip()

    if "#" in value:
        value = value.split("#", 1)[0].strip()

    if len(value) >= 2:
        if value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]

    return value.strip()


def read_config():
    if not CONFIG_FILE.exists():
        raise RuntimeError(
            "Missing Input/topic.txt"
        )

    config = {}

    for raw in CONFIG_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        config[key.strip().upper()] = clean_value(
            value
        )

    return config


def read_format(config):
    value = config.get(
        "FORMAT",
        "full"
    ).lower().strip()

    if value not in ("short", "full"):
        raise RuntimeError(
            f"Invalid FORMAT: {value}"
        )

    return value


def find_visual(part, scene):
    folder = VISUAL_DIR / f"part_{part:02d}"

    candidates = [
        folder / f"scene_{scene:02d}.png",
        folder / f"scene_{scene:02d}.jpg",
        folder / f"scene_{scene:02d}.jpeg",
    ]

    for path in candidates:
        if path.exists() and path.stat().st_size > 1000:
            return path

    return None


def visual_to_data_uri(path):
    suffix = path.suffix.lower()

    if suffix == ".png":
        mime = "image/png"
    elif suffix in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    else:
        raise RuntimeError(
            f"Unsupported visual format: {path}"
        )

    encoded = base64.b64encode(
        path.read_bytes()
    ).decode("ascii")

    return f"data:{mime};base64,{encoded}"


def build_motion_prompt(
    scene,
    format_value,
):
    visual = str(
        scene.get("visual", "")
    ).strip()

    narration = str(
        scene.get("narration", "")
    ).strip()

    purpose = str(
        scene.get("purpose", "")
    ).strip()

    base = f"""
Create a photorealistic live-action cinematic video from the reference image.

The people must look like real human beings.
The environment must look physically real.
Natural skin texture.
Natural facial expressions.
Natural body movement.
Natural hand movement.
Realistic clothing movement.
Realistic environmental motion.
Realistic depth and lighting.

Do NOT turn the scene into:
cartoon,
comic,
anime,
illustration,
painting,
3D animation,
game graphics,
plastic-looking characters,
fantasy CGI.

Maintain the identity, clothing, age, facial appearance and location
from the reference image.

SCENE PURPOSE:
{purpose}

SCENE DESCRIPTION:
{visual}

NARRATION CONTEXT:
{narration}

Generate genuine motion rather than a static camera effect.
The subjects should naturally move according to the scene.
Use subtle eye movement, breathing, head movement and realistic gestures
when appropriate.

Use cinematic camera movement such as:
slow dolly,
subtle tracking,
natural handheld movement,
gentle push-in,
slow lateral movement,
or realistic camera repositioning.

Do not use an artificial slideshow effect.

Keep the scene visually coherent from beginning to end.
"""

    if format_value == "short":
        base += """
SHORT-FORM PACING:

This is a short video.
Motion must begin immediately.

Do not waste the opening seconds on an empty establishing shot.

Make the movement visually support curiosity, tension or suspense.
If this scene is a hook, make the first moment visually intriguing.
If this scene is an escalation, increase movement or visual tension.
If this scene is the final reveal, make the visual moment feel important.

The visual storytelling must feel intentionally made for a short video,
not like a section cut out of a long movie.
"""

    return " ".join(
        base.split()
    )


def call_i2v(image_uri, prompt, duration):
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{ACCOUNT_ID}/ai/run/{MODEL}"
    )

    payload = {
        "input": {
            "image": image_uri,
            "prompt": prompt,
            "negative_prompt": (
                "cartoon, comic, anime, illustration, "
                "painting, drawing, 3d render, CGI, "
                "plastic skin, distorted face, "
                "deformed hands, extra fingers, "
                "frozen person, static image, "
                "slideshow, artificial motion"
            ),
            "resolution": "720P",
            "duration": duration,
            "watermark": False,
        }
    }

    data = json.dumps(
        payload
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization":
                f"Bearer {API_TOKEN}",
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):
        try:

            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT
            ) as response:

                raw = response.read().decode(
                    "utf-8"
                )

            result = json.loads(raw)

            state = str(
                result.get(
                    "state",
                    ""
                )
            ).lower()

            if state not in (
                "",
                "completed",
                "complete",
                "success"
            ):
                print(
                    f"Cloudflare state: {state}"
                )

            video_url = (
                result
                .get("result", {})
                .get("video")
            )

            if not video_url:
                raise RuntimeError(
                    "Cloudflare did not return "
                    "result.video"
                )

            return video_url

        except urllib.error.HTTPError as exc:

            body = exc.read().decode(
                "utf-8",
                errors="replace"
            )

            last_error = RuntimeError(
                f"Cloudflare HTTP {exc.code}: "
                f"{body[:1200]}"
            )

            retryable = exc.code in (
                408,
                429,
                500,
                502,
                503,
                504,
            )

            if not retryable:
                raise last_error

        except Exception as exc:
            last_error = exc

        if attempt < MAX_RETRIES:

            delay = min(
                INITIAL_BACKOFF *
                (2 ** (attempt - 1)),
                MAX_BACKOFF
            )

            jitter = random.randint(
                0,
                8
            )

            delay += jitter

            print(
                f"I2V attempt {attempt} failed: "
                f"{last_error}"
            )

            print(
                f"Retrying in {delay}s..."
            )

            time.sleep(delay)

    raise last_error or RuntimeError(
        "I2V generation failed"
    )


def download_video(url, output):
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

        data = response.read()

    if len(data) < 1000:
        raise RuntimeError(
            "Downloaded I2V video is too small"
        )

    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output.write_bytes(data)


def valid_video(path):
    if not path.exists():
        return False

    if path.stat().st_size <= 1000:
        return False

    header = path.read_bytes()[:32]

    return (
        b"ftyp" in header
        or header.startswith(b"\x00\x00\x00")
    )


def load_scenes():
    if not SCENES_FILE.exists():
        raise RuntimeError(
            "Missing output/scenes/scenes.json"
        )

    data = json.loads(
        SCENES_FILE.read_text(
            encoding="utf-8"
        )
    )

    if data.get("status") != "completed":
        raise RuntimeError(
            "scenes.json is not completed"
        )

    scenes = data.get(
        "scenes",
        []
    )

    if not scenes:
        raise RuntimeError(
            "No scenes found"
        )

    return scenes


def choose_duration(scene):
    raw = str(
        scene.get(
            "duration",
            ""
        )
    ).strip()

    try:
        value = float(raw)

        if value > 0:
            value = int(round(value))

            return max(
                3,
                min(
                    15,
                    value
                )
            )
    except Exception:
        pass

    return 6


def main():
    print("=" * 60)
    print("        IMAGE TO VIDEO GENERATION")
    print("=" * 60)

    if not ACCOUNT_ID:
        raise RuntimeError(
            "CLOUDFLARE_ACCOUNT_ID is not set"
        )

    if not API_TOKEN:
        raise RuntimeError(
            "CLOUDFLARE_API_TOKEN is not set"
        )

    config = read_config()

    format_value = read_format(
        config
    )

    print(
        f"Format : {format_value}"
    )

    print(
        f"Model  : {MODEL}"
    )

    scenes = load_scenes()

    VIDEO_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    jobs = []

    total = len(scenes)

    for index, scene in enumerate(
        scenes,
        start=1
    ):

        part = int(
            scene.get(
                "part",
                1
            )
        )

        scene_number = int(
            scene.get(
                "scene",
                index
            )
        )

        output = (
            VIDEO_DIR /
            f"part_{part:02d}" /
            f"scene_{scene_number:02d}.mp4"
        )

        print()
        print(
            f"[{index}/{total}] "
            f"Part {part} Scene {scene_number}"
        )

        if valid_video(output):

            print(
                "Existing valid I2V video found. "
                "Skipping."
            )

            jobs.append({
                "part": part,
                "scene": scene_number,
                "status": "completed",
                "file": str(output),
                "model": MODEL,
            })

            continue

        image = find_visual(
            part,
            scene_number
        )

        if not image:
            raise RuntimeError(
                f"Missing visual for "
                f"Part {part} Scene {scene_number}"
            )

        print(
            f"Reference image: {image}"
        )

        image_uri = visual_to_data_uri(
            image
        )

        prompt = build_motion_prompt(
            scene,
            format_value
        )

        duration = choose_duration(
            scene
        )

        print(
            f"Duration: {duration}s"
        )

        print(
            "Generating real AI motion..."
        )

        video_url = call_i2v(
            image_uri,
            prompt,
            duration
        )

        print(
            "Downloading generated video..."
        )

        download_video(
            video_url,
            output
        )

        if not valid_video(output):
            raise RuntimeError(
                f"Invalid generated video: "
                f"{output}"
            )

        print(
            f"SUCCESS: {output}"
        )

        jobs.append({
            "part": part,
            "scene": scene_number,
            "status": "completed",
            "file": str(output),
            "model": MODEL,
            "duration": duration,
        })

    manifest = {
        "status": "completed",
        "format": format_value,
        "model": MODEL,
        "total": total,
        "completed": len(jobs),
        "jobs": jobs,
    }

    manifest_path = (
        VIDEO_DIR /
        "i2v_jobs.json"
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    if len(jobs) != total:
        raise RuntimeError(
            f"I2V count mismatch: "
            f"{len(jobs)}/{total}"
        )

    print()
    print("=" * 60)
    print("       I2V GENERATION SUCCESS")
    print("=" * 60)
    print(
        f"Videos: {len(jobs)}/{total}"
    )
    print(
        f"Model : {MODEL}"
    )
    print(
        f"Output: {VIDEO_DIR}"
    )
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr
        )
        sys.exit(1)
