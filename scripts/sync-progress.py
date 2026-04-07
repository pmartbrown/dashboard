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
"""

import json, re, sys, datetime
from pathlib import Path

PENDING = Path("pending-sync.json")
TODO    = Path("todo.md")
TODAY   = datetime.date.today().isoformat()       # e.g. 2026-04-07

# ── helpers ──────────────────────────────────────────────────────────

def progress_label(pct: int, done: bool) -> str:
    if done or pct == 100:
        return "✅ Done"
    if pct == 0:
        return "—"
    return f"{pct}%"


def strip_markdown_links(text: str) -> str:
    """[visible](url) → visible"""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text).strip().lower()


def extract_item_name(col0: str) -> str:
    """Pull a clean name from the first column for the Completed table."""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", col0).strip()

# ── load pending-sync.json ───────────────────────────────────────────

if not PENDING.exists():
    print("No pending-sync.json — nothing to sync.")
    sys.exit(0)

data = json.loads(PENDING.read_text("utf-8"))

if data.get("cleared") or not data.get("items"):
    print("pending-sync.json is already cleared or empty — nothing to do.")
    sys.exit(0)

items = data["items"]
print(f'Found {len(items)} item(s) in pending-sync.json')

# ── build label → progress lookup ────────────────────────────────────

label_map: dict[str, dict] = {}
for item_id, item in items.items():
    raw_label = item.get("label", item_id)
    key = strip_markdown_links(raw_label)
    label_map[key] = {
        "progress": progress_label(item.get("pct", 0), item.get("done", False)),
        "is_done": item.get("done", False) or item.get("pct", 0) == 100,
    }

# ── update todo.md ───────────────────────────────────────────────────

if not TODO.exists():
    print("todo.md not found in repo root — skipping update.")
    sys.exit(1)

text = TODO.read_text("utf-8")
lines = text.splitlines(keepends=True)

new_lines: list[str] = []
completed_entries: list[str] = []   # rows to append to Completed table
updated = 0
moved   = 0

for line in lines:
    # Match table rows (skip separator rows like |---|---|)
    if line.startswith("|") and not re.match(r"^\|[-| ]+\|", line):
        cols = [c.strip() for c in line.strip("|\n").split("|")]
        if len(cols) >= 5:
            row_label = strip_markdown_links(cols[0])
            if row_label in label_map:
                info = label_map[row_label]
                if info["is_done"]:
                    # Move to completed — don't keep the row here
                    item_name = extract_item_name(cols[0])
                    completed_entries.append(
                        f"| {TODAY} | {item_name} |\n"
                    )
                    moved += 1
                    continue          # skip this line (remove from Active)
                else:
                    # Update progress in place
                    cols[4] = info["progress"]
                    new_lines.append("| " + " | ".join(cols[:5]) + " |\n")
                    updated += 1
                    continue
    new_lines.append(line)

# ── insert completed entries into the Completed table ────────────────

if completed_entries:
    final_lines: list[str] = []
    inserted = False
    for i, line in enumerate(new_lines):
        final_lines.append(line)
        # Find the Completed section's table header row
        if (not inserted
            and re.match(r"^\|[-| ]+\|", line)
            and i > 0
            and "Completed" in new_lines[i - 1]
            and "Item" in new_lines[i - 1]):
            # Insert new completed rows right after the separator
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

cleared_payload = {
    "cleared": True,
    "clearedAt": datetime.datetime.utcnow().isoformat() + "Z",
}
PENDING.write_text(json.dumps(cleared_payload, indent=2) + "\n", encoding="utf-8")
print("Cleared pending-sync.json — done ✅")
