import os
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime, timezone


ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")

VISUAL_JOBS_FILE = "output/visuals/visual_jobs.json"
SELECTED_MODEL_FILE = "output/config/selected_visual_model.json"
TOPIC_FILE = "Input/topic.txt"

MAX_RETRIES = 3
BASE_URL = "https://api.cloudflare.com/client/v4/accounts"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
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
                value.strip().strip('"').strip("'")
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
        timeout=180,
    ) as response:
        return response.read()


def extract_image(response_bytes):
    if not response_bytes:
        return None

    # PNG
    if response_bytes.startswith(b"\x89PNG"):
        return response_bytes

    # JPEG
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
            f"Visual scene: "
            f"{job['visual_prompt']}"
        )

    if job.get("camera_prompt"):
        parts.append(
            f"Camera: "
            f"{job['camera_prompt']}"
        )

    if job.get("lighting_prompt"):
        parts.append(
            f"Lighting: "
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

    if "stable-diffusion-xl-lightning" in model:
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": 768,
            "height": 432,
            "num_steps": 4,
            "guidance": 7.5,
            "seed": (
                int(job["part"]) * 10000
                + int(job["scene"])
            ),
        }

    elif "flux-1-schnell" in model:
        payload = {
            "prompt": (
                f"{prompt}\n"
                f"Negative prompt: "
                f"{negative_prompt}"
            ),
            "steps": 4,
            "seed": (
                int(job["part"]) * 10000
                + int(job["scene"])
            ),
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
            "Cloudflare API returned no valid image"
        )

    return image


def validate_jobs(data):
    jobs = data.get("jobs")

    if not isinstance(jobs, list):
        raise RuntimeError(
            "visual_jobs.json does not contain a valid jobs list"
        )

    expected = 1

    for job in jobs:
        if "part" not in job:
            raise RuntimeError(
                "Visual job missing part"
            )

        if "scene" not in job:
            raise RuntimeError(
                "Visual job missing scene"
            )

        if int(job["scene"]) <= 0:
            raise RuntimeError(
                "Invalid scene number"
            )

        expected += 1


def main():
    print(
        "===== VISUAL GENERATION ====="
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
        VISUAL_JOBS_FILE
    ):
        raise SystemExit(
            "ERROR: visual_jobs.json not found"
        )

    if not os.path.exists(
        SELECTED_MODEL_FILE
    ):
        raise SystemExit(
            "ERROR: selected_visual_model.json not found"
        )

    data = load_json(
        VISUAL_JOBS_FILE
    )

    selected = load_json(
        SELECTED_MODEL_FILE
    )

    validate_jobs(data)

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

    jobs = data["jobs"]

    total = len(jobs)
    completed = 0
    skipped = 0
    failed = 0

    print(
        f"Provider: {provider}"
    )

    print(
        f"Model: {model}"
    )

    print(
        f"Total visual jobs: {total}"
    )

    for index, job in enumerate(
        jobs,
        start=1,
    ):
        part = int(job["part"])
        scene = int(job["scene"])

        output_dir = (
            f"output/visuals/"
            f"part_{part:02d}"
        )

        output_file = (
            f"{output_dir}/"
            f"scene_{scene:02d}.png"
        )

        os.makedirs(
            output_dir,
            exist_ok=True,
        )

        # Resume support
        if (
            job.get("status") == "completed"
            and os.path.exists(output_file)
            and os.path.getsize(output_file) > 0
        ):
            skipped += 1

            print(
                f"[{index}/{total}] "
                f"Part {part} Scene {scene} "
                f"already completed — SKIP"
            )

            continue

        print(
            f"\n[{index}/{total}] "
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

                temp_file = (
                    f"{output_file}.tmp"
                )

                with open(
                    temp_file,
                    "wb",
                ) as f:
                    f.write(image)

                os.replace(
                    temp_file,
                    output_file,
                )

                job["status"] = (
                    "completed"
                )
                job["provider"] = provider
                job["model"] = model
                job["asset_path"] = (
                    output_file
                )
                job["error"] = None
                job["completed_at"] = (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )

                save_json(
                    VISUAL_JOBS_FILE,
                    data,
                )

                completed += 1
                success = True

                print(
                    f"SUCCESS: "
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
                    f"HTTP {e.code}: "
                    f"{e.reason}. "
                    f"{body[:500]}"
                )

                print(
                    f"FAILED attempt "
                    f"{attempt}: "
                    f"{last_error}"
                )

            except Exception as e:
                last_error = str(e)

                print(
                    f"FAILED attempt "
                    f"{attempt}: "
                    f"{last_error}"
                )

        if not success:
            job["status"] = "failed"
            job["provider"] = provider
            job["model"] = model
            job["error"] = last_error

            save_json(
                VISUAL_JOBS_FILE,
                data,
            )

            failed += 1

            print(
                f"FAILED: Part {part} "
                f"Scene {scene}"
            )

            # Failure policy:
            # checkpoint immediately and stop.
            raise SystemExit(
                f"Visual generation stopped at "
                f"Part {part} Scene {scene}. "
                f"Checkpoint saved."
            )

    data["updated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    data["provider"] = provider
    data["model"] = model
    data["total_jobs"] = total
    data["completed_jobs"] = (
        sum(
            1
            for job in jobs
            if job.get("status")
            == "completed"
        )
    )
    data["failed_jobs"] = (
        sum(
            1
            for job in jobs
            if job.get("status")
            == "failed"
        )
    )

    save_json(
        VISUAL_JOBS_FILE,
        data,
    )

    print(
        "\n===== VISUAL GENERATION SUMMARY ====="
    )

    print(
        f"Total: {total}"
    )

    print(
        f"Generated this run: {completed}"
    )

    print(
        f"Skipped/resumed: {skipped}"
    )

    print(
        f"Failed: {failed}"
    )

    print(
        f"Provider: {provider}"
    )

    print(
        f"Model: {model}"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
