import os
import json
import base64
import time
import random
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")

SCENES_FILE = "output/scenes/scenes.json"
VISUAL_JOBS_FILE = "output/visuals/visual_jobs.json"
SELECTED_MODEL_FILE = "output/config/selected_visual_model.json"
TOPIC_FILE = "Input/topic.txt"

MAX_RETRIES = 6
INITIAL_BACKOFF = 20
MAX_BACKOFF = 300
REQUEST_TIMEOUT = 180

BASE_URL = "https://api.cloudflare.com/client/v4/accounts"


def now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    temp = f"{path}.tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    os.replace(temp, path)


def get_topic():
    if not os.path.exists(TOPIC_FILE):
        return ""

    values = {}

    with open(TOPIC_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)

            values[key.strip()] = (
                value.strip()
                .strip('"')
                .strip("'")
            )

    return values.get("TOPIC", "")


def visual_path(part, scene):
    return (
        f"output/visuals/"
        f"part_{int(part):02d}/"
        f"scene_{int(scene):02d}.png"
    )


def is_valid_image(path):
    if not os.path.exists(path):
        return False

    try:
        if os.path.getsize(path) <= 0:
            return False

        with open(path, "rb") as f:
            header = f.read(8)

        return (
            header.startswith(b"\x89PNG")
            or header.startswith(b"\xff\xd8")
        )

    except Exception:
        return False


def make_job(scene, old_job=None):
    part = int(scene["part"])
    scene_number = int(scene["scene"])

    visual_prompt = str(
        scene.get("visual_prompt", "")
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
        "asset_type": "visual",
        "visual_prompt": visual_prompt,
        "negative_prompt": str(
            scene.get("negative_prompt", "")
        ).strip(),
        "camera_prompt": str(
            scene.get("camera_prompt", "")
        ).strip(),
        "lighting_prompt": str(
            scene.get("lighting_prompt", "")
        ).strip(),
        "duration": scene.get("duration", "auto"),
        "asset_path": None,
        "provider": None,
        "model": None,
        "error": None,
    }

    if isinstance(old_job, dict):
        for key in (
            "provider",
            "model",
            "error",
            "completed_at",
        ):
            if key in old_job:
                job[key] = old_job[key]

    return job


def build_jobs_from_scenes():
    if not os.path.exists(SCENES_FILE):
        raise RuntimeError(
            "output/scenes/scenes.json not found"
        )

    scenes_data = load_json(SCENES_FILE)

    if scenes_data.get("status") != "completed":
        raise RuntimeError(
            "Scene generation is not completed"
        )

    scenes = scenes_data.get("scenes", [])

    if not isinstance(scenes, list) or not scenes:
        raise RuntimeError(
            "No scenes found in scenes.json"
        )

    old_jobs = {}

    if os.path.exists(VISUAL_JOBS_FILE):
        try:
            old_data = load_json(VISUAL_JOBS_FILE)

            for item in old_data.get("jobs", []):
                key = (
                    int(item["part"]),
                    int(item["scene"]),
                )
                old_jobs[key] = item

        except Exception as e:
            print(
                "WARNING: Existing visual manifest "
                f"could not be read: {e}"
            )

    jobs = []

    for scene in scenes:
        part = int(scene["part"])
        scene_number = int(scene["scene"])

        key = (part, scene_number)

        path = visual_path(part, scene_number)

        old_job = old_jobs.get(key)

        job = make_job(
            scene,
            old_job,
        )

        if is_valid_image(path):
            job["status"] = "completed"
            job["asset_path"] = path
            job["error"] = None

        else:
            job["status"] = "pending"
            job["asset_path"] = None

        jobs.append(job)

    jobs.sort(
        key=lambda x: (
            int(x["part"]),
            int(x["scene"]),
        )
    )

    return jobs


def build_prompt(job, topic):
    parts = []

    if topic:
        parts.append(
            f"Story topic: {topic}"
        )

    parts.append(
        "Visual scene: "
        + job["visual_prompt"]
    )

    if job.get("camera_prompt"):
        parts.append(
            "Camera: "
            + job["camera_prompt"]
        )

    if job.get("lighting_prompt"):
        parts.append(
            "Lighting: "
            + job["lighting_prompt"]
        )

    parts.append(
        "Style: cinematic realistic, "
        "photorealistic, natural motion, "
        "realistic Indian environment, "
        "high detail, cinematic composition."
    )

    return "\n".join(parts)


def build_negative_prompt(job):
    default_negative = (
        "cartoon, anime, illustration, neon, "
        "glitch, distorted face, deformed body, "
        "extra fingers, extra limbs, blurry, "
        "low quality, text, watermark, logo"
    )

    custom = str(
        job.get("negative_prompt", "")
    ).strip()

    if custom:
        return f"{custom}, {default_negative}"

    return default_negative


def api_request(model, payload):
    url = (
        f"{BASE_URL}/{ACCOUNT_ID}"
        f"/ai/run/{model}"
    )

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=REQUEST_TIMEOUT,
    ) as response:
        return response.read()


def extract_image(response_bytes):
    if not response_bytes:
        return None

    if response_bytes.startswith(b"\x89PNG"):
        return response_bytes

    if response_bytes.startswith(b"\xff\xd8"):
        return response_bytes

    try:
        result = json.loads(
            response_bytes.decode(
                "utf-8"
            )
        )
    except Exception:
        return None

    candidates = []

    def collect(value):
        if isinstance(value, str):
            candidates.append(value)

        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(result)

    for value in candidates:
        try:
            decoded = base64.b64decode(
                value,
                validate=True,
            )

            if (
                decoded.startswith(b"\x89PNG")
                or decoded.startswith(b"\xff\xd8")
            ):
                return decoded

        except Exception:
            continue

    return None


def generate_image(model, job, topic):
    prompt = build_prompt(
        job,
        topic,
    )

    negative = build_negative_prompt(
        job
    )

    seed = (
        int(job["part"]) * 10000
        + int(job["scene"])
    )

    if "stable-diffusion-xl-lightning" in model:
        payload = {
            "prompt": prompt,
            "negative_prompt": negative,
            "width": 768,
            "height": 432,
            "num_steps": 4,
            "guidance": 7.5,
            "seed": seed,
        }

    elif "flux-1-schnell" in model:
        payload = {
            "prompt": (
                f"{prompt}\n"
                f"Negative prompt: {negative}"
            ),
            "steps": 4,
            "seed": seed,
        }

    else:
        payload = {
            "prompt": prompt,
        }

    response = api_request(
        model,
        payload,
    )

    image = extract_image(response)

    if not image:
        raise RuntimeError(
            "Cloudflare API returned no valid image"
        )

    return image


def update_manifest(jobs, provider, model, status=None):
    completed = 0
    failed = 0

    for job in jobs:
        path = visual_path(
            job["part"],
            job["scene"],
        )

        if is_valid_image(path):
            job["status"] = "completed"
            job["asset_path"] = path
            completed += 1

        elif job.get("status") == "failed":
            failed += 1

        else:
            job["status"] = "pending"
            job["asset_path"] = None

    total = len(jobs)

    if status is None:
        status = (
            "completed"
            if completed == total
            else "running"
        )

    data = {
        "status": status,
        "topic": get_topic(),
        "provider": provider,
        "model": model,
        "total_scenes": total,
        "completed_scenes": completed,
        "pending_scenes": (
            total - completed - failed
        ),
        "failed_scenes": failed,
        "updated_at": now(),
        "jobs": jobs,
    }

    save_json(
        VISUAL_JOBS_FILE,
        data,
    )


def main():
    print(
        "======================================"
    )
    print(
        "       LOK AI VISUAL GENERATOR"
    )
    print(
        "======================================"
    )

    if not ACCOUNT_ID:
        raise SystemExit(
            "ERROR: CLOUDFLARE_ACCOUNT_ID is not set"
        )

    if not API_TOKEN:
        raise SystemExit(
            "ERROR: CLOUDFLARE_API_TOKEN is not set"
        )

    if not os.path.exists(
        SELECTED_MODEL_FILE
    ):
        raise SystemExit(
            "ERROR: selected_visual_model.json "
            "not found"
        )

    selected = load_json(
        SELECTED_MODEL_FILE
    )

    provider = selected.get("provider")
    model = selected.get("model")

    if provider != "cloudflare_workers_ai":
        raise SystemExit(
            "ERROR: Invalid visual provider: "
            f"{provider}"
        )

    if not model:
        raise SystemExit(
            "ERROR: No visual model selected"
        )

    print(
        "Rebuilding visual jobs directly "
        "from scenes.json..."
    )

    jobs = build_jobs_from_scenes()

    total = len(jobs)

    existing = sum(
        1
        for job in jobs
        if is_valid_image(
            visual_path(
                job["part"],
                job["scene"],
            )
        )
    )

    print(
        f"EXPECTED VISUALS: {total}"
    )

    print(
        f"EXISTING VALID : {existing}"
    )

    print(
        f"TO GENERATE    : {total - existing}"
    )

    # Save rebuilt manifest BEFORE generation.
    update_manifest(
        jobs,
        provider,
        model,
        "running",
    )

    topic = get_topic()

    generated = 0
    skipped = 0

    for index, job in enumerate(
        jobs,
        start=1,
    ):
        part = int(job["part"])
        scene = int(job["scene"])

        output_file = visual_path(
            part,
            scene,
        )

        os.makedirs(
            os.path.dirname(output_file),
            exist_ok=True,
        )

        if is_valid_image(
            output_file
        ):
            skipped += 1

            print(
                f"[{index}/{total}] "
                f"Part {part} Scene {scene} "
                "VALID — SKIP"
            )

            continue

        print()
        print(
            f"[{index}/{total}] "
            f"GENERATING Part {part} "
            f"Scene {scene}"
        )

        success = False
        last_error = ""

        for attempt in range(
            1,
            MAX_RETRIES + 1,
        ):
            try:
                print(
                    f"Attempt {attempt}/{MAX_RETRIES}"
                )

                image = generate_image(
                    model,
                    job,
                    topic,
                )

                temp_file = (
                    f"{output_file}.tmp"
                )

                with open(
                    temp_file,
                    "wb",
                ) as f:
                    f.write(image)

                if not is_valid_image(
                    temp_file
                ):
                    try:
                        os.remove(temp_file)
                    except OSError:
                        pass

                    raise RuntimeError(
                        "Generated image is invalid"
                    )

                os.replace(
                    temp_file,
                    output_file,
                )

                if not is_valid_image(
                    output_file
                ):
                    raise RuntimeError(
                        "Image verification failed "
                        "after save"
                    )

                job["status"] = "completed"
                job["asset_path"] = output_file
                job["provider"] = provider
                job["model"] = model
                job["error"] = None
                job["completed_at"] = now()

                generated += 1
                success = True

                update_manifest(
                    jobs,
                    provider,
                    model,
                    "running",
                )

                print(
                    "SUCCESS: "
                    f"{output_file}"
                )

                break

            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                except Exception:
                    body = ""

                last_error = (
                    f"HTTP {e.code}: {e.reason}"
                )

                if body:
                    last_error += (
                        f" | {body[:500]}"
                    )

                print(
                    f"FAILED: {last_error}"
                )

                retryable = (
                    e.code == 429
                    or e.code >= 500
                )

                if not retryable:
                    break

                if attempt < MAX_RETRIES:
                    retry_after = None

                    try:
                        retry_after = e.headers.get(
                            "Retry-After"
                        )
                    except Exception:
                        pass

                    if retry_after:
                        try:
                            delay = int(
                                float(
                                    retry_after
                                )
                            )
                        except Exception:
                            delay = (
                                INITIAL_BACKOFF
                                * (
                                    2
                                    ** (
                                        attempt - 1
                                    )
                                )
                            )
                    else:
                        delay = (
                            INITIAL_BACKOFF
                            * (
                                2
                                ** (
                                    attempt - 1
                                )
                            )
                        )

                    delay = min(
                        delay
                        + random.randint(0, 10),
                        MAX_BACKOFF,
                    )

                    print(
                        f"Retrying after {delay}s..."
                    )

                    time.sleep(delay)

            except Exception as e:
                last_error = str(e)

                print(
                    f"FAILED: {last_error}"
                )

                if attempt < MAX_RETRIES:
                    delay = min(
                        INITIAL_BACKOFF
                        * (
                            2
                            ** (
                                attempt - 1
                            )
                        )
                        + random.randint(0, 10),
                        MAX_BACKOFF,
                    )

                    print(
                        f"Retrying after {delay}s..."
                    )

                    time.sleep(delay)

        if not success:
            job["status"] = "failed"
            job["asset_path"] = None
            job["error"] = last_error

            update_manifest(
                jobs,
                provider,
                model,
                "incomplete",
            )

            print()
            print(
                "======================================"
            )
            print(
                "VISUAL GENERATION STOPPED"
            )
            print(
                f"Failed: Part {part} Scene {scene}"
            )
            print(
                "Checkpoint saved."
            )
            print(
                "======================================"
            )

            raise SystemExit(1)

    # FINAL HARD VALIDATION
    missing = []

    for job in jobs:
        path = visual_path(
            job["part"],
            job["scene"],
        )

        if not is_valid_image(path):
            missing.append(
                f"Part {job['part']} "
                f"Scene {job['scene']}"
            )

    print()
    print(
        "======================================"
    )
    print(
        "      FINAL VISUAL VALIDATION"
    )
    print(
        "======================================"
    )

    print(
        f"Expected: {total}"
    )

    print(
        f"Generated this run: {generated}"
    )

    print(
        f"Skipped/resumed: {skipped}"
    )

    print(
        f"Missing: {len(missing)}"
    )

    if missing:
        print()
        print(
            "MISSING VISUALS:"
        )

        for item in missing:
            print(
                f" - {item}"
            )

        update_manifest(
            jobs,
            provider,
            model,
            "incomplete",
        )

        raise SystemExit(
            "ERROR: Visual generation incomplete"
        )

    update_manifest(
        jobs,
        provider,
        model,
        "completed",
    )

    print()
    print(
        "STATUS: COMPLETED"
    )
    print(
        f"TOTAL VISUALS: {total}"
    )
    print(
        "ALL VISUAL ASSETS VERIFIED"
    )
    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
