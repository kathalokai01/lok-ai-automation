import json
import os
from datetime import datetime, timezone
from pathlib import Path


SCENES_FILE = Path("output/scenes/scenes.json")
CHARACTER_BIBLE_FILE = Path(
    "output/story/character_bible.json"
)
OUTPUT_FILE = Path(
    "output/visuals/visual_jobs.json"
)


def load_json(path):
    if not path.exists():
        raise SystemExit(
            f"ERROR: Required file not found: {path}"
        )

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    except Exception as e:
        raise SystemExit(
            f"ERROR: Could not read {path}: {e}"
        )


def save_json_atomic(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temp_file.open(
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

    os.replace(
        temp_file,
        path,
    )


def make_job(scene, character_bible):
    part = scene.get("part")
    scene_number = scene.get("scene")

    visual_prompt = str(
        scene.get(
            "visual_prompt",
            "",
        )
    ).strip()

    if not visual_prompt:
        raise ValueError(
            f"Empty visual prompt for "
            f"Part {part} Scene {scene_number}"
        )

    return {
        "part": part,
        "scene": scene_number,
        "status": "pending",
        "asset_type": "visual",
        "visual_prompt": visual_prompt,
        "negative_prompt": str(
            scene.get(
                "negative_prompt",
                "",
            )
        ).strip(),
        "camera_prompt": str(
            scene.get(
                "camera_prompt",
                "",
            )
        ).strip(),
        "lighting_prompt": str(
            scene.get(
                "lighting_prompt",
                "",
            )
        ).strip(),
        "duration": scene.get(
            "duration",
            "auto",
        ),
        "character_bible": character_bible,
        "asset_path": None,
        "provider": None,
        "model": None,
        "error": None,
    }


def main():
    print(
        "===== PREPARE VISUAL GENERATION ====="
    )

    scenes_data = load_json(
        SCENES_FILE
    )

    character_data = load_json(
        CHARACTER_BIBLE_FILE
    )

    if scenes_data.get("status") != "completed":
        raise SystemExit(
            "ERROR: Scene generation is not completed"
        )

    characters = character_data.get(
        "characters",
        [],
    )

    if not characters:
        raise SystemExit(
            "ERROR: Character Bible contains no characters"
        )

    source_scenes = scenes_data.get(
        "scenes",
        [],
    )

    if not source_scenes:
        raise SystemExit(
            "ERROR: No generated scenes found"
        )

    topic = scenes_data.get(
        "topic",
        "",
    )

    existing_jobs = {}

    if OUTPUT_FILE.exists():

        try:
            existing_data = load_json(
                OUTPUT_FILE
            )

            for job in existing_data.get(
                "jobs",
                [],
            ):

                key = (
                    job.get("part"),
                    job.get("scene"),
                )

                existing_jobs[key] = job

            print(
                f"Existing visual jobs found: "
                f"{len(existing_jobs)}"
            )

        except Exception as e:

            print(
                "WARNING: Existing visual job "
                f"file could not be reused: {e}"
            )

    jobs = []

    for scene in source_scenes:

        part = scene.get("part")
        scene_number = scene.get("scene")

        key = (
            part,
            scene_number,
        )

        if key in existing_jobs:

            existing_job = existing_jobs[key]

            # Keep completed/generated state.
            if existing_job.get("status") == "completed":
                jobs.append(existing_job)

                print(
                    f"Keeping completed visual job: "
                    f"Part {part} Scene {scene_number}"
                )

                continue

        try:

            job = make_job(
                scene,
                characters,
            )

            jobs.append(job)

            print(
                f"Prepared: "
                f"Part {part} Scene {scene_number}"
            )

        except Exception as e:

            jobs.append(
                {
                    "part": part,
                    "scene": scene_number,
                    "status": "failed",
                    "asset_type": "visual",
                    "visual_prompt": "",
                    "negative_prompt": "",
                    "camera_prompt": "",
                    "lighting_prompt": "",
                    "duration": scene.get(
                        "duration",
                        "auto",
                    ),
                    "character_bible": characters,
                    "asset_path": None,
                    "provider": None,
                    "model": None,
                    "error": str(e),
                }
            )

            print(
                f"FAILED: Part {part} "
                f"Scene {scene_number}: {e}"
            )

    jobs.sort(
        key=lambda item: (
            item.get("part", 0),
            item.get("scene", 0),
        )
    )

    expected_keys = {
        (
            scene.get("part"),
            scene.get("scene"),
        )
        for scene in source_scenes
    }

    actual_keys = {
        (
            job.get("part"),
            job.get("scene"),
        )
        for job in jobs
    }

    missing = expected_keys - actual_keys

    if missing:
        raise SystemExit(
            f"ERROR: Missing visual jobs: {sorted(missing)}"
        )

    duplicate_keys = (
        len(jobs) != len(actual_keys)
    )

    if duplicate_keys:
        raise SystemExit(
            "ERROR: Duplicate visual jobs detected"
        )

    failed_jobs = [
        job
        for job in jobs
        if job.get("status") == "failed"
    ]

    completed_jobs = [
        job
        for job in jobs
        if job.get("status") == "completed"
    ]

    output = {
        "status": (
            "ready"
            if not failed_jobs
            else "failed"
        ),
        "topic": topic,
        "total_scenes": len(jobs),
        "completed_scenes": len(
            completed_jobs
        ),
        "pending_scenes": len(jobs)
        - len(completed_jobs)
        - len(failed_jobs),
        "failed_scenes": len(
            failed_jobs
        ),
        "character_bible_source": str(
            CHARACTER_BIBLE_FILE
        ),
        "scene_source": str(
            SCENES_FILE
        ),
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "jobs": jobs,
    }

    save_json_atomic(
        OUTPUT_FILE,
        output,
    )

    print(
        "\n===== VISUAL JOB MANIFEST ====="
    )

    print(
        f"Topic: {topic}"
    )

    print(
        f"Total scenes: {len(jobs)}"
    )

    print(
        f"Completed: {len(completed_jobs)}"
    )

    print(
        f"Pending: {output['pending_scenes']}"
    )

    print(
        f"Failed: {len(failed_jobs)}"
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )

    if failed_jobs:
        print(
            "\nERROR: Some visual jobs failed."
        )
        raise SystemExit(1)

    print(
        "\nVisual job preparation: PASSED"
    )


if __name__ == "__main__":
    main()
