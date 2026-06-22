"""
sync-progress.py
────────────────
Reads pending-sync.json (pushed by the dashboard), updates the matching
rows in todo.md, then clears pending-sync.json so the same update is
never applied twice.

When an item reaches 100% / done, it is REMOVED from its Active section
and APPENDED to the "Completed (Last 30 Days)" table with today's date.

Runs inside a GitHub Action — no tokens or network calls needed because
both files live in the same repo checkout.

Also supports full-file replacement via todo_b64_url in pending-sync.json.
"""

import json, re, sys, datetime
from pathlib import Path

PENDING = Path("pending-sync.json")
TODO    = Path("todo.md")
TODAY   = datetime.date.today().isoformat()

# ── helpers ──────────────────────────────────────────────────────────

def progress_label(pct: int, done: bool) -> str:
    if done or pct == 100:
        return "\u2705 Done"
    if pct == 0:
        return "\u2014"
    return f"{pct}%"


def strip_markdown_links(text: str) -> str:
    """[visible](url) -> visible"""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text).strip().lower()


def extract_item_name(col0: str) -> str:
    """Pull a clean name from the first column for the Completed table."""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", col0).strip()

# ── load pending-sync.json ───────────────────────────────────────────

if not PENDING.exists():
    print("No pending-sync.json — nothing to sync.")
    sys.exit(0)

data = json.loads(PENDING.read_text("utf-8"))

# ── full-file replace mode (todo_b64_url) ────────────────────────────

if "todo_b64_url" in data:
    import urllib.request, base64 as _b64
    url = data["todo_b64_url"]
    print(f"Full-file replace mode: fetching {url}")
    with urllib.request.urlopen(url) as resp:
        raw = resp.read().decode("utf-8").strip()
    content = _b64.b64decode(raw).decode("utf-8")
    TODO.write_text(content, encoding="utf-8")
    print(f"Wrote todo.md ({len(content):,} chars)")
    PENDING.write_text(json.dumps({
        "cleared": True,
        "clearedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "mode": "todo_b64_url",
        "source": url,
    }, indent=2) + "\n", encoding="utf-8")
    print("Cleared pending-sync.json — done \u2705")
    sys.exit(0)

# ── standard progress-update mode ───────────────────────────────────

if data.get("cleared") or not data.get("items"):
    print("pending-sync.json is already cleared or empty — nothing to do.")
    sys.exit(0)

items = data["items"]
print(f'Found {len(items)} item(s) in pending-sync.json')

# ── build label -> progress lookup ────────────────────────────────────

label_map: dict[str, dict] = {}
for item_id, item in items.items():
    raw_label = item.get("label", item_id)
    key = strip_markdown_links(raw_label)
    label_map[key] = {
        "progress": progress_label(item.get("pct", 0), item.get("done", False)),
        "is_done": item.get("done", False) or item.get("pct", 0) == 100,
    }

# ── update todo.md ──────────────────────────────────────────────────

if not TODO.exists():
    print("todo.md not found in repo root — skipping update.")
    sys.exit(1)

text = TODO.read_text("utf-8")
lines = text.splitlines(keepends=True)

new_lines: list[str] = []
completed_entries: list[str] = []
updated = 0
moved   = 0

for line in lines:
    if line.startswith("|") and not re.match(r"^\|[-| ]+\|", line):
        cols = [c.strip() for c in line.strip("|\n").split("|")]
        if len(cols) >= 5:
            row_label = strip_markdown_links(cols[0])
            if row_label in label_map:
                info = label_map[row_label]
                if info["is_done"]:
                    item_name = extract_item_name(cols[0])
                    completed_entries.append(f"| {TODAY} | {item_name} |\n")
                    moved += 1
                    continue
                else:
                    cols[4] = info["progress"]
                    new_lines.append("| " + " | ".join(cols[:5]) + " |\n")
                    updated += 1
                    continue
    new_lines.append(line)

if completed_entries:
    final_lines: list[str] = []
    inserted = False
    for i, line in enumerate(new_lines):
        final_lines.append(line)
        if (not inserted
            and re.match(r"^\|[-| ]+\|", line)
            and i > 0
            and "Completed" in new_lines[i - 1]
            and "Item" in new_lines[i - 1]):
            for entry in completed_entries:
                final_lines.append(entry)
            inserted = True
    if not inserted:
        final_lines.append("\n")
        for entry in completed_entries:
            final_lines.append(entry)
    new_lines = final_lines

TODO.write_text("".join(new_lines), encoding="utf-8")
print(f'Updated {updated} row(s) in place, moved {moved} to Completed.')

# ── clear pending-sync.json ──────────────────────────────────────────

PENDING.write_text(json.dumps({
    "cleared": True,
    "clearedAt": datetime.datetime.utcnow().isoformat() + "Z",
}, indent=2) + "\n", encoding="utf-8")
print("Cleared pending-sync.json — done \u2705")
