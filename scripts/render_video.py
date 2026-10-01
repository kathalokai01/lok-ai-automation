#!/usr/bin/env python3

import json
import os
import subprocess
from pathlib import Path


INPUT = Path("Input/topic.txt")
NARRATION = Path("output/narration/audio_jobs.json")
VISUALS = Path("output/visuals/visual_jobs.json")

SCENES_OUT = Path("output/scenes")
PARTS_OUT = Path("output/parts")
MANIFEST_OUT = Path("output/video_render_manifest.json")


def load_json(path: Path):
    if not path.exists():
        raise SystemExit(f"ERROR: Required file not found: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: Invalid JSON in {path}: {exc}")


def read_config(key: str, default: str = "") -> str:
    if not INPUT.exists():
        return default

    for raw in INPUT.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        k, value = line.split("=", 1)

        if k.strip() != key:
            continue

        value = value.split("#", 1)[0].strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ('"', "'")
        ):
            value = value[1:-1]

        return value.strip()

    return default


def run_command(command):
    print("RUN:", " ".join(str(x) for x in command))
    subprocess.run(command, check=True)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    value = result.stdout.strip()

    if not value:
        raise RuntimeError(f"Could not determine duration: {path}")

    return round(float(value), 3)


def valid_video(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1000:
        return False

    try:
        return probe_duration(path) > 0.01
    except Exception:
        return False


def get_output_geometry(video_format: str):
    value = video_format.strip().lower()

    if value in {"short", "shorts", "vertical", "9:16"}:
        return 720, 1280

    if value in {"square", "1:1"}:
        return 1080, 1080

    return 1920, 1080


def build_video_filter(video_format: str, fps: int):
    width, height = get_output_geometry(video_format)

    return (
        f"scale={width}:{height}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"fps={fps}"
    )


def job_status_is_complete(job):
    status = str(job.get("status", "")).strip().lower()

    return status in {
        "completed",
        "complete",
        "success",
        "generated",
        "done",
    }


def extract_jobs(manifest):
    jobs = manifest.get("jobs")

    if isinstance(jobs, list):
        return jobs

    # Compatibility with manifests using "scenes"
    scenes = manifest.get("scenes")

    if isinstance(scenes, list):
        return scenes

    return []


def build_job_map(manifest):
    result = {}

    for job in extract_jobs(manifest):
        if not isinstance(job, dict):
            continue

        try:
            part = int(job.get("part"))
            scene = int(job.get("scene"))
        except (TypeError, ValueError):
            continue

        if job_status_is_complete(job):
            result[(part, scene)] = job

    return result


def resolve_audio(job, part, scene):
    candidates = [
        job.get("output"),
        job.get("output_path"),
        job.get("audio"),
        job.get("audio_path"),
        job.get("file"),
        job.get("path"),
        f"output/narration/audio/part_{part:02d}/scene_{scene:02d}.mp3",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        path = Path(str(candidate))

        if path.exists() and path.stat().st_size > 0:
            return path

    return Path(
        f"output/narration/audio/part_{part:02d}/scene_{scene:02d}.mp3"
    )


def resolve_visual(job, part, scene):
    candidates = [
        job.get("asset_path"),
        job.get("output"),
        job.get("output_path"),
        job.get("visual"),
        job.get("visual_path"),
        job.get("file"),
        job.get("path"),
        f"output/visuals/part_{part:02d}/scene_{scene:02d}.png",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        path = Path(str(candidate))

        if path.exists() and path.stat().st_size > 0:
            return path

    return Path(
        f"output/visuals/part_{part:02d}/scene_{scene:02d}.png"
    )


def render_scene(visual, audio, output, fps, video_format):
    output.parent.mkdir(parents=True, exist_ok=True)

    temp_output = output.with_suffix(".tmp.mp4")

    if temp_output.exists():
        temp_output.unlink()

    video_filter = build_video_filter(video_format, fps)

    run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",

            "-loop",
            "1",
            "-i",
            str(visual),

            "-i",
            str(audio),

            "-map",
            "0:v:0",
            "-map",
            "1:a:0",

            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-tune",
            "stillimage",

            "-pix_fmt",
            "yuv420p",

            "-vf",
            video_filter,

            "-c:a",
            "aac",
            "-b:a",
            "128k",

            "-shortest",
            "-movflags",
            "+faststart",

            str(temp_output),
        ]
    )

    if not temp_output.exists() or temp_output.stat().st_size < 1000:
        raise RuntimeError(
            f"FFmpeg failed to create valid video: {output}"
        )

    os.replace(temp_output, output)


def create_part_video(part, scene_records):
    scene_records = sorted(
        scene_records,
        key=lambda item: item["scene"],
    )

    concat_file = PARTS_OUT / f"part_{part:02d}_concat.txt"
    output = PARTS_OUT / f"part_{part:02d}.mp4"
    temp_output = output.with_suffix(".tmp.mp4")

    lines = []

    for record in scene_records:
        scene_path = Path(record["video"]).resolve()

        if not valid_video(scene_path):
            raise SystemExit(
                f"ERROR: Invalid scene video: {scene_path}"
            )

        escaped = str(scene_path).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")

    concat_file.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    if temp_output.exists():
        temp_output.unlink()

    run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(temp_output),
        ]
    )

    if not temp_output.exists():
        raise RuntimeError(
            f"Part video was not created: {output}"
        )

    os.replace(temp_output, output)

    if not valid_video(output):
        raise RuntimeError(
            f"Part video validation failed: {output}"
        )

    duration = probe_duration(output)

    print(
        f"PART COMPLETE: Part {part} | "
        f"{output} | {duration}s"
    )

    return output, duration


def main():
    print("==============================================")
    print("          LOK AI VIDEO RENDERER")
    print("==============================================")

    video_format = read_config("FORMAT", "short")

    try:
        fps = int(read_config("FPS", "24"))
    except ValueError:
        fps = 24

    if fps <= 0:
        fps = 24

    width, height = get_output_geometry(video_format)

    print(f"FORMAT : {video_format}")
    print(f"SIZE   : {width}x{height}")
    print(f"FPS    : {fps}")
    print()

    narration = load_json(NARRATION)
    visuals = load_json(VISUALS)

    # IMPORTANT:
    # Do NOT require narration["status"] == "completed".
    # The TTS manifest may use a different top-level schema.
    audio_jobs = build_job_map(narration)
    visual_jobs = build_job_map(visuals)

    # If the TTS manifest does not expose completed job status,
    # discover actual audio files directly from the expected paths.
    if not audio_jobs:
        print(
            "WARNING: No completed audio jobs detected "
            "from manifest status."
        )

        for audio_path in sorted(
            Path("output/narration/audio").glob(
                "part_*/scene_*.mp3"
            )
        ):
            try:
                part = int(
                    audio_path.parent.name.split("_")[1]
                )
                scene = int(
                    audio_path.stem.split("_")[1]
                )
            except (IndexError, ValueError):
                continue

            if audio_path.stat().st_size > 0:
                audio_jobs[(part, scene)] = {
                    "part": part,
                    "scene": scene,
                    "status": "completed",
                    "output": str(audio_path),
                }

    # Same fallback for visuals.
    if not visual_jobs:
        print(
            "WARNING: No completed visual jobs detected "
            "from manifest status."
        )

        for visual_path in sorted(
            Path("output/visuals").glob(
                "part_*/scene_*.png"
            )
        ):
            try:
                part = int(
                    visual_path.parent.name.split("_")[1]
                )
                scene = int(
                    visual_path.stem.split("_")[1]
                )
            except (IndexError, ValueError):
                continue

            if visual_path.stat().st_size > 0:
                visual_jobs[(part, scene)] = {
                    "part": part,
                    "scene": scene,
                    "status": "completed",
                    "asset_path": str(visual_path),
                }

    if not audio_jobs:
        raise SystemExit(
            "ERROR: No usable TTS audio files found."
        )

    if not visual_jobs:
        raise SystemExit(
            "ERROR: No usable visual files found."
        )

    print(f"Audio scenes detected  : {len(audio_jobs)}")
    print(f"Visual scenes detected : {len(visual_jobs)}")
    print()

    SCENES_OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    PARTS_OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    scene_records = []

    for key in sorted(audio_jobs):
        part, scene = key

        if key not in visual_jobs:
            raise SystemExit(
                f"ERROR: Missing visual for "
                f"Part {part} Scene {scene}"
            )

        audio = resolve_audio(
            audio_jobs[key],
            part,
            scene,
        )

        visual = resolve_visual(
            visual_jobs[key],
            part,
            scene,
        )

        if not audio.exists():
            raise SystemExit(
                f"ERROR: Audio missing: {audio}"
            )

        if not visual.exists():
            raise SystemExit(
                f"ERROR: Visual missing: {visual}"
            )

        output = (
            SCENES_OUT
            / f"part_{part:02d}"
            / f"scene_{scene:02d}.mp4"
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        print(
            f"SCENE: Part {part} / Scene {scene}"
        )

        if valid_video(output):
            print(
                f"SKIP existing valid video: {output}"
            )
        else:
            render_scene(
                visual=visual,
                audio=audio,
                output=output,
                fps=fps,
                video_format=video_format,
            )

        duration = probe_duration(output)

        scene_records.append(
            {
                "part": part,
                "scene": scene,
                "video": str(output),
                "audio": str(audio),
                "visual": str(visual),
                "duration": duration,
            }
        )

    parts = sorted(
        {
            record["part"]
            for record in scene_records
        }
    )

    part_outputs = []

    for part in parts:
        records = [
            record
            for record in scene_records
            if record["part"] == part
        ]

        output, duration = create_part_video(
            part,
            records,
        )

        part_outputs.append(
            {
                "part": part,
                "output": str(output),
                "duration": duration,
                "scenes": len(records),
            }
        )

    manifest = {
        "status": "completed",
        "format": video_format,
        "width": width,
        "height": height,
        "fps": fps,
        "total_scenes": len(scene_records),
        "total_parts": len(part_outputs),
        "parts": part_outputs,
        "scenes": scene_records,
    }

    MANIFEST_OUT.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print()
    print("==============================================")
    print(
        f"VIDEO RENDERING COMPLETED"
    )
    print(
        f"Scenes : {len(scene_records)}"
    )
    print(
        f"Parts  : {len(part_outputs)}"
    )
    print(
        f"Output : {MANIFEST_OUT}"
    )
    print("==============================================")


if __name__ == "__main__":
    main()
