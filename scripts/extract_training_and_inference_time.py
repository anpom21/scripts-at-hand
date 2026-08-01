import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import torch
from diffusers import DDIMScheduler, UNet2DModel
from tensorboard.backend.event_processing.event_file_loader import EventFileLoader
from tqdm.auto import tqdm

from src.waste_diffuser.pipeline import Pipeline


@dataclass
class TrainingTimeSummary:
    event_file_count: int
    first_event_time_unix: float
    last_event_time_unix: float
    total_training_time_seconds: float


@dataclass
class InferenceTimeSummary:
    device: str
    num_inference_steps: int
    batch_size: int
    warmup_batches: int
    timed_batches: int
    avg_batch_time_seconds: float
    std_batch_time_seconds: float
    min_batch_time_seconds: float
    max_batch_time_seconds: float
    avg_time_per_image_seconds: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract total training time from TensorBoard event logs and benchmark "
            "per-image inference time with batched sampling."
        )
    )
    parser.add_argument("--run-dir", type=Path, required=True, help="Path to a diffusion training run directory")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="TensorBoard log directory (default: <run-dir>/logs/training)",
    )
    parser.add_argument(
        "--num-inference-steps",
        type=int,
        default=None,
        help="Denoising steps for benchmark (default: inferred from config.json or 50)",
    )
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size used for timing")
    parser.add_argument("--warmup-batches", type=int, default=1, help="Warmup batches before timing")
    parser.add_argument("--timed-batches", type=int, default=5, help="Number of measured batches")
    parser.add_argument(
        "--device",
        type=str,
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="Torch device, e.g. cuda or cpu",
    )
    parser.add_argument(
        "--class-label",
        type=int,
        default=None,
        help="Optional class label for class-conditional models",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional output JSON path (default: <run-dir>/timing_summary_<timestamp>.json)",
    )
    return parser.parse_args()


def find_event_files(log_dir: Path) -> list[Path]:
    if not log_dir.exists():
        raise FileNotFoundError(f"Log directory does not exist: {log_dir}")

    files = sorted(log_dir.rglob("events.out.tfevents.*"))
    if not files:
        raise FileNotFoundError(f"No TensorBoard event files found in: {log_dir}")
    return files


def extract_training_time(event_files: list[Path]) -> TrainingTimeSummary:
    first_time = None
    last_time = None

    for event_file in tqdm(event_files, desc="Parsing TensorBoard logs", unit="file"):
        loader = EventFileLoader(str(event_file))
        for event in loader.Load():
            wall_time = float(getattr(event, "wall_time", 0.0))
            if wall_time <= 0:
                continue

            if first_time is None or wall_time < first_time:
                first_time = wall_time
            if last_time is None or wall_time > last_time:
                last_time = wall_time

    if first_time is None or last_time is None:
        raise RuntimeError("No valid wall_time entries were found in TensorBoard event files")

    return TrainingTimeSummary(
        event_file_count=len(event_files),
        first_event_time_unix=first_time,
        last_event_time_unix=last_time,
        total_training_time_seconds=last_time - first_time,
    )


def infer_num_inference_steps(run_dir: Path) -> int:
    config_path = run_dir / "config.json"
    if not config_path.exists():
        return 50

    config = json.loads(config_path.read_text())
    params = config.get("diffusion_parameters", {})
    steps = params.get("ddpm_num_inference_steps")
    if isinstance(steps, int) and steps > 0:
        return steps
    return 50


def load_pipeline(run_dir: Path, device: str) -> Pipeline:
    unet = UNet2DModel.from_pretrained(str(run_dir), subfolder="unet")
    scheduler = DDIMScheduler.from_pretrained(str(run_dir), subfolder="scheduler")
    pipeline = Pipeline(unet=unet, scheduler=scheduler).to(device)
    pipeline.set_progress_bar_config(disable=True)
    pipeline.unet.eval()
    return pipeline


def run_one_batch(
    pipeline: Pipeline,
    batch_size: int,
    num_inference_steps: int,
    device: str,
    generator: torch.Generator,
    class_label: int | None,
) -> float:
    class_labels = None
    if class_label is not None:
        class_labels = torch.full((batch_size,), class_label, device=device, dtype=torch.long)

    if device.startswith("cuda"):
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    _ = pipeline(
        batch_size=batch_size,
        num_inference_steps=num_inference_steps,
        generator=generator,
        class_labels=class_labels,
    )
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    return time.perf_counter() - t0


def benchmark_inference(
    pipeline: Pipeline,
    batch_size: int,
    num_inference_steps: int,
    warmup_batches: int,
    timed_batches: int,
    device: str,
    class_label: int | None,
    seed: int,
) -> InferenceTimeSummary:
    num_class_embeds = getattr(pipeline.unet.config, "num_class_embeds", None)
    if num_class_embeds is None:
        resolved_class_label = None
    else:
        if class_label is None:
            print("No --class-label provided for a class-conditional model; defaulting to class 0")
            resolved_class_label = 0
        else:
            resolved_class_label = class_label

        if not (0 <= resolved_class_label < int(num_class_embeds)):
            raise ValueError(
                f"--class-label must be in [0, {int(num_class_embeds) - 1}] for this model, got {resolved_class_label}"
            )

    generator = torch.Generator(device=device).manual_seed(seed)

    for _ in tqdm(range(warmup_batches), desc="Warmup", unit="batch", disable=warmup_batches == 0):
        _ = run_one_batch(
            pipeline=pipeline,
            batch_size=batch_size,
            num_inference_steps=num_inference_steps,
            device=device,
            generator=generator,
            class_label=resolved_class_label,
        )

    batch_times = []
    for _ in tqdm(range(timed_batches), desc="Benchmark", unit="batch"):
        dt = run_one_batch(
            pipeline=pipeline,
            batch_size=batch_size,
            num_inference_steps=num_inference_steps,
            device=device,
            generator=generator,
            class_label=resolved_class_label,
        )
        batch_times.append(dt)

    avg_batch = sum(batch_times) / len(batch_times)
    variance = sum((x - avg_batch) ** 2 for x in batch_times) / len(batch_times)
    std_batch = variance ** 0.5

    return InferenceTimeSummary(
        device=device,
        num_inference_steps=num_inference_steps,
        batch_size=batch_size,
        warmup_batches=warmup_batches,
        timed_batches=timed_batches,
        avg_batch_time_seconds=avg_batch,
        std_batch_time_seconds=std_batch,
        min_batch_time_seconds=min(batch_times),
        max_batch_time_seconds=max(batch_times),
        avg_time_per_image_seconds=avg_batch / float(batch_size),
    )


def format_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def main() -> None:
    args = parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be > 0")
    if args.warmup_batches < 0:
        raise ValueError("--warmup-batches must be >= 0")
    if args.timed_batches <= 0:
        raise ValueError("--timed-batches must be > 0")

    log_dir = args.log_dir.resolve() if args.log_dir else (run_dir / "logs" / "training")
    event_files = find_event_files(log_dir)
    training_summary = extract_training_time(event_files)

    num_steps = args.num_inference_steps or infer_num_inference_steps(run_dir)
    pipeline = load_pipeline(run_dir=run_dir, device=args.device)
    inference_summary = benchmark_inference(
        pipeline=pipeline,
        batch_size=args.batch_size,
        num_inference_steps=num_steps,
        warmup_batches=args.warmup_batches,
        timed_batches=args.timed_batches,
        device=args.device,
        class_label=args.class_label,
        seed=args.seed,
    )

    summary = {
        "run_dir": str(run_dir),
        "log_dir": str(log_dir),
        "training": {
            **asdict(training_summary),
            "first_event_time_iso": format_time(training_summary.first_event_time_unix),
            "last_event_time_iso": format_time(training_summary.last_event_time_unix),
        },
        "inference": asdict(inference_summary),
    }

    print(json.dumps(summary, indent=2))

    output_path = args.output_json
    if output_path is None:
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        output_path = run_dir / f"timing_summary_{stamp}.json"
    output_path = output_path.resolve()
    output_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSaved summary to: {output_path}")


if __name__ == "__main__":
    main()