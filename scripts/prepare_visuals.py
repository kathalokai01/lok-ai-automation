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


def visual_path(part, scene):
    return Path(
        f"output/visuals/"
        f"part_{int(part):02d}/"
        f"scene_{int(scene):02d}.png"
    )


def is_valid_visual(path):
    if not path.exists():
        return False

    if path.stat().st_size <= 0:
        return False

    try:
        with path.open("rb") as file:
            header = file.read(8)

        return (
            header.startswith(b"\x89PNG")
            or header.startswith(b"\xff\xd8")
        )

    except Exception:
        return False


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
        "======================================"
    )
    print(
        "     PREPARE VISUAL GENERATION"
    )
    print(
        "======================================"
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
                "Existing visual jobs found: "
                f"{len(existing_jobs)}"
            )

        except Exception as e:
            print(
                "WARNING: Existing visual "
                f"manifest ignored: {e}"
            )

    jobs = []

    for scene in source_scenes:
        part = scene.get("part")
        scene_number = scene.get("scene")

        key = (
            part,
            scene_number,
        )

        output_path = visual_path(
            part,
            scene_number,
        )

        existing_job = existing_jobs.get(
            key
        )

        # IMPORTANT:
        # completed status is trusted ONLY
        # when the actual visual file exists.
        if (
            existing_job
            and is_valid_visual(output_path)
        ):
            existing_job["status"] = "completed"
            existing_job["asset_path"] = str(
                output_path
            )
            existing_job["error"] = None

            jobs.append(existing_job)

            print(
                "VALID — keeping visual: "
                f"Part {part} Scene {scene_number}"
            )

            continue

        try:
            job = make_job(
                scene,
                characters,
            )

            jobs.append(job)

            if existing_job:
                print(
                    "MISSING — resetting to pending: "
                    f"Part {part} Scene {scene_number}"
                )
            else:
                print(
                    "Prepared: "
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
                "FAILED: Part "
                f"{part} Scene {scene_number}: {e}"
            )

    jobs.sort(
        key=lambda item: (
            int(item.get("part", 0)),
            int(item.get("scene", 0)),
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
            "ERROR: Missing visual jobs: "
            f"{sorted(missing)}"
        )

    if len(jobs) != len(actual_keys):
        raise SystemExit(
            "ERROR: Duplicate visual jobs detected"
        )

    completed_jobs = []
    pending_jobs = []
    failed_jobs = []

    for job in jobs:
        part = int(job["part"])
        scene = int(job["scene"])

        path = visual_path(
            part,
            scene,
        )

        if is_valid_visual(path):
            job["status"] = "completed"
            job["asset_path"] = str(path)
            job["error"] = None
            completed_jobs.append(job)

        elif job.get("status") == "failed":
            failed_jobs.append(job)

        else:
            job["status"] = "pending"
            job["asset_path"] = None
            pending_jobs.append(job)

    output = {
        "status": (
            "completed"
            if len(completed_jobs) == len(jobs)
            else "ready"
        ),
        "topic": topic,
        "total_scenes": len(jobs),
        "completed_scenes": len(
            completed_jobs
        ),
        "pending_scenes": len(
            pending_jobs
        ),
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

    print()
    print(
        "===== VISUAL JOB MANIFEST ====="
    )
    print(
        f"Total scenes : {len(jobs)}"
    )
    print(
        f"Completed    : {len(completed_jobs)}"
    )
    print(
        f"Pending      : {len(pending_jobs)}"
    )
    print(
        f"Failed       : {len(failed_jobs)}"
    )

    if pending_jobs:
        print()
        print(
            "===== MISSING VISUALS ====="
        )

        for job in pending_jobs:
            print(
                f" - Part {job['part']} "
                f"Scene {job['scene']}"
            )

    if failed_jobs:
        print()
        print(
            "===== FAILED VISUAL JOBS ====="
        )

        for job in failed_jobs:
            print(
                f" - Part {job['part']} "
                f"Scene {job['scene']}: "
                f"{job.get('error', '')}"
            )

    print()
    print(
        "Visual manifest preparation: PASSED"
    )

    # Do NOT fail merely because visuals are pending.
    # generate_visuals.py must receive them and generate them.


if __name__ == "__main__":
    main()
