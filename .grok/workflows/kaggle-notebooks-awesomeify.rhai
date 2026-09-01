let meta = #{
    name: "kaggle-notebooks-awesomeify",
    description: "Verify, assure, and live-publish goals/kaggle-notebooks-awesomeify after generator notebooks exist",
    when_to_use: "When executing goals/kaggle-notebooks-awesomeify/goal.md: studio notebooks, marketplace copy, local gates, Kaggle COMPLETE, evidence.md",
    phases: [
        #{ title: "Inventory", detail: "confirm seven public kernels and marketplace copy" },
        #{ title: "Verify", detail: "pytest kaggle-meta drift-check dry-run push" },
        #{ title: "Assure", detail: "adversarial fact skeptics" },
        #{ title: "Repair", detail: "one bug-squash pass if needed" },
        #{ title: "Live", detail: "push execute COMPLETE manager QA evidence" },
        #{ title: "Report", detail: "done-condition scratch report" },
    ],
};

fn trimmed(s) {
    if type_of(s) == "string" { s.trim(); s } else { "" }
}

fn ok_of(r) {
    if r == () { return false; }
    if !r.success { return false; }
    if r.output == () { return false; }
    if type_of(r.output) == "map" && r.output.ok == true { return true; }
    false
}

fn verify_schema() {
    #{
        "type": "object",
        "required": ["ok", "summary", "failed_commands"],
        "properties": #{
            "ok": #{ "type": "boolean" },
            "summary": #{ "type": "string" },
            "failed_commands": #{ "type": "array", "items": #{ "type": "string" } },
        },
    }
}

fn verdict_schema() {
    #{
        "type": "object",
        "required": ["real", "reason", "evidence"],
        "properties": #{
            "real": #{ "type": "boolean" },
            "reason": #{ "type": "string" },
            "evidence": #{ "type": "string" },
        },
    }
}

fn live_schema() {
    #{
        "type": "object",
        "required": ["ok", "summary", "evidence_path"],
        "properties": #{
            "ok": #{ "type": "boolean" },
            "summary": #{ "type": "string" },
            "evidence_path": #{ "type": "string" },
        },
    }
}

let skip_live = false;
if args != () && args.skip_live == true { skip_live = true; }

phase("Inventory");
let inv = agent(
    "Read goals/kaggle-notebooks-awesomeify/facts.md and scripts/openopps_kaggle/_core.py PUBLIC_EXAMPLE_NOTEBOOKS plus starter_kernel_metadata. Confirm seven public kernel ids exist (starter, advanced-usage, hiring-market-map, skills-radar, sql-playground, explorer, snapshot-health), dataset title is OpenOppsDB, description does not tell readers to run openoppsdb-manager, explorer source contains gr.Blocks. Use grep and read_file. Set ok=true only with evidence. failed_commands empty if ok.",
    #{ label: "inventory", capability_mode: "read-only", output_schema: verify_schema() }
);
if !ok_of(inv) { complete(#{ summary: "Inventory failed", ok: false }); }

phase("Verify");
let vjobs = [
    #{
        prompt: "Run PYTHONPATH=scripts uv run pytest tests/unit/openopps/kaggle/ tests/unit/openopps/test_readme_landing.py -q --tb=line. Then just kaggle-meta. Then git diff --stat -- kaggle scripts/openopps_kaggle Justfile web/content/docs/operations.mdx README.md. Set ok=true only if pytest passed and kaggle-meta wrote the new example dirs (sql-playground, explorer, snapshot-health). failed_commands lists failing commands. Do not commit, push, or live-publish.",
        label: "verify-local",
        capability_mode: "execute",
        output_schema: verify_schema(),
    },
    #{
        prompt: "Dry-run only: just kaggle-example-notebooks-push and just kaggle-notebook-push (execute defaults to 0). Confirm JSON includes seven public kernel paths plus manager. Do not pass execute=1. Set ok=true only if dry-run JSON ok. Use run_terminal_command.",
        label: "verify-dry-push",
        capability_mode: "execute",
        output_schema: verify_schema(),
    },
];
let vres = parallel(vjobs);
let verify_ok = true;
let failed = [];
for r in vres {
    if !ok_of(r) {
        verify_ok = false;
        if r != () && r.output != () && r.output.failed_commands != () {
            for c in r.output.failed_commands { failed.push(c); }
        } else {
            failed.push("verify-agent-failed");
        }
    }
}

phase("Assure");
let facts = [
    "Public kernels stay credential-free and read-only on /kaggle/input",
    "Starter and Advanced use %%sql; explorer is Gradio Blocks not gr.Interface",
    "Dataset description features Starter and Explorer and omits manager cron",
    "GPU and TPU stay off; no second publish stack",
];
let ajobs = [];
let fi = 0;
for f in facts {
    let p = "Adversarially verify this accepted fact against shipped code with grep/read_file: ";
    p += f;
    p += ". Set real=true only with a file path and quote. Default real=false.";
    ajobs.push(#{
        prompt: p,
        label: "assure-" + fi.to_string(),
        capability_mode: "read-only",
        output_schema: verdict_schema(),
    });
    fi += 1;
}
let ares = parallel(ajobs);
let unproven = [];
let ai = 0;
for r in ares {
    if r == () || !r.success || r.output == () || r.output.real != true {
        unproven.push(facts[ai]);
    }
    ai += 1;
}

if !verify_ok || unproven.len() > 0 {
    phase("Repair");
    let rp = "Repair confirmed gaps for goals/kaggle-notebooks-awesomeify. Failed commands: ";
    rp += json_encode(failed);
    rp += " Unproven facts: ";
    rp += json_encode(unproven);
    rp += " Touch only scripts/openopps_kaggle, kaggle/, Justfile, tests/unit/openopps/kaggle, tests/unit/openopps/test_readme_landing.py, web/content/docs/operations.mdx, README.md, goals/kaggle-notebooks-awesomeify. Re-run pytest kaggle and just kaggle-meta. Do not git commit, push, or live-publish.";
    let repair = agent(rp, #{ label: "repair", capability_mode: "all", output_schema: verify_schema() });
    if !ok_of(repair) { complete(#{ summary: "Repair failed", ok: false, failed: failed, unproven: unproven }); }
}

if skip_live {
    phase("Report");
    let report = write_scratch_file("report.md", "Local verify/assure only. skip_live=true. No Kaggle mutation.");
    complete(#{ summary: "Local gates only", ok: true, path: report, skip_live: true });
}

phase("Live");
let live = agent(
    "Live Kaggle path for goals/kaggle-notebooks-awesomeify after local gates. 1) just kaggle-example-notebooks-push execute=1 timeout=7200. 2) Poll just kaggle-example-notebooks-status until all seven public kernels COMPLETE. Do not fake COMPLETE. 3) just kaggle-example-notebooks-pull-check. 4) just kaggle-notebook-push execute=1 timeout=7200 and wait for manager COMPLETE. Dataset version only via existing quality gate. 5) Human-equivalent Kaggle check: open dataset page and kernel pages if browser tools exist; record whether Starter/Advanced sql, Explorer Gradio, charts, and dataset notebook index look live. 6) Write goals/kaggle-notebooks-awesomeify/evidence.md with statuses. If secrets/runtime block, set ok=false and say the goal stays open. Never invent COMPLETE.",
    #{ label: "live-kaggle", capability_mode: "all", output_schema: live_schema() }
);

phase("Report");
let live_ok = ok_of(live);
let summary = "kaggle-notebooks-awesomeify workflow finished";
if live != () && live.output != () && live.output.summary != () {
    summary = trimmed(live.output.summary);
}
let evidence = "";
if live != () && live.output != () && live.output.evidence_path != () {
    evidence = trimmed(live.output.evidence_path);
}
let report = write_scratch_file("report.md", summary);
complete(#{ summary: summary, ok: live_ok, evidence_path: evidence, path: report });
