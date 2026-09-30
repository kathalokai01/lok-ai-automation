#!/usr/bin/env python3

import json
import os
import time
import urllib.request
from pathlib import Path


INPUT = Path("output/story/ai_story.json")
OUTPUT = Path("output/story/character_bible.json")
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


def build_character_context(story):
    context = []

    for part in story.get("parts", []):
        part_number = part.get("part")

        for scene in part.get("scenes", []):
            context.append({
                "part": part_number,
                "scene": scene.get("scene"),
                "narration": scene.get("narration", ""),
                "dialogue": scene.get("dialogue", ""),
                "visual_prompt": scene.get("visual_prompt", "")
            })

    return context


def generate_character_bible(api_key, model, story):
    character_context = build_character_context(story)

    character_schema = {
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
You are the Character Bible generation AI for an automated
Hindi cinematic storytelling pipeline.

Create a production-ready CHARACTER BIBLE for the complete story.

Your main goal is to identify recurring and important characters and
define stable visual identities that can be reused across every scene.

STORY TOPIC:
{story.get("topic", "")}

COMPLETE STORY SCENES:
{json.dumps(character_context, ensure_ascii=False, indent=2)}

IMPORTANT RULES:

1. Identify all important recurring characters.
2. Do not invent unnecessary characters.
3. If a clearly important character has no explicit name, create a
   stable descriptive name that can be used consistently.
4. The same character must keep the same identity throughout the story.
5. Character descriptions must be visually useful for image/video
   generation.
6. Preserve important story facts already present in the scenes.
7. Do not contradict the existing story.
8. Keep age, gender, facial structure, hairstyle, clothing and other
   visual traits consistent.
9. Give every important character a stable character_id such as
   CHAR_001, CHAR_002, CHAR_003.
10. Background crowds and incidental unnamed people should generally
    NOT be included unless they are important to the story.
11. Use conservative production-friendly details when the story does
    not specify something.
12. Avoid unnecessary fantasy, cartoon, anime or exaggerated details.
13. Visual identity should be suitable for realistic cinematic
    generation.
14. The character bible will later be used for scene-level visual
    generation, so consistency is extremely important.
15. Write descriptive visual fields in English because they will be
    used as visual-generation context.
16. Personality and role can remain concise and factual.
17. Do not create multiple character entries for the same person.
18. Return ONLY the requested JSON structure.

Required character fields:

- character_id
- name
- role
- importance
- age
- gender
- personality
- appearance
- face_features
- hair
- clothing
- body_features
- distinctive_features
- visual_identity
- consistency_rules
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
            "responseSchema": character_schema
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
                f"Generating Character Bible "
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

            characters = generated.get("characters")

            if not isinstance(characters, list):
                raise ValueError(
                    "Character Bible does not contain a valid "
                    "'characters' array"
                )

            seen_ids = set()

            for character in characters:

                required_fields = [
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

                for field in required_fields:
                    if field not in character:
                        raise ValueError(
                            f"Character is missing required field: "
                            f"{field}"
                        )

                character_id = character["character_id"]

                if character_id in seen_ids:
                    raise ValueError(
                        f"Duplicate character_id: {character_id}"
                    )

                seen_ids.add(character_id)

                if not isinstance(
                    character["consistency_rules"],
                    list
                ):
                    raise ValueError(
                        f"Invalid consistency_rules for "
                        f"{character_id}"
                    )

            return generated

        except Exception as e:

            last_error = e

            print(
                f"Character Bible generation failed: {e}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(3)

    raise SystemExit(
        "ERROR: Character Bible generation failed after "
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

if story.get("status") != "completed":
    raise SystemExit(
        "ERROR: AI story is not in completed state"
    )

topic = str(
    story.get("topic", "")
).strip()

if not topic:
    raise SystemExit(
        "ERROR: Story topic is empty"
    )


if OUTPUT.exists():

    try:
        existing = load_json(OUTPUT)

        if (
            existing.get("status") == "completed"
            and existing.get("topic") == topic
            and existing.get("characters")
        ):
            print(
                "Existing Character Bible found. "
                "Skipping regeneration."
            )

            existing["model"] = MODEL

            save_json(existing)

            print("===================================")
            print("CHARACTER BIBLE ALREADY COMPLETED")
            print(f"Topic: {topic}")
            print(f"Model: {MODEL}")
            print(f"Characters: {len(existing['characters'])}")
            print(f"Output: {OUTPUT}")
            print("===================================")

            raise SystemExit(0)

    except SystemExit:
        raise

    except Exception:
        print(
            "Existing Character Bible is invalid. "
            "Starting fresh."
        )


print("Generating Character Bible...")

generated = generate_character_bible(
    api_key,
    MODEL,
    story
)


characters = generated.get(
    "characters",
    []
)


character_bible = {
    "status": "completed",
    "topic": topic,
    "model": MODEL,
    "characters": characters
}


save_json(character_bible)


print("===================================")
print("CHARACTER BIBLE GENERATION COMPLETED")
print(f"Topic: {topic}")
print(f"Model: {MODEL}")
print(f"Characters: {len(characters)}")
print(f"Output: {OUTPUT}")
print("===================================")
