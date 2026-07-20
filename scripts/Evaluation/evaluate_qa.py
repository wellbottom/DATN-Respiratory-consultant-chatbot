"""
-----
* RAGAS metrics (faithfulness, answer_relevancy, context_precision,
  context_recall) need an LLM judge. answer_relevancy additionally needs an
  embedding backend. ROUGE needs neither.
* This dataset is synthetic, so ground truth defaults to ``evidence_span``
  (proxy). See evaluation/rag_metrics.py for the full caveat.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.embedding_pipeline.common import configure_utf8_stdio, load_project_env  # noqa: E402
from evaluation.rag_metrics import EvaluationConfig, evaluate_datasets  # noqa: E402

ALL_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall", "rouge")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dataset",
        nargs="+",
        type=str,
        default=[str(REPO_ROOT / "core" / "data" / "qa_generation_artifacts" / "main" / "vinmec_child_articles.qa.jsonl")],
        help="One or more QA JSONL dataset paths. Glob patterns (e.g. *.qa.jsonl) are expanded.",
    )
    out_group = parser.add_mutually_exclusive_group()
    out_group.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report path for a SINGLE dataset. Ignored when multiple datasets are given.",
    )
    out_group.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write one '<dataset_stem>.eval.json' report per dataset.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Evaluate at most N rows per file.")
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=None,
        help="If set with --limit, take a random sample of that size instead of the first N rows.",
    )
    parser.add_argument(
        "--metrics",
        nargs="+",
        choices=[*ALL_METRICS, "all", "ragas"],
        default=["all"],
        help="Which metrics to run. 'ragas' = the four LLM metrics, 'all' = everything.",
    )
    parser.add_argument(
        "--judge-provider",
        choices=["codexhub", "ollama"],
        default=None,
        help="LLM judge provider for RAGAS metrics (default: codexhub / deepseek-v4-pro).",
    )
    parser.add_argument(
        "--embedding-backend",
        default="siliconflow",
        help="Embedding backend for answer_relevancy (siliconflow | ollama | sentence-transformers | hashing).",
    )
    parser.add_argument("--n-reverse-questions", type=int, default=3, help="n for Answer Relevancy.")
    # Field overrides
    parser.add_argument("--question-field", default="question")
    parser.add_argument("--answer-field", default="answer")
    parser.add_argument("--context-field", default="context")
    parser.add_argument(
        "--ground-truth-field",
        default="evidence_span",
        help="Field used as ground truth for ROUGE / Context Recall (default: evidence_span).",
    )
    parser.add_argument(
        "--chunks-field",
        default=None,
        help="Row field holding a pre-ranked list of retrieved chunks (for real Context Precision).",
    )
    parser.add_argument(
        "--id-field",
        default="id",
        help="Row field used as the stable resume key (default: id).",
    )
    # Resume / checkpoint
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Ignore any existing checkpoint and evaluate every row from scratch.",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Recompute checkpoint rows whose previous record had an error.",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help="Directory for checkpoint files (default: alongside each report as <report>.partial.jsonl).",
    )
    parser.add_argument(
        "--cleanup-checkpoint",
        action="store_true",
        help="Delete the checkpoint after a report is successfully written.",
    )
    parser.set_defaults(resume=True)
    return parser.parse_args()


def _resolve_metric_flags(selected: list[str]) -> dict[str, bool]:
    chosen = set(selected)
    if "all" in chosen:
        chosen.update(ALL_METRICS)
    if "ragas" in chosen:
        chosen.update({"faithfulness", "answer_relevancy", "context_precision", "context_recall"})
    return {
        "run_faithfulness": "faithfulness" in chosen,
        "run_answer_relevancy": "answer_relevancy" in chosen,
        "run_context_precision": "context_precision" in chosen,
        "run_context_recall": "context_recall" in chosen,
        "run_rouge": "rouge" in chosen,
    }


def _expand_datasets(patterns: list[str]) -> list[Path]:
    """Expand glob patterns and de-duplicate while preserving order."""

    resolved: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        candidates = matches if matches else [pattern]
        for candidate in sorted(matches) if matches else candidates:
            path = Path(candidate)
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                resolved.append(path)
    return resolved


def _progress(done: int, total: int) -> None:
    bar_width = 30
    filled = int(bar_width * done / total) if total else bar_width
    bar = "#" * filled + "-" * (bar_width - filled)
    print(f"\r[{bar}] {done}/{total}", end="", file=sys.stderr, flush=True)
    if done == total:
        print("", file=sys.stderr, flush=True)


def _file_progress(index: int, total: int, dataset_path: Path) -> None:
    print(f"\n[{index}/{total}] {dataset_path}", file=sys.stderr, flush=True)


def _build_configs(args: argparse.Namespace, datasets: list[Path]) -> list[EvaluationConfig]:
    flags = _resolve_metric_flags(args.metrics)
    multi = len(datasets) > 1

    configs: list[EvaluationConfig] = []
    for dataset in datasets:
        if args.output_dir is not None:
            output_path = args.output_dir / f"{dataset.stem}.eval.json"
        elif multi:
            # Multiple files but no output dir: write reports next to each dataset.
            output_path = dataset.with_suffix(dataset.suffix + ".eval.json")
        else:
            output_path = args.output  # may be None (print summary only)

        checkpoint_path = None
        if args.checkpoint_dir is not None:
            checkpoint_path = args.checkpoint_dir / f"{dataset.stem}.partial.jsonl"

        configs.append(
            EvaluationConfig(
                dataset_path=dataset,
                output_path=output_path,
                checkpoint_path=checkpoint_path,
                limit=args.limit,
                sample_seed=args.sample_seed,
                question_field=args.question_field,
                answer_field=args.answer_field,
                context_field=args.context_field,
                ground_truth_field=args.ground_truth_field,
                chunks_field=args.chunks_field,
                id_field=args.id_field,
                n_reverse_questions=args.n_reverse_questions,
                embedding_backend=args.embedding_backend,
                judge_provider=args.judge_provider,
                resume=args.resume,
                retry_errors=args.retry_errors,
                cleanup_checkpoint=args.cleanup_checkpoint,
                **flags,
            )
        )
    return configs


def main() -> None:
    configure_utf8_stdio()
    load_project_env()
    args = parse_args()

    datasets = _expand_datasets(args.dataset)
    missing = [str(p) for p in datasets if not p.exists()]
    if missing:
        raise SystemExit("Dataset(s) not found:\n  " + "\n  ".join(missing))
    if not datasets:
        raise SystemExit("No datasets matched the given --dataset patterns.")

    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    configs = _build_configs(args, datasets)

    report = evaluate_datasets(
        configs,
        progress=_progress,
        file_progress=_file_progress if len(configs) > 1 else None,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report.get("files_failed"):
        # Non-zero exit so callers/CI notice partial failures, but completed
        # files are already written and checkpointed.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
