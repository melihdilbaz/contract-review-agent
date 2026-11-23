import argparse
import json
import sys

from pathlib import Path

from contract_review.pipeline import (
    review_contract_v0,
    review_contract_v1,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contract-review",
        description="Local contract review agent.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # --------------------------------------------------
    # REVIEW SUBCOMMAND
    # --------------------------------------------------

    review_parser = subparsers.add_parser(
        "review",
        help="Review a contract against company policies.",
    )

    review_parser.add_argument(
        "--version",
        choices=["v0", "v1", "v2"],
        default="v2",
        help="Review pipeline version (default: v2).",
    )

    review_parser.add_argument(
        "--contract",
        required=True,
        type=Path,
        help="Path to the contract text file.",
    )

    # --------------------------------------------------
    # EVAL SUBCOMMAND
    # --------------------------------------------------

    eval_parser = subparsers.add_parser(
        "eval",
        help="Evaluate a pipeline against the fixed dataset.",
    )

    eval_parser.add_argument(
        "--version",
        choices=["v0", "v1", "v2", "all"],
        required=True,
        help="Evaluation pipeline version.",
    )

    eval_parser.add_argument(
        "--mode",
        choices=["report", "live"],
        default="report",
        help="Read saved results (default) or run live inference.",
    )

    return parser


def run_review(args: argparse.Namespace) -> int:
    try:
        contract_text = args.contract.read_text(
            encoding="utf-8"
        )

        if args.version == "v0":
            result, metadata = review_contract_v0(
                contract_text=contract_text,
                contract_source=str(args.contract),
            )

        elif args.version == "v1":
            result, metadata = review_contract_v1(
                contract_text=contract_text,
                contract_source=str(args.contract),
            )

        elif args.version == "v2":
            from contract_review.pipeline_v2 import review_contract_v2

            result, metadata = review_contract_v2(
                contract_text=contract_text,
                contract_source=str(args.contract),
            )

        else:
            print(
                f"Unsupported review version: {args.version}",
                file=sys.stderr,
            )
            return 2

    except Exception as exc:
        print(
            "Contract review failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "Check local audit logs for details.",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "version": args.version,
                "contract": str(args.contract),
                "result": result.model_dump(),
                "metadata": metadata,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    return 0


def run_eval_command(args: argparse.Namespace) -> int:
    try:
        from contract_review.run_eval import (
            RESULTS_DIR,
            run_eval,
        )

        if args.mode == "report":
            versions = (
                ["v0", "v1", "v2"]
                if args.version == "all"
                else [args.version]
            )

            reports = {}

            for version in versions:
                path = RESULTS_DIR / f"{version}.json"

                if not path.exists():
                    raise FileNotFoundError(
                        f"Missing saved evaluation: {path}"
                    )

                saved = json.loads(
                    path.read_text(encoding="utf-8")
                )

                if saved.get("version") != version:
                    raise ValueError(
                        f"Version mismatch in {path}"
                    )

                reports[version] = {
                    "metrics": saved["metrics"],
                    "results_path": str(path),
                }

            output = {
                "mode": "report",
                "reports": reports,
                "comparison_note": (
                    "Saved V0/V1 results and V2 live extraction "
                    "results are not a controlled paired comparison. "
                    "For the frozen V0/V1 paired experiment, see "
                    "eval/results/paired_v0_v1.json."
                ),
            }

        else:
            if args.version == "all":
                raise ValueError(
                    "Live mode requires one version: v0, v1 or v2."
                )

            if args.version == "v2":
                from contract_review.run_eval_v2 import (
                    run_v2_eval,
                )
                result, output_path = run_v2_eval()
            else:
                result, output_path = run_eval(args.version)

            output = {
                "mode": "live",
                "version": args.version,
                "metrics": result["metrics"],
                "results_path": str(output_path),
            }

    except Exception as exc:
        print(
            "Evaluation failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        )
    )

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "review":
        return run_review(args)

    if args.command == "eval":
        return run_eval_command(args)

    parser.error(
        f"Unsupported command: {args.command}"
    )

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
