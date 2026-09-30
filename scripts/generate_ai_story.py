#!/usr/bin/env python3

import json
from pathlib import Path

INPUT = Path("output/story/story.json")
OUTPUT = Path("output/story/ai_story.json")


def load_json(path):
    if not path.exists():
        raise SystemExit(f"ERROR: File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


story = load_json(INPUT)

topic = str(story.get("topic", "")).strip()

if not topic:
    raise SystemExit("ERROR: Story topic is empty")


ai_story = {
    "status": "pending_ai_generation",
    "topic": topic,
    "parts": []
}


for part in story.get("parts", []):

    part_data = {
        "part": part["part"],
        "scenes": []
    }

    for scene in part.get("scenes", []):

        scene_data = {
            "scene": scene["scene"],
            "role": scene.get("role", ""),
            "status": "pending",

            "prompt": "",
            "narration": "",
            "dialogue": "",

            "visual_prompt": "",
            "negative_prompt": "",
            "camera_prompt": "",
            "lighting_prompt": "",

            "sfx_prompt": "",
            "music_prompt": ""
        }

        part_data["scenes"].append(scene_data)

    ai_story["parts"].append(part_data)


OUTPUT.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT.open("w", encoding="utf-8") as f:
    json.dump(
        ai_story,
        f,
        ensure_ascii=False,
        indent=2
    )

total_scenes = sum(
    len(part["scenes"])
    for part in ai_story["parts"]
)

print(f"AI story structure created: {OUTPUT}")
print(f"Topic: {topic}")
print(f"Total scenes: {total_scenes}")
