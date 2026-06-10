import argparse
import asyncio
import json
from pathlib import Path

from evaluation.judge import judge_response
from evaluation.schemas import EvalCase


def load_cases(path: Path, limit: int | None) -> list[EvalCase]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [EvalCase(**json.loads(line)) for line in lines]
    return cases[:limit] if limit else cases


def print_report(results: list[dict]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r["verdict"]["overall_pass"])

    print(f"\n=== Evaluation Report ({passed}/{total} passed) ===\n")
    for row in results:
        v = row["verdict"]
        status = "PASS" if v["overall_pass"] else "FAIL"
        print(f"[{status}] {row['id']}")
        print(f"  quality: {v['quality']['score']}/5 — {v['quality']['reason']}")
        print(f"  purity:  {v['language_purity']['score']}/5 — {v['language_purity']['reason']}")
        print(f"  target:  {v['target_language_match']['score']}/5 — {v['target_language_match']['reason']}")
        print(f"  source:  {v['source_language_match']['score']}/5 — {v['source_language_match']['reason']}")
        print(f"  summary: {v['summary']}\n")


async def run(dataset: str, limit: int | None, output: str | None) -> None:
    cases = load_cases(Path(dataset), limit)
    results = []
    for case in cases:
        verdict = await judge_response(case)
        results.append({"id": case.id, "verdict": verdict.model_dump()})
    print_report(results)
    if output:
        Path(output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LLM judge on a JSONL dataset")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output")
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.limit, args.output))


if __name__ == "__main__":
    main()
