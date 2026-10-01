import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone


API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    raise SystemExit("ERROR: GEMINI_API_KEY is not set")


BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
OUTPUT_FILE = "output/config/selected_visual_model.json"


def api_request(url, method="GET", payload=None, timeout=90):
    headers = {
        "x-goog-api-key": API_KEY,
        "Content-Type": "application/json",
    }

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def get_available_visual_models():
    url = f"{BASE_URL}/models"

    result = api_request(url)

    models = []

    for model in result.get("models", []):
        name = model.get("name", "")
        methods = model.get(
            "supportedGenerationMethods",
            [],
        )

        if not name:
            continue

        if "generateContent" not in methods:
            continue

        if not name.startswith("models/"):
            continue

        model_id = name.split("/", 1)[1]
        lower = model_id.lower()

        # Image-generation Gemini models are explicitly
        # identified by "image" in the model ID.
        if "gemini" not in lower:
            continue

        if "image" not in lower:
            continue

        # Exclude unrelated image/vision-only naming variants.
        if any(
            word in lower
            for word in (
                "embedding",
                "vision",
                "audio",
                "tts",
            )
        ):
            continue

        models.append(
            {
                "name": name,
                "model_id": model_id,
                "display_name": model.get(
                    "displayName",
                    "",
                ),
                "methods": methods,
            }
        )

    return models


def model_priority(model):
    model_id = model["model_id"].lower()

    # Current high-volume Nano Banana 2 model.
    if model_id == "gemini-3.1-flash-image":
        return 0

    # Current Lite image model.
    if model_id == "gemini-3.1-flash-lite-image":
        return 5

    # Older Flash image generation model.
    if model_id == "gemini-2.5-flash-image":
        return 10

    # Other Flash image models.
    if "flash" in model_id and "image" in model_id:
        return 20

    # Other Gemini image models.
    if "gemini" in model_id and "image" in model_id:
        return 30

    return 100


def test_visual_model(model):
    model_id = model["model_id"]

    url = (
        f"{BASE_URL}/models/"
        f"{model_id}:generateContent"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Generate a simple cinematic "
                            "realistic image of an empty "
                            "Indian village road at dusk."
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": [
                "IMAGE"
            ],
        },
    }

    try:
        result = api_request(
            url,
            method="POST",
            payload=payload,
            timeout=120,
        )

        candidates = result.get(
            "candidates",
            [],
        )

        if not candidates:
            return False, "No candidates returned"

        content = candidates[0].get(
            "content",
            {},
        )

        parts = content.get(
            "parts",
            [],
        )

        if not parts:
            return False, "No response parts returned"

        image_found = False

        for part in parts:
            inline_data = part.get(
                "inlineData"
            )

            if inline_data:
                mime_type = inline_data.get(
                    "mimeType",
                    "",
                )

                data = inline_data.get(
                    "data",
                    "",
                )

                if data and mime_type.startswith(
                    "image/"
                ):
                    image_found = True
                    break

        if not image_found:
            return (
                False,
                "API returned no image data",
            )

        return (
            True,
            "IMAGE_GENERATION_OK",
        )

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode(
                "utf-8"
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
        return False, str(e)


def save_selection(
    model,
    tested_models,
):
    os.makedirs(
        os.path.dirname(
            OUTPUT_FILE
        ),
        exist_ok=True,
    )

    result = {
        "status": "selected",
        "provider": "gemini",
        "model": model["model_id"],
        "model_resource": model["name"],
        "display_name": model.get(
            "display_name",
            "",
        ),
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
        "===== GEMINI VISUAL MODEL DISCOVERY ====="
    )

    print(
        "Fetching available image-generation models..."
    )

    try:
        models = (
            get_available_visual_models()
        )

    except urllib.error.HTTPError as e:
        raise SystemExit(
            "ERROR: Failed to list Gemini "
            f"models: HTTP {e.code} "
            f"{e.reason}"
        )

    except Exception as e:
        raise SystemExit(
            "ERROR: Failed to list Gemini "
            f"visual models: {e}"
        )

    if not models:
        raise SystemExit(
            "ERROR: No Gemini image-generation "
            "models were found for this API key."
        )

    models.sort(
        key=model_priority
    )

    print(
        f"Visual models found: "
        f"{len(models)}"
    )

    print(
        "\n===== VISUAL MODEL PRIORITY ====="
    )

    for index, model in enumerate(
        models,
        start=1,
    ):
        print(
            f"{index}. "
            f"{model['model_id']}"
        )

    print(
        "================================="
    )

    tested_models = []

    for model in models:
        model_id = model[
            "model_id"
        ]

        print(
            f"\nTesting visual model: "
            f"{model_id}"
        )

        success, detail = (
            test_visual_model(model)
        )

        tested_models.append(
            {
                "model": model_id,
                "success": success,
                "detail": detail[:500],
            }
        )

        if success:
            selected = save_selection(
                model,
                tested_models,
            )

            print(
                "\n===== VISUAL MODEL SELECTED ====="
            )

            print(
                f"Selected model: "
                f"{selected['model']}"
            )

            print(
                f"Provider: "
                f"{selected['provider']}"
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
            f"FAILED: {model_id}"
        )

        print(
            f"Reason: {detail[:500]}"
        )

        print(
            "Trying next visual model..."
        )

    print(
        "\n===== VISUAL MODEL SELECTION FAILED ====="
    )

    print(
        "All discovered Gemini image-generation "
        "models failed the live image test."
    )

    raise SystemExit(1)


if __name__ == "__main__":
    main()
