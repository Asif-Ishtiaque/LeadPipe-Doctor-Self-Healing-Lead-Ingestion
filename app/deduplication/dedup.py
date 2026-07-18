"""Fuzzy deduplication across name, phone, and email.

Two leads are considered the same person if they share an exact non-null
email, share an exact non-null phone (already E.164-normalized), or have a
close fuzzy name match. Within each duplicate cluster we keep the "best"
record -- the one with the fewest missing fields, breaking ties by most
recent created_at.

A naive all-pairs comparison is O(n^2), which doesn't hold up at the
100k+ lead volumes this pipeline is meant to run at. Instead we use a
union-find over exact keys (email, phone) plus a last-name-prefix bucket for
the fuzzy name pass, so fuzzy comparison only ever happens within small
same-prefix groups instead of across the whole dataset.
"""

from collections import defaultdict

from rapidfuzz import fuzz

from app.schema.canonical import Lead

NAME_MATCH_THRESHOLD = 90


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _full_name(lead: Lead) -> str:
    return f"{lead.first_name} {lead.last_name}".strip().lower()


def _completeness(lead: Lead) -> int:
    return sum(1 for v in (lead.first_name, lead.last_name, lead.email, lead.phone_e164, lead.campaign_id) if v)


def _best_key(lead: Lead) -> tuple[float, int, object]:
    # quality_score is the primary tiebreaker (leads are scored before
    # dedup runs, see app/agent/pipeline.py) -- completeness and recency
    # only matter if two leads in a cluster scored identically.
    return (lead.quality_score or 0.0, _completeness(lead), lead.created_at)


def deduplicate(leads: list[Lead]) -> tuple[list[Lead], list[Lead]]:
    """Returns (kept, marked_as_duplicate). `kept` retains the best record
    from each cluster of matching leads; every other cluster member comes
    back in `marked_as_duplicate` with status set accordingly."""
    n = len(leads)
    uf = _UnionFind(n)

    by_email: dict[str, int] = {}
    by_phone: dict[str, int] = {}
    by_name_prefix: dict[str, list[int]] = defaultdict(list)

    for i, lead in enumerate(leads):
        if lead.email:
            key = lead.email.lower()
            if key in by_email:
                uf.union(i, by_email[key])
            else:
                by_email[key] = i

        if lead.phone_e164:
            if lead.phone_e164 in by_phone:
                uf.union(i, by_phone[lead.phone_e164])
            else:
                by_phone[lead.phone_e164] = i

        prefix = (lead.last_name or "")[:3].lower()
        by_name_prefix[prefix].append(i)

    for bucket in by_name_prefix.values():
        for pos, i in enumerate(bucket):
            for j in bucket[pos + 1 :]:
                if fuzz.ratio(_full_name(leads[i]), _full_name(leads[j])) >= NAME_MATCH_THRESHOLD:
                    uf.union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters[uf.find(i)].append(i)

    kept: list[Lead] = []
    duplicates: list[Lead] = []

    for indices in clusters.values():
        cluster = [leads[i] for i in indices]
        if len(cluster) == 1:
            kept.append(cluster[0])
            continue
        best = max(cluster, key=_best_key)
        kept.append(best)
        for member in cluster:
            if member is not best:
                member.status = "duplicate"
                duplicates.append(member)

    return kept, duplicates
