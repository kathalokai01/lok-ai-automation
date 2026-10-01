import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone


API_KEY = os.environ.get("GEMINI_API_KEY")

AI_STORY_FILE = "output/story/ai_story.json"
MODEL_FILE = "output/config/selected_model.json"
OUTPUT_FILE = "output/narration/narration.json"

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

MAX_RETRIES = 3


if not API_KEY:
    raise SystemExit("ERROR: GEMINI_API_KEY is not set")


def load_json(path):
    if not os.path.isfile(path):
        raise SystemExit(
            f"ERROR: Required file not found: {path}"
        )

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        raise SystemExit(
            f"ERROR: Could not read {path}: {e}"
        )


def save_json_atomic(path, data):
    os.makedirs(
        os.path.dirname(path),
        exist_ok=True,
    )

    temp_file = f"{path}.tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")

    os.replace(temp_file, path)


def api_request(url, payload, timeout=120):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": API_KEY,
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def extract_response_text(result):
    candidates = result.get("candidates", [])

    if not candidates:
        raise ValueError(
            "No candidates returned"
        )

    content = candidates[0].get(
        "content",
        {},
    )

    parts = content.get(
        "parts",
        [],
    )

    if not parts:
        raise ValueError(
            "No response parts returned"
        )

    text = parts[0].get(
        "text",
        "",
    ).strip()

    if not text:
        raise ValueError(
            "Empty model response"
        )

    return text


def clean_json_text(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return text


def generate_scene_narration(
    model,
    scene,
    config,
):
    model_url = (
        f"{BASE_URL}/models/"
        f"{model}:generateContent"
    )

    part = scene.get("part")
    scene_number = scene.get("scene")

    source_narration = scene.get(
        "narration",
        "",
    )

    dialogue = scene.get(
        "dialogue",
        "",
    )

    duration = scene.get(
        "duration",
        "auto",
    )

    voice = config.get(
        "VOICE",
        "male",
    )

    speed = config.get(
        "SPEED",
        "+0%",
    )

    prompt = f"""
You are preparing narration text for an AI-generated Hindi story video.

Return ONLY valid JSON.
Do not use markdown.
Do not add explanations.

Create the final narration for this scene.

Requirements:
- Preserve the story meaning.
- Use natural spoken Hindi.
- Keep narration cinematic and emotionally appropriate.
- Do not invent new plot events.
- Do not repeat dialogue unnecessarily.
- If dialogue is already present, narration should complement it.
- Do not include speaker labels unless they are necessary.
- Do not include stage directions.
- Do not include sound effects.
- Do not include camera instructions.
- Keep the narration suitable for text-to-speech.
- Respect the requested scene duration.
- Voice setting: {voice}
- Speed setting: {speed}

Part: {part}
Scene: {scene_number}
Scene duration: {duration}

Source narration:
{source_narration}

Dialogue:
{dialogue}

Return exactly this JSON structure:

{{
  "text": "final spoken narration text",
  "estimated_duration": "scene duration"
}}
"""

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
            "temperature": 0.2,
            "maxOutputTokens": 1200,
            "responseMimeType": "application/json",
        },
    }

    result = api_request(
        model_url,
        payload,
        timeout=120,
    )

    response_text = extract_response_text(
        result
    )

    response_text = clean_json_text(
        response_text
    )

    generated = json.loads(
        response_text
    )

    if not isinstance(generated, dict):
        raise ValueError(
            "Narration response is not an object"
        )

    text = generated.get(
        "text",
        "",
    )

    if not isinstance(text, str):
        raise ValueError(
            "Narration text is not a string"
        )

    text = text.strip()

    if not text:
        raise ValueError(
            "Generated narration text is empty"
        )

    estimated_duration = generated.get(
        "estimated_duration",
        duration,
    )

    return {
        "part": part,
        "scene": scene_number,
        "text": text,
        "voice": voice,
        "speed": speed,
        "duration": duration,
        "estimated_duration": estimated_duration,
        "status": "completed",
    }


def validate_scene_numbers(
    narration_scenes,
    expected_scenes,
):
    expected_keys = {
        (
            scene.get("part"),
            scene.get("scene"),
        )
        for scene in expected_scenes
    }

    actual_keys = {
        (
            scene.get("part"),
            scene.get("scene"),
        )
        for scene in narration_scenes
    }

    missing = sorted(
        expected_keys - actual_keys
    )

    duplicates = (
        len(narration_scenes)
        != len(actual_keys)
    )

    if missing:
        raise ValueError(
            f"Missing narration scenes: {missing}"
        )

    if duplicates:
        raise ValueError(
            "Duplicate narration scene numbers found"
        )


def load_config():
    config_file = "Input/topic.txt"

    if not os.path.isfile(config_file):
        raise SystemExit(
            f"ERROR: Configuration file not found: "
            f"{config_file}"
        )

    config = {}

    with open(
        config_file,
        "r",
        encoding="utf-8",
    ) as file:

        for raw_line in file:
            line = raw_line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split(
                "=",
                1,
            )

            config[key.strip()] = (
                value.strip()
                .strip('"')
                .strip("'")
            )

    return config


def main():

    print(
        "===== NARRATION GENERATION ====="
    )

    ai_story = load_json(
        AI_STORY_FILE
    )

    model_config = load_json(
        MODEL_FILE
    )

    config = load_config()

    if ai_story.get("status") != "completed":
        raise SystemExit(
            "ERROR: AI story is not completed"
        )

    if model_config.get("status") != "selected":
        raise SystemExit(
            "ERROR: Gemini model is not selected"
        )

    model = model_config.get("model")

    if not model:
        raise SystemExit(
            "ERROR: No selected Gemini model found"
        )

    topic = ai_story.get(
        "topic",
        config.get("TOPIC", ""),
    )

    parts = ai_story.get(
        "parts",
        [],
    )

    expected_scenes = []

    for part_data in parts:

        part_number = part_data.get(
            "part"
        )

        scenes = part_data.get(
            "scenes",
            [],
        )

        for scene in scenes:

            scene_copy = dict(scene)

            scene_copy["part"] = (
                part_number
            )

            expected_scenes.append(
                scene_copy
            )

    if not expected_scenes:
        raise SystemExit(
            "ERROR: No scenes found in AI story"
        )

    print(
        f"Selected Gemini model: {model}"
    )

    print(
        f"Total scenes: "
        f"{len(expected_scenes)}"
    )

    existing = None

    if os.path.isfile(OUTPUT_FILE):

        try:
            existing = load_json(
                OUTPUT_FILE
            )
        except SystemExit:
            existing = None

    narration_map = {}

    if (
        existing
        and existing.get("status")
        in (
            "in_progress",
            "completed",
        )
    ):

        for item in existing.get(
            "scenes",
            [],
        ):

            key = (
                item.get("part"),
                item.get("scene"),
            )

            if (
                item.get("status")
                == "completed"
                and item.get("text")
            ):
                narration_map[key] = item

        print(
            f"Resuming existing narration: "
            f"{len(narration_map)} scenes"
        )

    output = {
        "status": "in_progress",
        "topic": topic,
        "model": model,
        "total_parts": len(parts),
        "total_scenes": len(
            expected_scenes
        ),
        "voice": config.get(
            "VOICE",
            "male",
        ),
        "speed": config.get(
            "SPEED",
            "+0%",
        ),
        "scenes": [],
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    save_json_atomic(
        OUTPUT_FILE,
        output,
    )

    for index, scene in enumerate(
        expected_scenes,
        start=1,
    ):

        part = scene.get("part")
        scene_number = scene.get("scene")

        key = (
            part,
            scene_number,
        )

        if key in narration_map:

            print(
                f"[{index}/{len(expected_scenes)}] "
                f"Skipping completed "
                f"Part {part} Scene {scene_number}"
            )

            continue

        print(
            f"\n[{index}/{len(expected_scenes)}] "
            f"Generating narration "
            f"Part {part} Scene {scene_number}"
        )

        last_error = None
        generated = None

        for attempt in range(
            1,
            MAX_RETRIES + 1,
        ):

            try:

                print(
                    f"Attempt {attempt}/"
                    f"{MAX_RETRIES}"
                )

                generated = (
                    generate_scene_narration(
                        model,
                        scene,
                        config,
                    )
                )

                break

            except urllib.error.HTTPError as e:

                try:
                    body = (
                        e.read()
                        .decode("utf-8")
                    )
                except Exception:
                    body = ""

                last_error = (
                    f"HTTP {e.code}: "
                    f"{e.reason}. "
                    f"{body[:500]}"
                )

                print(
                    f"FAILED: {last_error}"
                )

            except Exception as e:

                last_error = str(e)

                print(
                    f"FAILED: {last_error}"
                )

        if generated is None:

            print(
                "\nERROR: Narration generation "
                "failed."
            )

            print(
                f"Part: {part}, "
                f"Scene: {scene_number}"
            )

            print(
                f"Reason: {last_error}"
            )

            output["scenes"] = sorted(
                narration_map.values(),
                key=lambda item: (
                    item.get("part", 0),
                    item.get("scene", 0),
                ),
            )

            output["last_completed"] = (
                output["scenes"][-1]
                if output["scenes"]
                else None
            )

            save_json_atomic(
                OUTPUT_FILE,
                output,
            )

            raise SystemExit(1)

        narration_map[key] = generated

        output["scenes"] = sorted(
            narration_map.values(),
            key=lambda item: (
                item.get("part", 0),
                item.get("scene", 0),
            ),
        )

        output["last_completed"] = (
            generated
        )

        # Checkpoint after every scene.
        save_json_atomic(
            OUTPUT_FILE,
            output,
        )

        print(
            f"Completed: "
            f"Part {part} Scene {scene_number}"
        )

    final_scenes = sorted(
        narration_map.values(),
        key=lambda item: (
            item.get("part", 0),
            item.get("scene", 0),
        ),
    )

    validate_scene_numbers(
        final_scenes,
        expected_scenes,
    )

    if len(final_scenes) != len(
        expected_scenes
    ):
        raise SystemExit(
            "ERROR: Final narration scene "
            "count does not match AI story"
        )

    output["status"] = "completed"
    output["scenes"] = final_scenes
    output["total_scenes"] = len(
        final_scenes
    )
    output["completed_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    save_json_atomic(
        OUTPUT_FILE,
        output,
    )

    print(
        "\n===== NARRATION GENERATION "
        "COMPLETED ====="
    )

    print(
        f"Scenes generated: "
        f"{len(final_scenes)}"
    )

    print(
        f"Model: {model}"
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
