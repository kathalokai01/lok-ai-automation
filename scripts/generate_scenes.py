#!/usr/bin/env python3

import json
import os
import time
import urllib.request
from pathlib import Path

AI_STORY = Path("output/story/ai_story.json")
CHARACTER_BIBLE = Path("output/story/character_bible.json")
OUT = Path("output/scenes/scenes.json")

MODEL = "gemini-3.5-flash-lite"
MAX_RETRIES = 3


def load_json(path):
    if not path.exists():
        raise SystemExit(f"ERROR: File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def call_gemini(prompt):
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise SystemExit("ERROR: GEMINI_API_KEY is not set")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{MODEL}:generateContent"
    )

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
            "temperature": 0.8,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "part": {
                        "type": "INTEGER"
                    },
                    "scene": {
                        "type": "INTEGER"
                    },
                    "narration": {
                        "type": "STRING"
                    },
                    "dialogue": {
                        "type": "STRING"
                    },
                    "visual_prompt": {
                        "type": "STRING"
                    },
                    "negative_prompt": {
                        "type": "STRING"
                    },
                    "camera_prompt": {
                        "type": "STRING"
                    },
                    "lighting_prompt": {
                        "type": "STRING"
                    },
                    "sfx_prompt": {
                        "type": "STRING"
                    },
                    "music_prompt": {
                        "type": "STRING"
                    },
                    "duration": {
                        "type": "NUMBER"
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
        }
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        },
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))

    text = (
        result["candidates"][0]["content"]["parts"][0]["text"]
        .strip()
    )

    return json.loads(text)


def build_prompt(story, bible, part_data, scene_data):
    topic = story.get("topic", "")
    visual_style = story.get("visual_style", "cinematic_realistic")

    character_text = json.dumps(
        bible.get("characters", []),
        ensure_ascii=False,
        indent=2
    )

    return f"""
You are the scene-generation engine for an AI cinematic video.

Create production-ready data for exactly ONE scene.

STORY TOPIC:
{topic}

VISUAL STYLE:
{visual_style}

CHARACTER BIBLE:
{character_text}

PART:
{part_data.get("part")}

SCENE:
{scene_data.get("scene")}

SCENE ROLE:
{scene_data.get("role", "")}

SOURCE NARRATION:
{scene_data.get("narration", "")}

SOURCE DIALOGUE:
{scene_data.get("dialogue", "")}

SOURCE VISUAL PROMPT:
{scene_data.get("visual_prompt", "")}

REQUIREMENTS:

1. Keep the story faithful to the source material.
2. Do not invent unnecessary characters.
3. Use the Character Bible for recurring characters.
4. Preserve character appearance and identity across scenes.
5. Visual prompt must be detailed and suitable for cinematic image/video generation.
6. Describe environment, characters, action, composition and atmosphere.
7. Use realistic cinematic visuals.
8. Avoid cartoon/anime/game-like appearance.
9. Avoid neon colors and artificial glitch effects.
10. Camera prompt must describe cinematic camera movement or framing.
11. Lighting prompt must describe realistic cinematic lighting.
12. SFX prompt must describe appropriate environmental or action sounds.
13. Music prompt must describe suitable cinematic background music.
14. Narration must be natural Hindi.
15. Dialogue must be natural Hindi.
16. Visual prompts should be written in English.
17. Negative prompt should explicitly protect realism and character consistency.
18. Duration must be a realistic scene duration in seconds.
19. Do not include markdown.
20. Return ONLY valid JSON matching the requested schema.

Generate the scene now.
"""


def generate_scene(story, bible, part_data, scene_data):
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = call_gemini(
                build_prompt(
                    story,
                    bible,
                    part_data,
                    scene_data
                )
            )

            expected_part = part_data.get("part")
            expected_scene = scene_data.get("scene")

            if result.get("part") != expected_part:
                raise ValueError(
                    f"Wrong part returned: {result.get('part')}"
                )

            if result.get("scene") != expected_scene:
                raise ValueError(
                    f"Wrong scene returned: {result.get('scene')}"
                )

            return result

        except Exception as e:
            last_error = e
            print(
                f"Scene {part_data.get('part')}-"
                f"{scene_data.get('scene')} "
                f"attempt {attempt}/{MAX_RETRIES} failed: {e}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)

    raise SystemExit(
        f"ERROR: Scene generation failed after "
        f"{MAX_RETRIES} attempts: {last_error}"
    )


def main():
    story = load_json(AI_STORY)
    bible = load_json(CHARACTER_BIBLE)

    if story.get("status") != "completed":
        raise SystemExit(
            "ERROR: ai_story.json is not completed"
        )

    if bible.get("status") != "completed":
        raise SystemExit(
            "ERROR: character_bible.json is not completed"
        )

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    existing = {
        "status": "in_progress",
        "topic": story.get("topic", ""),
        "total_scenes": 0,
        "completed_scenes": 0,
        "scenes": []
    }

    if OUT.exists():
        try:
            existing = load_json(OUT)
            print("Existing scene output found. Resuming...")
        except Exception:
            print("Existing scene output is invalid. Starting fresh.")

    completed_keys = {
        (
            item.get("part"),
            item.get("scene")
        )
        for item in existing.get("scenes", [])
        if item.get("status") == "completed"
    }

    all_scene_count = sum(
        len(part.get("scenes", []))
        for part in story.get("parts", [])
    )

    existing["total_scenes"] = all_scene_count
    existing["topic"] = story.get("topic", "")

    for part_data in story.get("parts", []):

        for scene_data in part_data.get("scenes", []):

            key = (
                part_data.get("part"),
                scene_data.get("scene")
            )

            if key in completed_keys:
                print(
                    f"Skipping completed scene "
                    f"{key[0]}-{key[1]}"
                )
                continue

            print(
                f"Generating scene "
                f"{key[0]}-{key[1]}..."
            )

            result = generate_scene(
                story,
                bible,
                part_data,
                scene_data
            )

            result["status"] = "completed"

            existing["scenes"] = [
                item
                for item in existing["scenes"]
                if (
                    item.get("part"),
                    item.get("scene")
                ) != key
            ]

            existing["scenes"].append(result)

            existing["scenes"].sort(
                key=lambda x: (
                    x.get("part", 0),
                    x.get("scene", 0)
                )
            )

            existing["completed_scenes"] = len(
                [
                    item
                    for item in existing["scenes"]
                    if item.get("status") == "completed"
                ]
            )

            temp = OUT.with_suffix(".tmp")

            with temp.open(
                "w",
                encoding="utf-8"
            ) as f:
                json.dump(
                    existing,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            temp.replace(OUT)

            print(
                f"Scene {key[0]}-{key[1]} completed."
            )

    existing["status"] = "completed"

    temp = OUT.with_suffix(".tmp")

    with temp.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            existing,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp.replace(OUT)

    print()
    print("===== SCENE GENERATION COMPLETE =====")
    print(f"Topic: {existing['topic']}")
    print(f"Total scenes: {existing['total_scenes']}")
    print(f"Completed scenes: {existing['completed_scenes']}")
    print(f"Output: {OUT}")
    print("=====================================")


if __name__ == "__main__":
    main()
