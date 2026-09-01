"""Studio-grade public OpenOppsDB Kaggle notebooks."""

from __future__ import annotations

from typing import Any

from openopps_kaggle.constants import (
    ADVANCED_NB_ID,
    EXPLORER_NB_ID,
    HIRING_MARKET_NB_ID,
    NOTEBOOK_DUCKDB_ENGINE_VERSION,
    NOTEBOOK_DUCKDB_VERSION,
    NOTEBOOK_GRADIO_VERSION,
    NOTEBOOK_JUPYSQL_VERSION,
    NOTEBOOK_PLOTLY_VERSION,
    ROUTE_LEDGER_BRASS,
    ROUTE_LEDGER_INFO,
    ROUTE_LEDGER_INK,
    ROUTE_LEDGER_PAPER,
    ROUTE_LEDGER_PINE,
    SKILLS_RADAR_NB_ID,
    SNAPSHOT_HEALTH_NB_ID,
    SQL_PLAYGROUND_NB_ID,
    STARTER_NB_ID,
)


def _cells():
    from openopps_kaggle._core import (
        _code_cell,
        _markdown_cell,
        _public_notebook_document,
    )

    return _markdown_cell, _code_cell, _public_notebook_document


def _kaggle_code_url(notebook_id: str) -> str:
    slug = notebook_id.split("/", 1)[1]
    return f"https://www.kaggle.com/code/{notebook_id.split('/', 1)[0]}/{slug}"


def notebook_index_markdown() -> str:
    rows = (
        (
            "Starter",
            STARTER_NB_ID,
            "Front door: tables, recent open jobs, first `%%sql` cells",
        ),
        (
            "Explorer (featured)",
            EXPLORER_NB_ID,
            "Gradio UI: jobs, companies, skills, filters/plots",
        ),
        (
            "Advanced usage",
            ADVANCED_NB_ID,
            "Joins, version history, company drill-down, Parquet",
        ),
        (
            "SQL playground",
            SQL_PLAYGROUND_NB_ID,
            "JupySQL studio: CTEs, DuckDB attach, Parquet scans",
        ),
        (
            "Hiring market map",
            HIRING_MARKET_NB_ID,
            "Company, provider, location, and remote mix charts",
        ),
        (
            "Skills radar",
            SKILLS_RADAR_NB_ID,
            "Skill groups, keywords, and co-occurrence",
        ),
        (
            "Snapshot health",
            SNAPSHOT_HEALTH_NB_ID,
            "Coverage, freshness, sync runs, observation mix",
        ),
    )
    lines = [
        "| Notebook | Kernel | What it is for |",
        "| --- | --- | --- |",
    ]
    for title, notebook_id, purpose in rows:
        url = _kaggle_code_url(notebook_id)
        lines.append(f"| **{title}** | [`{notebook_id}`]({url}) | {purpose} |")
    return "\n".join(lines)


def _pip_sql_source() -> str:
    return (
        f"%pip install -q jupysql=={NOTEBOOK_JUPYSQL_VERSION} "
        f"duckdb=={NOTEBOOK_DUCKDB_VERSION} "
        f"duckdb-engine=={NOTEBOOK_DUCKDB_ENGINE_VERSION} "
        f"plotly=={NOTEBOOK_PLOTLY_VERSION}"
    )


def _pip_gradio_source() -> str:
    return (
        f"%pip install -q gradio=={NOTEBOOK_GRADIO_VERSION} "
        f"plotly=={NOTEBOOK_PLOTLY_VERSION}"
    )


def _paths_setup_source() -> str:
    return '''from pathlib import Path
import sqlite3

import pandas as pd
import plotly.express as px
import plotly.io as pio

pio.templates.default = "plotly_white"
ROUTE_LEDGER = {
    "pine": "''' + ROUTE_LEDGER_PINE + '''",
    "paper": "''' + ROUTE_LEDGER_PAPER + '''",
    "brass": "''' + ROUTE_LEDGER_BRASS + '''",
    "ink": "''' + ROUTE_LEDGER_INK + '''",
    "info": "''' + ROUTE_LEDGER_INFO + '''",
}

db_candidates = sorted(Path("/kaggle/input").glob("**/openoppsdb.sqlite"))
if not db_candidates:
    raise FileNotFoundError("No openoppsdb.sqlite input found under /kaggle/input")
DB_PATH = db_candidates[0]
DATASET_DIR = DB_PATH.parent
DB_URI = f"file:{DB_PATH}?mode=ro&immutable=1"
PARQUET_DIR = DATASET_DIR / "exports" / "parquet"
print(f"Reading OpenOppsDB snapshot from {DB_PATH}")
'''


def _jupysql_connect_source() -> str:
    return '''import duckdb

con = duckdb.connect()
attach_path = str(DB_PATH).replace("'", "''")
con.execute(f"ATTACH '{attach_path}' AS oo (TYPE SQLITE, READ_ONLY)")
print("DuckDB attached the read-only SQLite snapshot as oo")
'''


def _overview(title: str, body: str) -> str:
    return (
        f"# {title}\n\n"
        f"{body}\n\n"
        "## Contents\n\n"
        "- Setup (read-only `/kaggle/input`, `mode=ro&immutable=1`)\n"
        "- Queries and charts for this kernel\n"
        "- Links to the rest of the collection\n\n"
        "## Collection\n\n"
        f"{notebook_index_markdown()}\n"
    )


def starter_notebook() -> dict[str, Any]:
    md, code, document = _cells()
    return document(
        [
            md(
                "overview",
                _overview(
                    "OpenOppsDB — Starter",
                    "Front door for the public OpenOppsDB snapshot. "
                    "Read-only, credential-free, attached only to "
                    "`wyattowalsh/openoppsdb`. Use `%%sql` for the first "
                    "queries, then continue in Explorer or the SQL playground.",
                ),
            ),
            code("pip", _pip_sql_source()),
            code("paths", _paths_setup_source()),
            code(
                "sql-ext",
                "%load_ext sql\n"
                "%config SqlMagic.displaylimit = 25\n"
                "%config SqlMagic.autolimit = 100",
            ),
            code("duckdb-attach", _jupysql_connect_source()),
            code("sql-con", "%sql con --alias openopps"),
            code(
                "sql-tables",
                "%%sql\n"
                "SELECT table_name, table_title, table_description\n"
                "FROM oo.openopps_tables\n"
                "ORDER BY table_name",
            ),
            code(
                "sql-recent-jobs",
                "%%sql\n"
                "SELECT job_id, title, company, locations, employment_type,\n"
                "       first_seen_at, last_seen_at, posting_url\n"
                "FROM oo.job_versions\n"
                "ORDER BY last_seen_at DESC\n"
                "LIMIT 20",
            ),
            code(
                "counts-chart",
                '''with sqlite3.connect(DB_URI, uri=True) as conn:
    tables = pd.read_sql_query(
        "select table_name from openopps_tables order by table_name",
        conn,
    )
    counts = pd.DataFrame(
        {
            "table": tables["table_name"],
            "rows": [
                conn.execute(f'select count(*) from "{name}"').fetchone()[0]
                for name in tables["table_name"]
            ],
        }
    )
focus = counts[counts["table"].isin(
    ["jobs", "job_versions", "job_sync_runs", "sources", "boards"]
)]
fig = px.bar(
    focus,
    x="table",
    y="rows",
    color_discrete_sequence=[ROUTE_LEDGER["pine"]],
    title="Core table row counts",
)
fig.update_layout(paper_bgcolor=ROUTE_LEDGER["paper"], font_color=ROUTE_LEDGER["ink"])
fig.show()
focus
''',
            ),
        ]
    )


def advanced_usage_notebook() -> dict[str, Any]:
    md, code, document = _cells()
    return document(
        [
            md(
                "overview",
                _overview(
                    "OpenOppsDB — Advanced usage",
                    "Durable joins, version history, a company drill-down, and "
                    "when to use Parquet exports. SQL magics run through DuckDB "
                    "attached to the read-only SQLite snapshot.",
                ),
            ),
            code("pip", _pip_sql_source()),
            code("paths", _paths_setup_source()),
            code(
                "sql-ext",
                "%load_ext sql\n"
                "%config SqlMagic.displaylimit = 25\n"
                "%config SqlMagic.autolimit = 100",
            ),
            code("duckdb-attach", _jupysql_connect_source()),
            code("sql-con", "%sql con --alias openopps"),
            code(
                "sql-current-roles",
                "%%sql\n"
                "SELECT j.id AS job_id,\n"
                "       coalesce(v.company, b.name) AS company,\n"
                "       v.title, j.provider_id, j.status, v.remote,\n"
                "       v.employment_type, j.first_seen_at, j.last_seen_at,\n"
                "       v.posting_url\n"
                "FROM oo.jobs j\n"
                "JOIN oo.job_versions v ON v.id = j.current_version_id\n"
                "LEFT JOIN oo.boards b ON b.key = j.board_key\n"
                "WHERE j.status = 'open'\n"
                "ORDER BY j.last_seen_at DESC\n"
                "LIMIT 25",
            ),
            code(
                "sql-version-history",
                "%%sql --save version_history\n"
                "SELECT j.id AS job_id,\n"
                "       coalesce(max(v.company), max(b.name)) AS company,\n"
                "       max(v.title) AS latest_title,\n"
                "       count(v.id) AS version_count,\n"
                "       min(v.first_seen_at) AS first_version_seen_at,\n"
                "       max(v.last_seen_at) AS last_version_seen_at\n"
                "FROM oo.jobs j\n"
                "JOIN oo.job_versions v ON v.job_id = j.id\n"
                "LEFT JOIN oo.boards b ON b.key = j.board_key\n"
                "GROUP BY j.id\n"
                "HAVING count(v.id) > 1\n"
                "ORDER BY version_count DESC, last_version_seen_at DESC\n"
                "LIMIT 20",
            ),
            code(
                "sql-observation-mix",
                "%%sql\n"
                "SELECT observation_kind, count(*) AS observations\n"
                "FROM oo.job_sync_observations\n"
                "GROUP BY observation_kind\n"
                "ORDER BY observations DESC",
            ),
            code(
                "company-dossier",
                '''with sqlite3.connect(DB_URI, uri=True) as conn:
    companies = pd.read_sql_query(
        """
        select coalesce(v.company, b.name, 'Unknown') as company,
               count(*) as open_roles
        from jobs j
        join job_versions v on v.id = j.current_version_id
        left join boards b on b.key = j.board_key
        where j.status = 'open'
        group by company
        order by open_roles desc, company
        limit 15
        """,
        conn,
    )
focus_company = companies["company"].iloc[0] if not companies.empty else None
if focus_company:
    with sqlite3.connect(DB_URI, uri=True) as conn:
        dossier = pd.read_sql_query(
            """
            select j.id as job_id, v.title, j.provider_id, v.remote,
                   v.employment_type, j.last_seen_at, v.posting_url
            from jobs j
            join job_versions v on v.id = j.current_version_id
            left join boards b on b.key = j.board_key
            where j.status = 'open'
              and coalesce(v.company, b.name, 'Unknown') = ?
            order by j.last_seen_at desc
            limit 25
            """,
            conn,
            params=(focus_company,),
        )
    print(f"Company drill-down: {focus_company}")
    display(companies)
    display(dossier)
else:
    print("No open-role companies in this snapshot.")
    companies
''',
            ),
            code(
                "parquet-duckdb",
                '''parquet_path = PARQUET_DIR / "job_versions.parquet"
if parquet_path.exists():
    sample = con.execute(
        """
        select id, title, company, left(cast(description as varchar), 240) as description_head,
               posting_url
        from read_parquet(?)
        where description is not null
        limit 10
        """,
        [str(parquet_path)],
    ).df()
else:
    sample = pd.DataFrame({"note": ["Parquet export not found"]})
sample
''',
            ),
        ]
    )


def hiring_market_map_notebook() -> dict[str, Any]:
    md, code, document = _cells()
    return document(
        [
            md(
                "overview",
                _overview(
                    "OpenOppsDB — Hiring market map",
                    "Current open roles by company, provider, location, and "
                    "remote/workplace signal. Chart-first with Route Ledger Plotly.",
                ),
            ),
            code("paths", _paths_setup_source()),
            code(
                "market_tables",
                '''with sqlite3.connect(DB_URI, uri=True) as conn:
    top_companies = pd.read_sql_query(
        """
        select coalesce(v.company, b.name, 'Unknown') as company,
               count(*) as open_roles,
               count(distinct j.board_key) as boards
        from jobs j
        join job_versions v on v.id = j.current_version_id
        left join boards b on b.key = j.board_key
        where j.status = 'open'
        group by company
        order by open_roles desc, company
        limit 20
        """,
        conn,
    )
    provider_mix = pd.read_sql_query(
        """
        select provider_id, count(*) as open_roles
        from jobs
        where status = 'open'
        group by provider_id
        order by open_roles desc, provider_id
        limit 15
        """,
        conn,
    )
    location_mix = pd.read_sql_query(
        """
        select l.label as location, count(distinct j.id) as open_roles
        from jobs j
        join job_versions v on v.id = j.current_version_id
        join job_version_locations l on l.job_version_id = v.id
        where j.status = 'open' and l.label is not null and l.label <> ''
        group by l.label
        order by open_roles desc, location
        limit 20
        """,
        conn,
    )
    remote_mix = pd.read_sql_query(
        """
        select coalesce(v.remote, 'Unknown') as remote, count(*) as open_roles
        from jobs j
        join job_versions v on v.id = j.current_version_id
        where j.status = 'open'
        group by remote
        order by open_roles desc
        """,
        conn,
    )

display(top_companies)
display(provider_mix)
display(location_mix)
remote_mix
''',
            ),
            code(
                "market_charts",
                '''company_fig = px.bar(
    top_companies.head(10).sort_values("open_roles"),
    x="open_roles",
    y="company",
    orientation="h",
    color_discrete_sequence=[ROUTE_LEDGER["pine"]],
    title="Top companies",
)
company_fig.update_layout(
    paper_bgcolor=ROUTE_LEDGER["paper"], font_color=ROUTE_LEDGER["ink"]
)
location_fig = px.bar(
    location_mix.head(10).sort_values("open_roles"),
    x="open_roles",
    y="location",
    orientation="h",
    color_discrete_sequence=[ROUTE_LEDGER["brass"]],
    title="Top locations",
)
location_fig.update_layout(
    paper_bgcolor=ROUTE_LEDGER["paper"], font_color=ROUTE_LEDGER["ink"]
)
company_fig.show()
location_fig.show()
''',
            ),
        ]
    )


def skills_radar_notebook() -> dict[str, Any]:
    md, code, document = _cells()
    return document(
        [
            md(
                "overview",
                _overview(
                    "OpenOppsDB — Skills radar",
                    "Skill groups, keywords, role slices, and skill-pair "
                    "co-occurrence in current open roles.",
                ),
            ),
            code("paths", _paths_setup_source()),
            code(
                "skill_tables",
                '''with sqlite3.connect(DB_URI, uri=True) as conn:
    top_skills = pd.read_sql_query(
        """
        select lower(s.name) as skill, count(distinct j.id) as open_roles
        from jobs j
        join job_versions v on v.id = j.current_version_id
        join job_version_skills s on s.job_version_id = v.id
        where j.status = 'open' and s.name is not null and s.name <> ''
        group by lower(s.name)
        order by open_roles desc, skill
        limit 25
        """,
        conn,
    )
    top_keywords = pd.read_sql_query(
        """
        select lower(k.keyword) as keyword, count(distinct j.id) as open_roles
        from jobs j
        join job_versions v on v.id = j.current_version_id
        join job_version_skills s on s.job_version_id = v.id
        join job_version_skill_keywords k on k.skill_id = s.id
        where j.status = 'open' and k.keyword is not null and k.keyword <> ''
        group by lower(k.keyword)
        order by open_roles desc, keyword
        limit 25
        """,
        conn,
    )
    skill_pairs = pd.read_sql_query(
        """
        select lower(s1.name) as skill_a, lower(s2.name) as skill_b,
               count(distinct j.id) as open_roles
        from jobs j
        join job_versions v on v.id = j.current_version_id
        join job_version_skills s1 on s1.job_version_id = v.id
        join job_version_skills s2
          on s2.job_version_id = v.id and lower(s1.name) < lower(s2.name)
        where j.status = 'open'
          and s1.name is not null and s1.name <> ''
          and s2.name is not null and s2.name <> ''
        group by lower(s1.name), lower(s2.name)
        order by open_roles desc, skill_a, skill_b
        limit 25
        """,
        conn,
    )

display(top_skills)
display(top_keywords)
skill_pairs
''',
            ),
            code(
                "role_slices",
                '''with sqlite3.connect(DB_URI, uri=True) as conn:
    role_slices = pd.read_sql_query(
        """
        with role_labels as (
            select v.id as version_id,
                case
                    when lower(v.title) like '%data%' then 'data'
                    when lower(v.title) like '%engineer%' then 'engineering'
                    when lower(v.title) like '%product%' then 'product'
                    when lower(v.title) like '%sales%' then 'sales'
                    else 'other'
                end as role_slice
            from jobs j
            join job_versions v on v.id = j.current_version_id
            where j.status = 'open'
        )
        select r.role_slice, lower(s.name) as skill, count(*) as mentions
        from role_labels r
        join job_version_skills s on s.job_version_id = r.version_id
        where s.name is not null and s.name <> ''
        group by r.role_slice, lower(s.name)
        order by mentions desc, role_slice, skill
        limit 40
        """,
        conn,
    )

role_slices
''',
            ),
            code(
                "skill_chart",
                '''if top_skills.empty:
    print("No skill rows found in this snapshot.")
else:
    fig = px.bar(
        top_skills.head(15).sort_values("open_roles"),
        x="open_roles",
        y="skill",
        orientation="h",
        color_discrete_sequence=[ROUTE_LEDGER["info"]],
        title="Top skills",
    )
    fig.update_layout(
        paper_bgcolor=ROUTE_LEDGER["paper"], font_color=ROUTE_LEDGER["ink"]
    )
    fig.show()
''',
            ),
        ]
    )


def sql_playground_notebook() -> dict[str, Any]:
    md, code, document = _cells()
    return document(
        [
            md(
                "overview",
                _overview(
                    "OpenOppsDB — SQL playground",
                    "Deep JupySQL studio. DuckDB attaches the read-only SQLite "
                    "snapshot as `oo` and can scan Parquet exports. Use "
                    "`%%sql --save` / `--with` for CTE composition.",
                ),
            ),
            code("pip", _pip_sql_source()),
            code("paths", _paths_setup_source()),
            code(
                "sql-ext",
                "%load_ext sql\n"
                "%config SqlMagic.displaylimit = 25\n"
                "%config SqlMagic.autolimit = 100",
            ),
            code("duckdb-attach", _jupysql_connect_source()),
            code("sql-con", "%sql con --alias openopps"),
            code(
                "sql-open-jobs",
                "%%sql --save open_jobs\n"
                "SELECT j.id AS job_id, coalesce(v.company, b.name) AS company,\n"
                "       v.title, j.provider_id, v.remote, j.last_seen_at\n"
                "FROM oo.jobs j\n"
                "JOIN oo.job_versions v ON v.id = j.current_version_id\n"
                "LEFT JOIN oo.boards b ON b.key = j.board_key\n"
                "WHERE j.status = 'open'",
            ),
            code(
                "sql-open-jobs-by-provider",
                "%%sql --with open_jobs\n"
                "SELECT provider_id, count(*) AS open_roles\n"
                "FROM open_jobs\n"
                "GROUP BY provider_id\n"
                "ORDER BY open_roles DESC",
            ),
            code(
                "sql-freshness",
                "%%sql\n"
                "SELECT date_trunc('day', try_cast(last_seen_at AS timestamp)) AS day,\n"
                "       count(*) AS open_roles\n"
                "FROM oo.jobs\n"
                "WHERE status = 'open'\n"
                "GROUP BY 1\n"
                "ORDER BY 1 DESC\n"
                "LIMIT 30",
            ),
            code(
                "sql-parquet",
                '''if (PARQUET_DIR / "jobs.parquet").exists():
    parquet_jobs = con.execute(
        "select count(*) as parquet_job_rows from read_parquet(?)",
        [str(PARQUET_DIR / "jobs.parquet")],
    ).df()
else:
    parquet_jobs = pd.DataFrame({"note": ["jobs.parquet not found"]})
parquet_jobs
''',
            ),
        ]
    )


def explorer_notebook() -> dict[str, Any]:
    md, code, document = _cells()
    return document(
        [
            md(
                "overview",
                _overview(
                    "OpenOppsDB — Explorer",
                    "Featured Gradio app for the public snapshot. Tabs: jobs, "
                    "companies, skills, and filters/plots. Route Ledger theme. "
                    "Read-only, no credentials.",
                ),
            ),
            code("pip", _pip_gradio_source()),
            code("paths", _paths_setup_source()),
            code(
                "explorer_app",
                '''import gradio as gr

with sqlite3.connect(DB_URI, uri=True) as conn:
    jobs_df = pd.read_sql_query(
        """
        select j.id as job_id,
               coalesce(v.company, b.name, 'Unknown') as company,
               v.title, j.provider_id, j.status, v.remote,
               v.employment_type, j.last_seen_at, v.posting_url
        from jobs j
        join job_versions v on v.id = j.current_version_id
        left join boards b on b.key = j.board_key
        where j.status = 'open'
        """,
        conn,
    )
    skills_df = pd.read_sql_query(
        """
        select lower(s.name) as skill, count(distinct j.id) as open_roles
        from jobs j
        join job_versions v on v.id = j.current_version_id
        join job_version_skills s on s.job_version_id = v.id
        where j.status = 'open' and s.name is not null and s.name <> ''
        group by lower(s.name)
        order by open_roles desc, skill
        limit 50
        """,
        conn,
    )

companies = sorted(jobs_df["company"].dropna().unique().tolist()) if not jobs_df.empty else []
providers = sorted(jobs_df["provider_id"].dropna().unique().tolist()) if not jobs_df.empty else []
remotes = sorted(jobs_df["remote"].dropna().astype(str).unique().tolist()) if not jobs_df.empty else []

def _filter_jobs(company, provider, remote):
    frame = jobs_df.copy()
    if company:
        frame = frame[frame["company"] == company]
    if provider:
        frame = frame[frame["provider_id"] == provider]
    if remote:
        frame = frame[frame["remote"].astype(str) == remote]
    return frame.head(200)

def _company_dossier(company):
    if not company:
        return pd.DataFrame()
    return jobs_df[jobs_df["company"] == company].head(200)

def _jobs_plot(company, provider, remote):
    frame = _filter_jobs(company, provider, remote)
    if frame.empty:
        return px.bar(title="No rows")
    mix = frame.groupby("provider_id").size().reset_index(name="open_roles")
    fig = px.bar(
        mix,
        x="provider_id",
        y="open_roles",
        color_discrete_sequence=[ROUTE_LEDGER["pine"]],
        title="Open roles by provider",
    )
    fig.update_layout(paper_bgcolor=ROUTE_LEDGER["paper"], font_color=ROUTE_LEDGER["ink"])
    return fig

def _skills_plot():
    if skills_df.empty:
        return px.bar(title="No skills")
    fig = px.bar(
        skills_df.head(20).sort_values("open_roles"),
        x="open_roles",
        y="skill",
        orientation="h",
        color_discrete_sequence=[ROUTE_LEDGER["brass"]],
        title="Top skills",
    )
    fig.update_layout(paper_bgcolor=ROUTE_LEDGER["paper"], font_color=ROUTE_LEDGER["ink"])
    return fig

theme = gr.themes.Soft(primary_hue="green", secondary_hue="stone")
css = f"""
.gradio-container {{ background: {ROUTE_LEDGER["paper"]} !important; color: {ROUTE_LEDGER["ink"]}; }}
"""
with gr.Blocks(theme=theme, css=css, title="OpenOppsDB Explorer") as demo:
    gr.Markdown("# OpenOppsDB Explorer")
    with gr.Tab("jobs"):
        c1 = gr.Dropdown(choices=companies, label="company", value=None)
        p1 = gr.Dropdown(choices=providers, label="provider", value=None)
        r1 = gr.Dropdown(choices=remotes, label="remote", value=None)
        jobs_out = gr.Dataframe(value=jobs_df.head(50))
        c1.change(_filter_jobs, [c1, p1, r1], jobs_out)
        p1.change(_filter_jobs, [c1, p1, r1], jobs_out)
        r1.change(_filter_jobs, [c1, p1, r1], jobs_out)
    with gr.Tab("companies"):
        c2 = gr.Dropdown(choices=companies, label="company dossier", value=companies[0] if companies else None)
        dossier_out = gr.Dataframe(value=_company_dossier(companies[0]) if companies else pd.DataFrame())
        c2.change(_company_dossier, c2, dossier_out)
    with gr.Tab("skills"):
        gr.Dataframe(value=skills_df, wrap=True)
        gr.Plot(value=_skills_plot())
    with gr.Tab("filters/plots"):
        c3 = gr.Dropdown(choices=companies, label="company", value=None)
        p3 = gr.Dropdown(choices=providers, label="provider", value=None)
        r3 = gr.Dropdown(choices=remotes, label="remote", value=None)
        plot_out = gr.Plot(value=_jobs_plot(None, None, None))
        c3.change(_jobs_plot, [c3, p3, r3], plot_out)
        p3.change(_jobs_plot, [c3, p3, r3], plot_out)
        r3.change(_jobs_plot, [c3, p3, r3], plot_out)

demo.launch()
''',
            ),
        ]
    )


def snapshot_health_notebook() -> dict[str, Any]:
    md, code, document = _cells()
    return document(
        [
            md(
                "overview",
                _overview(
                    "OpenOppsDB — Snapshot health",
                    "Coverage, freshness, sync runs, and observation mix for "
                    "the attached snapshot. Chart-first.",
                ),
            ),
            code("paths", _paths_setup_source()),
            code(
                "health_tables",
                '''with sqlite3.connect(DB_URI, uri=True) as conn:
    run_mix = pd.read_sql_query(
        """
        select status, count(*) as runs
        from job_sync_runs
        group by status
        order by runs desc
        """,
        conn,
    )
    observation_mix = pd.read_sql_query(
        """
        select observation_kind, count(*) as observations
        from job_sync_observations
        group by observation_kind
        order by observations desc
        """,
        conn,
    )
    freshness = pd.read_sql_query(
        """
        select status, min(last_seen_at) as oldest_last_seen,
               max(last_seen_at) as newest_last_seen, count(*) as jobs
        from jobs
        group by status
        order by jobs desc
        """,
        conn,
    )
    coverage = pd.read_sql_query(
        """
        select count(distinct source_id) as sources,
               count(distinct board_key) as boards,
               count(*) as open_jobs
        from jobs
        where status = 'open'
        """,
        conn,
    )

display(coverage)
display(freshness)
display(run_mix)
observation_mix
''',
            ),
            code(
                "health_charts",
                '''if not observation_mix.empty:
    fig = px.bar(
        observation_mix,
        x="observation_kind",
        y="observations",
        color_discrete_sequence=[ROUTE_LEDGER["pine"]],
        title="Observation mix",
    )
    fig.update_layout(
        paper_bgcolor=ROUTE_LEDGER["paper"], font_color=ROUTE_LEDGER["ink"]
    )
    fig.show()
if not run_mix.empty:
    fig2 = px.bar(
        run_mix,
        x="status",
        y="runs",
        color_discrete_sequence=[ROUTE_LEDGER["brass"]],
        title="Sync run status",
    )
    fig2.update_layout(
        paper_bgcolor=ROUTE_LEDGER["paper"], font_color=ROUTE_LEDGER["ink"]
    )
    fig2.show()
''',
            ),
        ]
    )
