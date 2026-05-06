"""Process supervisor for the bridge + brain pair.

Production entrypoint for OpenClaw on a host. Started via
``scripts/run-supervisor.sh`` (or, eventually, by launchd from inside
the Bridge.app bundle). Owns two children:

1. ``bridge``         — ``python -m bridge`` — FastAPI on 127.0.0.1:8788
2. ``brain.<agent>``  — ``python -m agent``  — agent process

The agent name comes from ``AGENT_NAME`` in the env (default ``agent``).
The Keychain actor name and the brain child's label both derive from
it, so a single supervisor process serves whatever brain identity the
operator picked at install time.

Children start sequentially: the bridge must be healthy on
``/v1/health`` before the brain comes up, so the brain's first call
does not race the FastAPI app's startup.

Crash policy: each child is restarted with exponential backoff
(``1s, 2s, 4s, …`` capped at 10s). Three restarts inside a 30s window
is a poison-pill — the supervisor logs fatal and exits non-zero,
leaving launchd to decide whether to restart the whole tree (it will,
unless ThrottleInterval has fired). This keeps us out of busy-loops
when a child is wedged on something the supervisor can't fix
(e.g. corrupt SQLite state, missing Keychain item, etc.).

Shutdown: SIGTERM/SIGINT triggers graceful shutdown — brain first
(give it up to ``_SHUTDOWN_GRACE_S`` to finish whatever message it is
currently dispatching), then bridge. Each child gets the same grace
window before SIGKILL.

Token loading: the brain child needs a ``BRAIN_TOKEN`` env var to
authenticate against the bridge. The supervisor reads
``brain.<agent>`` from Keychain at startup and injects it into the
brain's environment. If ``BRAIN_TOKEN`` is already in the supervisor's
environment, that wins (test/dev escape hatch).

Test seams: ``Supervisor.__init__`` accepts ``spawn`` and
``health_check`` callables so unit tests can avoid real subprocesses
and HTTP. Production callers use the module-level defaults.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final

from bridge import keychain
from bridge.config import Settings
from bridge.logging_setup import configure_logging

logger = logging.getLogger("bridge.supervisor")

# Health-gate settings. The supervisor's job at startup is "wait until
# the bridge's HTTP socket is accepting connections, then start the
# brain". It deliberately does NOT do an HTTP GET against /v1/health —
# that endpoint runs live probes against every dependency (Redis,
# OpenRouter, IMAP, Apple bridge, …) and can take seconds per call.
# Polling /v1/health every 250ms with a short timeout caused a
# pathological pile-up: each in-flight probe spawned a fresh OpenRouter
# HTTP call, sockets accumulated faster than they drained, the
# supervisor's probes kept timing out, the supervisor restarted the
# bridge, and the cycle repeated under launchd until system load
# averages climbed past 60 and the Mac froze (2026-05-06 incident).
#
# A pure TCP `connect()` to 127.0.0.1:8788 is sufficient: if uvicorn is
# listening, the bridge is "up enough" for the brain to start. Whether
# Redis or OpenRouter are healthy is a runtime concern surfaced via
# /v1/health, not a startup gate.
_HEALTH_TIMEOUT_S: Final[float] = 30.0
_HEALTH_POLL_INTERVAL_S: Final[float] = 1.0
_HEALTH_PROBE_TIMEOUT_S: Final[float] = 1.0
_BRIDGE_HOST: Final[str] = "127.0.0.1"
_BRIDGE_PORT: Final[int] = 8788

# Crash + shutdown policy.
_SHUTDOWN_GRACE_S: Final[float] = 10.0
_BACKOFF_INITIAL_S: Final[float] = 1.0
_BACKOFF_MAX_S: Final[float] = 10.0
_POISON_PILL_THRESHOLD: Final[int] = 3
_POISON_PILL_WINDOW_S: Final[float] = 30.0

# Exit codes: keep them stable so launchd / tests can distinguish.
EXIT_OK: Final[int] = 0
EXIT_HEALTH_TIMEOUT: Final[int] = 10
EXIT_POISON_PILL: Final[int] = 11
EXIT_KEYCHAIN_MISSING: Final[int] = 12


class SupervisorError(RuntimeError):
    """Raised when the supervisor cannot proceed (health timeout, poison pill, etc.)."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# Type aliases for the test-seam callables.
HealthCheckFn = Callable[[], Awaitable[bool]]


@dataclass
class Child:
    """One supervised subprocess.

    ``ready_check`` is an optional readiness probe — when set, the
    supervisor waits for it to return True after spawning this child
    and before spawning the next one. The order of ``Supervisor.children``
    is therefore the dependency order: e.g. ``[redis, bridge, brain]``
    where Redis must be accepting connections before the bridge starts,
    and the bridge must be accepting connections before the brain
    subscribes to the WebSocket event bus. Children with no ``ready_check``
    are spawned without waiting.
    """

    name: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    ready_check: HealthCheckFn | None = None
    # Mutable runtime state — all touched only by the supervisor coroutine
    # that owns this child, so no locking needed.
    proc: asyncio.subprocess.Process | None = None
    restart_history: list[float] = field(default_factory=list)
    backoff_s: float = _BACKOFF_INITIAL_S


SpawnFn = Callable[[Child], Awaitable[asyncio.subprocess.Process]]


async def _default_spawn(child: Child) -> asyncio.subprocess.Process:
    """Spawn a child with stderr/stdout inherited from the supervisor.

    Inheriting means launchd's ``StandardOutPath`` / ``StandardErrorPath``
    capture every line from every child, no extra plumbing needed.
    JSON-formatted lines from each component stay distinguishable via
    their own ``logger`` field.
    """
    return await asyncio.create_subprocess_exec(
        *child.argv,
        env={**os.environ, **child.env},
        # stdin closed; stdout/stderr inherited from supervisor's fds.
        stdin=asyncio.subprocess.DEVNULL,
    )


def _default_health_check_factory(
    host: str = _BRIDGE_HOST,
    port: int = _BRIDGE_PORT,
    timeout_s: float = _HEALTH_PROBE_TIMEOUT_S,
) -> HealthCheckFn:
    """Return a coroutine that does a TCP connect to ``host:port``.

    Returns True the moment uvicorn is accepting connections — fast,
    cheap, doesn't trigger any of the bridge's dependency probes. See
    the module-level comment on ``_HEALTH_TIMEOUT_S`` for why this is
    a TCP probe and not an HTTP one.
    """

    async def probe() -> bool:
        try:
            async with asyncio.timeout(timeout_s):
                _, writer = await asyncio.open_connection(host, port)
                writer.close()
                with contextlib.suppress(ConnectionResetError, BrokenPipeError):
                    await writer.wait_closed()
                return True
        except (TimeoutError, OSError):
            return False

    return probe


@dataclass
class Supervisor:
    """Owns the bridge + brain.agent lifecycle.

    Construction takes the children to run plus optional test seams.
    ``run()`` returns the process exit code.
    """

    children: list[Child]
    spawn: SpawnFn = field(default=_default_spawn)
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)
    # Sleep is patchable for fast tests.
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep)

    async def run(self) -> int:
        """Main loop. Returns the exit code the process should exit with."""
        if not self.children:
            logger.error("supervisor_no_children")
            return EXIT_OK

        self._install_signal_handlers()

        # Captured-out-of-except: PEP 654 forbids `return` from inside an
        # `except*` block, and a try cannot mix `except` and `except*`,
        # so we record the fatal error and act on it after.
        fatal: SupervisorError | None = None

        # Phase 1: startup. Each child is spawned in declaration order;
        # if it has a ready_check, we block until it returns True before
        # spawning the next. This is how Redis blocks the bridge from
        # starting (TCP probe to 6379), and the bridge blocks the brain
        # (TCP probe to 8788). Children with no ready_check launch
        # in fire-and-forget mode.
        try:
            for child in self.children:
                await self._start(child)
                if child.ready_check is not None:
                    await self._wait_ready(child)
            logger.info(
                "supervisor_started",
                extra={"children": [c.name for c in self.children]},
            )
        except SupervisorError as exc:
            fatal = exc

        # Phase 2: watch loop (TaskGroup wraps everything in ExceptionGroup).
        if fatal is None:
            try:
                async with asyncio.TaskGroup() as tg:
                    for child in self.children:
                        tg.create_task(self._watch(child), name=f"watch:{child.name}")
            except* SupervisorError as eg:
                first = eg.exceptions[0]
                if isinstance(first, SupervisorError):
                    fatal = first

        if fatal is not None:
            logger.error(
                "supervisor_aborting",
                extra={"reason": str(fatal), "exit_code": fatal.exit_code},
            )
            await self._graceful_stop_all()
            return fatal.exit_code

        await self._graceful_stop_all()
        return EXIT_OK

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._on_signal, sig.name)

    def _on_signal(self, sig_name: str) -> None:
        logger.info("supervisor_signal", extra={"signal": sig_name})
        self.shutdown_event.set()

    async def _start(self, child: Child) -> None:
        child.proc = await self.spawn(child)
        logger.info(
            "supervisor_child_started",
            extra={"child": child.name, "pid": child.proc.pid},
        )

    async def _wait_ready(self, child: Child) -> None:
        """Poll ``child.ready_check`` until it returns True or we time out.

        The probe contract: a coroutine returning ``True`` when the
        child is accepting work. For Redis it's a TCP connect to 6379;
        for the bridge it's a TCP connect to 8788. Neither does any
        application-layer work — that keeps probes fast and free of
        side-effects on dependency probes.
        """
        assert child.ready_check is not None, "_wait_ready called without a probe"
        deadline = time.monotonic() + _HEALTH_TIMEOUT_S
        attempts = 0
        while True:
            if self.shutdown_event.is_set():
                raise SupervisorError("shutdown during ready-gate", EXIT_OK)
            if await child.ready_check():
                logger.info(
                    "supervisor_child_ready",
                    extra={"child": child.name, "attempts": attempts},
                )
                return
            attempts += 1
            if time.monotonic() >= deadline:
                msg = f"{child.name} did not become ready within {_HEALTH_TIMEOUT_S}s"
                raise SupervisorError(msg, EXIT_HEALTH_TIMEOUT)
            await self.sleep(_HEALTH_POLL_INTERVAL_S)

    async def _watch(self, child: Child) -> None:
        """Watch one child. Restart on unexpected exit; bail on poison-pill.

        Returns when the shutdown event is set (and the child has been
        signalled by ``_graceful_stop_all`` from the parent).
        """
        while not self.shutdown_event.is_set():
            assert child.proc is not None, "child must be started before _watch"
            wait_task = asyncio.create_task(child.proc.wait())
            shutdown_task = asyncio.create_task(self.shutdown_event.wait())
            done, pending = await asyncio.wait(
                {wait_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

            if shutdown_task in done:
                # Shutdown takes priority — let _graceful_stop_all deliver
                # the SIGTERM. Watch loop ends here; the wait_task we just
                # cancelled may still resolve to an exit code, but that is
                # the graceful-stop coroutine's concern.
                return

            # Child exited on its own. Decide: restart or poison-pill.
            exit_code = child.proc.returncode
            logger.warning(
                "supervisor_child_exited",
                extra={"child": child.name, "exit_code": exit_code},
            )
            now = time.monotonic()
            child.restart_history = [
                t for t in child.restart_history if now - t < _POISON_PILL_WINDOW_S
            ]
            child.restart_history.append(now)
            if len(child.restart_history) >= _POISON_PILL_THRESHOLD:
                msg = (
                    f"{child.name} crashed {_POISON_PILL_THRESHOLD} times in "
                    f"{_POISON_PILL_WINDOW_S}s — giving up"
                )
                raise SupervisorError(msg, EXIT_POISON_PILL)

            await self.sleep(child.backoff_s)
            child.backoff_s = min(child.backoff_s * 2, _BACKOFF_MAX_S)
            if self.shutdown_event.is_set():
                return
            await self._start(child)

    async def _graceful_stop_all(self) -> None:
        """Send SIGTERM to children in reverse-start order, then SIGKILL on timeout."""
        # Reverse so the brain stops before the bridge it depends on.
        for child in reversed(self.children):
            await self._stop(child)

    async def _stop(self, child: Child) -> None:
        proc = child.proc
        if proc is None or proc.returncode is not None:
            return
        logger.info("supervisor_child_stopping", extra={"child": child.name})
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_GRACE_S)
        except TimeoutError:
            logger.warning(
                "supervisor_child_kill",
                extra={"child": child.name, "grace_s": _SHUTDOWN_GRACE_S},
            )
            try:
                proc.kill()
            except ProcessLookupError:
                return
            await proc.wait()


# ----------------------------------------------------------------------
# Production wiring
# ----------------------------------------------------------------------


_DEFAULT_AGENT_NAME: Final[str] = "agent"


def _agent_name() -> str:
    """Resolve the brain identifier from env. Defaults to "agent"."""
    return os.environ.get("AGENT_NAME", "").strip() or _DEFAULT_AGENT_NAME


def _load_brain_token(agent_name: str) -> str:
    """Return the brain.<agent> token from env or Keychain.

    Mirrors ``scripts/run-brain.sh``'s logic so the supervisor can
    replace it: the env var wins for tests/dev; otherwise we read the
    matching Keychain entry.
    """
    env_token = os.environ.get("BRAIN_TOKEN")
    if env_token:
        return env_token
    actor = f"brain.{agent_name}"
    cred = keychain.get_credential(actor)
    if cred is None or not cred.token:
        msg = (
            f"no Keychain credential for {actor} — mint one with: "
            f"scripts/mint-token.py --actor {actor} --scopes "
            "llm:call,vault:read,vault:write,events:subscribe,"
            "events:publish,agent:drafts:write"
        )
        raise SupervisorError(msg, EXIT_KEYCHAIN_MISSING)
    return cred.token


def _ensure_redis_password() -> str:
    """Return the Redis password from Keychain, generating one if absent.

    The bundled redis-server is started with ``--requirepass``; the
    bridge connects with the matching password (loaded by
    ``bridge.config`` from the same Keychain slot, account
    ``provider.redis``). On a fresh install the slot is empty — we
    generate a fresh secret, persist it, and use it. Subsequent boots
    pick it up from Keychain unchanged.
    """
    import secrets  # stdlib; cheap to import here rather than at module top

    cred = keychain.get_credential("provider.redis")
    if cred is not None and cred.token:
        return cred.token
    password = secrets.token_hex(32)
    keychain.set_credential("provider.redis", password, [])
    logger.info("redis_password_generated", extra={"actor": "provider.redis"})
    return password


def _bundled_redis_server() -> str | None:
    """Path to the redis-server binary inside Bridge.app's MacOS/, or None.

    Lives at ``Bridge.app/Contents/MacOS/redis-server`` when frozen
    (copied by ``bundle/bridge/build.sh``). In dev, returns None — the
    operator runs Redis externally via ``scripts/run-redis.sh``.

    Why MacOS/ and not Resources/: ``codesign --deep`` only walks the
    canonical executable directories (MacOS/, Frameworks/, PlugIns/);
    Resources/ is treated as data. A Mach-O placed in Resources/ is
    therefore never resigned during the bundle's codesign step and
    notarization rejects the bundle for that nested binary lacking
    Developer ID + secure timestamp + hardened runtime. MacOS/ is the
    canonical home for any Mach-O the bundle needs to run.
    """
    if not getattr(sys, "frozen", False):
        return None
    # ``sys.executable`` is ``Bridge.app/Contents/MacOS/OpenClawBridge``.
    # Sibling files in the same MacOS/ directory.
    macos_dir = os.path.dirname(sys.executable)
    redis_path = os.path.join(macos_dir, "redis-server")
    if os.path.exists(redis_path):
        return redis_path
    logger.warning(
        "supervisor_bundled_redis_missing",
        extra={"expected_path": redis_path},
    )
    return None


def _redis_log_dir() -> str:
    """Working directory Redis writes any temp/RDB files into.

    Same convention as the LaunchAgent's ``__LOG_DIR__`` substitution
    (``~/.openclaw``). Created on demand.
    """
    home = os.path.expanduser("~")
    log_dir = os.path.join(home, ".openclaw")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _redis_ready_probe() -> HealthCheckFn:
    """TCP probe for the bundled Redis on 127.0.0.1:6379."""
    return _default_health_check_factory(
        host="127.0.0.1", port=6379, timeout_s=_HEALTH_PROBE_TIMEOUT_S
    )


def _redis_argv(redis_bin: str, password: str) -> list[str]:
    """Command line for the bundled redis-server.

    Mirrors ``ops/redis/redis.conf`` settings via CLI flags so the
    bundle does not need to ship a redis.conf alongside the binary.
    """
    return [
        redis_bin,
        "--bind",
        "127.0.0.1",
        "--port",
        "6379",
        "--protected-mode",
        "yes",
        "--requirepass",
        password,
        # No persistence — pub/sub is ephemeral, dedup is in SQLite.
        "--save",
        "",
        "--appendonly",
        "no",
        # Memory ceiling matches ops/redis/redis.conf.
        "--maxmemory",
        "256mb",
        "--maxmemory-policy",
        "allkeys-lru",
        # Logs to stderr so launchd's StandardErrorPath captures them
        # alongside the bridge's JSON lines (Redis text + bridge JSON
        # interleaved is acceptable; first column is monotonic anyway).
        "--logfile",
        "",
        "--loglevel",
        "notice",
        "--timeout",
        "0",
        "--tcp-keepalive",
        "60",
        # Working directory for any temp files.
        "--dir",
        _redis_log_dir(),
        # Foreground — supervisor manages the process directly.
        "--daemonize",
        "no",
    ]


def _build_default_children() -> list[Child]:
    """Production child list — Redis, then bridge, then brain.<agent>.

    In a PyInstaller-frozen .app, ``sys.executable`` points at the bundle's
    single signed binary, which does not accept ``-m``. Instead, the binary
    is multi-mode (see ``bundle/bridge/entry.py``): argv[1] selects the
    mode. In dev (``scripts/run-supervisor.sh``), ``sys.executable`` is the
    venv's Python, which does accept ``-m``. ``sys.frozen`` is set by
    PyInstaller; absent in dev.

    The brain child's label is derived from ``AGENT_NAME`` so a fresh
    install with a custom agent name (e.g. ``AGENT_NAME=helper``) shows
    up in logs and process trees as ``brain.helper`` rather than a
    fixed string. The brain process inherits ``AGENT_NAME`` so its own
    config matches.

    Bundled Redis: when frozen, the build step copies a redis-server
    binary into ``Contents/MacOS/redis-server`` and the supervisor
    runs it as the first child, gating bridge startup on its TCP
    readiness. In dev, no Redis child is spawned — the operator is
    expected to run Redis externally (``scripts/run-redis.sh`` or
    ``brew services start redis``).
    """
    children: list[Child] = []

    # Redis (bundle-only — dev relies on external Redis).
    redis_bin = _bundled_redis_server()
    if redis_bin is not None:
        password = _ensure_redis_password()
        children.append(
            Child(
                name="redis",
                argv=_redis_argv(redis_bin, password),
                ready_check=_redis_ready_probe(),
            )
        )

    bridge_ready = _default_health_check_factory()  # TCP 127.0.0.1:8788

    agent_name = _agent_name()
    brain_label = f"brain.{agent_name}"
    brain_env = {
        "BRAIN_TOKEN": _load_brain_token(agent_name),
        "AGENT_NAME": agent_name,
    }

    if getattr(sys, "frozen", False):
        binary = sys.executable
        children.extend(
            [
                Child(
                    name="bridge",
                    argv=[binary, "bridge"],
                    ready_check=bridge_ready,
                ),
                Child(
                    name=brain_label,
                    argv=[binary, "brain"],
                    env=brain_env,
                ),
            ]
        )
    else:
        python = sys.executable
        children.extend(
            [
                Child(
                    name="bridge",
                    argv=[python, "-m", "bridge"],
                    ready_check=bridge_ready,
                ),
                Child(
                    name=brain_label,
                    argv=[python, "-m", "agent"],
                    env=brain_env,
                ),
            ]
        )
    return children


def _redirect_stdio_to_log_files() -> None:
    """Redirect this process's stdout/stderr to ~/.openclaw/bridge.{out,err}.log.

    The SMAppService-style LaunchAgent plist (see
    ``bundle/bridge/launchagent.plist.template``) deliberately omits
    ``StandardOutPath`` / ``StandardErrorPath`` because launchd does not
    expand ``~`` or ``$HOME`` in plist values, and we cannot hardcode
    an absolute path that works for any user. Each frozen run does its
    own redirect here so logs land in the right per-user place.

    Dev runs (``scripts/run-supervisor.sh``) inherit the operator's
    terminal stdout/stderr — we only redirect when ``sys.frozen`` is
    set, i.e. when the bundle's binary is running under launchd.
    """
    if not getattr(sys, "frozen", False):
        return
    log_dir = os.path.join(os.path.expanduser("~"), ".openclaw")
    os.makedirs(log_dir, exist_ok=True)
    out_path = os.path.join(log_dir, "bridge.out.log")
    err_path = os.path.join(log_dir, "bridge.err.log")
    # Open append+line-buffered. dup2 onto fd 1/2 so child processes
    # spawned via inherited fds also write here.
    out_fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    err_fd = os.open(err_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(out_fd, 1)
    os.dup2(err_fd, 2)
    os.close(out_fd)
    os.close(err_fd)
    # Re-open Python's sys.stdout / sys.stderr against the new fds.
    sys.stdout = os.fdopen(1, "w", buffering=1, encoding="utf-8")
    sys.stderr = os.fdopen(2, "w", buffering=1, encoding="utf-8")


def main() -> int:
    _redirect_stdio_to_log_files()
    cfg = Settings.from_env()
    configure_logging(cfg.log_level)
    try:
        children = _build_default_children()
    except SupervisorError as exc:
        logger.error("supervisor_startup_failed", extra={"reason": str(exc)})
        return exc.exit_code
    supervisor = Supervisor(children=children)
    return asyncio.run(supervisor.run())


if __name__ == "__main__":
    sys.exit(main())
