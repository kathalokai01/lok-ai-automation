#!/usr/bin/env python3

import json
from pathlib import Path

from input_config import (
    load_input_config,
    cfg,
    cfg_bool,
    cfg_text,
    get_parts,
    get_scenes,
    get_story_length,
    get_scene_duration,
    resolve_topic,
    resolve_story_text,
    normalize_format,
    get_caption_mode,
)


OUT = Path("output/story/story_plan.json")


def main():
    config = load_input_config()

    format_type = normalize_format(config)
    topic = resolve_topic(config)
    story_text = resolve_story_text(config)

    parts = get_parts(config)
    scenes_per_part = get_scenes(config)
    story_length = get_story_length(config)
    scene_duration = get_scene_duration(config)

    if parts < 1:
        raise SystemExit("ERROR: PARTS must be >= 1")

    if scenes_per_part < 1:
        raise SystemExit("ERROR: SCENES must be >= 1")

    audience = cfg_text(config, "AUDIENCE", "adult")
    caption_mode = get_caption_mode(config)

    part_hook = cfg_bool(config, "PART_HOOK", True)
    part_suspense = cfg_bool(config, "PART_SUSPENSE", True)
    final_resolution = cfg_bool(config, "FINAL_RESOLUTION", True)

    character_bible = cfg_bool(config, "CHARACTER_BIBLE", True)
    character_consistency = cfg_bool(
        config,
        "CHARACTER_CONSISTENCY",
        True,
    )
    world_consistency = cfg_bool(
        config,
        "WORLD_CONSISTENCY",
        True,
    )
    scene_continuity = cfg_bool(
        config,
        "SCENE_CONTINUITY",
        True,
    )

    visual_style = cfg_text(
        config,
        "VISUAL_STYLE",
        "cinematic_realistic",
    )

    realism = cfg_text(
        config,
        "REALISM",
        "high",
    )

    camera_style = cfg_text(
        config,
        "CAMERA_STYLE",
        "cinematic",
    )

    lighting = cfg_text(
        config,
        "LIGHTING",
        "cinematic",
    )

    mood = cfg_text(
        config,
        "MOOD",
        "dramatic",
    )

    quality = cfg_text(
        config,
        "QUALITY",
        "high",
    )

    cinematic_camera = cfg_bool(
        config,
        "CINEMATIC_CAMERA",
        True,
    )

    natural_motion = cfg_bool(
        config,
        "NATURAL_MOTION",
        True,
    )

    realistic_lighting = cfg_bool(
        config,
        "REALISTIC_LIGHTING",
        True,
    )

    negative_prompt_enabled = cfg_bool(
        config,
        "NEGATIVE_PROMPT",
        True,
    )

    avoid_cartoon = cfg_bool(
        config,
        "AVOID_CARTOON_LOOK",
        True,
    )

    avoid_neon = cfg_bool(
        config,
        "AVOID_NEON",
        True,
    )

    avoid_glitch = cfg_bool(
        config,
        "AVOID_GLITCH_EFFECTS",
        True,
    )

    music_enabled = cfg_bool(
        config,
        "MUSIC",
        True,
    )

    sfx_enabled = cfg_bool(
        config,
        "SFX",
        True,
    )

    ambient_enabled = cfg_bool(
        config,
        "AMBIENT_SOUND",
        True,
    )

    music_style = cfg_text(
        config,
        "MUSIC_STYLE",
        "cinematic",
    )

    transitions = cfg_text(
        config,
        "TRANSITIONS",
        "cinematic",
    )

    fps = config.get("FPS", 24)

    scene_roles_full = [
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
        "climax or resolution",
    ]

    scene_roles_short = [
        "cold opening hook",
        "immediate setup",
        "mystery or unanswered question",
        "first escalation",
        "important clue",
        "major reveal",
        "tension escalation",
        "unexpected turn",
        "twist or emotional payoff",
        "final suspense beat",
        "strong closing hook",
    ]

    if format_type == "short":
        scene_roles = scene_roles_short
    else:
        scene_roles = scene_roles_full

    plan = {
        "status": "planned",

        # Canonical content source.
        # generate_story.py remains responsible for the final title.
        "topic": topic,

        "story_text": story_text,

        "title_source": (
            "TOPIC"
            if topic
            else "STORY_TEXT"
        ),

        "format": format_type,

        "audience": audience,

        "story_length": story_length,

        "scene_duration": scene_duration,

        "parts_count": parts,

        "scenes_per_part": scenes_per_part,

        "total_scenes": parts * scenes_per_part,

        "caption_mode": caption_mode,

        "parts": [],

        "generation_notes": {
            "part_hook": part_hook,
            "part_suspense": part_suspense,
            "final_resolution": final_resolution,

            "character_bible": character_bible,
            "character_consistency": character_consistency,
            "world_consistency": world_consistency,
            "scene_continuity": scene_continuity,

            "visual_style": visual_style,
            "realism": realism,

            "cinematic_camera": cinematic_camera,
            "camera_style": camera_style,

            "lighting": lighting,
            "realistic_lighting": realistic_lighting,

            "mood": mood,
            "quality": quality,

            "natural_motion": natural_motion,

            "negative_prompt": negative_prompt_enabled,
            "avoid_cartoon_look": avoid_cartoon,
            "avoid_neon": avoid_neon,
            "avoid_glitch_effects": avoid_glitch,

            "music": music_enabled,
            "music_style": music_style,

            "sfx": sfx_enabled,
            "ambient_sound": ambient_enabled,

            "transitions": transitions,

            "fps": fps,
        },
    }

    for part_no in range(1, parts + 1):

        part = {
            "part": part_no,

            "hook_required": (
                part_hook
            ),

            "suspense_required": (
                part_suspense
                and part_no < parts
            ),

            "final_resolution": (
                final_resolution
                and part_no == parts
            ),

            "scenes": [],
        }

        for scene_no in range(
            1,
            scenes_per_part + 1,
        ):

            role = scene_roles[
                min(
                    scene_no - 1,
                    len(scene_roles) - 1,
                )
            ]

            scene = {
                "scene": scene_no,

                "status": "pending",

                "role": role,

                "narration": "",

                "visual_prompt": "",

                "negative_prompt": "",

                "sfx_prompt": "",

                "music_prompt": "",

                "scene_duration": scene_duration,

                "visual_style": visual_style,

                "realism": realism,

                "camera_style": camera_style,

                "lighting": lighting,

                "mood": mood,

                "natural_motion": natural_motion,

                "character_consistency": (
                    character_consistency
                ),

                "world_consistency": (
                    world_consistency
                ),

                "scene_continuity": (
                    scene_continuity
                ),
            }

            part["scenes"].append(scene)

        plan["parts"].append(part)

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUT.write_text(
        json.dumps(
            plan,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print("=" * 60)
    print("STORY PLAN CREATED")
    print("=" * 60)
    print(f"Output          : {OUT}")
    print(f"Format          : {format_type}")
    print(f"Topic           : {topic}")
    print(
        f"Story text      : "
        f"{'provided' if story_text else 'not provided'}"
    )
    print(f"Audience        : {audience}")
    print(f"Story length    : {story_length}")
    print(f"Scene duration  : {scene_duration}")
    print(f"Parts           : {parts}")
    print(f"Scenes/part     : {scenes_per_part}")
    print(
        f"Total scenes    : "
        f"{parts * scenes_per_part}"
    )
    print(f"Hook enabled    : {part_hook}")
    print(f"Suspense        : {part_suspense}")
    print(f"Final resolution: {final_resolution}")
    print(f"Visual style    : {visual_style}")
    print(f"Realism         : {realism}")
    print("=" * 60)


if __name__ == "__main__":
    main()
