import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENT_FILE = Path(os.environ["GITHUB_EVENT_PATH"])
REPORT_FILE = ROOT / "data" / "reports.json"

# Approximate city-center coordinates for initial regional filtering.
STORES = {
    "Walmart — Staunton, VA": {
        "name": "Walmart", "city": "Staunton", "state": "VA",
        "lat": 38.1496, "lon": -79.0717
    },
    "GameStop — Staunton, VA": {
        "name": "GameStop", "city": "Staunton", "state": "VA",
        "lat": 38.1496, "lon": -79.0717
    },
    "Walmart — Waynesboro, VA": {
        "name": "Walmart", "city": "Waynesboro", "state": "VA",
        "lat": 38.0685, "lon": -78.8895
    },
    "Target — Waynesboro, VA": {
        "name": "Target", "city": "Waynesboro", "state": "VA",
        "lat": 38.0685, "lon": -78.8895
    },
    "GameStop — Waynesboro, VA": {
        "name": "GameStop", "city": "Waynesboro", "state": "VA",
        "lat": 38.0685, "lon": -78.8895
    },
    "Walmart — Harrisonburg, VA": {
        "name": "Walmart", "city": "Harrisonburg", "state": "VA",
        "lat": 38.4496, "lon": -78.8689
    },
    "Target — Harrisonburg, VA": {
        "name": "Target", "city": "Harrisonburg", "state": "VA",
        "lat": 38.4496, "lon": -78.8689
    },
    "GameStop — Harrisonburg, VA": {
        "name": "GameStop", "city": "Harrisonburg", "state": "VA",
        "lat": 38.4496, "lon": -78.8689
    },
    "Best Buy — Harrisonburg, VA": {
        "name": "Best Buy", "city": "Harrisonburg", "state": "VA",
        "lat": 38.4496, "lon": -78.8689
    },
}


def section(body, heading):
    pattern = (
        r"^### " + re.escape(heading)
        + r"\s*\n(.*?)(?=^### |\Z)"
    )
    match = re.search(pattern, body or "", re.M | re.S)

    if not match:
        return ""

    value = match.group(1).strip()

    if value in ("_No response_", "_No response_\n"):
        return ""

    return value


def main():
    event = json.loads(
        EVENT_FILE.read_text(encoding="utf-8")
    )

    issue = event.get("issue", {})
    body = issue.get("body") or ""

    store_choice = section(body, "Store")
    other_store = section(
        body,
        "Other store name and full street address"
    )

    known_store = STORES.get(store_choice)

    if known_store:
        store = dict(known_store)
        store["label"] = store_choice
    else:
        store = {
            "name": other_store or "Unlisted store",
            "city": "",
            "state": "",
            "lat": None,
            "lon": None,
            "label": store_choice or "Unlisted store",
        }

    created = (
        issue.get("created_at")
        or datetime.now(timezone.utc).isoformat()
    )

    report = {
        "id": issue.get("number"),
        "issue_url": issue.get("html_url", ""),
        "created_at": created,
        "updated_at": issue.get("updated_at") or created,
        "game": section(body, "Game"),
        "product": section(body, "Product"),
        "store": store,
        "report_type": section(body, "What did you find?"),
        "quantity": section(body, "Quantity seen (optional)"),
        "details": section(body, "Additional details (optional)"),
        "verification": "Unverified community report",
        "issue_state": issue.get("state", "open"),
    }

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        payload = json.loads(
            REPORT_FILE.read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {
            "last_updated": None,
            "reports": []
        }

    reports = [
        item for item in payload.get("reports", [])
        if item.get("id") != report["id"]
    ]

    reports.append(report)

    reports.sort(
        key=lambda item: item.get("created_at", ""),
        reverse=True
    )

    payload["reports"] = reports[:1000]
    payload["last_updated"] = (
        datetime.now(timezone.utc).isoformat()
    )

    REPORT_FILE.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False
        ) + "\n",
        encoding="utf-8"
    )

    print(f"Published report #{report['id']}")


if __name__ == "__main__":
    main()
