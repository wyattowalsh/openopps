"""Durable promotion ledger, repository lock, and owned-path apply."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import stat
import time
from uuid import uuid4
from zipfile import ZipFile

from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.inventory import read_wheel_resources
from openopps.discovery.models import (
    ApplyJournal,
    ApplyJournalEntry,
    JournalFileState,
    PromotionIntent,
    PromotionLedgerEvent,
    RepositoryCASState,
)
from openopps.discovery.promotion import (
    PromotionDecisionError,
    PromotionLedgerError,
    RecoveryAction,
    append_ledger_event,
    choose_recovery_action,
    compute_promotion_intent_digest,
    transition_journal,
    validate_applied_commit,
    validate_ledger_chain,
)


LEDGER_RELATIVE_PATH = "src/openopps/discovery/data/promotion_decision_ledger.jsonl"
ENVELOPE_RELATIVE_PATH = (
    "src/openopps/discovery/data/approved_ingestion_selector_envelope.json"
)
RECEIPT_RELATIVE_PATH = (
    "src/openopps/discovery/data/evidence_only_decision_receipt.json"
)
DECISION_RELATIVE_PATH = (
    "src/openopps/discovery/data/discovery_promotion_policy_decision.json"
)
CATALOG_RELATIVE_PATH = (
    "src/openopps/providers/sources/data/portfolio_source_catalog.json"
)
GENERATED_RELATIVE_PATH = "web/lib/generated/openopps-data.json"
LOCK_RELATIVE_PATH = "var/openopps/promotion.lock"
RECOVERY_RELATIVE_ROOT = "var/openopps/promotion-recovery"
DEFAULT_OWNED_PATHS = (
    ENVELOPE_RELATIVE_PATH,
    LEDGER_RELATIVE_PATH,
    RECEIPT_RELATIVE_PATH,
)
SHARED_DELIVERY_OWNED_PATHS = (
    CATALOG_RELATIVE_PATH,
    DECISION_RELATIVE_PATH,
    ENVELOPE_RELATIVE_PATH,
    GENERATED_RELATIVE_PATH,
    LEDGER_RELATIVE_PATH,
    RECEIPT_RELATIVE_PATH,
)
READONLY_WHEEL_PATHS = {
    "policy_code": "src/openopps/source_policy.py",
    "policy_corpus": "deployment/openopps-data/source-corpus-v6.json",
    "policy_evidence": (
        "src/openopps/providers/sources/data/source_policy_evidence.json"
    ),
    "policy_schema": (
        "src/openopps/providers/sources/data/source_policy_evidence.schema.json"
    ),
    "discovery_schemas": "src/openopps/discovery/data/manifest.json",
}
SHARED_DELIVERY_WHEEL_MEMBERS = {
    "catalog": CATALOG_RELATIVE_PATH,
    "decision": DECISION_RELATIVE_PATH,
    "discovery_schemas": READONLY_WHEEL_PATHS["discovery_schemas"],
    "envelope": ENVELOPE_RELATIVE_PATH,
    "generated": GENERATED_RELATIVE_PATH,
    "ledger": LEDGER_RELATIVE_PATH,
    "policy_code": READONLY_WHEEL_PATHS["policy_code"],
    "policy_corpus": READONLY_WHEEL_PATHS["policy_corpus"],
    "policy_evidence": READONLY_WHEEL_PATHS["policy_evidence"],
    "policy_schema": READONLY_WHEEL_PATHS["policy_schema"],
    "receipt": RECEIPT_RELATIVE_PATH,
}
MAINTAINER_MODE = "maintainer"
HISTORY_COMPLETE = "complete"

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Unix-only promotion lock
    _fcntl = None


class PromotionLockError(ValueError):
    """The repository promotion lock cannot be acquired or validated."""


class PromotionApplyError(ValueError):
    """Owned-path apply, staging, or recovery cannot be proven closed."""


class HistoryAvailabilityError(PromotionLedgerError):
    """Reachable repository history is missing, shallow, or inconsistent."""


class ApplyInterrupt(RuntimeError):
    """Test-only crash cut injected after a named apply step."""

    def __init__(self, step: str) -> None:
        super().__init__("apply interrupted")
        self.step = step


@dataclass(frozen=True, slots=True)
class PromotionLayout:
    ledger: str = LEDGER_RELATIVE_PATH
    envelope: str = ENVELOPE_RELATIVE_PATH
    receipt: str = RECEIPT_RELATIVE_PATH
    decision: str = DECISION_RELATIVE_PATH
    catalog: str = CATALOG_RELATIVE_PATH
    generated: str = GENERATED_RELATIVE_PATH
    lock: str = LOCK_RELATIVE_PATH
    recovery_root: str = RECOVERY_RELATIVE_ROOT


@dataclass(frozen=True, slots=True)
class StagedAfterTree:
    root: Path
    after_bytes: Mapping[str, bytes]
    entries: tuple[ApplyJournalEntry, ...]


def require_maintainer_mutation(invocation_mode: str) -> None:
    """Scout, verify, preview, CI, and agents cannot mutate promotion state."""

    if invocation_mode != MAINTAINER_MODE:
        raise PromotionDecisionError(
            "only maintainer invocation may reserve, apply, recover, or revoke"
        )


def _maybe_crash(step: str, crash_at: str | None) -> None:
    if crash_at is not None and crash_at == step:
        raise ApplyInterrupt(step)


def _validate_relative(path: str) -> PurePosixPath:
    components = path.split("/")
    if (
        not path
        or path.startswith("/")
        or path.endswith("/")
        or "\\" in path
        or "%" in path
        or any(component in {"", ".", ".."} for component in components)
        or PurePosixPath(path).is_absolute()
    ):
        raise PromotionApplyError("owned path must be repository-relative")
    return PurePosixPath(path)


def _resolve_root(repository_root: Path) -> Path:
    root = Path(repository_root)
    if not root.is_absolute():
        root = root.absolute()
    if root.is_symlink():
        raise PromotionLockError("repository root must not be a symlink")
    if not root.is_dir():
        raise PromotionLockError("repository root must be a directory")
    return root


def _contained_path(root: Path, relative: str) -> Path:
    path = _validate_relative(relative)
    current = root
    for part in path.parts:
        if current.is_symlink():
            raise PromotionApplyError("owned path contains a symlink")
        current = current / part
        if current.exists() and current.is_symlink():
            raise PromotionApplyError("owned path contains a symlink")
    if current != root and root not in current.parents:
        raise PromotionApplyError("owned path escapes the repository root")
    return current


def encode_promotion_ledger(events: Sequence[PromotionLedgerEvent]) -> bytes:
    """Encode the canonical hash-chained JSON Lines ledger."""

    validate_ledger_chain(tuple(events), reachable_history=())
    return b"".join(
        canonical_json_bytes(event.model_dump(mode="json", by_alias=True))
        for event in events
    )


def _read_ledger_events(path: Path) -> tuple[PromotionLedgerEvent, ...]:
    raw = path.read_bytes()
    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        raise PromotionLedgerError("ledger history is incomplete")
    events: list[PromotionLedgerEvent] = []
    for line in raw.split(b"\n"):
        if not line:
            continue
        payload = decode_canonical_json(line + b"\n")
        if not isinstance(payload, dict):
            raise PromotionLedgerError("ledger event is not an object")
        events.append(
            PromotionLedgerEvent.model_validate_json(
                line + b"\n",
                strict=True,
                by_alias=True,
                by_name=False,
            )
        )
    validate_ledger_chain(tuple(events), reachable_history=())
    return tuple(events)


def load_promotion_ledger(
    path: Path,
    *,
    committed_events: Sequence[PromotionLedgerEvent] = (),
    history_status: str = HISTORY_COMPLETE,
) -> tuple[PromotionLedgerEvent, ...]:
    """Load the durable ledger and fail closed on shallow or rewritten history."""

    if history_status != HISTORY_COMPLETE:
        raise HistoryAvailabilityError("reachable history is unavailable")
    if path.exists() and path.is_symlink():
        raise PromotionLedgerError("ledger path must not be a symlink")
    events = () if not path.exists() else _read_ledger_events(path)
    committed = tuple(committed_events)
    if committed != events[: len(committed)]:
        raise HistoryAvailabilityError("reachable history is inconsistent")
    return events


def _atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise PromotionApplyError("atomic replace path must not be a symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    temporary = path.with_name(f".{path.name}.promoting")
    if temporary.exists():
        if temporary.is_symlink():
            raise PromotionApplyError("atomic replace path must not be a symlink")
        temporary.unlink()
    descriptor = os.open(temporary, flags, 0o644)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise PromotionApplyError("atomic replace write failed")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def write_promotion_ledger(path: Path, events: Sequence[PromotionLedgerEvent]) -> None:
    """Replace the ledger file with one validated canonical JSON Lines document."""

    _atomic_replace(path, encode_promotion_ledger(events))


def reject_ledger_deletion() -> None:
    raise PromotionLedgerError("whole-promotion ledger deletion is forbidden")


def _file_state(path: Path) -> JournalFileState:
    if not path.exists():
        empty = b""
        return JournalFileState(
            exists=False,
            mode=0,
            content=empty,
            sha256=sha256(empty).hexdigest(),
        )
    if path.is_symlink() or not path.is_file():
        raise PromotionApplyError("owned path must be a regular file")
    content = path.read_bytes()
    mode = stat.S_IMODE(path.stat().st_mode)
    return JournalFileState(
        exists=True,
        mode=mode,
        content=content,
        sha256=sha256(content).hexdigest(),
    )


def _journal_file_state(*, exists: bool, mode: int, content: bytes) -> JournalFileState:
    return JournalFileState(
        exists=exists,
        mode=mode,
        content=content,
        sha256=sha256(content).hexdigest(),
    )


def observe_cas_state(
    repository_root: Path,
    *,
    head_sha: str,
    catalog_fingerprint: str,
    layout: PromotionLayout = PromotionLayout(),
    owned_paths: Sequence[str] = DEFAULT_OWNED_PATHS,
) -> RepositoryCASState:
    """Read lock-time compare-and-swap identities without calling Git."""

    root = _resolve_root(repository_root)
    ledger_path = _contained_path(root, layout.ledger)
    events = () if not ledger_path.exists() else _read_ledger_events(ledger_path)
    tail = events[-1].event_digest if events else None
    recovery_root = _contained_path(root, layout.recovery_root)
    journals: list[str] = []
    if recovery_root.exists():
        if recovery_root.is_symlink() or not recovery_root.is_dir():
            raise PromotionApplyError("recovery root must be a directory")
        for child in sorted(recovery_root.iterdir()):
            journal = child / "journal.json"
            if journal.is_file() and not journal.is_symlink():
                journals.append(sha256(journal.read_bytes()).hexdigest())
    dirty = False
    for relative in owned_paths:
        candidate = _contained_path(root, relative)
        sibling = candidate.with_name(f".{candidate.name}.promoting")
        if sibling.exists():
            dirty = True
    return RepositoryCASState(
        head_sha=head_sha,
        catalog_fingerprint=catalog_fingerprint,
        ledger_tail_digest=tail,
        recovery_journal_digests=tuple(sorted(set(journals))),
        owned_paths_clean=not dirty,
    )


def compare_cas(
    observed: RepositoryCASState,
    expected: RepositoryCASState,
) -> None:
    if observed != expected:
        raise PromotionLockError("compare-and-swap state does not match")
    if not observed.owned_paths_clean:
        raise PromotionLockError("owned paths are not clean")


def _open_lock_file(root: Path, relative: str) -> tuple[int, os.stat_result]:
    path = _contained_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise PromotionLockError("lock path contains a symlink")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise PromotionLockError("lock path must be a regular file")
        listed = os.lstat(path)
        if stat.S_ISLNK(listed.st_mode):
            raise PromotionLockError("lock path must not be a symlink")
        if (opened.st_dev, opened.st_ino) != (listed.st_dev, listed.st_ino):
            raise PromotionLockError("lock inode does not match path")
        return descriptor, opened
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def acquire_promotion_lock(
    repository_root: Path,
    *,
    operation: str,
    nonce: str | None = None,
    intent_digest: str | None = None,
    layout: PromotionLayout = PromotionLayout(),
) -> Iterator[str]:
    """Acquire one nonblocking OS-native exclusive promotion lock."""

    if _fcntl is None:
        raise PromotionLockError("promotion lock requires OS-native flock")
    root = _resolve_root(repository_root)
    descriptor, _opened = _open_lock_file(root, layout.lock)
    owner = nonce or uuid4().hex
    try:
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError:
            raise PromotionLockError("promotion lock is held") from None
        metadata = canonical_json_bytes(
            {
                "intentDigest": intent_digest,
                "nonce": owner,
                "operation": operation,
                "pid": os.getpid(),
                "startNs": time.time_ns(),
            }
        )
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, metadata)
        os.fsync(descriptor)
        yield owner
    finally:
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _latest_event(
    events: Sequence[PromotionLedgerEvent],
    decision_id: str,
) -> PromotionLedgerEvent | None:
    latest: PromotionLedgerEvent | None = None
    for event in events:
        if event.decision_id == decision_id:
            latest = event
    return latest


def reserve_promotion(
    repository_root: Path,
    *,
    decision_id: str,
    intent: PromotionIntent,
    invocation_mode: str,
    head_sha: str,
    catalog_fingerprint: str,
    expected_cas: RepositoryCASState,
    committed_events: Sequence[PromotionLedgerEvent] = (),
    history_status: str = HISTORY_COMPLETE,
    layout: PromotionLayout = PromotionLayout(),
    owned_paths: Sequence[str] = DEFAULT_OWNED_PATHS,
) -> PromotionLedgerEvent:
    """Append one reserved ledger event under the repository lock."""

    require_maintainer_mutation(invocation_mode)
    root = _resolve_root(repository_root)
    with acquire_promotion_lock(
        root,
        operation="reserve",
        intent_digest=compute_promotion_intent_digest(intent),
        layout=layout,
    ):
        observed = observe_cas_state(
            root,
            head_sha=head_sha,
            catalog_fingerprint=catalog_fingerprint,
            layout=layout,
            owned_paths=owned_paths,
        )
        compare_cas(observed, expected_cas)
        ledger_path = _contained_path(root, layout.ledger)
        current = load_promotion_ledger(
            ledger_path,
            committed_events=committed_events,
            history_status=history_status,
        )
        if current != tuple(committed_events):
            raise PromotionLedgerError("reservation requires a committed ledger prefix")
        event = append_ledger_event(
            current_events=current,
            reachable_history=(),
            decision_id=decision_id,
            intent=intent,
            state="reserved",
        )
        write_promotion_ledger(ledger_path, (*current, event))
        return event


def revoke_promotion(
    repository_root: Path,
    *,
    decision_id: str,
    intent: PromotionIntent,
    invocation_mode: str,
    head_sha: str,
    catalog_fingerprint: str,
    expected_cas: RepositoryCASState,
    committed_events: Sequence[PromotionLedgerEvent] = (),
    history_status: str = HISTORY_COMPLETE,
    layout: PromotionLayout = PromotionLayout(),
) -> PromotionLedgerEvent:
    """Append one revoked ledger event under the repository lock."""

    require_maintainer_mutation(invocation_mode)
    root = _resolve_root(repository_root)
    with acquire_promotion_lock(
        root,
        operation="revoke",
        intent_digest=compute_promotion_intent_digest(intent),
        layout=layout,
    ):
        observed = observe_cas_state(
            root,
            head_sha=head_sha,
            catalog_fingerprint=catalog_fingerprint,
            layout=layout,
        )
        compare_cas(observed, expected_cas)
        ledger_path = _contained_path(root, layout.ledger)
        current = load_promotion_ledger(
            ledger_path,
            committed_events=committed_events,
            history_status=history_status,
        )
        event = append_ledger_event(
            current_events=current,
            reachable_history=(),
            decision_id=decision_id,
            intent=intent,
            state="revoked",
        )
        write_promotion_ledger(ledger_path, (*current, event))
        return event


def stage_after_tree(
    repository_root: Path,
    after_bytes: Mapping[str, bytes],
    *,
    allowlist: Sequence[str] = DEFAULT_OWNED_PATHS,
    staging_root: Path | None = None,
) -> StagedAfterTree:
    """Render one private after-tree of allowlisted owned paths."""

    root = _resolve_root(repository_root)
    allowed = frozenset(allowlist)
    if set(after_bytes) - allowed:
        raise PromotionApplyError("staged path is not in the owned allowlist")
    ordered = tuple(sorted(after_bytes))
    entries: list[ApplyJournalEntry] = []
    staging = staging_root or (root / "var/openopps/promotion-staging")
    if staging.exists() and staging.is_symlink():
        raise PromotionApplyError("staging root must not be a symlink")
    staging.mkdir(parents=True, exist_ok=True)
    for relative in ordered:
        before = _file_state(_contained_path(root, relative))
        payload = after_bytes[relative]
        after = _journal_file_state(exists=True, mode=0o644, content=payload)
        destination = _contained_path(staging, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        entries.append(
            ApplyJournalEntry(path=relative, before=before, after=after)
        )
    return StagedAfterTree(
        root=staging,
        after_bytes={key: after_bytes[key] for key in ordered},
        entries=tuple(entries),
    )


def run_generation_closure(
    runner: Callable[[Path], Mapping[str, bytes]] | None,
    staged_root: Path,
) -> Mapping[str, bytes]:
    """Run handed-off generation twice and require byte-identical output."""

    if runner is None:
        return {}
    first = dict(runner(staged_root))
    second = dict(runner(staged_root))
    if first != second:
        raise PromotionApplyError("staged generation is not byte-identical")
    return first


def build_staged_wheel(
    staged_root: Path,
    members: Mapping[str, str],
    output_path: Path,
) -> Path:
    """Build one candidate wheel zip from staged member paths."""

    with ZipFile(output_path, mode="w") as archive:
        for _logical_name, relative in sorted(members.items()):
            payload = _contained_path(staged_root, relative).read_bytes()
            archive.writestr(relative, payload)
    return output_path


def verify_wheel_identities(
    wheel_path: Path,
    expected: Mapping[str, bytes],
    member_paths: Mapping[str, str],
) -> None:
    resources = read_wheel_resources(wheel_path, member_paths)
    if set(resources) != set(expected):
        raise PromotionApplyError("wheel resource identities do not match")
    for name, payload in expected.items():
        if resources[name] != payload:
            raise PromotionApplyError("wheel resource bytes do not match")


def _journal_path(root: Path, layout: PromotionLayout, intent_digest: str) -> Path:
    return _contained_path(root, f"{layout.recovery_root}/{intent_digest}/journal.json")


def _write_journal(path: Path, journal: ApplyJournal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_replace(
        path,
        canonical_json_bytes(journal.model_dump(mode="json", by_alias=True)),
    )


def _load_journal(path: Path) -> ApplyJournal:
    payload = decode_canonical_json(path.read_bytes())
    if not isinstance(payload, dict):
        raise PromotionApplyError("apply journal is not an object")
    return ApplyJournal.model_validate_json(
        canonical_json_bytes(payload),
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _install_state(root: Path, relative: str, state: JournalFileState) -> None:
    path = _contained_path(root, relative)
    if not state.exists:
        if path.exists():
            path.unlink()
        return
    _atomic_replace(path, state.content)
    os.chmod(path, state.mode)


def _observed_path_state(
    root: Path, journal: ApplyJournal
) -> dict[str, dict[str, object]]:
    observed: dict[str, dict[str, object]] = {}
    for entry in journal.entries:
        state = _file_state(_contained_path(root, entry.path))
        observed[entry.path] = {
            "exists": state.exists,
            "mode": state.mode,
            "sha256": state.sha256,
        }
    return observed


def apply_promotion(
    repository_root: Path,
    *,
    decision_id: str,
    intent: PromotionIntent,
    invocation_mode: str,
    head_sha: str,
    catalog_fingerprint: str,
    expected_cas: RepositoryCASState,
    after_bytes: Mapping[str, bytes],
    committed_events: Sequence[PromotionLedgerEvent],
    lock_nonce: str,
    allowlist: Sequence[str] = DEFAULT_OWNED_PATHS,
    history_status: str = HISTORY_COMPLETE,
    layout: PromotionLayout = PromotionLayout(),
    generation_runner: Callable[[Path], Mapping[str, bytes]] | None = None,
    wheel_members: Mapping[str, str] | None = None,
    readonly_wheel_bytes: Mapping[str, bytes] | None = None,
    crash_at: str | None = None,
) -> ApplyJournal:
    """Install a preverified after-tree through the fsynced apply journal."""

    require_maintainer_mutation(invocation_mode)
    root = _resolve_root(repository_root)
    intent_digest = compute_promotion_intent_digest(intent)
    with acquire_promotion_lock(
        root,
        operation="apply",
        nonce=lock_nonce,
        intent_digest=intent_digest,
        layout=layout,
    ):
        observed = observe_cas_state(
            root,
            head_sha=head_sha,
            catalog_fingerprint=catalog_fingerprint,
            layout=layout,
            owned_paths=allowlist,
        )
        compare_cas(observed, expected_cas)
        ledger_path = _contained_path(root, layout.ledger)
        current = load_promotion_ledger(
            ledger_path,
            committed_events=committed_events,
            history_status=history_status,
        )
        if current != tuple(committed_events):
            raise PromotionLedgerError("apply requires the reservation to be committed")
        reserved = _latest_event(current, decision_id)
        if reserved is None or reserved.state != "reserved":
            raise PromotionLedgerError("apply requires a reserved decision")
        if reserved.promotion_intent_digest != intent_digest:
            raise PromotionLedgerError("apply intent does not match reservation")
        applied_event = append_ledger_event(
            current_events=current,
            reachable_history=(),
            decision_id=decision_id,
            intent=intent,
            state="applied",
        )
        payload = dict(after_bytes)
        payload[layout.ledger] = encode_promotion_ledger((*current, applied_event))
        staged = stage_after_tree(
            root,
            payload,
            allowlist=allowlist,
            staging_root=root / "var/openopps/promotion-staging" / intent_digest,
        )
        generated = run_generation_closure(generation_runner, staged.root)
        if generated:
            merged = dict(staged.after_bytes)
            merged.update(generated)
            staged = stage_after_tree(
                root,
                merged,
                allowlist=allowlist,
                staging_root=staged.root,
            )
        if readonly_wheel_bytes:
            for relative, payload in readonly_wheel_bytes.items():
                destination = _contained_path(staged.root, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
        if wheel_members is not None:
            wheel_path = staged.root / "candidate.whl"
            build_staged_wheel(staged.root, wheel_members, wheel_path)
            expected_wheel = {}
            for name, relative in wheel_members.items():
                if relative in staged.after_bytes:
                    expected_wheel[name] = staged.after_bytes[relative]
                else:
                    expected_wheel[name] = _contained_path(
                        staged.root, relative
                    ).read_bytes()
            verify_wheel_identities(wheel_path, expected_wheel, wheel_members)
        journal = ApplyJournal(
            schema_version=1,
            phase="prepared",
            promotion_intent_digest=intent_digest,
            lock_nonce=lock_nonce,
            head_sha=head_sha,
            entries=staged.entries,
        )
        journal_path = _journal_path(root, layout, intent_digest)
        _write_journal(journal_path, journal)
        _maybe_crash("journal_prepared", crash_at)
        journal = transition_journal(journal, "applying")
        _write_journal(journal_path, journal)
        _maybe_crash("journal_applying", crash_at)
        for entry in journal.entries:
            _install_state(root, entry.path, entry.after)
            _maybe_crash(f"install:{entry.path}", crash_at)
        _maybe_crash("ledger_append", crash_at)
        journal = transition_journal(journal, "finalizing")
        _write_journal(journal_path, journal)
        _maybe_crash("journal_finalizing", crash_at)
        validate_applied_commit(
            journal,
            changed_paths=frozenset(entry.path for entry in journal.entries),
            reservation_parent_present=True,
        )
        journal_path.unlink()
        journal_path.parent.rmdir()
        return journal


def recover_promotion(
    repository_root: Path,
    *,
    intent: PromotionIntent,
    invocation_mode: str,
    head_sha: str,
    catalog_fingerprint: str,
    expected_cas: RepositoryCASState,
    committed_events: Sequence[PromotionLedgerEvent],
    decision_id: str,
    allowlist: Sequence[str] = DEFAULT_OWNED_PATHS,
    history_status: str = HISTORY_COMPLETE,
    layout: PromotionLayout = PromotionLayout(),
) -> RecoveryAction:
    """Finalize an exact after-tree or restore preimages and revoke."""

    require_maintainer_mutation(invocation_mode)
    root = _resolve_root(repository_root)
    intent_digest = compute_promotion_intent_digest(intent)
    with acquire_promotion_lock(
        root,
        operation="recover",
        intent_digest=intent_digest,
        layout=layout,
    ):
        observed = observe_cas_state(
            root,
            head_sha=head_sha,
            catalog_fingerprint=catalog_fingerprint,
            layout=layout,
            owned_paths=allowlist,
        )
        if (
            observed.head_sha != expected_cas.head_sha
            or observed.catalog_fingerprint != expected_cas.catalog_fingerprint
        ):
            raise PromotionLockError("compare-and-swap state does not match")
        journal_path = _journal_path(root, layout, intent_digest)
        if not journal_path.exists():
            raise PromotionApplyError("recovery journal is missing")
        journal = _load_journal(journal_path)
        action = choose_recovery_action(journal, _observed_path_state(root, journal))
        if action is RecoveryAction.FINALIZE:
            if journal.phase != "finalizing":
                journal = journal.model_copy(update={"phase": "finalizing"})
                _write_journal(journal_path, journal)
            journal_path.unlink()
            if journal_path.parent.exists():
                journal_path.parent.rmdir()
            return action
        for entry in journal.entries:
            _install_state(root, entry.path, entry.before)
        ledger_path = _contained_path(root, layout.ledger)
        current = load_promotion_ledger(
            ledger_path,
            committed_events=committed_events,
            history_status=history_status,
        )
        latest = _latest_event(current, decision_id)
        if latest is not None and latest.state != "revoked":
            event = append_ledger_event(
                current_events=current,
                reachable_history=(),
                decision_id=decision_id,
                intent=intent,
                state="revoked",
            )
            write_promotion_ledger(ledger_path, (*current, event))
        journal_path.unlink()
        if journal_path.parent.exists():
            journal_path.parent.rmdir()
        return action


def assert_zero_drift(
    repository_root: Path,
    after_bytes: Mapping[str, bytes],
    *,
    generation_runner: Callable[[Path], Mapping[str, bytes]] | None = None,
    wheel_members: Mapping[str, str] | None = None,
) -> None:
    """Post-apply generation and wheel readback must match the applied bytes."""

    root = _resolve_root(repository_root)
    for relative, payload in after_bytes.items():
        if _contained_path(root, relative).read_bytes() != payload:
            raise PromotionApplyError("post-apply path drifted")
    generated = run_generation_closure(generation_runner, root)
    for relative, payload in generated.items():
        if after_bytes.get(relative) != payload:
            raise PromotionApplyError("post-apply generation drifted")
    if wheel_members is not None:
        wheel_path = root / "var/openopps/promotion-staging/readback.whl"
        wheel_path.parent.mkdir(parents=True, exist_ok=True)
        build_staged_wheel(root, wheel_members, wheel_path)
        expected = {
            name: _contained_path(root, relative).read_bytes()
            for name, relative in wheel_members.items()
        }
        verify_wheel_identities(wheel_path, expected, wheel_members)
