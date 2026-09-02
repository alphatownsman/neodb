"""Report soft-deleted catalog items that journal pieces still point at.

    neodb-manage shell < misc/bin/deleted_items_in_use.py

Writes a CSV to DEST_CSV (default /tmp/deleted_items_in_use.csv) and a
summary plus the actionable rows to stdout. Read-only.

A piece on such an item cannot be re-imported from an NDJSON archive:
Item.delete(soft=True) calls Item.clear(), which nulls the lookup ids and
detaches every ExternalResource, so nothing is left for the importer to
match on -- and it refuses to rebuild a local url, since an unresolved
local url means deleted rather than missing.

"resolves" is the check the importer actually makes,
Item.get_by_url(url, resolve_merge=True) followed by `not is_deleted`: a
deleted item merged into a live one still resolves and is NOT broken.
Those rows go to the CSV only, and can be ignored.

Caveat: the unresolvable count is an upper bound. The archive carries the
item's external_resources urls as they were at export time, so if the item
was deleted and an equivalent has since been re-added, the importer may
still match the record through those. That cannot be determined from here:
clear() orphaned the ExternalResource rows, so which urls belonged to this
item is no longer recorded.
"""

import csv
import os
from collections import defaultdict
from typing import NamedTuple

from catalog.models import Item
from journal.models.common import Content
from journal.models.itemlist import ListMember

DEST = os.environ.get("DEST_CSV") or "/tmp/deleted_items_in_use.csv"
PREVIEW = 40  # unresolvable rows printed to stdout; the CSV holds them all


class Row(NamedTuple):
    url: str
    uuid: str
    category: str
    type: str
    title: str
    merged_to: str
    resolves: bool
    owners: int
    pieces: str


# the same reflection journal_exists_for_item() uses for the "Item in use."
# permission check, so this matches what blocked a non-staff delete
PIECE_CLASSES = list(Content.__subclasses__()) + list(ListMember.__subclasses__())

piece_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
owner_ids: dict[int, set[int]] = defaultdict(set)

for cls in PIECE_CLASSES:
    fields = set()
    for f in cls._meta.get_fields():
        fields.add(f.name)
    if "item" not in fields:
        print(f"skipping {cls.__name__}: no item field")
        continue
    cols = ["item_id"]
    if "owner" in fields:
        cols.append("owner_id")
    for values in (
        cls.objects.filter(item__is_deleted=True).values_list(*cols).iterator()
    ):
        piece_counts[values[0]][cls.__name__] += 1
        if len(values) > 1 and values[1] is not None:
            owner_ids[values[0]].add(values[1])

print(f"classes checked: {len(PIECE_CLASSES)}")
print(f"deleted items with pieces: {len(piece_counts)}")

rows: list[Row] = []
items = Item.objects.filter(pk__in=list(piece_counts.keys())).select_related(
    "merged_to_item"
)
for item in items:
    resolved = Item.get_by_url(item.absolute_url, resolve_merge=True)
    parts = []
    for name in sorted(piece_counts[item.pk]):
        parts.append(f"{name}:{piece_counts[item.pk][name]}")
    rows.append(
        Row(
            url=item.absolute_url,
            uuid=item.uuid,
            category=str(item.category),
            type=item.__class__.__name__,
            title=item.display_title,
            merged_to=item.merged_to_item.absolute_url if item.merged_to_item else "",
            resolves=bool(resolved) and not resolved.is_deleted,
            owners=len(owner_ids[item.pk]),
            pieces=";".join(parts),
        )
    )

rows.sort(key=lambda r: (r.resolves, -r.owners, r.url))
broken = [r for r in rows if not r.resolves]

with open(DEST, "w", newline="") as fh:
    writer = csv.writer(fh)
    writer.writerow(Row._fields)
    for row in rows:
        writer.writerow(row)

print(f"unresolvable (would fail an NDJSON re-import): {len(broken)}")
print(f"resolvable via merge (harmless): {len(rows) - len(broken)}")
print(f"wrote {DEST}")

if broken:
    print("")
    print("owners\tpieces\turl\ttitle")
    for row in broken[:PREVIEW]:
        print(f"{row.owners}\t{row.pieces}\t{row.url}\t{row.title[:60]}")
    if len(broken) > PREVIEW:
        print(f"... {len(broken) - PREVIEW} more, see {DEST}")
