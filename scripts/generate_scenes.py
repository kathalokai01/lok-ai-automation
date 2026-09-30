#!/usr/bin/env python3

import json
import os
import time
import urllib.request
from pathlib import Path


AI_STORY = Path("output/story/ai_story.json")
CHARACTER_BIBLE = Path("output/story/character_bible.json")
OUTPUT = Path("output/scenes/scenes.json")
MODEL_FILE = Path("output/config/selected_model.json")

MAX_RETRIES = 3


def load_json(path):
    if not path.exists():
        raise SystemExit(f"ERROR: File not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise SystemExit(
            f"ERROR: Could not read JSON file {path}: {e}"
        )


def load_selected_model():
    config = load_json(MODEL_FILE)

    if config.get("status") != "selected":
        raise SystemExit(
            "ERROR: Gemini model selection is not in selected state"
        )

    model = config.get("model")

    if not model:
        raise SystemExit(
            "ERROR: No selected Gemini model found"
        )

    return model


def save_json(data):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    temp = OUTPUT.with_suffix(".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )
        f.write("\n")

    temp.replace(OUTPUT)


def build_scene_schema():
    return {
        "type": "object",
        "properties": {
            "part": {
                "type": "integer"
            },
            "scene": {
                "type": "integer"
            },
            "narration": {
                "type": "string"
            },
            "dialogue": {
                "type": "string"
            },
            "visual_prompt": {
                "type": "string"
            },
            "negative_prompt": {
                "type": "string"
            },
            "camera_prompt": {
                "type": "string"
            },
            "lighting_prompt": {
                "type": "string"
            },
            "sfx_prompt": {
                "type": "string"
            },
            "music_prompt": {
                "type": "string"
            },
            "duration": {
                "type": "number"
            }
        },
        "required": [
            "part",
            "scene",
            "narration",
            "dialogue",
            "visual_prompt",
            "negative_prompt",
            "camera_prompt",
            "lighting_prompt",
            "sfx_prompt",
            "music_prompt",
            "duration"
        ]
    }


def generate_scene(
    api_key,
    model,
    topic,
    part,
    scene,
    character_bible,
    previous_scene
):
    schema = {
        "type": "object",
        "properties": {
            "scene": build_scene_schema()
        },
        "required": [
            "scene"
        ]
    }

    prompt = f"""
You are the scene-generation AI for an automated Hindi cinematic
storytelling pipeline.

Generate the complete production-ready content for ONE scene.

STORY TOPIC:
{topic}

PART:
{part.get("part")}

SCENE:
{scene.get("scene")}

SCENE ROLE:
{scene.get("role", "")}

CURRENT SCENE NARRATION:
{scene.get("narration", "")}

CURRENT SCENE DIALOGUE:
{scene.get("dialogue", "")}

CURRENT VISUAL PROMPT:
{scene.get("visual_prompt", "")}

CURRENT NEGATIVE PROMPT:
{scene.get("negative_prompt", "")}

CURRENT CAMERA PROMPT:
{scene.get("camera_prompt", "")}

CURRENT LIGHTING PROMPT:
{scene.get("lighting_prompt", "")}

CURRENT SFX PROMPT:
{scene.get("sfx_prompt", "")}

CURRENT MUSIC PROMPT:
{scene.get("music_prompt", "")}

CHARACTER BIBLE:
{json.dumps(character_bible, ensure_ascii=False, indent=2)}

PREVIOUS SCENE CONTEXT:
{json.dumps(previous_scene, ensure_ascii=False, indent=2)}

IMPORTANT:
- Preserve the story meaning.
- Maintain character consistency using the Character Bible.
- Maintain world and location consistency.
- Maintain continuity with the previous scene.
- Keep the same characters visually consistent.
- Narration must be natural Hindi.
- Dialogue must be natural Hindi.
- Visual prompts must be realistic cinematic visual descriptions.
- Avoid cartoon, anime and artificial-looking visuals.
- Camera prompts must specify useful cinematic framing or movement.
- Lighting must remain physically realistic.
- SFX must match the scene.
- Music must match the emotional tone.
- Duration must be a realistic number of seconds.
- Do not change the part number.
- Do not change the scene number.
- Do not introduce unnecessary characters.
- Do not add watermarks, logos, text overlays or subtitles to visuals.
- Avoid neon, glitch effects and unrealistic lighting.
- Preserve natural human motion and realistic anatomy.
- Return ONLY the requested JSON structure.
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
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }

    api_url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent"
    )

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            print(
                f"Generating Part {part.get('part')} "
                f"Scene {scene.get('scene')} "
                f"(attempt {attempt}/{MAX_RETRIES}) "
                f"using model {model}..."
            )

            request = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key
                },
                method="POST"
            )

            with urllib.request.urlopen(
                request,
                timeout=120
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            candidates = result.get("candidates", [])

            if not candidates:
                raise ValueError(
                    "Gemini returned no candidates"
                )

            parts = (
                candidates[0]
                .get("content", {})
                .get("parts", [])
            )

            if not parts:
                raise ValueError(
                    "Gemini returned no response parts"
                )

            text = parts[0].get("text", "").strip()

            if not text:
                raise ValueError(
                    "Gemini returned an empty response"
                )

            generated = json.loads(text)

            result_scene = generated.get("scene")

            if not isinstance(result_scene, dict):
                raise ValueError(
                    "Gemini returned an invalid scene object"
                )

            expected_part = part.get("part")
            expected_scene = scene.get("scene")

            if result_scene.get("part") != expected_part:
                raise ValueError(
                    "Gemini returned incorrect part number"
                )

            if result_scene.get("scene") != expected_scene:
                raise ValueError(
                    "Gemini returned incorrect scene number"
                )

            return result_scene

        except Exception as e:

            last_error = e

            print(
                f"Scene generation failed: {e}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(3)

    raise SystemExit(
        f"ERROR: Part {part.get('part')} "
        f"Scene {scene.get('scene')} failed after "
        f"{MAX_RETRIES} attempts: {last_error}"
    )


api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    raise SystemExit(
        "ERROR: GEMINI_API_KEY is not set"
    )


MODEL = load_selected_model()

print("===== GEMINI MODEL =====")
print(f"Selected model: {MODEL}")
print("========================")


story = load_json(AI_STORY)
character_bible = load_json(CHARACTER_BIBLE)

if story.get("status") != "completed":
    raise SystemExit(
        "ERROR: AI story is not in completed state"
    )

if not character_bible.get("characters"):
    raise SystemExit(
        "ERROR: Character Bible contains no characters"
    )


topic = str(
    story.get("topic", "")
).strip()

if not topic:
    raise SystemExit(
        "ERROR: Story topic is empty"
    )


scenes_output = {
    "status": "in_progress",
    "topic": topic,
    "model": MODEL,
    "scenes": []
}


if OUTPUT.exists():

    try:
        existing = load_json(OUTPUT)

        if existing.get("topic") == topic:
            scenes_output = existing
            scenes_output["model"] = MODEL

            print(
                "Existing scenes found. Resuming..."
            )

    except Exception:

        print(
            "Existing scenes file is invalid. "
            "Starting fresh."
        )


all_parts = story.get("parts", [])

completed_map = {
    (
        item.get("part"),
        item.get("scene")
    ): item
    for item in scenes_output.get("scenes", [])
    if item.get("status") == "completed"
}


previous_scene = None


for part in all_parts:

    for scene in part.get("scenes", []):

        part_number = part.get("part")
        scene_number = scene.get("scene")

        key = (
            part_number,
            scene_number
        )

        if key in completed_map:

            completed = completed_map[key]

            print(
                f"Part {part_number} "
                f"Scene {scene_number} "
                f"already completed. Skipping."
            )

            previous_scene = completed
            continue

        generated = generate_scene(
            api_key=api_key,
            model=MODEL,
            topic=topic,
            part=part,
            scene=scene,
            character_bible=character_bible,
            previous_scene=previous_scene
        )

        completed_scene = {
            "part": part_number,
            "scene": scene_number,
            "status": "completed",
            "narration": generated["narration"],
            "dialogue": generated["dialogue"],
            "visual_prompt": generated["visual_prompt"],
            "negative_prompt": generated["negative_prompt"],
            "camera_prompt": generated["camera_prompt"],
            "lighting_prompt": generated["lighting_prompt"],
            "sfx_prompt": generated["sfx_prompt"],
            "music_prompt": generated["music_prompt"],
            "duration": generated["duration"]
        }

        scenes_output["scenes"] = [
            item
            for item in scenes_output.get("scenes", [])
            if not (
                item.get("part") == part_number
                and item.get("scene") == scene_number
            )
        ]

        scenes_output["scenes"].append(
            completed_scene
        )

        scenes_output["scenes"].sort(
            key=lambda item: (
                item.get("part", 0),
                item.get("scene", 0)
            )
        )

        scenes_output["status"] = "in_progress"
        scenes_output["model"] = MODEL

        save_json(scenes_output)

        previous_scene = completed_scene

        print(
            f"Part {part_number} "
            f"Scene {scene_number} completed and saved."
        )


scenes_output["status"] = "completed"
scenes_output["model"] = MODEL

save_json(scenes_output)


print("===================================")
print("SCENE GENERATION COMPLETED")
print(f"Topic: {topic}")
print(f"Model: {MODEL}")
print(f"Scenes: {len(scenes_output['scenes'])}")
print(f"Output: {OUTPUT}")
print("===================================")
