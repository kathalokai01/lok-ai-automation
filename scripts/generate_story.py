#!/usr/bin/env python3

import json
from pathlib import Path

PLAN = Path("output/story/story_plan.json")
OUT = Path("output/story/story.json")


def load_json(path):
    if not path.exists():
        raise SystemExit(f"ERROR: File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


plan = load_json(PLAN)

topic = str(plan.get("topic", "")).strip()

if not topic:
    raise SystemExit("ERROR: Story topic is empty")


story = {
    "status": "ready_for_generation",
    "topic": topic,
    "format": plan.get("format"),
    "audience": plan.get("audience"),
    "parts": []
}


for part in plan.get("parts", []):

    part_data = {
        "part": part["part"],
        "hook_required": part.get("hook_required", False),
        "suspense_required": part.get("suspense_required", False),
        "final_resolution": part.get("final_resolution", False),
        "scenes": []
    }

    for scene in part.get("scenes", []):

        scene_data = {
            "scene": scene["scene"],
            "role": scene.get("role", ""),
            "status": "pending",

            "narration": "",
            "dialogue": "",

            "visual_prompt": "",
            "negative_prompt": "",

            "camera_prompt": "",
            "lighting_prompt": "",

            "sfx_prompt": "",
            "music_prompt": "",

            "duration": None
        }

        part_data["scenes"].append(scene_data)

    story["parts"].append(part_data)


OUT.parent.mkdir(
    parents=True,
    exist_ok=True
)

with OUT.open("w", encoding="utf-8") as f:
    json.dump(
        story,
        f,
        ensure_ascii=False,
        indent=2
    )

print(f"Story structure created: {OUT}")
print(f"Topic: {topic}")
print(
    f"Parts: {len(story['parts'])}, "
    f"total scenes: "
    f"{sum(len(p['scenes']) for p in story['parts'])}"
)
