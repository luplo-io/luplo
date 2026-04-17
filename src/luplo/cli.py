"""luplo CLI — ``lp`` command-line interface.

All commands delegate to ``LocalBackend``.  Async core functions are
bridged via ``asyncio.run()``.  Configuration is loaded from ``.luplo``
file → env vars → CLI flags (highest priority wins).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx
import typer

from luplo.config import CONFIG_FILENAME, load_config, write_config
from luplo.core.backend.local import LocalBackend
from luplo.core.db import close_pool, create_pool
from luplo.core.models import ItemCreate

KEYRING_SERVICE = "luplo"
KEYRING_TOKEN_KEY = "token"

app = typer.Typer(
    name="lp",
    help="luplo — long-term memory for engineering decisions.",
    no_args_is_help=True,
)

items_app = typer.Typer(name="items", help="Manage items (decisions, knowledge, policies).")
work_app = typer.Typer(name="work", help="Manage work units.")
systems_app = typer.Typer(name="systems", help="Manage systems.")
glossary_app = typer.Typer(name="glossary", help="Manage the glossary.")
task_app = typer.Typer(name="task", help="Manage tasks (item_type='task').")
qa_app = typer.Typer(name="qa", help="Manage QA checks (item_type='qa_check').")
auth_app = typer.Typer(name="token", help="Manage authentication tokens.")
admin_app = typer.Typer(name="admin", help="Administrative commands (requires admin).")
server_app = typer.Typer(name="server", help="Server configuration and secrets.")

app.add_typer(items_app)
app.add_typer(work_app)
app.add_typer(systems_app)
app.add_typer(glossary_app)
app.add_typer(task_app)
app.add_typer(qa_app)
app.add_typer(auth_app)
app.add_typer(admin_app)
app.add_typer(server_app)


# ── Token storage (keyring) ──────────────────────────────────────


def _store_token(server_url: str, token: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, f"{KEYRING_TOKEN_KEY}:{server_url}", token)


def _load_token(server_url: str) -> str | None:
    import keyring

    return keyring.get_password(KEYRING_SERVICE, f"{KEYRING_TOKEN_KEY}:{server_url}")


def _delete_token(server_url: str) -> None:
    import keyring
    from keyring.errors import PasswordDeleteError

    try:
        keyring.delete_password(KEYRING_SERVICE, f"{KEYRING_TOKEN_KEY}:{server_url}")
    except PasswordDeleteError:
        pass


def _cfg_server_url(flag: str | None = None) -> str:
    if flag:
        return flag
    cfg = load_config()
    if cfg.server_url:
        return cfg.server_url
    typer.echo(
        "Error: no server URL. Use --server, LUPLO_SERVER_URL, or set [backend].server_url.",
        err=True,
    )
    raise typer.Exit(1)


# ── Config helpers ───────────────────────────────────────────────


def _cfg_project(flag: str | None = None) -> str:
    """Resolve project ID from flag → env → .luplo."""
    if flag:
        return flag
    cfg = load_config()
    if cfg.project_id:
        return cfg.project_id
    typer.echo("Error: no project. Use --project, LUPLO_PROJECT, or run 'lp init'.", err=True)
    raise typer.Exit(1)


def _cfg_actor(flag: str | None = None) -> str:
    """Resolve actor ID from flag → env → .luplo."""
    if flag:
        return flag
    cfg = load_config()
    if cfg.actor_id:
        return cfg.actor_id
    typer.echo("Error: no actor. Use --actor, LUPLO_ACTOR_ID, or run 'lp init'.", err=True)
    raise typer.Exit(1)


def _cfg_db_url() -> str:
    """Resolve DB URL from env → .luplo."""
    cfg = load_config()
    return cfg.db_url


# ── Backend lifecycle ────────────────────────────────────────────


@asynccontextmanager
async def _backend() -> AsyncIterator[LocalBackend]:
    """Create a LocalBackend with a connection pool, yield it, then clean up."""
    db_url = _cfg_db_url()
    pool = await create_pool(db_url)
    try:
        yield LocalBackend(pool)
    finally:
        await close_pool(pool)


def _run(coro: object) -> object:
    """Run an async coroutine from sync typer commands.

    Translates ID-resolution errors raised from the core layer into
    actionable messages and a non-zero exit code, so the user sees
    something useful instead of a stack trace.
    """
    from luplo.core.errors import (
        AmbiguousIdError,
        IdTooShortError,
        InvalidIdFormatError,
    )

    try:
        return asyncio.run(coro)  # type: ignore[arg-type]
    except AmbiguousIdError as exc:
        typer.echo(f"Error: {exc.message}", err=True)
        for mid, label in exc.matches:
            typer.echo(f"  - {mid[:12]}  {label}", err=True)
        raise typer.Exit(2)
    except IdTooShortError as exc:
        typer.echo(f"Error: {exc.message}", err=True)
        raise typer.Exit(2)
    except InvalidIdFormatError as exc:
        typer.echo(f"Error: {exc.message}", err=True)
        raise typer.Exit(2)


# ── Init ─────────────────────────────────────────────────────────


@app.command("init")
def init(
    project: str = typer.Option(
        ...,
        "--project",
        "-p",
        help="Project ID (e.g. 'hearthward'). Stored in .luplo and created in DB.",
    ),
    email: str = typer.Option(
        ...,
        "--email",
        "-e",
        help="Your email (required — primary identifier after v0.5.1).",
    ),
    project_name: Optional[str] = typer.Option(
        None,
        "--project-name",
        help="Human-readable project name. Defaults to project ID.",
    ),
    actor_name: Optional[str] = typer.Option(
        None,
        "--name",
        help="Your display name. Defaults to the local-part of email.",
    ),
    actor_id: Optional[str] = typer.Option(
        None,
        "--actor-id",
        help="Explicit actor UUID. Auto-generated (uuid4) if omitted.",
    ),
    db_url: str = typer.Option(
        "postgresql://localhost/luplo",
        "--db-url",
        help="PostgreSQL connection string.",
        envvar="LUPLO_DB_URL",
    ),
    server_url: str = typer.Option(
        "",
        "--server-url",
        help="Optional remote server URL (for `lp login`).",
        envvar="LUPLO_SERVER_URL",
    ),
) -> None:
    """Initialise luplo in the current directory.

    Creates a .luplo config file, runs database migrations, and seeds the
    project and actor. After init, all other commands read from .luplo
    automatically.

    \b
    Examples:
        lp init -p hearthward -e me@example.com
        lp init -p hearthward -e me@example.com --name "Ryan"
        lp init -p myapp -e me@example.com --db-url postgresql://...
    """
    p_name = project_name or project
    a_name = actor_name or email.split("@", 1)[0]
    a_id = actor_id or str(uuid.uuid4())
    config_path = Path.cwd() / CONFIG_FILENAME

    # 1. Write .luplo
    write_config(
        config_path,
        db_url=db_url,
        project_id=project,
        project_name=p_name,
        actor_id=a_id,
        actor_name=a_name,
        actor_email=email,
        server_url=server_url,
    )
    typer.echo(f"Created {CONFIG_FILENAME}")

    # 2. Run migrations
    typer.echo("Running migrations...")
    project_root = Path(__file__).resolve().parent.parent.parent
    alembic_ini = project_root / "alembic.ini"
    env = {**os.environ, "LUPLO_DB_URL": db_url}

    if alembic_ini.exists():
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            typer.echo(f"Migration failed: {result.stderr}", err=True)
            raise typer.Exit(1)
        typer.echo("Migrations up to date.")
    else:
        typer.echo("Warning: alembic.ini not found, skipping migrations.", err=True)

    # 3. Seed project + actor
    async def _seed() -> None:
        pool = await create_pool(db_url)
        try:
            async with pool.connection() as conn:
                await conn.execute(
                    "INSERT INTO projects (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (project, p_name),
                )
                await conn.execute(
                    "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)"
                    " ON CONFLICT (id) DO NOTHING",
                    (a_id, a_name, email),
                )
        finally:
            await close_pool(pool)

    _run(_seed())
    typer.echo(f"Project '{p_name}' ({project}) ready.")
    typer.echo(f"Actor '{a_name}' ({a_id[:8]}…) <{email}> ready.")

    # 4. Add .luplo to .gitignore
    gitignore = Path.cwd() / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if CONFIG_FILENAME not in content:
            with open(gitignore, "a") as f:
                f.write(f"\n# luplo local config (contains DB credentials)\n{CONFIG_FILENAME}\n")
            typer.echo(f"Added {CONFIG_FILENAME} to .gitignore")
    else:
        gitignore.write_text(
            f"# luplo local config (contains DB credentials)\n{CONFIG_FILENAME}\n"
        )
        typer.echo(f"Created .gitignore with {CONFIG_FILENAME}")

    typer.echo("")
    typer.echo("Done! Try:")
    typer.echo(f'  lp items add "Your first decision"')
    typer.echo(f"  lp items list")
    typer.echo(f"  lp brief")


# ── Items ────────────────────────────────────────────────────────


@items_app.command("add")
def items_add(
    title: str = typer.Argument(..., help="Item title."),
    item_type: str = typer.Option("decision", "--type", "-t", help="Item type."),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="Item body."),
    rationale: Optional[str] = typer.Option(None, "--rationale", "-r"),
    system: Optional[list[str]] = typer.Option(None, "--system", "-s"),
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Add a new item."""
    pid = _cfg_project(project)
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            item = await b.create_item(
                ItemCreate(
                    project_id=pid,
                    actor_id=aid,
                    item_type=item_type,
                    title=title,
                    body=body,
                    rationale=rationale,
                    system_ids=system or [],
                )
            )
            typer.echo(f"Created {item.item_type} [{item.id[:8]}] {item.title}")

    _run(_do())


@items_app.command("show")
def items_show(
    item_id: str = typer.Argument(
        ...,
        help="Full UUID or 8-char+ hex prefix. Ambiguous prefixes error out.",
    ),
) -> None:
    """Show a single item."""

    async def _do() -> None:
        pid = _cfg_project(None)
        async with _backend() as b:
            item = await b.get_item(item_id, project_id=pid)
            if not item:
                typer.echo(f"Item {item_id} not found.", err=True)
                raise typer.Exit(1)
            typer.echo(f"[{item.id[:8]}] {item.title}")
            typer.echo(f"  type: {item.item_type}")
            typer.echo(f"  systems: {', '.join(item.system_ids) or '—'}")
            typer.echo(f"  created: {item.created_at:%Y-%m-%d %H:%M}")
            if item.body:
                typer.echo(f"  body: {item.body[:200]}")
            if item.rationale:
                typer.echo(f"  rationale: {item.rationale[:200]}")
            if item.supersedes_id:
                typer.echo(f"  supersedes: {item.supersedes_id[:8]}")

    _run(_do())


@items_app.command("list")
def items_list(
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    item_type: Optional[str] = typer.Option(None, "--type", "-t"),
    system: Optional[str] = typer.Option(None, "--system", "-s"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """List items for a project."""
    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            results = await b.list_items(
                pid,
                item_type=item_type,
                system_id=system,
                limit=limit,
            )
            if not results:
                typer.echo("No items found.")
                return
            for item in results:
                systems = f" [{','.join(item.system_ids)}]" if item.system_ids else ""
                typer.echo(f"  {item.id[:8]}  {item.item_type:<12} {item.title}{systems}")

    _run(_do())


@items_app.command("search")
def items_search(
    query: str = typer.Argument(..., help="Search query."),
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """Search items using glossary-expanded tsquery."""
    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            results = await b.search(query, pid, limit=limit)
            if not results:
                typer.echo("No results.")
                return
            for r in results:
                score = f"{r.score:.3f}"
                typer.echo(f"  {score}  {r.item.id[:8]}  {r.item.title}")
                if r.snippet and r.snippet != r.item.title:
                    typer.echo(f"         {r.snippet[:100]}")

    _run(_do())


# ── Work Units ───────────────────────────────────────────────────


@work_app.command("open")
def work_open(
    title: str = typer.Argument(..., help="Work unit title."),
    description: Optional[str] = typer.Option(None, "--desc", "-d"),
    system: Optional[list[str]] = typer.Option(None, "--system", "-s"),
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Open a new work unit."""
    import uuid

    pid = _cfg_project(project)
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            wu = await b.open_work_unit(
                id=str(uuid.uuid4()),
                project_id=pid,
                title=title,
                description=description,
                system_ids=system,
                created_by=aid,
            )
            typer.echo(f"Opened work unit [{wu.id[:8]}] {wu.title}")

    _run(_do())


@work_app.command("resume")
def work_resume(
    query: str = typer.Argument(..., help="Title keyword to search."),
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
) -> None:
    """Find in-progress work units by title."""
    from luplo.core.work_units import find_work_units

    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            async with b.pool.connection() as conn:
                results = await find_work_units(conn, pid, query)
            if not results:
                typer.echo("No matching work units in progress.")
                return
            for wu in results:
                systems = f" [{','.join(wu.system_ids)}]" if wu.system_ids else ""
                typer.echo(f"  {wu.id[:8]}  {wu.title}{systems}  ({wu.created_at:%Y-%m-%d})")

    _run(_do())


@work_app.command("close")
def work_close(
    work_id: str = typer.Argument(..., help="Work unit ID."),
    status: str = typer.Option("done", "--status", help="done or abandoned."),
    force: bool = typer.Option(
        False, "--force", "-f", help="Close even if an in_progress task remains."
    ),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Close a work unit. Refuses if an in_progress task remains (use --force)."""
    aid = _cfg_actor(actor)
    from luplo.core.errors import WorkUnitHasActiveTasksError

    async def _do() -> None:
        async with _backend() as b:
            try:
                result = await b.close_work_unit(work_id, actor_id=aid, force=force)
            except WorkUnitHasActiveTasksError as e:
                typer.echo(f"Error: {e.message}", err=True)
                raise typer.Exit(2) from e
            if result:
                typer.echo(f"Closed [{result.id[:8]}] {result.title} -> {result.status}")
            else:
                typer.echo("Work unit not found or already closed.", err=True)
                raise typer.Exit(1)

    _run(_do())


# ── Systems ──────────────────────────────────────────────────────


@systems_app.command("add")
def systems_add(
    name: str = typer.Argument(..., help="System name."),
    description: Optional[str] = typer.Option(None, "--desc", "-d"),
    depends: Optional[list[str]] = typer.Option(None, "--depends"),
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
) -> None:
    """Add a new system."""
    import uuid

    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            s = await b.create_system(
                id=str(uuid.uuid4()),
                project_id=pid,
                name=name,
                description=description,
                depends_on_system_ids=depends,
            )
            typer.echo(f"Created system [{s.id[:8]}] {s.name}")

    _run(_do())


@systems_app.command("list")
def systems_list(
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
) -> None:
    """List all systems for a project."""
    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            results = await b.list_systems(pid)
            if not results:
                typer.echo("No systems.")
                return
            for s in results:
                deps = (
                    f" -> {','.join(s.depends_on_system_ids)}" if s.depends_on_system_ids else ""
                )
                typer.echo(f"  {s.id[:8]}  {s.name}{deps}")

    _run(_do())


# ── Glossary ─────────────────────────────────────────────────────


@glossary_app.command("ls")
def glossary_ls(
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """List glossary groups."""
    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            groups = await b.list_glossary_groups(pid, limit=limit)
            if not groups:
                typer.echo("No glossary groups.")
                return
            for g in groups:
                defn = f" — {g.definition}" if g.definition else ""
                typer.echo(f"  {g.id[:8]}  {g.canonical}{defn}")

    _run(_do())


@glossary_app.command("pending")
def glossary_pending(
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Show terms awaiting curation."""
    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            terms = await b.list_pending_terms(pid, limit=limit)
            if not terms:
                typer.echo("No pending terms.")
                return
            for t in terms:
                group = t.group_id[:8] if t.group_id else "orphan"
                typer.echo(f'  {t.id[:8]}  "{t.surface}" -> group:{group}')
                if t.context_snippet:
                    typer.echo(f"           ctx: {t.context_snippet[:80]}")

    _run(_do())


@glossary_app.command("approve")
def glossary_approve(
    term_id: str = typer.Argument(..., help="Term ID to approve."),
    group_id: str = typer.Option(..., "--group", "-g", help="Target group ID."),
    canonical: bool = typer.Option(False, "--canonical", "-c", help="Set as canonical."),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Approve a pending term into a group."""
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            t = await b.approve_term(
                term_id,
                group_id=group_id,
                actor_id=aid,
                as_canonical=canonical,
            )
            if t:
                typer.echo(f'Approved "{t.surface}" as {t.status}')
            else:
                typer.echo("Term not found.", err=True)

    _run(_do())


@glossary_app.command("reject")
def glossary_reject(
    term_id: str = typer.Argument(..., help="Term ID to reject."),
    reason: Optional[str] = typer.Option(None, "--reason", "-r"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Reject a term permanently."""
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            r = await b.reject_term(term_id, actor_id=aid, reason=reason)
            if r:
                typer.echo(f'Rejected "{r.rejected_term}"')
            else:
                typer.echo("Term not found.", err=True)

    _run(_do())


# ── Brief ────────────────────────────────────────────────────────


@app.command("brief")
def brief(
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    system: Optional[str] = typer.Option(None, "--system", "-s"),
) -> None:
    """Get a project brief — active work + recent decisions."""
    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            active = await b.list_work_units(pid, status="in_progress")
            if active:
                typer.echo("Active work units:")
                for wu in active:
                    systems = f" [{','.join(wu.system_ids)}]" if wu.system_ids else ""
                    typer.echo(f"  {wu.id[:8]}  {wu.title}{systems}")
            else:
                typer.echo("No active work units.")

            typer.echo("")

            recent = await b.list_items(pid, system_id=system, limit=10)
            if recent:
                typer.echo("Recent items:")
                for item in recent:
                    typer.echo(f"  {item.id[:8]}  {item.item_type:<12} {item.title}")
            else:
                typer.echo("No items yet.")

    _run(_do())


# ── Worker ───────────────────────────────────────────────────────


@app.command("worker")
def worker_start() -> None:
    """Start the background worker (sync jobs + glossary processing)."""
    from luplo.core.worker import run_worker

    async def _do() -> None:
        db_url = _cfg_db_url()
        pool = await create_pool(db_url)
        try:
            typer.echo("Worker running. Ctrl+C to stop.")
            await run_worker(pool)
        except KeyboardInterrupt:
            pass
        finally:
            await close_pool(pool)

    _run(_do())


# ── Tasks ────────────────────────────────────────────────────────


def _print_task(item: object) -> None:
    """Compact one-liner for a task item."""
    from luplo.core.models import Item

    assert isinstance(item, Item)
    status = item.context.get("status", "?")
    sort_order = item.context.get("sort_order", "?")
    typer.echo(f"  {item.id[:8]}  [{status:<11}] (#{sort_order:>3}) {item.title}")


@task_app.command("add")
def task_add(
    title: str = typer.Argument(..., help="Task title."),
    work_unit: str = typer.Option(
        ...,
        "--wu",
        "-w",
        help="Work unit full UUID or 8-char+ hex prefix.",
    ),
    body: Optional[str] = typer.Option(None, "--body", "-b"),
    system: Optional[list[str]] = typer.Option(None, "--system", "-s"),
    sort_order: Optional[int] = typer.Option(None, "--sort"),
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Add a new task in 'proposed' status."""
    pid = _cfg_project(project)
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            t = await b.create_task(
                project_id=pid,
                work_unit_id=work_unit,
                title=title,
                actor_id=aid,
                sort_order=sort_order,
                systems=system,
                body=body,
            )
            _print_task(t)

    _run(_do())


@task_app.command("ls")
def task_ls(
    work_unit: str = typer.Option(..., "--wu", "-w"),
    status: Optional[str] = typer.Option(None, "--status", "-s"),
) -> None:
    """List tasks (chain heads) for a work unit, ordered by sort_order."""

    async def _do() -> None:
        async with _backend() as b:
            rows = await b.list_tasks(work_unit, status=status)
            if not rows:
                typer.echo("No tasks.")
                return
            for r in rows:
                _print_task(r)

    _run(_do())


@task_app.command("show")
def task_show(
    task_id: str = typer.Argument(
        ...,
        help="Full UUID or 8-char+ hex prefix. Ambiguous prefixes error out.",
    ),
) -> None:
    """Show a single task (resolved to chain head)."""

    async def _do() -> None:
        pid = _cfg_project(None)
        async with _backend() as b:
            t = await b.get_task(task_id, project_id=pid)
            if not t:
                typer.echo(f"Task {task_id} not found.", err=True)
                raise typer.Exit(1)
            _print_task(t)
            for k, v in t.context.items():
                typer.echo(f"    {k}: {v}")
            typer.echo(f"    work_unit: {t.work_unit_id}")

    _run(_do())


@task_app.command("start")
def task_start(
    task_id: str = typer.Argument(...),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Transition task to 'in_progress' (enforces 1 in_progress per WU)."""
    aid = _cfg_actor(actor)
    from luplo.core.errors import TaskAlreadyInProgressError

    async def _do() -> None:
        async with _backend() as b:
            try:
                t = await b.start_task(task_id, actor_id=aid)
            except TaskAlreadyInProgressError as e:
                typer.echo(f"Error: {e.message}", err=True)
                raise typer.Exit(1) from e
            _print_task(t)

    _run(_do())


@task_app.command("done")
def task_done(
    task_id: str = typer.Argument(...),
    summary: Optional[str] = typer.Option(None, "--summary"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Transition task to 'done'."""
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            t = await b.complete_task(task_id, actor_id=aid, summary=summary)
            _print_task(t)

    _run(_do())


@task_app.command("blocked")
def task_blocked(
    task_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", "-r"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Transition task to 'blocked' (auto-creates a decision item)."""
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            t = await b.block_task(task_id, actor_id=aid, reason=reason)
            _print_task(t)
            typer.echo("  (auto-created decision item — see `lp items list --type decision`)")

    _run(_do())


@task_app.command("skip")
def task_skip(
    task_id: str = typer.Argument(...),
    reason: Optional[str] = typer.Option(None, "--reason", "-r"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Transition task to 'skipped' (terminal)."""
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            t = await b.skip_task(task_id, actor_id=aid, reason=reason)
            _print_task(t)

    _run(_do())


@task_app.command("reorder")
def task_reorder(
    work_unit: str = typer.Argument(..., help="Work unit ID."),
    task_ids: list[str] = typer.Argument(..., help="Task IDs in desired order."),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Reorder tasks (in-place sort_order update — P10)."""
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            rows = await b.reorder_tasks(work_unit, task_ids, actor_id=aid)
            for r in rows:
                _print_task(r)

    _run(_do())


@task_app.command("in-progress")
def task_in_progress(work_unit: str = typer.Option(..., "--wu", "-w")) -> None:
    """Show the current in_progress task for a work unit, if any."""

    async def _do() -> None:
        async with _backend() as b:
            t = await b.get_in_progress_task(work_unit)
            if t is None:
                typer.echo("(none)")
            else:
                _print_task(t)

    _run(_do())


# ── QA Checks ────────────────────────────────────────────────────


def _print_qa(item: object) -> None:
    from luplo.core.models import Item

    assert isinstance(item, Item)
    status = item.context.get("status", "?")
    coverage = item.context.get("coverage", "?")
    areas = ",".join(item.context.get("areas") or []) or "—"
    typer.echo(f"  {item.id[:8]}  [{status:<10}] {coverage:<12} ({areas}) {item.title}")


@qa_app.command("add")
def qa_add(
    title: str = typer.Argument(...),
    coverage: str = typer.Option(..., "--coverage", "-c", help="auto_partial | human_only"),
    area: Optional[list[str]] = typer.Option(
        None, "--area", help="vfx, sfx, ux, edge_case, perf, a11y, sec"
    ),
    tasks_target: Optional[list[str]] = typer.Option(
        None, "--task", "-t", help="Target task IDs."
    ),
    items_target: Optional[list[str]] = typer.Option(
        None, "--item", "-i", help="Target item IDs."
    ),
    work_unit: Optional[str] = typer.Option(None, "--wu", "-w"),
    body: Optional[str] = typer.Option(None, "--body"),
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    """Add a new qa_check in 'pending' status."""
    pid = _cfg_project(project)
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            q = await b.create_qa(
                project_id=pid,
                title=title,
                actor_id=aid,
                coverage=coverage,
                areas=area,
                target_task_ids=tasks_target,
                target_item_ids=items_target,
                work_unit_id=work_unit,
                body=body,
            )
            _print_qa(q)

    _run(_do())


@qa_app.command("ls")
def qa_ls(
    status: Optional[str] = typer.Option(None, "--status", "-s"),
    work_unit: Optional[str] = typer.Option(None, "--wu", "-w"),
    task: Optional[str] = typer.Option(
        None, "--task", "-t", help="Filter to qa_checks targeting this task."
    ),
    item_id_filter: Optional[str] = typer.Option(None, "--item", "-i"),
    project: Optional[str] = typer.Option(None, "--project", "-p", envvar="LUPLO_PROJECT"),
) -> None:
    """List qa_checks. With --task / --item shows pending qa for that target."""
    pid = _cfg_project(project)

    async def _do() -> None:
        async with _backend() as b:
            if task:
                rows = await b.list_pending_qa_for_task(task)
            elif item_id_filter:
                rows = await b.list_pending_qa_for_item(item_id_filter)
            else:
                rows = await b.list_qa(pid, status=status, work_unit_id=work_unit)
            if not rows:
                typer.echo("No qa_checks.")
                return
            for r in rows:
                _print_qa(r)

    _run(_do())


@qa_app.command("show")
def qa_show(
    qa_id: str = typer.Argument(
        ...,
        help="Full UUID or 8-char+ hex prefix. Ambiguous prefixes error out.",
    ),
) -> None:
    """Show a single qa_check (chain head)."""

    async def _do() -> None:
        pid = _cfg_project(None)
        async with _backend() as b:
            q = await b.get_qa(qa_id, project_id=pid)
            if not q:
                typer.echo(f"qa_check {qa_id} not found.", err=True)
                raise typer.Exit(1)
            _print_qa(q)
            for k, v in q.context.items():
                typer.echo(f"    {k}: {v}")

    _run(_do())


@qa_app.command("start")
def qa_start(
    qa_id: str = typer.Argument(...),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            q = await b.start_qa(qa_id, actor_id=aid)
            _print_qa(q)

    _run(_do())


@qa_app.command("pass")
def qa_pass(
    qa_id: str = typer.Argument(...),
    evidence: Optional[str] = typer.Option(None, "--evidence", "-e"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            q = await b.pass_qa(qa_id, actor_id=aid, evidence=evidence)
            _print_qa(q)

    _run(_do())


@qa_app.command("fail")
def qa_fail(
    qa_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", "-r"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            q = await b.fail_qa(qa_id, actor_id=aid, reason=reason)
            _print_qa(q)

    _run(_do())


@qa_app.command("block")
def qa_block(
    qa_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", "-r"),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            q = await b.block_qa(qa_id, actor_id=aid, reason=reason)
            _print_qa(q)

    _run(_do())


@qa_app.command("assign")
def qa_assign(
    qa_id: str = typer.Argument(...),
    assignee: str = typer.Option(..., "--to", help="Assignee actor UUID."),
    actor: Optional[str] = typer.Option(None, "--actor", "-a", envvar="LUPLO_ACTOR_ID"),
) -> None:
    aid = _cfg_actor(actor)

    async def _do() -> None:
        async with _backend() as b:
            q = await b.assign_qa(qa_id, actor_id=aid, assignee_actor_id=assignee)
            _print_qa(q)

    _run(_do())


# ── Auth (remote) ────────────────────────────────────────────────


@app.command("login")
def login(
    email: Optional[str] = typer.Option(None, "--email", "-e"),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        "-P",
        help="If omitted, you'll be prompted.",
    ),
    server: Optional[str] = typer.Option(None, "--server", help="Server URL."),
    oauth: Optional[str] = typer.Option(
        None,
        "--oauth",
        help="OAuth provider (github|google). Not yet wired — use password login.",
    ),
) -> None:
    """Log in to a remote luplo server and store the JWT in keyring."""
    server_url = _cfg_server_url(server).rstrip("/")

    if oauth:
        typer.echo(
            "OAuth CLI login (loopback + PKCE) is not yet wired in v0.5.1. "
            "Browse to {}/auth/login in a browser, or use password login.".format(server_url),
            err=True,
        )
        raise typer.Exit(2)

    cfg = load_config()
    email_val = email or cfg.actor_email
    if not email_val:
        email_val = typer.prompt("Email")
    password_val = password or typer.prompt("Password", hide_input=True)

    with httpx.Client(timeout=10.0) as client:
        try:
            resp = client.post(
                f"{server_url}/auth/login",
                data={"email": email_val, "password": password_val},
            )
        except httpx.HTTPError as e:
            typer.echo(f"Connection failed: {e}", err=True)
            raise typer.Exit(1) from e

    if resp.status_code != 200:
        typer.echo(f"Login failed ({resp.status_code}): {resp.text}", err=True)
        raise typer.Exit(1)

    token = resp.json().get("token")
    if not token:
        typer.echo(f"Server did not return a token: {resp.text}", err=True)
        raise typer.Exit(1)

    _store_token(server_url, token)
    typer.echo(f"Logged in to {server_url} as {email_val}.")


@app.command("logout")
def logout(server: Optional[str] = typer.Option(None, "--server")) -> None:
    """Forget the stored JWT for *server*."""
    server_url = _cfg_server_url(server).rstrip("/")
    _delete_token(server_url)
    typer.echo(f"Removed credentials for {server_url}.")


@app.command("whoami")
def whoami(server: Optional[str] = typer.Option(None, "--server")) -> None:
    """Show the authenticated actor for *server*."""
    server_url = _cfg_server_url(server).rstrip("/")
    token = _load_token(server_url)
    if not token:
        typer.echo("Not logged in. Run `lp login`.", err=True)
        raise typer.Exit(1)
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(
            f"{server_url}/auth/whoami",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        typer.echo(f"whoami failed ({resp.status_code}): {resp.text}", err=True)
        raise typer.Exit(1)
    data = resp.json()
    admin = " (admin)" if data.get("is_admin") else ""
    typer.echo(f"{data['email']} [{data['id'][:8]}…]{admin}")


@auth_app.command("refresh")
def token_refresh(server: Optional[str] = typer.Option(None, "--server")) -> None:
    """Request a fresh JWT using the current token."""
    server_url = _cfg_server_url(server).rstrip("/")
    token = _load_token(server_url)
    if not token:
        typer.echo("Not logged in.", err=True)
        raise typer.Exit(1)
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{server_url}/auth/token/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        typer.echo(f"Refresh failed ({resp.status_code}): {resp.text}", err=True)
        raise typer.Exit(1)
    new_token = resp.json().get("token")
    if not new_token:
        typer.echo("Server did not return a token.", err=True)
        raise typer.Exit(1)
    _store_token(server_url, new_token)
    typer.echo("Token refreshed.")


# ── Admin (local DB) ─────────────────────────────────────────────


@admin_app.command("set-password")
def admin_set_password(
    email: str = typer.Argument(..., help="Target actor email."),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        "-P",
        help="If omitted, you'll be prompted.",
    ),
) -> None:
    """Set or reset a local actor's password (argon2id)."""
    from luplo.core.actors import get_actor_by_email, set_password
    from luplo.server.auth.password import WeakPasswordError, hash_password

    pw = password or typer.prompt("New password", hide_input=True, confirmation_prompt=True)
    try:
        hashed = hash_password(pw)
    except WeakPasswordError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    async def _do() -> None:
        db_url = _cfg_db_url()
        pool = await create_pool(db_url)
        try:
            async with pool.connection() as conn:
                actor = await get_actor_by_email(conn, email)
                if not actor:
                    typer.echo(f"Actor with email '{email}' not found.", err=True)
                    raise typer.Exit(1)
                await set_password(conn, actor.id, hashed)
        finally:
            await close_pool(pool)

    _run(_do())
    typer.echo(f"Password updated for {email}.")


# ── Server config ────────────────────────────────────────────────


@server_app.command("init-secrets")
def server_init_secrets(
    output: Path = typer.Option(
        Path("luplo-server.toml"),
        "--output",
        "-o",
        help="Where to write the generated server config.",
    ),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Generate a fresh JWT secret + session secret and print an .env snippet.

    Does not overwrite existing secrets files unless --force.
    """
    import secrets

    jwt_secret = secrets.token_hex(32)
    session_secret = secrets.token_hex(32)

    if output.exists() and not force:
        typer.echo(f"{output} already exists (pass --force to overwrite).", err=True)
        raise typer.Exit(1)

    output.write_text(
        "# luplo server config. Secrets belong in env vars, not this file.\n"
        "# Set: LUPLO_JWT_SECRET, LUPLO_SESSION_SECRET, LUPLO_ADMIN_PASSWORD_INITIAL\n"
        "\n"
        'db_url = "postgresql://localhost/luplo"\n'
        'base_url = "http://localhost:8000"\n'
        "jwt_ttl_minutes = 60\n"
        "allowed_email_domains = []\n"
        "auto_create_users = true\n"
    )
    typer.echo(f"Wrote {output}")
    typer.echo("")
    typer.echo("Add these to your .env (or export in the server shell):")
    typer.echo(f"  LUPLO_JWT_SECRET={jwt_secret}")
    typer.echo(f"  LUPLO_SESSION_SECRET={session_secret}")
    typer.echo("  LUPLO_ADMIN_EMAIL=admin@example.com")
    typer.echo("  LUPLO_ADMIN_PASSWORD_INITIAL=<pick a strong >=12 char password>")


@server_app.command("config-check")
def server_config_check() -> None:
    """Load server settings from env + luplo-server.toml and report problems."""
    try:
        from luplo.server.config import fail_fast_check, load_settings
    except ImportError as e:
        typer.echo(f"Server dependencies not installed: {e}", err=True)
        typer.echo("Install with: uv sync --extra server", err=True)
        raise typer.Exit(1) from e

    settings = load_settings()
    problems = fail_fast_check(settings)
    typer.echo(f"db_url: {settings.db_url}")
    typer.echo(f"jwt_alg: {settings.jwt_alg}")
    typer.echo(f"jwt_ttl_minutes: {settings.jwt_ttl_minutes}")
    typer.echo(f"jwt_secret: {'<set>' if settings.jwt_secret else '<MISSING>'}")
    typer.echo(f"admin_email: {settings.admin_email or '<unset>'}")
    typer.echo(f"github_enabled: {settings.github_enabled}")
    typer.echo(f"google_enabled: {settings.google_enabled}")
    typer.echo(f"allowed_email_domains: {settings.allowed_email_domains or '(unrestricted)'}")
    typer.echo(f"auto_create_users: {settings.auto_create_users}")
    if problems:
        typer.echo("")
        typer.echo("Problems:", err=True)
        for p in problems:
            typer.echo(f"  - {p}", err=True)
        raise typer.Exit(1)
    typer.echo("")
    typer.echo("Config OK.")


if __name__ == "__main__":
    app()
