import os
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime, timezone


ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")

OUTPUT_FILE = "output/config/selected_visual_model.json"

BASE_URL = "https://api.cloudflare.com/client/v4/accounts"

VISUAL_MODELS = [
    {
        "model": "@cf/bytedance/stable-diffusion-xl-lightning",
        "display_name": "Stable Diffusion XL Lightning",
        "priority": 0,
    },
    {
        "model": "@cf/black-forest-labs/flux-1-schnell",
        "display_name": "FLUX.1 Schnell",
        "priority": 10,
    },
]


def api_request(model, payload, timeout=180):
    url = (
        f"{BASE_URL}/{ACCOUNT_ID}"
        f"/ai/run/{model}"
    )

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return response.read()


def extract_image(response_bytes):
    """
    Cloudflare image responses can be returned as
    raw image bytes or JSON containing base64 data.
    """

    if not response_bytes:
        return None

    # Direct image response
    if response_bytes.startswith(b"\x89PNG"):
        return response_bytes

    if response_bytes.startswith(b"\xff\xd8"):
        return response_bytes

    # JSON response
    try:
        result = json.loads(
            response_bytes.decode("utf-8")
        )
    except Exception:
        return None

    if not isinstance(result, dict):
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


def test_model(model_info):
    model = model_info["model"]

    prompt = (
        "A cinematic realistic Indian village road "
        "at dusk, natural lighting, realistic "
        "environment, detailed photography, "
        "dramatic atmosphere, no text."
    )

    if "stable-diffusion-xl-lightning" in model:
        payload = {
            "prompt": prompt,
            "negative_prompt": (
                "cartoon, anime, illustration, "
                "neon, glitch, distorted, blurry, "
                "text, watermark, logo"
            ),
            "width": 768,
            "height": 432,
            "num_steps": 4,
            "guidance": 7.5,
            "seed": 123456,
        }

    else:
        payload = {
            "prompt": prompt,
            "steps": 4,
            "seed": 123456,
        }

    try:
        response = api_request(
            model,
            payload,
        )

        image_bytes = extract_image(
            response
        )

        if not image_bytes:
            return (
                False,
                "API returned no valid image data",
            )

        return (
            True,
            "IMAGE_GENERATION_OK",
        )

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            body = ""

        return (
            False,
            f"HTTP {e.code}: "
            f"{e.reason}. "
            f"{body[:500]}",
        )

    except Exception as e:
        return (
            False,
            str(e),
        )


def save_selection(
    model_info,
    tested_models,
):
    os.makedirs(
        os.path.dirname(OUTPUT_FILE),
        exist_ok=True,
    )

    result = {
        "status": "selected",
        "provider": "cloudflare_workers_ai",
        "model": model_info["model"],
        "display_name": model_info[
            "display_name"
        ],
        "selected_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "tested_models": tested_models,
    }

    temp_file = (
        f"{OUTPUT_FILE}.tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")

    os.replace(
        temp_file,
        OUTPUT_FILE,
    )

    return result


def main():
    print(
        "===== CLOUDFLARE VISUAL MODEL SELECTION ====="
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

    print(
        "Cloudflare credentials detected."
    )

    tested_models = []

    models = sorted(
        VISUAL_MODELS,
        key=lambda item: item[
            "priority"
        ],
    )

    print(
        "\n===== MODEL PRIORITY ====="
    )

    for index, model in enumerate(
        models,
        start=1,
    ):
        print(
            f"{index}. "
            f"{model['model']}"
        )

    print(
        "=========================="
    )

    for model_info in models:
        model = model_info[
            "model"
        ]

        print(
            f"\nTesting model: {model}"
        )

        success, detail = test_model(
            model_info
        )

        tested_models.append(
            {
                "model": model,
                "success": success,
                "detail": detail[:500],
            }
        )

        if success:
            selected = save_selection(
                model_info,
                tested_models,
            )

            print(
                "\n===== VISUAL MODEL SELECTED ====="
            )

            print(
                f"Provider: "
                f"{selected['provider']}"
            )

            print(
                f"Model: "
                f"{selected['model']}"
            )

            print(
                f"Saved to: "
                f"{OUTPUT_FILE}"
            )

            print(
                "=================================="
            )

            return

        print(
            f"FAILED: {model}"
        )

        print(
            f"Reason: {detail[:500]}"
        )

        print(
            "Trying next model..."
        )

    print(
        "\n===== ALL VISUAL MODELS FAILED ====="
    )

    for item in tested_models:
        print(
            f"- {item['model']}: "
            f"{item['detail']}"
        )

    raise SystemExit(1)


if __name__ == "__main__":
    main()
