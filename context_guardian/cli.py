"""Command-line interface for local inspection and guidance generation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .bridge import run_protocol
from .inspector import ContextGuardian
from .models import ConversationMessage, ReviewDecision
from .providers import ProviderError, provider_from_name
from .verification import verify_file


def _load_messages(path: Path) -> list[ConversationMessage]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("messages", [])
    if not isinstance(data, list):
        raise ValueError('conversation file must contain a JSON array or {"messages": [...]}')
    return [ConversationMessage.model_validate(item) for item in data]


def _print_result(result) -> None:
    print("Context Guardian")
    print(f"{len(result.candidates)} candidates detected.")
    print(f"Auto Keep: {len(result.auto_keep)}")
    print(f"Auto Drop: {len(result.auto_drop)}")
    print(f"Review: {len(result.review)}")
    if result.review:
        print("\nReview candidates:")
        for candidate in result.review:
            print(f"\n[{candidate.category.value}] {candidate.content}")
            print(f"  importance={candidate.importance:.2f} confidence={candidate.confidence:.2f}")
            if candidate.reason:
                print(f"  reason: {candidate.reason}")


def _interactive_decisions(result) -> list[ReviewDecision]:
    decisions: list[ReviewDecision] = []
    try:
        tty = open("/dev/tty", "r+", encoding="utf-8", buffering=1)
    except OSError:
        tty = None

    if tty is None:
        for candidate in result.review:
            try:
                answer = input(f"\nKeep this candidate? [Y/n] {candidate.content}\n> ").strip().lower()
            except EOFError:
                answer = ""
            action = "drop" if answer in {"n", "no", "d", "drop"} else "keep"
            decisions.append(ReviewDecision(candidate_id=candidate.id, action=action))
        return decisions

    with tty:
        tty.write(f"\nContext Guardian: {len(result.review)} candidate(s) need review.\n")
        for candidate in result.review:
            tty.write(f"\n{candidate.content}\nKeep this candidate? [Y/n] ")
            answer = tty.readline().strip().lower()
            action = "drop" if answer in {"n", "no", "d", "drop"} else "keep"
            decisions.append(ReviewDecision(candidate_id=candidate.id, action=action))
    return decisions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="context-guardian")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="inspect a conversation JSON file")
    inspect.add_argument("conversation", type=Path, nargs="?", help="JSON file; omit for stdin")
    inspect.add_argument("--provider", choices=["rules", "openai"], default="rules")
    inspect.add_argument("--json", action="store_true", dest="as_json")
    inspect.add_argument("--review", action="store_true", help="interactively decide review candidates")

    review = subparsers.add_parser("review", help="inspect a conversation and review uncertain candidates")
    review.add_argument("conversation", type=Path, nargs="?", help="JSON file; omit for stdin")
    review.add_argument("--provider", choices=["rules", "openai"], default="rules")
    review.add_argument("--json", action="store_true", dest="as_json")

    protocol = subparsers.add_parser("bridge", help="run the JSONL adapter bridge")
    protocol.add_argument("--stdio", action="store_true", help="read and write JSONL on stdio")

    verify = subparsers.add_parser("verify", help="run the deterministic no-key release fixture")
    verify.add_argument("conversation", type=Path, help="JSON fixture to verify")
    verify.add_argument("--json", action="store_true", dest="as_json")

    checkpoint = subparsers.add_parser(
        "checkpoint", help="review a conversation and write a portable context checkpoint"
    )
    checkpoint.add_argument("conversation", type=Path, nargs="?", help="JSON file; omit for stdin")
    checkpoint.add_argument(
        "--output",
        type=Path,
        default=Path(".agents/context-guardian.md"),
        help="Markdown checkpoint path (default: .agents/context-guardian.md)",
    )
    checkpoint.add_argument("--provider", choices=["rules", "openai"], default="rules")
    checkpoint.add_argument(
        "--review-mode",
        choices=["interactive", "keep", "drop"],
        default=os.getenv("CONTEXT_GUARDIAN_REVIEW_MODE", "interactive"),
        help="review uncertain candidates interactively or resolve them deterministically",
    )
    checkpoint.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "bridge":
        return run_protocol()

    try:
        if args.command == "verify":
            verification = verify_file(args.conversation)
            if args.as_json:
                print(json.dumps(verification, ensure_ascii=False, indent=2))
            else:
                status = "PASS" if verification["passed"] else "FAIL"
                print(f"Context Guardian verification: {status}")
                for name, passed in verification["checks"].items():
                    print(f"  {'PASS' if passed else 'FAIL'} {name}")
                print(json.dumps(verification["metrics"], ensure_ascii=False, indent=2))
            return 0 if verification["passed"] else 1

        if args.command == "checkpoint":
            if args.conversation:
                messages = _load_messages(args.conversation)
            else:
                data = json.load(sys.stdin)
                items = data.get("messages", []) if isinstance(data, dict) else data
                if not isinstance(items, list):
                    raise ValueError('stdin must contain a JSON array or {"messages": [...]}')
                messages = [ConversationMessage.model_validate(item) for item in items]

            guardian = ContextGuardian(provider=provider_from_name(args.provider))
            result = guardian.inspect_with_fallback(messages)
            if args.review_mode == "interactive":
                decisions = _interactive_decisions(result)
            else:
                action = "keep" if args.review_mode == "keep" else "drop"
                decisions = [ReviewDecision(candidate_id=item.id, action=action) for item in result.review]
            checkpoint = guardian.build_checkpoint(result.candidates, decisions)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(checkpoint.text + "\n", encoding="utf-8")
            if args.as_json:
                print(
                    json.dumps(
                        {
                            "inspection": result.model_dump(mode="json"),
                            "decisions": [item.model_dump(mode="json") for item in decisions],
                            "checkpoint": checkpoint.model_dump(mode="json"),
                            "output": str(args.output),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(f"Context Guardian checkpoint written to {args.output}")
                print(f"Reviewed {len(decisions)} uncertain candidate(s).")
            return 0

        if args.conversation:
            messages = _load_messages(args.conversation)
        else:
            data = json.load(sys.stdin)
            items = data.get("messages", []) if isinstance(data, dict) else data
            if not isinstance(items, list):
                raise ValueError('stdin must contain a JSON array or {"messages": [...]}')
            messages = [ConversationMessage.model_validate(item) for item in items]
        guardian = ContextGuardian(provider=provider_from_name(args.provider))
        result = guardian.inspect(messages)
        interactive = getattr(args, "review", False) or args.command == "review"
        decisions = _interactive_decisions(result) if interactive else []
        if args.as_json:
            payload = result.model_dump(mode="json")
            if decisions:
                payload["decisions"] = [decision.model_dump(mode="json") for decision in decisions]
                payload["guidance"] = guardian.build_guidance(result.candidates, decisions).model_dump(
                    mode="json"
                )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_result(result)
            if interactive:
                guidance = guardian.build_guidance(result.candidates, decisions)
                print("\n" + guidance.text)
        return 0
    except (OSError, ProviderError, ValueError, KeyboardInterrupt) as exc:
        print(f"context-guardian: {exc}", file=sys.stderr)
        return 2
