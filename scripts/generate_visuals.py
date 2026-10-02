import os
import json
import base64
import time
import random
import urllib.request
import urllib.error
from datetime import datetime, timezone


ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")

VISUAL_JOBS_FILE = "output/visuals/visual_jobs.json"
SELECTED_MODEL_FILE = "output/config/selected_visual_model.json"
TOPIC_FILE = "Input/topic.txt"

MAX_RETRIES = 6

INITIAL_BACKOFF = 20
MAX_BACKOFF = 300

REQUEST_TIMEOUT = 180

BASE_URL = "https://api.cloudflare.com/client/v4/accounts"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(
        os.path.dirname(path),
        exist_ok=True,
    )

    temp = f"{path}.tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")

    os.replace(temp, path)


def get_topic():
    if not os.path.exists(TOPIC_FILE):
        return ""

    values = {}

    with open(
        TOPIC_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split(
                "=",
                1,
            )

            values[key.strip()] = (
                value.strip()
                .strip('"')
                .strip("'")
            )

    return values.get("TOPIC", "")


def api_request(model, payload):
    url = (
        f"{BASE_URL}/{ACCOUNT_ID}"
        f"/ai/run/{model}"
    )

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
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


def build_prompt(job, topic):
    parts = []

    if topic:
        parts.append(
            f"Story topic: {topic}"
        )

    if job.get("visual_prompt"):
        parts.append(
            "Visual scene: "
            f"{job['visual_prompt']}"
        )

    if job.get("camera_prompt"):
        parts.append(
            "Camera: "
            f"{job['camera_prompt']}"
        )

    if job.get("lighting_prompt"):
        parts.append(
            "Lighting: "
            f"{job['lighting_prompt']}"
        )

    parts.append(
        "Style: cinematic realistic, "
        "photorealistic, natural motion, "
        "realistic Indian environment, "
        "high detail, cinematic composition."
    )

    return "\n".join(parts)


def build_negative_prompt(job):
    negative = job.get(
        "negative_prompt",
        "",
    )

    defaults = (
        "cartoon, anime, illustration, "
        "neon, glitch, distorted face, "
        "deformed body, extra fingers, "
        "extra limbs, blurry, low quality, "
        "text, watermark, logo"
    )

    if negative:
        return (
            f"{negative}, {defaults}"
        )

    return defaults


def generate_image(model, job, topic):
    prompt = build_prompt(
        job,
        topic,
    )

    negative_prompt = (
        build_negative_prompt(job)
    )

    seed = (
        int(job["part"]) * 10000
        + int(job["scene"])
    )

    if "stable-diffusion-xl-lightning" in model:
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
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
                f"Negative prompt: "
                f"{negative_prompt}"
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

    image = extract_image(
        response
    )

    if not image:
        raise RuntimeError(
            "Cloudflare API returned "
            "no valid image"
        )

    return image


def get_output_file(part, scene):
    return (
        f"output/visuals/"
        f"part_{part:02d}/"
        f"scene_{scene:02d}.png"
    )


def is_valid_image(path):
    if not os.path.exists(path):
        return False

    if os.path.getsize(path) <= 0:
        return False

    try:
        with open(
            path,
            "rb",
        ) as f:
            header = f.read(8)

        return (
            header.startswith(b"\x89PNG")
            or header.startswith(b"\xff\xd8")
        )

    except Exception:
        return False


def save_job_checkpoint(
    data,
    job,
    provider,
    model,
    output_file,
    status,
    error=None,
):
    job["status"] = status
    job["provider"] = provider
    job["model"] = model
    job["asset_path"] = (
        output_file
        if status == "completed"
        else None
    )
    job["error"] = error

    if status == "completed":
        job["completed_at"] = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

    data["updated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    data["provider"] = provider
    data["model"] = model

    jobs = data.get(
        "jobs",
        [],
    )

    data["total_jobs"] = len(jobs)

    data["completed_jobs"] = sum(
        1
        for item in jobs
        if item.get("status")
        == "completed"
        and is_valid_image(
            get_output_file(
                int(item["part"]),
                int(item["scene"]),
            )
        )
    )

    data["failed_jobs"] = sum(
        1
        for item in jobs
        if item.get("status")
        == "failed"
    )

    data["pending_jobs"] = (
        data["total_jobs"]
        - data["completed_jobs"]
        - data["failed_jobs"]
    )

    save_json(
        VISUAL_JOBS_FILE,
        data,
    )


def validate_jobs(data):
    jobs = data.get("jobs")

    if not isinstance(jobs, list):
        raise RuntimeError(
            "visual_jobs.json does not contain "
            "a valid jobs list"
        )

    if not jobs:
        raise RuntimeError(
            "visual_jobs.json contains zero jobs"
        )

    seen = set()

    for job in jobs:
        if "part" not in job:
            raise RuntimeError(
                "Visual job missing part"
            )

        if "scene" not in job:
            raise RuntimeError(
                "Visual job missing scene"
            )

        part = int(job["part"])
        scene = int(job["scene"])

        if part <= 0 or scene <= 0:
            raise RuntimeError(
                "Invalid part/scene number"
            )

        key = (
            part,
            scene,
        )

        if key in seen:
            raise RuntimeError(
                "Duplicate visual job: "
                f"Part {part} Scene {scene}"
            )

        seen.add(key)

    return jobs


def validate_all_visuals(jobs):
    missing = []

    for job in jobs:
        part = int(job["part"])
        scene = int(job["scene"])

        path = get_output_file(
            part,
            scene,
        )

        if not is_valid_image(path):
            missing.append(
                f"Part {part} Scene {scene}"
            )

    return missing


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
            "ERROR: CLOUDFLARE_ACCOUNT_ID "
            "is not set"
        )

    if not API_TOKEN:
        raise SystemExit(
            "ERROR: CLOUDFLARE_API_TOKEN "
            "is not set"
        )

    if not os.path.exists(
        VISUAL_JOBS_FILE
    ):
        raise SystemExit(
            "ERROR: visual_jobs.json not found"
        )

    if not os.path.exists(
        SELECTED_MODEL_FILE
    ):
        raise SystemExit(
            "ERROR: selected_visual_model.json "
            "not found"
        )

    data = load_json(
        VISUAL_JOBS_FILE
    )

    selected = load_json(
        SELECTED_MODEL_FILE
    )

    jobs = validate_jobs(data)

    model = selected.get(
        "model"
    )

    provider = selected.get(
        "provider"
    )

    if provider != "cloudflare_workers_ai":
        raise SystemExit(
            "ERROR: Selected visual provider "
            f"is not Cloudflare: {provider}"
        )

    if not model:
        raise SystemExit(
            "ERROR: No visual model selected"
        )

    topic = get_topic()

    total = len(jobs)

    print(
        f"Provider: {provider}"
    )

    print(
        f"Model: {model}"
    )

    print(
        f"Expected visual jobs: {total}"
    )

    restored_completed = 0

    # First normalize existing jobs.
    for job in jobs:
        part = int(job["part"])
        scene = int(job["scene"])

        output_file = get_output_file(
            part,
            scene,
        )

        if is_valid_image(
            output_file
        ):
            job["status"] = "completed"
            job["asset_path"] = output_file
            job["provider"] = provider
            job["model"] = model
            job["error"] = None

            restored_completed += 1

    save_json(
        VISUAL_JOBS_FILE,
        data,
    )

    print(
        f"Existing valid visuals: "
        f"{restored_completed}/{total}"
    )

    generated_this_run = 0
    skipped = restored_completed

    for index, job in enumerate(
        jobs,
        start=1,
    ):
        part = int(job["part"])
        scene = int(job["scene"])

        output_file = get_output_file(
            part,
            scene,
        )

        os.makedirs(
            os.path.dirname(output_file),
            exist_ok=True,
        )

        # Never regenerate a valid existing image.
        if is_valid_image(
            output_file
        ):
            print(
                f"[{index}/{total}] "
                f"Part {part} Scene {scene} "
                f"VALID — SKIP"
            )
            continue

        print()
        print(
            f"[{index}/{total}] "
            f"Generating Part {part} "
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
                    f"Attempt {attempt}/"
                    f"{MAX_RETRIES}"
                )

                image = generate_image(
                    model,
                    job,
                    topic,
                )

                if not image:
                    raise RuntimeError(
                        "Empty image response"
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
                        os.remove(
                            temp_file
                        )
                    except OSError:
                        pass

                    raise RuntimeError(
                        "Generated file is not "
                        "a valid PNG/JPEG"
                    )

                os.replace(
                    temp_file,
                    output_file,
                )

                save_job_checkpoint(
                    data,
                    job,
                    provider,
                    model,
                    output_file,
                    "completed",
                    None,
                )

                generated_this_run += 1
                success = True

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

                retry_after = None

                try:
                    retry_after = e.headers.get(
                        "Retry-After"
                    )
                except Exception:
                    pass

                last_error = (
                    f"HTTP {e.code}: "
                    f"{e.reason}"
                )

                if body:
                    last_error += (
                        f" | {body[:500]}"
                    )

                print(
                    f"FAILED attempt {attempt}: "
                    f"{last_error}"
                )

                retryable = (
                    e.code == 429
                    or e.code >= 500
                )

                if not retryable:
                    break

                if attempt < MAX_RETRIES:
                    if retry_after:
                        try:
                            delay = min(
                                int(
                                    float(
                                        retry_after
                                    )
                                ),
                                MAX_BACKOFF,
                            )
                        except Exception:
                            delay = (
                                INITIAL_BACKOFF
                                * (
                                    2
                                    ** (
                                        attempt
                                        - 1
                                    )
                                )
                            )
                    else:
                        delay = min(
                            INITIAL_BACKOFF
                            * (
                                2
                                ** (
                                    attempt
                                    - 1
                                )
                            ),
                            MAX_BACKOFF,
                        )

                    jitter = random.randint(
                        0,
                        10,
                    )

                    delay = min(
                        delay + jitter,
                        MAX_BACKOFF,
                    )

                    print(
                        f"Retrying after "
                        f"{delay}s..."
                    )

                    time.sleep(delay)

            except Exception as e:
                last_error = str(e)

                print(
                    f"FAILED attempt {attempt}: "
                    f"{last_error}"
                )

                if attempt < MAX_RETRIES:
                    delay = min(
                        INITIAL_BACKOFF
                        * (
                            2
                            ** (
                                attempt
                                - 1
                            )
                        ),
                        MAX_BACKOFF,
                    )

                    jitter = random.randint(
                        0,
                        10,
                    )

                    delay = min(
                        delay + jitter,
                        MAX_BACKOFF,
                    )

                    print(
                        f"Retrying after "
                        f"{delay}s..."
                    )

                    time.sleep(delay)

        if not success:
            save_job_checkpoint(
                data,
                job,
                provider,
                model,
                output_file,
                "failed",
                last_error,
            )

            print()
            print(
                "======================================"
            )
            print(
                "VISUAL GENERATION STOPPED"
            )
            print(
                f"Failed: Part {part} "
                f"Scene {scene}"
            )
            print(
                "Checkpoint saved."
            )
            print(
                "======================================"
            )

            raise SystemExit(1)

    # Final hard validation.
    missing = validate_all_visuals(
        jobs
    )

    completed = (
        total - len(missing)
    )

    print()
    print(
        "===== FINAL VISUAL VALIDATION ====="
    )

    print(
        f"Expected: {total}"
    )

    print(
        f"Valid:    {completed}"
    )

    print(
        f"Missing:  {len(missing)}"
    )

    if missing:
        print(
            "Missing visuals:"
        )

        for item in missing:
            print(
                f" - {item}"
            )

        data["status"] = "incomplete"
        save_json(
            VISUAL_JOBS_FILE,
            data,
        )

        raise SystemExit(
            "ERROR: Visual generation "
            "is incomplete."
        )

    data["status"] = "completed"
    data["provider"] = provider
    data["model"] = model
    data["total_jobs"] = total
    data["completed_jobs"] = total
    data["pending_jobs"] = 0
    data["failed_jobs"] = 0
    data["updated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    save_json(
        VISUAL_JOBS_FILE,
        data,
    )

    print()
    print(
        "===== VISUAL GENERATION SUMMARY ====="
    )

    print(
        f"Total:              {total}"
    )

    print(
        f"Generated this run: {generated_this_run}"
    )

    print(
        f"Skipped/resumed:    {skipped}"
    )

    print(
        "Missing:             0"
    )

    print(
        f"Provider:            {provider}"
    )

    print(
        f"Model:               {model}"
    )

    print(
        "STATUS:              COMPLETED"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
