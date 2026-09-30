#!/usr/bin/env python3

import json
import os
import time
import urllib.request
from pathlib import Path


INPUT = Path("output/story/story.json")
OUTPUT = Path("output/story/ai_story.json")
MODEL_FILE = Path("output/config/selected_model.json")

MAX_RETRIES = 3


def load_json(path):
    if not path.exists():
        raise SystemExit(f"ERROR: File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


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

    temp.replace(OUTPUT)


def generate_part(api_key, model, topic, part):

    scenes = part.get("scenes", [])

    scene_context = []

    for scene in scenes:
        scene_context.append({
            "scene": scene["scene"],
            "role": scene.get("role", "")
        })

    scene_schema = {
        "type": "object",
        "properties": {
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
            }
        },
        "required": [
            "scene",
            "narration",
            "dialogue",
            "visual_prompt",
            "negative_prompt",
            "camera_prompt",
            "lighting_prompt",
            "sfx_prompt",
            "music_prompt"
        ]
    }

    schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "items": scene_schema
            }
        },
        "required": [
            "scenes"
        ]
    }

    prompt = f"""
You are the main story-generation AI for an automated Hindi cinematic
storytelling pipeline.

Create the complete content for PART {part["part"]} of this story.

STORY TOPIC:
{topic}

PART:
{part["part"]}

SCENE REQUIREMENTS:
{json.dumps(scene_context, ensure_ascii=False, indent=2)}

IMPORTANT:
- Write the narration in natural Hindi.
- Dialogue should be in Hindi.
- Keep the story coherent across all scenes.
- Maintain character consistency.
- Maintain world and location consistency.
- Maintain scene-to-scene continuity.
- Build suspense progressively.
- Follow the scene roles exactly.
- Make the storytelling cinematic and emotionally engaging.
- Do not use cartoon or anime language.
- Visual prompts must describe realistic cinematic visuals.
- Camera prompts must describe cinematic camera movement and framing.
- Lighting prompts must describe realistic cinematic lighting.
- SFX prompts must describe appropriate sound effects.
- Music prompts must describe appropriate cinematic background music.
- Negative prompts must prevent cartoon, anime, distorted anatomy,
  extra limbs, text artifacts, watermarks, neon/glitch appearance,
  unrealistic lighting and other unwanted visual artifacts.
- Do not change scene numbers.
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

    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        },
        method="POST"
    )

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            print(
                f"Generating Part {part['part']} "
                f"(attempt {attempt}/{MAX_RETRIES}) "
                f"using model {model}..."
            )

            with urllib.request.urlopen(
                request,
                timeout=120
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            text = (
                result["candidates"][0]
                ["content"]["parts"][0]["text"]
            )

            generated = json.loads(text)

            generated_scenes = generated.get(
                "scenes",
                []
            )

            if len(generated_scenes) != len(scenes):
                raise ValueError(
                    f"Expected {len(scenes)} scenes, "
                    f"received {len(generated_scenes)}"
                )

            expected_numbers = [
                scene["scene"]
                for scene in scenes
            ]

            actual_numbers = [
                scene.get("scene")
                for scene in generated_scenes
            ]

            if actual_numbers != expected_numbers:
                raise ValueError(
                    "Gemini returned incorrect scene numbers"
                )

            return generated_scenes

        except Exception as e:

            last_error = e

            print(
                f"Part {part['part']} generation failed: {e}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(3)

    raise SystemExit(
        f"ERROR: Part {part['part']} failed after "
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


story = load_json(INPUT)

topic = str(
    story.get("topic", "")
).strip()

if not topic:
    raise SystemExit(
        "ERROR: Story topic is empty"
    )


ai_story = {
    "status": "generating",
    "topic": topic,
    "model": MODEL,
    "parts": []
}


if OUTPUT.exists():

    try:

        existing = load_json(OUTPUT)

        if (
            existing.get("topic") == topic
            and existing.get("parts")
        ):
            ai_story = existing

            # Always record the currently selected model.
            ai_story["model"] = MODEL

            print(
                "Existing AI story found. Resuming..."
            )

    except Exception:

        print(
            "Existing AI story is invalid. "
            "Starting fresh."
        )


for part in story.get("parts", []):

    part_number = part["part"]

    existing_part = next(
        (
            p
            for p in ai_story.get("parts", [])
            if p.get("part") == part_number
        ),
        None
    )

    if existing_part and all(
        scene.get("status") == "completed"
        for scene in existing_part.get("scenes", [])
    ):
        print(
            f"Part {part_number} already completed. Skipping."
        )
        continue

    generated_scenes = generate_part(
        api_key,
        MODEL,
        topic,
        part
    )

    completed_part = {
        "part": part_number,
        "status": "completed",
        "scenes": []
    }

    for scene in generated_scenes:

        completed_part["scenes"].append({
            "scene": scene["scene"],

            "role": next(
                (
                    s.get("role", "")
                    for s in part.get("scenes", [])
                    if s["scene"] == scene["scene"]
                ),
                ""
            ),

            "status": "completed",

            "prompt": "",

            "narration": scene["narration"],
            "dialogue": scene["dialogue"],

            "visual_prompt": scene["visual_prompt"],
            "negative_prompt": scene["negative_prompt"],

            "camera_prompt": scene["camera_prompt"],
            "lighting_prompt": scene["lighting_prompt"],

            "sfx_prompt": scene["sfx_prompt"],
            "music_prompt": scene["music_prompt"]
        })

    ai_story["parts"] = [
        p
        for p in ai_story.get("parts", [])
        if p.get("part") != part_number
    ]

    ai_story["parts"].append(
        completed_part
    )

    ai_story["parts"].sort(
        key=lambda p: p["part"]
    )

    ai_story["status"] = "in_progress"

    save_json(ai_story)

    print(
        f"Part {part_number} completed and saved."
    )


ai_story["status"] = "completed"
ai_story["model"] = MODEL

save_json(ai_story)

total_scenes = sum(
    len(part.get("scenes", []))
    for part in ai_story["parts"]
)

print("===================================")
print("AI STORY GENERATION COMPLETED")
print(f"Topic: {topic}")
print(f"Model: {MODEL}")
print(f"Parts: {len(ai_story['parts'])}")
print(f"Scenes: {total_scenes}")
print(f"Output: {OUTPUT}")
print("===================================")
