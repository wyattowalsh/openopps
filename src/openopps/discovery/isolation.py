"""Application-level isolation seams for a credential-free scout subprocess.

This module deliberately describes an application boundary, not an operating-
system sandbox. The child receives canonical bytes over standard input and
returns canonical bytes over standard output. The parent retains the sole
quarantine write capability.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType
from typing import BinaryIO, TypeVar

from openopps.discovery.canonical import CanonicalJSONError, decode_canonical_json


_SAFE_ENVIRONMENT_KEYS = frozenset({"LANG", "LC_ALL", "LC_CTYPE", "TZ"})
_SUGGESTION_FIELDS = frozenset(
    {"candidateLocator", "parserId", "providerId", "provenanceResourceIds"}
)
_WORKER_MODULE = "openopps.discovery.worker"
_PROFILE_ID_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_MAX_TRUSTED_SEED = (1 << 63) - 1
_DEFAULT_OUTPUT_RELATIVE = "worker/result.json"


class IsolationError(ValueError):
    """A bounded isolation failure that does not retain untrusted inputs."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _validate_relative_path(relative: str) -> PurePosixPath:
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or relative.endswith("/")
        or "\\" in relative
        or "%" in relative
        or "\x00" in relative
        or "//" in relative
    ):
        raise IsolationError("filesystem_containment")
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        raise IsolationError("filesystem_containment")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
        raise IsolationError("filesystem_containment")
    return posix


def _directory_open_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise IsolationError("filesystem_no_follow_unavailable")
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY


def _validate_private_directory(descriptor: int) -> None:
    identity = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(identity.st_mode)
        or stat.S_IMODE(identity.st_mode) != 0o700
        or identity.st_uid != os.getuid()
    ):
        raise IsolationError("filesystem_directory_identity")


def _validate_private_file(descriptor: int) -> None:
    identity = os.fstat(descriptor)
    if (
        not stat.S_ISREG(identity.st_mode)
        or stat.S_IMODE(identity.st_mode) != 0o600
        or identity.st_uid != os.getuid()
        or identity.st_nlink != 1
    ):
        raise IsolationError("filesystem_file_identity")


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _validate_child_directory(
    parent_descriptor: int,
    name: str,
    child_descriptor: int,
) -> None:
    try:
        path_identity = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        raise IsolationError("filesystem_directory_identity") from None
    opened_identity = os.fstat(child_descriptor)
    if not _same_identity(path_identity, opened_identity):
        raise IsolationError("filesystem_directory_identity")
    _validate_private_directory(child_descriptor)


class ApplicationFilesystem:
    """One exclusive-write capability rooted at one private quarantine directory.

    Passing ``opener`` retains the original dependency-injection seam for unit
    callers. Omitting it selects the production descriptor-relative adapter,
    which rejects links and validates exact owner-only modes at every level.
    """

    def __init__(
        self,
        *,
        root: Path,
        opener: Callable[[Path, str], AbstractContextManager[BinaryIO]] | None = None,
    ) -> None:
        candidate = Path(root)
        if not candidate.is_absolute():
            candidate = candidate.absolute()
        self.root = candidate
        self._opener = opener

    def _write_with_injected_opener(self, relative: PurePosixPath, data: bytes) -> Path:
        assert self._opener is not None
        destination = self.root.joinpath(*relative.parts)
        if not destination.is_relative_to(self.root):
            raise IsolationError("filesystem_containment")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with self._opener(destination, "xb") as stream:
                stream.write(data)
        except IsolationError:
            raise
        except Exception:
            raise IsolationError("filesystem_write") from None
        return destination

    def _open_root(self) -> int:
        if not self.root.is_absolute() or any(
            part in {"", ".", ".."} for part in self.root.parts[1:]
        ):
            raise IsolationError("filesystem_root_identity")
        try:
            descriptor = os.open(os.path.sep, _directory_open_flags())
        except OSError:
            raise IsolationError("filesystem_root_identity") from None
        try:
            components = self.root.parts[1:]
            for index, component in enumerate(components):
                try:
                    child_descriptor = os.open(
                        component,
                        _directory_open_flags(),
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    if index != len(components) - 1:
                        raise IsolationError("filesystem_root_identity") from None
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                        child_descriptor = os.open(
                            component,
                            _directory_open_flags(),
                            dir_fd=descriptor,
                        )
                    except OSError:
                        raise IsolationError("filesystem_root_identity") from None
                except OSError:
                    raise IsolationError("filesystem_root_identity") from None
                os.close(descriptor)
                descriptor = child_descriptor
            _validate_private_directory(descriptor)
        except Exception:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _open_or_create_directory(parent_descriptor: int, name: str) -> int:
        flags = _directory_open_flags()
        try:
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        except FileNotFoundError:
            try:
                os.mkdir(name, 0o700, dir_fd=parent_descriptor)
            except OSError:
                raise IsolationError("filesystem_write") from None
            try:
                descriptor = os.open(name, flags, dir_fd=parent_descriptor)
            except OSError:
                raise IsolationError("filesystem_directory_identity") from None
        except OSError:
            raise IsolationError("filesystem_directory_identity") from None
        try:
            _validate_private_directory(descriptor)
        except Exception:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _write_file(parent_descriptor: int, name: str, data: bytes) -> os.stat_result:
        if not hasattr(os, "O_NOFOLLOW"):
            raise IsolationError("filesystem_no_follow_unavailable")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=parent_descriptor)
        except OSError:
            raise IsolationError("filesystem_write") from None
        try:
            os.fchmod(descriptor, 0o600)
            _validate_private_file(descriptor)
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise IsolationError("filesystem_write")
                view = view[written:]
            os.fsync(descriptor)
            _validate_private_file(descriptor)
            return os.fstat(descriptor)
        except IsolationError:
            raise
        except OSError:
            raise IsolationError("filesystem_write") from None
        finally:
            os.close(descriptor)

    def _write_descriptor_relative(self, relative: PurePosixPath, data: bytes) -> Path:
        descriptors = [self._open_root()]
        try:
            for component in relative.parts[:-1]:
                descriptors.append(
                    self._open_or_create_directory(descriptors[-1], component)
                )
            file_identity = self._write_file(descriptors[-1], relative.parts[-1], data)
            try:
                path_identity = os.stat(
                    relative.parts[-1],
                    dir_fd=descriptors[-1],
                    follow_symlinks=False,
                )
            except OSError:
                raise IsolationError("filesystem_file_identity") from None
            if not _same_identity(path_identity, file_identity):
                raise IsolationError("filesystem_file_identity")
            for index, component in reversed(tuple(enumerate(relative.parts[:-1]))):
                _validate_child_directory(
                    descriptors[index], component, descriptors[index + 1]
                )
                os.fsync(descriptors[index + 1])
            _validate_private_directory(descriptors[0])
            reopened_root = self._open_root()
            try:
                if not _same_identity(
                    os.fstat(reopened_root), os.fstat(descriptors[0])
                ):
                    raise IsolationError("filesystem_root_identity")
            finally:
                os.close(reopened_root)
            os.fsync(descriptors[0])
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
        return self.root.joinpath(*relative.parts)

    def write_new(self, relative: str, data: bytes) -> Path:
        """Write one new private file without following any in-root link."""

        path = _validate_relative_path(relative)
        if not isinstance(data, bytes):
            raise IsolationError("filesystem_payload")
        if self._opener is not None:
            return self._write_with_injected_opener(path, data)
        return self._write_descriptor_relative(path, data)


def build_credential_free_environment(
    parent: Mapping[str, str], *, allowlist: frozenset[str]
) -> dict[str, str]:
    """Build a positive safe-key environment and force proxy/user-site isolation."""

    admitted = _SAFE_ENVIRONMENT_KEYS & allowlist
    environment = {
        key: parent[key]
        for key in sorted(admitted)
        if key in parent and isinstance(parent[key], str)
    }
    environment.update({"NO_PROXY": "*", "PYTHONNOUSERSITE": "1"})
    return environment


_RegistryValue = TypeVar("_RegistryValue")


def build_builtin_registry(
    *,
    builtins: Mapping[str, _RegistryValue],
    selected_ids: Iterable[str],
    environment: Mapping[str, str],
) -> Mapping[str, _RegistryValue]:
    """Select only explicit in-process built-ins, ignoring plugin environment."""

    del environment
    selected: dict[str, _RegistryValue] = {}
    for identifier in selected_ids:
        if identifier not in builtins or identifier in selected:
            raise IsolationError("builtin_registry_identifier")
        selected[identifier] = builtins[identifier]
    return MappingProxyType(selected)


def validate_data_only_suggestion(
    payload: object,
    *,
    admitted_resource_ids: frozenset[str],
    allowed_parser_ids: frozenset[str],
    allowed_provider_ids: frozenset[str],
) -> Mapping[str, object]:
    """Validate untrusted agent output as closed suggestion data only."""

    if not isinstance(payload, Mapping):
        raise IsolationError("suggestion_shape")
    if set(payload) != _SUGGESTION_FIELDS:
        raise IsolationError("suggestion_authority_field")
    parser_id = payload.get("parserId")
    if not isinstance(parser_id, str) or parser_id not in allowed_parser_ids:
        raise IsolationError("suggestion_parser")
    provider_id = payload.get("providerId")
    if not isinstance(provider_id, str) or provider_id not in allowed_provider_ids:
        raise IsolationError("suggestion_provider")
    provenance = payload.get("provenanceResourceIds")
    if (
        not isinstance(provenance, list)
        or not provenance
        or any(not isinstance(item, str) for item in provenance)
        or len(set(provenance)) != len(provenance)
        or not set(provenance) <= admitted_resource_ids
    ):
        raise IsolationError("suggestion_provenance")
    locator = payload.get("candidateLocator")
    if not isinstance(locator, str) or not locator:
        raise IsolationError("suggestion_locator")
    return MappingProxyType(dict(payload))


@dataclass(frozen=True, slots=True)
class ScoutLaunchRequest:
    input_bytes: bytes
    quarantine_root: Path
    parent_environment: Mapping[str, str]
    environment_allowlist: frozenset[str]
    trusted_profile_id: str = "default"
    trusted_seed: int = 0
    output_relative: str = _DEFAULT_OUTPUT_RELATIVE
    admitted_resource_ids: frozenset[str] = frozenset()
    allowed_parser_ids: frozenset[str] = frozenset()
    allowed_provider_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class ScoutProcessLimits:
    """Finite parent-enforced byte and wall-clock process limits."""

    timeout_seconds: float = 30.0
    max_input_bytes: int = 1_048_576
    max_stdout_bytes: int = 4_194_304
    max_stderr_bytes: int = 65_536

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= 300
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in (
                    self.max_input_bytes,
                    self.max_stdout_bytes,
                    self.max_stderr_bytes,
                )
            )
            or self.max_input_bytes > 16_777_216
            or self.max_stdout_bytes > 16_777_216
            or self.max_stderr_bytes > 1_048_576
        ):
            raise IsolationError("isolated_process_limits")


def _validate_trusted_arguments(request: ScoutLaunchRequest) -> None:
    if not _PROFILE_ID_RE.fullmatch(request.trusted_profile_id):
        raise IsolationError("launcher_profile")
    if (
        isinstance(request.trusted_seed, bool)
        or not isinstance(request.trusted_seed, int)
        or not 0 <= request.trusted_seed <= _MAX_TRUSTED_SEED
    ):
        raise IsolationError("launcher_seed")
    _validate_relative_path(request.output_relative)
    if (
        not isinstance(request.environment_allowlist, frozenset)
        or len(request.environment_allowlist) > 64
        or any(
            not isinstance(value, str) or not value
            for value in request.environment_allowlist
        )
    ):
        raise IsolationError("launcher_environment")
    for registry in (
        request.admitted_resource_ids,
        request.allowed_parser_ids,
        request.allowed_provider_ids,
    ):
        if (
            not isinstance(registry, frozenset)
            or len(registry) > 4096
            or any(
                not isinstance(value, str) or not value or len(value) > 256
                for value in registry
            )
        ):
            raise IsolationError("launcher_registry")


@dataclass(frozen=True, slots=True)
class _TrustedExecutable:
    argv0: str
    path: str
    device: int
    inode: int


def _trusted_executable(executable: str) -> _TrustedExecutable:
    if not isinstance(executable, str) or "\x00" in executable:
        raise IsolationError("launcher_executable")
    candidate = Path(executable)
    if not candidate.is_absolute():
        raise IsolationError("launcher_executable")
    try:
        resolved = candidate.resolve(strict=True)
        identity = resolved.stat(follow_symlinks=False)
    except OSError:
        raise IsolationError("launcher_executable") from None
    if (
        not stat.S_ISREG(identity.st_mode)
        or identity.st_uid not in {0, os.getuid()}
        or identity.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(resolved, os.X_OK)
    ):
        raise IsolationError("launcher_executable")
    # Keep argv[0] at the validated venv spelling so Python can locate its
    # pyvenv.cfg, while the subprocess ``executable`` is the exact resolved
    # target. This prevents a caller-controlled symlink substitution between
    # validation and exec without losing virtual-environment semantics.
    return _TrustedExecutable(
        argv0=os.fspath(candidate),
        path=os.fspath(resolved),
        device=identity.st_dev,
        inode=identity.st_ino,
    )


def _revalidate_executable_identity(executable: _TrustedExecutable) -> None:
    try:
        identity = os.stat(executable.path, follow_symlinks=False)
    except OSError:
        raise IsolationError("launcher_executable") from None
    if (identity.st_dev, identity.st_ino) != (executable.device, executable.inode):
        raise IsolationError("launcher_executable")


async def _read_bounded_stream(
    stream: asyncio.StreamReader,
    *,
    byte_limit: int,
    reason_code: str,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(min(65_536, byte_limit - total + 1))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > byte_limit:
            raise IsolationError(reason_code)
        chunks.append(chunk)


async def _write_stdin(stream: asyncio.StreamWriter, data: bytes) -> None:
    try:
        stream.write(data)
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        stream.close()


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=0.5)
    except TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()


async def run_fresh_scout_process(
    *,
    executable: str,
    request: ScoutLaunchRequest,
    environment: Mapping[str, str],
    limits: ScoutProcessLimits,
) -> ProcessResult:
    """Run the fixed worker module with bounded pipes and no inherited handles."""

    _validate_trusted_arguments(request)
    expected_environment = build_credential_free_environment(
        request.parent_environment,
        allowlist=request.environment_allowlist,
    )
    if dict(environment) != expected_environment:
        raise IsolationError("launcher_environment")
    trusted_executable = _trusted_executable(executable)
    if len(request.input_bytes) > limits.max_input_bytes:
        raise IsolationError("isolated_process_input_overflow")
    argv = (
        trusted_executable.argv0,
        "-I",
        "-B",
        "-m",
        _WORKER_MODULE,
        "--profile-id",
        request.trusted_profile_id,
        "--seed",
        str(request.trusted_seed),
    )
    _revalidate_executable_identity(trusted_executable)
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            executable=trusted_executable.path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.sep,
            env=dict(environment),
            close_fds=True,
            start_new_session=True,
        )
    except (OSError, ValueError):
        raise IsolationError("isolated_process_start") from None
    try:
        _revalidate_executable_identity(trusted_executable)
    except IsolationError:
        await _stop_process(process)
        raise
    if process.stdin is None or process.stdout is None or process.stderr is None:
        await _stop_process(process)
        raise IsolationError("isolated_process_pipes")
    tasks = (
        asyncio.create_task(_write_stdin(process.stdin, request.input_bytes)),
        asyncio.create_task(
            _read_bounded_stream(
                process.stdout,
                byte_limit=limits.max_stdout_bytes,
                reason_code="isolated_process_stdout_overflow",
            )
        ),
        asyncio.create_task(
            _read_bounded_stream(
                process.stderr,
                byte_limit=limits.max_stderr_bytes,
                reason_code="isolated_process_stderr_overflow",
            )
        ),
        asyncio.create_task(process.wait()),
    )
    try:
        _, stdout, _stderr, returncode = await asyncio.wait_for(
            asyncio.gather(*tasks),
            timeout=limits.timeout_seconds,
        )
    except TimeoutError:
        raise IsolationError("isolated_process_timeout") from None
    finally:
        await _stop_process(process)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    if returncode != 0:
        raise IsolationError("isolated_process_failed")
    return ProcessResult(returncode=returncode, stdout=stdout, stderr=b"")


def _validate_worker_output(stdout: bytes, *, request: ScoutLaunchRequest) -> None:
    try:
        payload = decode_canonical_json(stdout)
        input_payload = decode_canonical_json(request.input_bytes)
    except CanonicalJSONError:
        raise IsolationError("isolated_process_output") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"profileId", "result", "seed"}
        or payload.get("profileId") != request.trusted_profile_id
        or payload.get("seed") != request.trusted_seed
        or payload.get("result") != input_payload
    ):
        raise IsolationError("isolated_process_output")
    result = payload["result"]
    if (
        not isinstance(result, dict)
        or set(result) != {"suggestions"}
        or not isinstance(result.get("suggestions"), list)
    ):
        raise IsolationError("isolated_process_output")
    for suggestion in result["suggestions"]:
        try:
            validate_data_only_suggestion(
                suggestion,
                admitted_resource_ids=request.admitted_resource_ids,
                allowed_parser_ids=request.allowed_parser_ids,
                allowed_provider_ids=request.allowed_provider_ids,
            )
        except IsolationError:
            raise IsolationError("isolated_process_output") from None


async def launch_isolated_scout(
    request: ScoutLaunchRequest,
    *,
    executable: str,
    filesystem: ApplicationFilesystem,
    limits: ScoutProcessLimits | None = None,
) -> ProcessResult:
    """Invoke one fresh validated worker and retain the sole write capability.

    Process substitution is intentionally not injectable: every caller uses
    the same executable, argument, environment, pipe, timeout, validation, and
    write path.  Tests replace the lower-level process primitive when they need
    observation, without creating a second production execution contract.
    """

    if Path(request.quarantine_root).absolute() != filesystem.root:
        raise IsolationError("launcher_quarantine_root")
    if not isinstance(request.input_bytes, bytes):
        raise IsolationError("launcher_input")
    _validate_trusted_arguments(request)
    environment = build_credential_free_environment(
        request.parent_environment,
        allowlist=request.environment_allowlist,
    )
    result = await run_fresh_scout_process(
        executable=executable,
        request=request,
        environment=environment,
        limits=limits or ScoutProcessLimits(),
    )
    _validate_worker_output(result.stdout, request=request)
    filesystem.write_new(request.output_relative, result.stdout)
    return result
