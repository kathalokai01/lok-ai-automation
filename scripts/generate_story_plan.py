#!/usr/bin/env python3

import json
import re
from pathlib import Path

CONFIG = Path("Input/topic.txt")
OUT = Path("output/story/story_plan.json")


def load_config(path):
    text = path.read_text(encoding="utf-8")
    values = {}

    for line in text.splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        # Remove inline comments
        value = re.sub(r"\s+#.*$", "", value).strip()

        if value.lower() in ("true", "false"):
            value = value.lower() == "true"

        elif re.fullmatch(r"-?\d+", value):
            value = int(value)

        elif len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]

        values[key] = value

    return values


cfg = load_config(CONFIG)

topic = str(cfg["TOPIC"]).strip()
parts = int(cfg["PARTS"])
scenes_per_part = int(cfg["SCENES"])

if parts < 1:
    raise SystemExit("ERROR: PARTS must be >= 1")

if scenes_per_part < 1:
    raise SystemExit("ERROR: SCENES must be >= 1")


scene_roles = [
    "opening hook and setup",
    "introduce the central situation",
    "develop the main conflict",
    "raise the stakes",
    "reveal an important clue",
    "turning point",
    "confrontation",
    "consequence",
    "emotional or thematic development",
    "climax preparation",
    "climax or resolution"
]


plan = {
    "status": "planned",
    "topic": topic,

    "format": cfg.get("FORMAT"),
    "audience": cfg.get("AUDIENCE"),

    "parts": [],

    "generation_notes": {
        "story_text_supplied": bool(
            str(cfg.get("STORY_TEXT", "")).strip()
        ),

        "character_bible": cfg.get(
            "CHARACTER_BIBLE", False
        ),

        "character_consistency": cfg.get(
            "CHARACTER_CONSISTENCY", False
        ),

        "world_consistency": cfg.get(
            "WORLD_CONSISTENCY", False
        ),

        "scene_continuity": cfg.get(
            "SCENE_CONTINUITY", False
        ),

        "visual_style": cfg.get(
            "VISUAL_STYLE"
        ),

        "camera_style": cfg.get(
            "CAMERA_STYLE"
        ),

        "lighting": cfg.get(
            "LIGHTING"
        ),

        "mood": cfg.get(
            "MOOD"
        )
    }
}


for part_no in range(1, parts + 1):

    part = {
        "part": part_no,

        "hook_required": bool(
            cfg.get("PART_HOOK", True)
        ),

        "suspense_required": bool(
            cfg.get("PART_SUSPENSE", True)
            and part_no < parts
        ),

        "final_resolution": bool(
            cfg.get("FINAL_RESOLUTION", True)
            and part_no == parts
        ),

        "scenes": []
    }


    for scene_no in range(1, scenes_per_part + 1):

        role = scene_roles[
            min(scene_no - 1, len(scene_roles) - 1)
        ]

        part["scenes"].append({

            "scene": scene_no,

            "status": "pending",

            "role": role,

            "narration": "",

            "visual_prompt": "",

            "negative_prompt": "",

            "sfx_prompt": "",

            "music_prompt": ""
        })


    plan["parts"].append(part)


OUT.parent.mkdir(
    parents=True,
    exist_ok=True
)

OUT.write_text(
    json.dumps(
        plan,
        ensure_ascii=False,
        indent=2
    ) + "\n",
    encoding="utf-8"
)


print(
    f"Story plan created: {OUT}"
)

print(
    f"Topic: {topic}"
)

print(
    f"Parts: {parts}, "
    f"scenes per part: {scenes_per_part}, "
    f"total scenes: {parts * scenes_per_part}"
)
