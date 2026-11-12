"""Spec Kit specs derived from Telosmith records (DEC-194 prototype; design: docs/integrations/spec-kit-derive.md).

Two operations, both standard library only:

- derive: regenerate the fenced, record-derived blocks in a feature's spec.md (and, if asked, the constitution).
  Text outside the fences is never touched. A block whose body no longer matches the hash in its opening fence
  was edited by hand: derive leaves it alone and reports it, so an authored edit is never overwritten.
- drift: report mismatches between specs and records, in both directions. Report-only: it writes nothing and
  proposes provisional records as JSON for a person or agent to append (`aec append`), never appends itself.

A derived block looks like this (HTML comments, invisible when the Markdown is rendered):

    <!-- telosmith:derived block=requirements select=cited sha256=0123456789abcdef -->
    ...generated text...
    <!-- telosmith:end -->

Results are structural: a clean drift report says the cited ids, versions and generated text agree with the
records. It does not say the spec states the right requirements.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .records import Record, Store

OPEN_RE = re.compile(r"^<!-- telosmith:derived (?P<attrs>[^>]*?)\s*-->[ \t\r]*$", re.M)
END = "<!-- telosmith:end -->"
END_RE = re.compile(r"^<!-- telosmith:end -->[ \t\r]*$", re.M)  # a standalone line, never an inline mention
ATTR_RE = re.compile(r"(\w+)=(\S+)")
# id@version citation. Ids start with an uppercase letter (P0, AEC-R2, DG-RA); code: refs are unversioned.
CITE_RE = re.compile(r"(?<![\w@.])([A-Z][A-Za-z0-9_.-]*?)@(\d+)(?!\w|\.\d)")
FR_RE = re.compile(r"^\s*[-*]\s+\*\*(FR-\d+)\*\*:?\s*(.*)$", re.M)
BLOCKS = {"requirements", "constitution"}
HASH_LEN = 16  # integrity of the generated text against hand edits, not a security property


@dataclass
class Block:
    start: int        # offset of the opening fence
    body_start: int   # offset just after the opening fence's newline
    body_end: int     # offset of the end fence
    end: int          # offset just after the end fence
    attrs: dict

    @property
    def kind(self) -> str:
        return self.attrs.get("block", "")


@dataclass
class DriftFinding:
    kind: str       # unresolved-citation, superseded-citation, unrecorded-requirement, stale-block, edited-block,
    #                 unknown-block, uncovered-record
    file: str
    subject: str    # the citation, FR id, block name or record ref concerned
    message: str
    proposal: dict | None = field(default=None)


def _norm(body: str) -> str:
    """Line endings and trailing spaces don't count as edits: a CRLF checkout or an editor trimming lines must not
    freeze a block (stress-test finding, DW5N)."""
    return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n"))


def digest(body: str) -> str:
    return hashlib.sha256(_norm(body).encode("utf-8")).hexdigest()[:HASH_LEN]


def find_blocks(text: str) -> tuple[list[Block], list[str]]:
    """Fenced blocks in document order, plus problems (an opening fence with no end fence)."""
    blocks, problems, pos = [], [], 0
    while True:
        m = OPEN_RE.search(text, pos)
        if not m:
            return blocks, problems
        body_start = m.end() + 1 if text[m.end():m.end() + 1] == "\n" else m.end()
        e = END_RE.search(text, body_start)
        end_at = e.start() if e else -1
        if end_at < 0:
            problems.append(f"opening fence at offset {m.start()} has no `{END}`; ignored")
            return blocks, problems
        blocks.append(Block(m.start(), body_start, end_at, end_at + len(END), dict(ATTR_RE.findall(m.group("attrs")))))
        pos = end_at + len(END)


def authored_text(text: str, blocks: list[Block]) -> str:
    """The spec with every derived body removed: what people wrote."""
    out, pos = [], 0
    for b in blocks:
        out.append(text[pos:b.start])
        pos = b.end
    out.append(text[pos:])
    return "".join(out)


def citations(text: str) -> list[str]:
    return sorted({f"{m.group(1)}@{m.group(2)}" for m in CITE_RE.finditer(text)})


def baseline(store: Store, rid: str) -> Record | None:
    """The version a spec should show: the newest version that is not provisional, else the newest.

    A provisional version appended over a committed one (write-back) is a pending proposal, not a replacement,
    until it is promoted (Copilot review on #72). Store.latest picks by version number alone, so it is not used.
    """
    versions = [r for r in store.records if r.id == rid]
    if not versions:
        return None
    settled = [r for r in versions if r.get("epistemic") != "provisional"]
    return max(settled or versions, key=lambda r: r.version)


def pending(store: Store, r: Record) -> list[Record]:
    """Provisional versions newer than the baseline r."""
    return sorted((x for x in store.records if x.id == r.id and x.version > r.version), key=lambda x: x.version)


def _baselines(store: Store) -> list[Record]:
    return [b for b in (baseline(store, rid) for rid in sorted(store.latest)) if b is not None]


def _one_line(s: str) -> str:
    """Record text on one line, with fence markers defused so record text can never open or close a block
    (Codex review on #73)."""
    return " ".join(s.split()).replace("<!-- telosmith:", "&lt;!-- telosmith:")


def select(store: Store, attrs: dict, authored: str) -> list[Record]:
    """Requirement records a block derives from, latest version of each, sorted by id.

    select=cited (default): requirements cited by id@version in the authored text.
    select=ids:A,B : exactly these ids.  select=serves:X : requirements with a `serves` relation to any version of X.
    """
    how = attrs.get("select", "cited")
    if how == "cited":
        ids = {c.rpartition("@")[0] for c in citations(authored)}
    elif how.startswith("ids:"):
        ids = {i for i in how[4:].split(",") if i}
    elif how.startswith("serves:"):
        target = how[7:]
        ids = {r.id for r in _baselines(store)
               if any(e.get("rel") == "serves" and str(e.get("to", "")).rpartition("@")[0] == target
                      for e in r.relations)}
    else:
        raise ValueError(f"unknown select={how!r}: use cited, ids:A,B or serves:X")
    recs = [baseline(store, i) for i in ids]
    return sorted((r for r in recs if r is not None and r.type == "requirement"), key=lambda r: r.id)


def _status(r: Record) -> str:
    return r.get("epistemic") or "unstated"


def render_requirements(store: Store, recs: list[Record]) -> str:
    lines = ["_Derived from Telosmith records by `telosmith speckit derive`. Change the records, not this block;"
             " an edit here stops it from being regenerated and is reported as drift._", ""]
    if not recs:
        lines.append("_No requirement records selected._")
    for r in recs:
        lines.append(f"- **{r.ref}** ({_status(r)}): {_one_line(r.text)}")
        # Acceptance is not derived: the vocabulary has no criterion -> requirement relation (`tests` is
        # evaluation -> claim). That link needs its own contract work first (Copilot review on #72).
        for x in pending(store, r):
            lines.append(f"  - Pending: `{x.ref}` ({_status(x)}, not accepted): {_one_line(x.text)}")
        impl = sorted(store.out_edges(r, "implemented_by"))
        if impl:
            lines.append("  - Implemented by: " + ", ".join(f"`{x}`" for x in impl))
    return "\n".join(lines) + "\n"


def render_constitution(store: Store) -> str:
    """Committed purposes (latest versions) and the committed requirements that directly serve them."""
    lines = ["_Derived from Telosmith records by `telosmith speckit derive`. Change the records, not this block._", ""]
    purposes = sorted((r for r in _baselines(store) if r.type == "purpose" and _status(r) == "committed"),
                      key=lambda r: r.id)
    if not purposes:
        lines.append("_No committed purpose records._")
    for p in purposes:
        lines.append(f"### {p.ref}")
        lines.append("")
        lines.append(_one_line(p.text))
        inv = sorted((r for r in _baselines(store) if r.type == "requirement" and _status(r) == "committed"
                      and any(e.get("rel") == "serves" and str(e.get("to", "")).rpartition("@")[0] == p.id
                              for e in r.relations)), key=lambda r: r.id)
        if inv:
            lines.append("")
            lines.extend(f"- **{r.ref}**: {_one_line(r.text)}" for r in inv)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def generate(store: Store, block: Block, authored: str) -> str:
    if block.kind == "requirements":
        return render_requirements(store, select(store, block.attrs, authored))
    if block.kind == "constitution":
        return render_constitution(store)
    raise ValueError(f"unknown block={block.kind!r}")


def _fence(attrs: dict, body: str) -> str:
    a = {k: v for k, v in attrs.items() if k != "sha256"}
    a["sha256"] = digest(body)
    head = " ".join(f"{k}={v}" for k, v in a.items())
    return f"<!-- telosmith:derived {head} -->\n{body}{END}"


def new_block(kind: str, select_how: str = "cited") -> str:
    attrs = {"block": kind} if kind == "constitution" else {"block": kind, "select": select_how}
    return _fence(attrs, "")


def insert_block(text: str, kind: str) -> str:
    """Add an empty block: after the `## Requirements` heading for requirements, else at the end."""
    blk = new_block(kind)
    if kind == "requirements":
        m = re.search(r"^## Requirements[^\n]*\n", text, re.M)
        if m:
            return text[:m.end()] + "\n" + blk + "\n" + text[m.end():]
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + "\n" + blk + "\n"


@dataclass
class DeriveResult:
    text: str
    changed: list[str] = field(default_factory=list)    # blocks regenerated with new content
    skipped: list[str] = field(default_factory=list)    # hand-edited or unknown blocks left alone, with why


def derive_text(store: Store, text: str, *, insert: str | None = None) -> DeriveResult:
    """Regenerate every derived block in `text`. Pure: returns the new text and what happened."""
    if insert and not any(b.kind == insert for b in find_blocks(text)[0]):
        text = insert_block(text, insert)
    blocks, problems = find_blocks(text)
    res = DeriveResult(text, skipped=list(problems))
    crlf = "\r\n" in text  # keep the file's line endings
    authored = authored_text(text, blocks)
    out, pos = [], 0
    for i, b in enumerate(blocks):
        name = f"{b.kind or '?'}#{i + 1}"
        out.append(text[pos:b.start])
        pos = b.end
        body = text[b.body_start:b.body_end]
        if b.kind not in BLOCKS:
            res.skipped.append(f"{name}: unknown block kind; left alone")
            out.append(text[b.start:b.end])
            continue
        if b.attrs.get("sha256") != digest(body):
            res.skipped.append(f"{name}: edited by hand since it was generated (hash mismatch); left alone")
            out.append(text[b.start:b.end])
            continue
        try:
            new = generate(store, b, authored)
        except ValueError as e:
            res.skipped.append(f"{name}: {e}; left alone")
            out.append(text[b.start:b.end])
            continue
        fenced = _fence(b.attrs, new)
        if crlf:
            fenced = fenced.replace("\n", "\r\n")
        if fenced != text[b.start:b.end]:
            res.changed.append(name)
        out.append(fenced)
    out.append(text[pos:])
    res.text = "".join(out)
    return res


def proposal_for(fr: str, line: str, spec: str, actor: str | None) -> dict:
    """A provisional requirement record a person or agent may append after review. Never appended here."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", Path(spec).parent.name).strip("-").upper() or "SPEC"
    rec = {"id": f"REQ-{slug}-{fr}", "version": 1, "type": "requirement", "epistemic": "provisional",
           "text": _one_line(line), "source_note": f"proposed from {spec} {fr} by telosmith speckit drift"}
    if actor:
        rec["authored_by"] = actor
    return rec


def drift_text(store: Store, text: str, file: str, *, actor: str | None = None) -> list[DriftFinding]:
    """Spec -> records findings for one file, plus stale and edited blocks."""
    found: list[DriftFinding] = []
    blocks, problems = find_blocks(text)
    for p in problems:
        found.append(DriftFinding("unknown-block", file, "fence", p))
    authored = authored_text(text, blocks)
    for c in citations(authored):
        rid, _, v = c.rpartition("@")
        if c not in store.by_ref:
            found.append(DriftFinding("unresolved-citation", file, c, f"{c} is cited but no such record version exists"))
        elif baseline(store, rid).version > int(v):
            found.append(DriftFinding("superseded-citation", file, c,
                                      f"{c} is cited; the current baseline is {baseline(store, rid).ref}"))
    for m in FR_RE.finditer(authored):
        if not CITE_RE.search(m.group(0)):
            found.append(DriftFinding("unrecorded-requirement", file, m.group(1),
                                      f"{m.group(1)} cites no record (id@version); proposed as a provisional record",
                                      proposal_for(m.group(1), m.group(2), file, actor)))
    for i, b in enumerate(blocks):
        name = f"{b.kind or '?'}#{i + 1}"
        body = text[b.body_start:b.body_end]
        if b.kind not in BLOCKS:
            found.append(DriftFinding("unknown-block", file, name, f"block={b.kind!r} is not one derive knows"))
        elif b.attrs.get("sha256") != digest(body):
            found.append(DriftFinding("edited-block", file, name, "edited by hand since generation; derive will skip it."
                                      " Move the change into the records (a provisional record), then regenerate"))
        else:
            try:
                if _norm(generate(store, b, authored)) != _norm(body):
                    found.append(DriftFinding("stale-block", file, name, "records changed since generation; run derive"))
            except ValueError as e:
                found.append(DriftFinding("unknown-block", file, name, str(e)))
    return found


def covered_ids(store: Store, texts: list[str]) -> set[str]:
    """Record ids a set of spec files cites, or derives into a requirements block."""
    ids: set[str] = set()
    for text in texts:
        blocks, _ = find_blocks(text)
        authored = authored_text(text, blocks)
        ids |= {c.rpartition("@")[0] for c in citations(authored)}
        for b in blocks:
            if b.kind == "requirements":
                try:
                    ids |= {r.id for r in select(store, b.attrs, authored)}
                except ValueError:
                    pass
    return ids


def uncovered(store: Store, texts: list[str], *, all_requirements: bool = False) -> list[Record]:
    """Records -> spec: committed requirements no scanned spec covers.

    By default only requirements that serve something the specs cite (so one feature's report stays about that
    feature); with all_requirements, every committed requirement (use on a whole specs/ tree).
    """
    ids = covered_ids(store, texts)
    out = []
    for r in _baselines(store):
        if r.type != "requirement" or _status(r) != "committed" or r.id in ids:
            continue
        serves = {str(e.get("to", "")).rpartition("@")[0] for e in r.relations if e.get("rel") == "serves"}
        if all_requirements or serves & ids:
            out.append(r)
    return sorted(out, key=lambda r: r.id)


# ---- filesystem layer -------------------------------------------------------------------------------------------

def find_records(start: Path) -> Path | None:
    for d in [start, *start.parents]:
        p = d / ".aec" / "records.jsonl"
        if p.is_file():
            return p
    return None


def spec_files(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_file():
            out.append(p)
        elif (p / "spec.md").is_file():
            out.append(p / "spec.md")
        else:
            out.extend(sorted(p.glob("*/spec.md")))
    return out


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".telosmith-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def cmd_derive(a) -> int:
    feature = Path(a.feature_dir)
    spec = feature / "spec.md" if feature.is_dir() else feature
    if not spec.is_file():
        print(f"error: no spec.md at {feature}")
        return 2
    rec_path = Path(a.records) if a.records else find_records(spec.resolve().parent)
    if not rec_path or not rec_path.is_file():
        print("error: no .aec/records.jsonl found above the feature; pass --records")
        return 2
    store = Store.load(rec_path)
    targets = [(spec, "requirements" if a.insert else None)]
    if a.constitution:
        targets.append((Path(a.constitution), "constitution" if a.insert else None))
    would_change = False
    for path, insert in targets:
        if not path.is_file():
            print(f"error: {path} not found")
            return 2
        old = path.read_bytes().decode("utf-8")
        res = derive_text(store, old, insert=insert)
        for s in res.skipped:
            print(f"{path}: skipped {s}")
        if res.text == old:
            print(f"{path}: up to date")
            continue
        would_change = True
        what = ", ".join(res.changed) or "new block inserted"
        if a.check:
            print(f"{path}: would regenerate {what}")
        else:
            _write(path, res.text)
            print(f"{path}: regenerated {what}")
    return 1 if (a.check and would_change) else 0


def cmd_drift(a) -> int:
    files = spec_files([Path(p) for p in a.paths])
    if not files:
        print("error: no spec.md found under the given paths")
        return 2
    rec_path = Path(a.records) if a.records else find_records(files[0].resolve().parent)
    if not rec_path or not rec_path.is_file():
        print("error: no .aec/records.jsonl found; pass --records")
        return 2
    store = Store.load(rec_path)
    actor = os.environ.get("RELAYKIT_ACTOR") or None
    texts, findings = [], []
    for f in files:
        t = f.read_bytes().decode("utf-8")
        texts.append(t)
        findings.extend(drift_text(store, t, str(f), actor=actor))
    for r in uncovered(store, texts, all_requirements=a.all):
        findings.append(DriftFinding("uncovered-record", str(rec_path), r.ref,
                                     f"committed requirement {r.ref} is cited by no scanned spec"))
    if a.json:
        print(json.dumps([asdict(x) for x in findings], indent=1))
    else:
        for x in findings:
            print(f"{x.kind}: {x.file}: {x.subject}: {x.message}")
            if x.proposal:
                print("  proposal (append only after review): " + json.dumps(x.proposal, ensure_ascii=False))
        print(f"{len(findings)} finding(s) across {len(files)} spec(s); structural only: a clean report does not "
              "show the spec states the right requirements")
    return 1 if (a.exit_code and findings) else 0


def add_parser(sub) -> None:
    sk = sub.add_parser("speckit", help="derive Spec Kit spec blocks from records, and report spec/record drift")
    sk_sub = sk.add_subparsers(dest="speckit_cmd", required=True)
    d = sk_sub.add_parser("derive", help="regenerate the fenced record-derived blocks in a feature's spec.md")
    d.add_argument("feature_dir", help="feature directory (or its spec.md)")
    d.add_argument("--records", help="records file (default: nearest .aec/records.jsonl above the feature)")
    d.add_argument("--constitution", help="also regenerate derived blocks in this constitution file")
    d.add_argument("--insert", action="store_true", help="add an empty derived block where none exists, then fill it")
    d.add_argument("--check", action="store_true", help="write nothing; exit 1 if anything would change")
    r = sk_sub.add_parser("drift", help="report spec/record mismatches in both directions (writes nothing)")
    r.add_argument("paths", nargs="+", help="feature directories, spec.md files, or a specs/ root")
    r.add_argument("--records", help="records file (default: nearest .aec/records.jsonl)")
    r.add_argument("--all", action="store_true", help="report every committed requirement no scanned spec covers")
    r.add_argument("--json", action="store_true")
    r.add_argument("--exit-code", action="store_true", help="exit 1 when there are findings")


def run(a, ap) -> int:
    return cmd_derive(a) if a.speckit_cmd == "derive" else cmd_drift(a)
