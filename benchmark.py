#!/usr/bin/env python3 -u
"""
OpenCode Fast Apply Benchmark Suite v2 — Rigorous & Reproducible

Methodology:
- Golden files: each scenario has a hand-written expected output
- Scoring: exact match (byte-for-byte) + diff similarity (normalized edit distance)
- Statistical rigor: N runs per model, reports mean/stddev/95% CI/pass@k
- Safety: marker leakage + catastrophic truncation detection
- Parallel execution: ThreadPoolExecutor with retry + circuit breaker
- Resilience: checkpoints after each scenario, resume on crash, graceful shutdown

Usage:
    python3 benchmark.py                          # 5 runs, all scenarios
    python3 benchmark.py --runs 10 --save         # 10 runs, save BENCHMARK.md
    python3 benchmark.py --fast-apply-only        # skip compaction
    python3 benchmark.py --compaction-only        # skip fast-apply
    python3 benchmark.py --scenario small-single  # single scenario
    python3 benchmark.py --runs 1                 # quick validation
    python3 benchmark.py --resume                 # resume from last checkpoint
    python3 benchmark.py --clean                  # delete checkpoint and start fresh
"""

import json, time, os, sys, math, urllib.request, threading, signal
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

PROXY = os.environ.get("FLOW_LITELLM_PROXY", "https://flow.ciandt.com/flow-llm-proxy")
PROXY_URL = f"{PROXY}/v1/chat/completions"
API_KEY = os.environ.get("FLOW_API_KEY", "")
TIMEOUT = 60
MARKER = "// ... existing code ..."
MAX_WORKERS = 6
MAX_RETRIES = 2
CIRCUIT_THRESHOLD = 3

BASE_DIR = Path(__file__).parent / "benchmarks" / "scenarios"

MODELS = [
    "anthropic.claude-4-6-opus", "anthropic.claude-4-6-sonnet",
    "anthropic.claude-4-5-sonnet", "anthropic.claude-4-5-haiku",
    "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash",
    "gpt5.5", "gpt5.2", "gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-5-nano",
    "gpt-4.1", "gpt-4o-mini", "o3-mini",
    "DeepSeek-R1", "DeepSeek-V4-Pro", "mistral-small-2503",
]

MERGE_SYSTEM = f"""You are a code merge specialist. You receive an original file and a partial edit using "{MARKER}" markers for unchanged sections.
Replace each marker with the corresponding unchanged code from the original. Return ONLY the complete merged file. No explanations, no markdown fences, no commentary."""

COMPACT_SYSTEM = """You are a conversation compactor for an AI coding agent. Summarize the conversation below, preserving:
1. ALL file paths mentioned (exact paths)
2. ALL decisions made and changes applied
3. ALL errors encountered and how they were resolved
4. Pending next steps

Be concise but complete. Target ~400 tokens. Use bullet points. Group by topic."""

# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint manager — survives crashes, supports resume
# ─────────────────────────────────────────────────────────────────────────────

CHECKPOINT_PATH = Path(__file__).parent / ".benchmark-checkpoint.json"

_shutdown_requested = False


def load_checkpoint():
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_checkpoint(state):
    tmp = CHECKPOINT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.rename(CHECKPOINT_PATH)


def delete_checkpoint():
    CHECKPOINT_PATH.unlink(missing_ok=True)


def handle_shutdown(signum, frame):
    global _shutdown_requested
    if _shutdown_requested:
        safe_print("\n[!] Force quit — checkpoint preserved for --resume")
        sys.exit(1)
    _shutdown_requested = True
    safe_print("\n[!] Graceful shutdown requested — finishing current models, saving checkpoint...")


def is_shutdown():
    return _shutdown_requested


# ─────────────────────────────────────────────────────────────────────────────
# Thread safety + circuit breaker
# ─────────────────────────────────────────────────────────────────────────────

_print_lock = threading.Lock()
_circuit = {}
_circuit_lock = threading.Lock()


def safe_print(*a, **kw):
    with _print_lock:
        print(*a, **kw)
        sys.stdout.flush()


def is_circuit_open(model):
    with _circuit_lock:
        return _circuit.get(model, 0) >= CIRCUIT_THRESHOLD


def record_circuit(model, success):
    with _circuit_lock:
        _circuit[model] = 0 if success else _circuit.get(model, 0) + 1


def reset_circuit():
    with _circuit_lock:
        _circuit.clear()


# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────

def call_api(model, system, user, max_tokens=4096):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(PROXY_URL, data=body, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
        dt = time.time() - t0
        c = d["choices"][0]["message"]["content"]
        u = d.get("usage", {})
        return {"ok": True, "content": c, "time": round(dt, 2),
                "tokens_in": u.get("prompt_tokens", 0),
                "tokens_out": u.get("completion_tokens", 0)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100], "time": round(time.time() - t0, 2)}


def call_with_retry(model, system, user, max_tokens=4096):
    if is_circuit_open(model):
        return {"ok": False, "error": "circuit open", "time": 0}
    for attempt in range(1 + MAX_RETRIES):
        r = call_api(model, system, user, max_tokens)
        if r["ok"]:
            record_circuit(model, True)
            return r
        if "429" in r.get("error", ""):
            time.sleep(2 ** attempt)
            continue
        if "timed out" in r.get("error", "").lower() and attempt < MAX_RETRIES:
            continue
        break
    record_circuit(model, False)
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def strip_fences(code):
    t = code.strip()
    lines = t.split("\n")
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return code


def normalize_output(text):
    return text.strip() + "\n"


def exact_match(output, golden):
    return 1 if normalize_output(output) == normalize_output(golden) else 0


def levenshtein(s1, s2):
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for c1 in s1:
        curr = [prev[0] + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if c1 == c2 else 1)))
        prev = curr
    return prev[-1]


def diff_similarity(output, golden):
    o = normalize_output(output)
    g = normalize_output(golden)
    max_len = max(len(o), len(g))
    if max_len == 0:
        return 1.0
    if max_len > 50000:
        import difflib
        ratio = difflib.SequenceMatcher(None, o, g).ratio()
        return round(ratio, 4)
    dist = levenshtein(o, g)
    return round(1 - (dist / max_len), 4)


def has_marker_leak(original, output):
    return MARKER not in original and MARKER in output


def has_truncation(original, output):
    ol = len(original.split("\n"))
    ml = len(output.split("\n"))
    cl = (len(original) - len(output)) / len(original) if len(original) > 0 else 0
    ll = (ol - ml) / ol if ol > 0 else 0
    return cl > 0.6 and ll > 0.5


def check_keywords(content, must_have):
    if not content or not must_have:
        return 0, 0
    low = content.lower()
    passed = sum(1 for kw in must_have if kw.lower() in low)
    return passed, len(must_have)


# ─────────────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────────────

def stats(values):
    n = len(values)
    if n == 0:
        return {"mean": 0, "std": 0, "ci_lo": 0, "ci_hi": 0, "n": 0}
    mean = sum(values) / n
    if n == 1:
        return {"mean": round(mean, 4), "std": 0, "ci_lo": round(mean, 4), "ci_hi": round(mean, 4), "n": 1}
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    std = variance ** 0.5
    se = std / math.sqrt(n)
    margin = 1.96 * se
    return {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "ci_lo": round(mean - margin, 4),
        "ci_hi": round(mean + margin, 4),
        "n": n,
    }


def pass_at_k(n, c, k):
    if n < k or c == 0:
        return 0.0
    return round(1 - (math.comb(n - c, k) / math.comb(n, k)), 4)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario loading
# ─────────────────────────────────────────────────────────────────────────────

def load_fast_apply_scenarios(filter_name=None):
    scenarios = []
    fa_dir = BASE_DIR / "fast-apply"
    if not fa_dir.exists():
        safe_print(f"WARNING: {fa_dir} not found")
        return []
    for d in sorted(fa_dir.iterdir()):
        if not d.is_dir():
            continue
        if filter_name and d.name != filter_name:
            continue
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        original = (d / "original.ts").read_text()
        edit = (d / "edit.ts").read_text()
        golden = (d / "golden.ts").read_text()
        scenarios.append({
            "name": meta["name"],
            "description": meta.get("description", ""),
            "instructions": meta.get("instructions", ""),
            "type": "fast-apply",
            "original": original,
            "edit": edit,
            "golden": golden,
            "dir": d,
        })
    return scenarios


def load_compaction_scenarios(filter_name=None):
    scenarios = []
    c_dir = BASE_DIR / "compaction"
    if not c_dir.exists():
        safe_print(f"WARNING: {c_dir} not found")
        return []
    for d in sorted(c_dir.iterdir()):
        if not d.is_dir():
            continue
        if filter_name and d.name != filter_name:
            continue
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        conversation = (d / "conversation.txt").read_text()
        golden = (d / "golden.txt").read_text()
        scenarios.append({
            "name": meta["name"],
            "description": meta.get("description", ""),
            "type": "compaction",
            "conversation": conversation,
            "golden": golden,
            "checks": meta.get("checks", {}),
            "dir": d,
        })
    return scenarios


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark runners
# ─────────────────────────────────────────────────────────────────────────────

def run_fast_apply_scenario(scenario, n_runs, only_models=None):
    name = scenario["name"]
    original = scenario["original"]
    edit = scenario["edit"]
    golden = scenario["golden"]
    instructions = scenario["instructions"]
    user_msg = f"<original>\n{original}\n</original>\n\n<edit>\n{edit}\n</edit>\n\nInstructions: {instructions}\n\nReturn the complete merged file:"
    models_to_run = only_models or MODELS
    max_tok = max(len(original.split("\n")) * 20, 4096)

    safe_print(f"\n{'=' * 100}")
    safe_print(f"BENCHMARK: Fast Apply — {name} ({scenario['description']}) — {n_runs} runs")
    safe_print(f"{'=' * 100}")

    model_results = {}

    def run_model(model):
        runs = []
        for _ in range(n_runs):
            if is_shutdown():
                break
            r = call_with_retry(model, MERGE_SYSTEM, user_msg, max_tok)
            if r["ok"]:
                output = strip_fences(r["content"])
                em = exact_match(output, golden)
                ds = diff_similarity(output, golden)
                leak = has_marker_leak(original, output)
                trunc = has_truncation(original, output)
                runs.append({
                    "exact": em, "diff_sim": ds, "leak": leak, "trunc": trunc,
                    "time": r["time"], "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                })
            else:
                runs.append({"exact": 0, "diff_sim": 0, "leak": False, "trunc": False,
                             "time": r["time"], "tokens_in": 0, "tokens_out": 0, "error": r.get("error", "")})
        return model, runs

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(run_model, m): m for m in models_to_run}
        for f in as_completed(futures):
            model, runs = f.result()
            model_results[model] = runs

    # Print results
    safe_print(f"{'MODEL':<30} {'EXACT':>7} {'DIFF_SIM':>9} {'TIME':>10} {'TOK/S':>8} {'PASS@1':>7} {'LEAK':>5} {'TRUNC':>6}")
    safe_print("-" * 95)

    summary = []
    for m in models_to_run:
        runs = model_results.get(m, [])
        if not runs or all("error" in r for r in runs):
            err = runs[0].get("error", "unknown") if runs else "no data"
            safe_print(f"{m:<30} {'FAIL':>7} {'':>9} {'':>10} {'':>8} {'':>7} {'':>5} {'':>6}  {err[:30]}")
            summary.append({"model": m, "ok": False, "error": err})
            continue

        exacts = [r["exact"] for r in runs if "error" not in r]
        diffs = [r["diff_sim"] for r in runs if "error" not in r]
        times = [r["time"] for r in runs if "error" not in r]
        tps_list = [r["tokens_out"] / r["time"] if r["time"] > 0 else 0 for r in runs if "error" not in r]
        leaks = sum(1 for r in runs if r.get("leak"))
        truncs = sum(1 for r in runs if r.get("trunc"))
        n_ok = len(exacts)

        e_st = stats(exacts)
        d_st = stats(diffs)
        t_st = stats(times)
        tps_st = stats(tps_list)

        p1 = pass_at_k(n_ok, sum(exacts), 1)
        p5 = pass_at_k(n_ok, sum(exacts), min(5, n_ok))

        safe_print(
            f"{m:<30} "
            f"{e_st['mean']*100:>5.1f}% "
            f"{d_st['mean']:>9.4f} "
            f"{t_st['mean']:>7.1f}±{t_st['std']:<4.1f} "
            f"{tps_st['mean']:>7.1f} "
            f"{p1:>6.2f} "
            f"{leaks:>5} "
            f"{truncs:>6}"
        )

        summary.append({
            "model": m, "ok": True, "n_runs": n_ok,
            "exact": e_st, "diff_sim": d_st, "time": t_st, "tps": tps_st,
            "pass_at_1": p1, "pass_at_5": p5,
            "leaks": leaks, "truncations": truncs,
        })

    return {"scenario": name, "description": scenario["description"], "results": summary}


def run_compaction_scenario(scenario, n_runs, only_models=None):
    name = scenario["name"]
    conversation = scenario["conversation"]
    golden = scenario["golden"]
    checks = scenario.get("checks", {})
    must_have = checks.get("must_have", [])
    user_msg = f"Summarize this coding agent conversation:\n\n{conversation}"
    models_to_run = only_models or MODELS

    safe_print(f"\n{'=' * 100}")
    safe_print(f"BENCHMARK: Compaction — {name} ({scenario['description']}) — {n_runs} runs")
    safe_print(f"{'=' * 100}")

    model_results = {}

    def run_model(model):
        runs = []
        for _ in range(n_runs):
            if is_shutdown():
                break
            r = call_with_retry(model, COMPACT_SYSTEM, user_msg, 1024)
            if r["ok"]:
                ds = diff_similarity(r["content"], golden)
                kw_passed, kw_total = check_keywords(r["content"], must_have)
                ratio = round(r["tokens_out"] / r["tokens_in"], 3) if r["tokens_in"] > 0 else 0
                runs.append({
                    "diff_sim": ds, "kw_passed": kw_passed, "kw_total": kw_total,
                    "ratio": ratio, "time": r["time"],
                    "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                })
            else:
                runs.append({"diff_sim": 0, "kw_passed": 0, "kw_total": len(must_have),
                             "ratio": 0, "time": r["time"], "error": r.get("error", "")})
        return model, runs

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(run_model, m): m for m in models_to_run}
        for f in as_completed(futures):
            model, runs = f.result()
            model_results[model] = runs

    safe_print(f"{'MODEL':<30} {'KW_SCORE':>9} {'DIFF_SIM':>9} {'RATIO':>7} {'TIME':>10} {'TOK/S':>8}")
    safe_print("-" * 85)

    summary = []
    for m in models_to_run:
        runs = model_results.get(m, [])
        if not runs or all("error" in r for r in runs):
            err = runs[0].get("error", "unknown") if runs else "no data"
            safe_print(f"{m:<30} {'FAIL':>9} {'':>9} {'':>7} {'':>10} {'':>8}  {err[:30]}")
            summary.append({"model": m, "ok": False, "error": err})
            continue

        ok_runs = [r for r in runs if "error" not in r]
        kw_scores = [r["kw_passed"] / r["kw_total"] if r["kw_total"] > 0 else 0 for r in ok_runs]
        diffs = [r["diff_sim"] for r in ok_runs]
        ratios = [r["ratio"] for r in ok_runs]
        times = [r["time"] for r in ok_runs]
        tps_list = [r["tokens_out"] / r["time"] if r["time"] > 0 else 0 for r in ok_runs]

        kw_st = stats(kw_scores)
        d_st = stats(diffs)
        r_st = stats(ratios)
        t_st = stats(times)
        tps_st = stats(tps_list)

        safe_print(
            f"{m:<30} "
            f"{kw_st['mean']*100:>7.1f}% "
            f"{d_st['mean']:>9.4f} "
            f"{r_st['mean']:>6.3f} "
            f"{t_st['mean']:>7.1f}±{t_st['std']:<4.1f} "
            f"{tps_st['mean']:>7.1f}"
        )

        summary.append({
            "model": m, "ok": True, "n_runs": len(ok_runs),
            "kw_score": kw_st, "diff_sim": d_st, "ratio": r_st,
            "time": t_st, "tps": tps_st,
        })

    return {"scenario": name, "description": scenario["description"], "results": summary}


# ─────────────────────────────────────────────────────────────────────────────
# Recommendations + pairwise tests
# ─────────────────────────────────────────────────────────────────────────────

def paired_ttest(vals_a, vals_b):
    n = min(len(vals_a), len(vals_b))
    if n < 2:
        return None, None
    diffs = [vals_a[i] - vals_b[i] for i in range(n)]
    mean_d = sum(diffs) / n
    var_d = sum((d - mean_d) ** 2 for d in diffs) / (n - 1)
    if var_d == 0:
        return float("inf") if mean_d != 0 else 0, 0 if mean_d == 0 else 1
    se_d = (var_d / n) ** 0.5
    t_stat = mean_d / se_d
    # Approximate p-value using normal distribution for simplicity
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2))))
    return round(t_stat, 3), round(p, 4)


def print_recommendations(fa_reports, compact_reports):
    safe_print(f"\n{'=' * 100}")
    safe_print("RECOMMENDATIONS")
    safe_print(f"{'=' * 100}")

    if fa_reports:
        safe_print("\n## Fast Apply")
        scores = {}
        for report in fa_reports:
            for r in report["results"]:
                if not r.get("ok"):
                    continue
                m = r["model"]
                if m not in scores:
                    scores[m] = {"exact_sum": 0, "time_sum": 0, "tps_sum": 0, "scenarios": 0}
                scores[m]["exact_sum"] += r["exact"]["mean"]
                scores[m]["time_sum"] += r["time"]["mean"]
                scores[m]["tps_sum"] += r["tps"]["mean"]
                scores[m]["scenarios"] += 1

        for m in scores:
            s = scores[m]
            n = s["scenarios"]
            s["exact_avg"] = round(s["exact_sum"] / n, 4) if n > 0 else 0
            s["time_avg"] = round(s["time_sum"] / n, 1) if n > 0 else 999
            s["tps_avg"] = round(s["tps_sum"] / n, 1) if n > 0 else 0

        ranked = sorted(scores.items(), key=lambda x: (-x[1]["exact_avg"], x[1]["time_avg"]))
        safe_print(f"{'MODEL':<30} {'EXACT_AVG':>10} {'TIME_AVG':>10} {'TOK/S_AVG':>10} {'SCENARIOS':>10}")
        safe_print("-" * 75)
        for m, s in ranked[:10]:
            safe_print(f"{m:<30} {s['exact_avg']*100:>8.1f}% {s['time_avg']:>9.1f}s {s['tps_avg']:>9.1f} {s['scenarios']:>10}")

        if len(ranked) >= 2:
            safe_print(f"\n  >> RECOMMENDED: {ranked[0][0]} (exact={ranked[0][1]['exact_avg']*100:.1f}%, avg time={ranked[0][1]['time_avg']}s)")

    if compact_reports:
        safe_print("\n## Compaction")
        scores = {}
        for report in compact_reports:
            for r in report["results"]:
                if not r.get("ok"):
                    continue
                m = r["model"]
                if m not in scores:
                    scores[m] = {"kw_sum": 0, "ratio_sum": 0, "time_sum": 0, "scenarios": 0}
                scores[m]["kw_sum"] += r["kw_score"]["mean"]
                scores[m]["ratio_sum"] += r["ratio"]["mean"]
                scores[m]["time_sum"] += r["time"]["mean"]
                scores[m]["scenarios"] += 1

        for m in scores:
            s = scores[m]
            n = s["scenarios"]
            s["kw_avg"] = round(s["kw_sum"] / n, 4) if n > 0 else 0
            s["ratio_avg"] = round(s["ratio_sum"] / n, 3) if n > 0 else 99
            s["time_avg"] = round(s["time_sum"] / n, 1) if n > 0 else 999

        ranked = sorted(scores.items(), key=lambda x: (-x[1]["kw_avg"], x[1]["ratio_avg"], x[1]["time_avg"]))
        safe_print(f"{'MODEL':<30} {'KW_AVG':>8} {'RATIO_AVG':>10} {'TIME_AVG':>10}")
        safe_print("-" * 65)
        for m, s in ranked[:10]:
            safe_print(f"{m:<30} {s['kw_avg']*100:>6.1f}% {s['ratio_avg']:>9.3f} {s['time_avg']:>9.1f}s")

        if ranked:
            safe_print(f"\n  >> RECOMMENDED: {ranked[0][0]} (keywords={ranked[0][1]['kw_avg']*100:.1f}%, ratio={ranked[0][1]['ratio_avg']}, time={ranked[0][1]['time_avg']}s)")


# ─────────────────────────────────────────────────────────────────────────────
# Markdown report
# ─────────────────────────────────────────────────────────────────────────────

def save_markdown(fa_reports, compact_reports, n_runs):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# OpenCode Fast Apply Benchmark Results",
        "",
        "## Methodology",
        "",
        f"- **Date**: {ts}",
        f"- **Proxy**: `{PROXY}`",
        f"- **Models tested**: {len(MODELS)}",
        f"- **Runs per model per scenario**: {n_runs}",
        f"- **Concurrency**: {MAX_WORKERS} threads, {MAX_RETRIES} retries, circuit breaker at {CIRCUIT_THRESHOLD}",
        f"- **Scoring**: Exact match (byte-for-byte vs golden file) + Diff similarity (normalized edit distance)",
        f"- **Statistics**: Mean, StdDev, 95% CI, Pass@1, Pass@5 (unbiased estimator)",
        "",
    ]

    for report in fa_reports:
        lines.append(f"## Fast Apply — {report['scenario']}")
        lines.append(f"_{report['description']}_")
        lines.append("")
        lines.append("| Model | Exact Match | Diff Sim | Time (s) | Tok/s | Pass@1 | Leaks | Truncations |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for r in sorted(report["results"], key=lambda x: (-x.get("exact", {}).get("mean", 0), x.get("time", {}).get("mean", 999)) if x.get("ok") else (0, 999)):
            if r.get("ok"):
                e = r["exact"]
                d = r["diff_sim"]
                t = r["time"]
                tps = r["tps"]
                lines.append(
                    f"| {r['model']} "
                    f"| {e['mean']*100:.1f}% [{e['ci_lo']*100:.0f}-{e['ci_hi']*100:.0f}] "
                    f"| {d['mean']:.4f} ±{d['std']:.4f} "
                    f"| {t['mean']:.1f} ±{t['std']:.1f} "
                    f"| {tps['mean']:.1f} "
                    f"| {r['pass_at_1']:.2f} "
                    f"| {r['leaks']} "
                    f"| {r['truncations']} |"
                )
            else:
                lines.append(f"| {r['model']} | FAIL | — | — | — | — | — | — |")
        lines.append("")

    for report in compact_reports:
        lines.append(f"## Compaction — {report['scenario']}")
        lines.append(f"_{report['description']}_")
        lines.append("")
        lines.append("| Model | Keywords | Diff Sim | Ratio | Time (s) | Tok/s |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for r in sorted(report["results"], key=lambda x: (-x.get("kw_score", {}).get("mean", 0), x.get("ratio", {}).get("mean", 99)) if x.get("ok") else (0, 99)):
            if r.get("ok"):
                kw = r["kw_score"]
                d = r["diff_sim"]
                ra = r["ratio"]
                t = r["time"]
                tps = r["tps"]
                lines.append(
                    f"| {r['model']} "
                    f"| {kw['mean']*100:.1f}% ±{kw['std']*100:.1f} "
                    f"| {d['mean']:.4f} "
                    f"| {ra['mean']:.3f} ±{ra['std']:.3f} "
                    f"| {t['mean']:.1f} ±{t['std']:.1f} "
                    f"| {tps['mean']:.1f} |"
                )
            else:
                lines.append(f"| {r['model']} | FAIL | — | — | — | — |")
        lines.append("")

    path = Path(__file__).parent / "BENCHMARK.md"
    path.write_text("\n".join(lines))
    safe_print(f"\nResults saved to {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main — with checkpoint/resume and graceful shutdown
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="OpenCode Fast Apply Benchmark v2")
    parser.add_argument("--runs", type=int, default=5, help="Runs per model per scenario (default: 5)")
    parser.add_argument("--save", action="store_true", help="Save results to BENCHMARK.md")
    parser.add_argument("--fast-apply-only", action="store_true")
    parser.add_argument("--compaction-only", action="store_true")
    parser.add_argument("--scenario", type=str, default=None, help="Run single scenario by name")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--clean", action="store_true", help="Delete checkpoint and start fresh")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    if args.clean:
        delete_checkpoint()
        print("Checkpoint deleted.")
        if not any([args.save, args.fast_apply_only, args.compaction_only, args.scenario]):
            return

    if not API_KEY:
        print("ERROR: FLOW_API_KEY not set")
        sys.exit(1)

    # Load scenarios
    fa_scenarios = [] if args.compaction_only else load_fast_apply_scenarios(args.scenario)
    c_scenarios = [] if args.fast_apply_only else load_compaction_scenarios(args.scenario)
    all_scenario_names = [s["name"] for s in fa_scenarios] + [s["name"] for s in c_scenarios]

    # Load checkpoint if resuming
    checkpoint = load_checkpoint() if args.resume else None
    completed_scenarios = set()
    fa_reports = []
    c_reports = []

    if checkpoint:
        completed_scenarios = set(checkpoint.get("completed", []))
        fa_reports = checkpoint.get("fa_reports", [])
        c_reports = checkpoint.get("c_reports", [])
        prev_runs = checkpoint.get("runs", args.runs)
        if prev_runs != args.runs:
            print(f"WARNING: checkpoint has --runs {prev_runs} but you passed --runs {args.runs}. Using {prev_runs} for consistency.")
            args.runs = prev_runs
        skipped = len(completed_scenarios)
        print(f"Resuming from checkpoint — {skipped} scenarios done, {len(all_scenario_names) - skipped} remaining")
    else:
        delete_checkpoint()

    # Filter out completed scenarios
    fa_todo = [s for s in fa_scenarios if s["name"] not in completed_scenarios]
    c_todo = [s for s in c_scenarios if s["name"] not in completed_scenarios]

    total_calls = (len(MODELS) * len(fa_todo) + len(MODELS) * len(c_todo)) * args.runs
    total_scenarios = len(fa_todo) + len(c_todo)

    print(f"OpenCode Benchmark Suite v2")
    print(f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Proxy: {PROXY}")
    print(f"Models: {len(MODELS)} | Scenarios: {total_scenarios} | Runs: {args.runs} | Calls remaining: {total_calls}")
    print(f"Workers: {MAX_WORKERS} | Retries: {MAX_RETRIES} | Est. time: {total_calls * 8 // 60}–{total_calls * 15 // 60} min")
    if completed_scenarios:
        print(f"Checkpoint: {len(completed_scenarios)} scenarios cached ({', '.join(sorted(completed_scenarios))})")

    t0 = time.time()

    # ── Main pass: run all scenarios ──
    for s in fa_todo:
        if is_shutdown():
            break
        reset_circuit()
        report = run_fast_apply_scenario(s, args.runs)
        fa_reports.append(report)
        completed_scenarios.add(s["name"])
        save_checkpoint({
            "completed": list(completed_scenarios),
            "fa_reports": fa_reports,
            "c_reports": c_reports,
            "runs": args.runs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        safe_print(f"  [checkpoint saved — {len(completed_scenarios)}/{len(all_scenario_names)} scenarios done]")

    for s in c_todo:
        if is_shutdown():
            break
        reset_circuit()
        report = run_compaction_scenario(s, args.runs)
        c_reports.append(report)
        completed_scenarios.add(s["name"])
        save_checkpoint({
            "completed": list(completed_scenarios),
            "fa_reports": fa_reports,
            "c_reports": c_reports,
            "runs": args.runs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        safe_print(f"  [checkpoint saved — {len(completed_scenarios)}/{len(all_scenario_names)} scenarios done]")

    # ── Retry pass: re-run failed models per scenario ──
    if not is_shutdown():
        failed_found = False
        for report in fa_reports:
            failed_models = [r["model"] for r in report["results"] if not r.get("ok")]
            if not failed_models:
                continue
            if not failed_found:
                safe_print(f"\n{'=' * 100}")
                safe_print("RETRY PASS — re-running failed models")
                safe_print(f"{'=' * 100}")
                failed_found = True

            scenario_name = report["scenario"]
            scenario = next((s for s in fa_scenarios if s["name"] == scenario_name), None)
            if not scenario:
                continue

            safe_print(f"\n  Retrying {len(failed_models)} models for {scenario_name}: {', '.join(failed_models)}")
            reset_circuit()
            retry_report = run_fast_apply_scenario(scenario, args.runs, only_models=failed_models)

            # Merge retry results into original report
            existing = {r["model"]: i for i, r in enumerate(report["results"])}
            for r in retry_report["results"]:
                if r["model"] in existing:
                    idx = existing[r["model"]]
                    if r.get("ok"):
                        report["results"][idx] = r
                        safe_print(f"    {r['model']}: recovered ({r['exact']['mean']*100:.0f}% exact)")
                    else:
                        safe_print(f"    {r['model']}: still failing ({r.get('error', 'unknown')[:40]})")

        for report in c_reports:
            failed_models = [r["model"] for r in report["results"] if not r.get("ok")]
            if not failed_models:
                continue
            if not failed_found:
                safe_print(f"\n{'=' * 100}")
                safe_print("RETRY PASS — re-running failed models")
                safe_print(f"{'=' * 100}")
                failed_found = True

            scenario_name = report["scenario"]
            scenario = next((s for s in c_scenarios if s["name"] == scenario_name), None)
            if not scenario:
                continue

            safe_print(f"\n  Retrying {len(failed_models)} models for {scenario_name}: {', '.join(failed_models)}")
            reset_circuit()
            retry_report = run_compaction_scenario(scenario, args.runs, only_models=failed_models)

            existing = {r["model"]: i for i, r in enumerate(report["results"])}
            for r in retry_report["results"]:
                if r["model"] in existing:
                    idx = existing[r["model"]]
                    if r.get("ok"):
                        report["results"][idx] = r
                        safe_print(f"    {r['model']}: recovered ({r['kw_score']['mean']*100:.0f}% keywords)")
                    else:
                        safe_print(f"    {r['model']}: still failing ({r.get('error', 'unknown')[:40]})")

        if failed_found:
            # Update checkpoint with retry results
            save_checkpoint({
                "completed": list(completed_scenarios),
                "fa_reports": fa_reports,
                "c_reports": c_reports,
                "runs": args.runs,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            safe_print("  [checkpoint updated with retry results]")
        else:
            safe_print("\n  No failed models — retry pass skipped.")

    elapsed = round(time.time() - t0, 1)

    if is_shutdown():
        safe_print(f"\n[!] Shutdown after {elapsed}s — {len(completed_scenarios)}/{len(all_scenario_names)} scenarios saved")
        safe_print(f"    Resume with: python3 benchmark.py --resume --runs {args.runs}" + (" --save" if args.save else ""))
    else:
        actual_calls = (len(MODELS) * len(fa_todo) + len(MODELS) * len(c_todo)) * args.runs
        rate = round(actual_calls / elapsed * 60, 1) if elapsed > 0 else 0
        print(f"\nTotal: {elapsed}s ({actual_calls} calls, {rate} calls/min)")

    print_recommendations(fa_reports, c_reports)

    if args.save:
        save_markdown(fa_reports, c_reports, args.runs)

    # Clean up checkpoint on successful full completion
    if not is_shutdown() and len(completed_scenarios) == len(all_scenario_names):
        delete_checkpoint()
        safe_print("[checkpoint cleared — full run complete]")


if __name__ == "__main__":
    main()
