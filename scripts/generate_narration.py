import os
import json
from datetime import datetime, timezone


AI_STORY_FILE = "output/story/ai_story.json"
MODEL_FILE = "output/config/selected_model.json"
OUTPUT_FILE = "output/narration/narration.json"
CONFIG_FILE = "Input/topic.txt"


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


def load_config():
    if not os.path.isfile(CONFIG_FILE):
        raise SystemExit(
            f"ERROR: Configuration file not found: {CONFIG_FILE}"
        )

    config = {}

    with open(
        CONFIG_FILE,
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

    if missing:
        raise ValueError(
            f"Missing narration scenes: {missing}"
        )

    if len(narration_scenes) != len(actual_keys):
        raise ValueError(
            "Duplicate narration scene numbers found"
        )


def build_narration_scene(
    scene,
    config,
):
    part = scene.get("part")
    scene_number = scene.get("scene")

    text = scene.get(
        "narration",
        "",
    )

    if not isinstance(text, str):
        raise ValueError(
            f"Narration is not text for "
            f"Part {part} Scene {scene_number}"
        )

    text = text.strip()

    if not text:
        raise ValueError(
            f"Empty narration found for "
            f"Part {part} Scene {scene_number}"
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

    return {
        "part": part,
        "scene": scene_number,
        "text": text,
        "voice": voice,
        "speed": speed,
        "duration": duration,
        "estimated_duration": duration,
        "status": "completed",
    }


def main():

    print(
        "===== NARRATION PREPARATION ====="
    )

    print(
        "No Gemini API call will be made."
    )

    print(
        "Narration will be taken directly "
        "from ai_story.json."
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

    model = model_config.get(
        "model",
        "",
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
        f"Selected model metadata: {model}"
    )

    print(
        f"Total parts: {len(parts)}"
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

    if existing:
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

        if narration_map:
            print(
                f"Existing completed scenes: "
                f"{len(narration_map)}"
            )

    output = {
        "status": "in_progress",
        "topic": topic,
        "model": model,
        "api_calls": 0,
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
            f"Preparing narration "
            f"Part {part} Scene {scene_number}"
        )

        generated = build_narration_scene(
            scene,
            config,
        )

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
    output["api_calls"] = 0
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
        "\n===== NARRATION PREPARATION "
        "COMPLETED ====="
    )

    print(
        f"Scenes prepared: "
        f"{len(final_scenes)}"
    )

    print(
        "Gemini API calls: 0"
    )

    print(
        f"Model metadata: {model}"
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
