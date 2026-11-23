import json
from pathlib import Path

from contract_review.models import Rule


def load_rules() -> list[Rule]:
    repo_root = Path(__file__).resolve().parents[2]
    rules_path = repo_root / "config" / "rules.json"

    with rules_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return [
        Rule(
            rule_id=item["rule_id"],
            policy=item["policy"],
        )
        for item in data["rules"]
    ]
