#!/usr/bin/env python3

import json
import os
import time
import urllib.request
from pathlib import Path


MODEL = "gemini-3.5-flash-lite"

INPUT = Path("output/story/ai_story.json")
OUTPUT = Path("output/story/character_bible.json")

MAX_RETRIES = 3


def load_json(path):
    if not path.exists():
        raise SystemExit(f"ERROR: File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp = path.with_suffix(".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp.replace(path)


def extract_story_content(story):
    scenes = []

    for part in story.get("parts", []):
        for scene in part.get("scenes", []):
            scenes.append({
                "part": part.get("part"),
                "scene": scene.get("scene"),
                "narration": scene.get("narration", ""),
                "dialogue": scene.get("dialogue", ""),
                "visual_prompt": scene.get("visual_prompt", "")
            })

    return scenes


def generate_character_bible(api_key, story):
    story_content = extract_story_content(story)

    schema = {
        "type": "object",
        "properties": {
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "character_id": {
                            "type": "string"
                        },
                        "name": {
                            "type": "string"
                        },
                        "role": {
                            "type": "string"
                        },
                        "importance": {
                            "type": "string"
                        },
                        "age": {
                            "type": "string"
                        },
                        "gender": {
                            "type": "string"
                        },
                        "personality": {
                            "type": "string"
                        },
                        "appearance": {
                            "type": "string"
                        },
                        "face_features": {
                            "type": "string"
                        },
                        "hair": {
                            "type": "string"
                        },
                        "clothing": {
                            "type": "string"
                        },
                        "body_features": {
                            "type": "string"
                        },
                        "distinctive_features": {
                            "type": "string"
                        },
                        "visual_identity": {
                            "type": "string"
                        },
                        "consistency_rules": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            }
                        }
                    },
                    "required": [
                        "character_id",
                        "name",
                        "role",
                        "importance",
                        "age",
                        "gender",
                        "personality",
                        "appearance",
                        "face_features",
                        "hair",
                        "clothing",
                        "body_features",
                        "distinctive_features",
                        "visual_identity",
                        "consistency_rules"
                    ]
                }
            }
        },
        "required": [
            "characters"
        ]
    }

    prompt = f"""
You are creating a production Character Bible for an AI cinematic video.

Topic:
{story.get("topic", "")}

Analyze the complete story scenes below.

Your task:
1. Identify every important recurring character.
2. Do NOT invent unnecessary characters.
3. If a character is clearly unnamed, give them a descriptive stable name.
4. Keep the same character identity across all scenes.
5. Extract only information supported by the story.
6. When exact physical details are missing, create conservative production-friendly details that do not contradict the story.
7. Make each character visually distinctive.
8. The Character Bible will later be used for image/video generation, so visual consistency is critical.
9. Write visual descriptions in English because they will be used as AI image-generation prompts.
10. Do not include camera instructions or scene descriptions in place of character descriptions.

Important:
- Character IDs must be stable.
- Use IDs such as CHAR_001, CHAR_002, etc.
- Do not create separate characters merely because the same character is described differently in different scenes.
- Background crowds or unnamed incidental people should generally not become Character Bible entries unless they are narratively important.

Story scenes:

{json.dumps(story_content, ensure_ascii=False, indent=2)}
"""

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
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
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }

    request = urllib.request.Request(
        url,
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
                .strip()
            )

            data = json.loads(text)

            if "characters" not in data:
                raise ValueError(
                    "Gemini response does not contain characters"
                )

            if not isinstance(data["characters"], list):
                raise ValueError(
                    "characters must be a list"
                )

            return data

        except Exception as e:
            last_error = e
            print(
                f"Character Bible attempt "
                f"{attempt}/{MAX_RETRIES} failed: {e}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)

    raise SystemExit(
        f"Character Bible generation failed: {last_error}"
    )


def main():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise SystemExit(
            "ERROR: GEMINI_API_KEY is not set"
        )

    story = load_json(INPUT)

    if story.get("status") != "completed":
        raise SystemExit(
            "ERROR: AI story is not completed"
        )

    print("Generating Character Bible...")

    bible = generate_character_bible(
        api_key,
        story
    )

    output = {
        "status": "completed",
        "topic": story.get("topic", ""),
        "character_count": len(
            bible.get("characters", [])
        ),
        "characters": bible.get("characters", [])
    }

    save_json(OUTPUT, output)

    print(
        f"Character Bible created: {OUTPUT}"
    )

    print(
        f"Characters found: "
        f"{output['character_count']}"
    )


if __name__ == "__main__":
    main()
