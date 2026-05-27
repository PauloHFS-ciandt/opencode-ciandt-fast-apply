# opencode-ciandt-fast-apply

An [OpenCode](https://opencode.ai) plugin that merges code edits using lazy markers via the CI&T Flow LLM Proxy. Instead of rewriting entire files, agents generate only the changed snippets — a fast merge model expands the markers and applies the edit.

## Why

Coding agents waste output tokens rewriting unchanged code. A 500-line file where 3 lines change means 497 wasted lines of output. This plugin changes the flow:

1. Agent generates a **partial snippet** with `// ... existing code ...` markers (~25 lines)
2. Plugin sends the snippet + original file to a **fast merge model** on the CI&T proxy
3. Merge model returns the complete file with changes applied
4. Safety guards validate the output before writing

The merge format is also **more accurate** than full rewrites — in benchmarks, 13/19 models achieved PERFECT merge quality vs 0/19 on full rewrite.

## Installation

Add to your `~/.config/opencode/opencode.json`:

```json
{
  "plugin": ["github:PauloHFS-ciandt/opencode-ciandt-fast-apply"]
}
```

Restart OpenCode. The plugin downloads automatically.

## Requirements

- [OpenCode](https://opencode.ai) v1.0+
- Access to CI&T Flow LLM Proxy (`flow.ciandt.com`)
- `FLOW_API_KEY` environment variable set (JWT token from CI&T)
- `FLOW_LITELLM_PROXY` environment variable (optional, defaults to `https://flow.ciandt.com/flow-llm-proxy`)

## How It Works

```
Agent (Opus/Sonnet/GPT)              Plugin                    CI&T Proxy
    |                                   |                          |
    |--- fast_apply(file, snippet) ---->|                          |
    |                                   |-- read original file     |
    |                                   |-- POST /chat/completions |
    |                                   |   model: gpt-5.1         |
    |                                   |   "merge this edit"      |
    |                                   |<-- merged file ----------|
    |                                   |-- safety guards          |
    |                                   |-- write file             |
    |<-- "Applied +3/-1 lines" ---------|                          |
```

## Edit Format

Agents use `// ... existing code ...` markers to represent unchanged sections:

```typescript
// ... existing code ...
function getUser(req, res) {
  if (!req.params.id.match(/^[a-f0-9-]{36}$/)) {
    throw new ValidationError("Invalid ID");
  }
  // ... existing code ...
}
// ... existing code ...
```

The merge model expands each marker with the corresponding original code.

## Configuration

All configuration via environment variables:

| Variable | Default | Description |
|---|---|---|
| `FLOW_API_KEY` | (required) | CI&T proxy JWT token |
| `FLOW_LITELLM_PROXY` | `https://flow.ciandt.com/flow-llm-proxy` | Proxy base URL |
| `FAST_APPLY_MODEL` | `gpt-5.1` | Model for merge operations |
| `FAST_APPLY_ENABLED` | `true` | Set to `false` to disable |

## Commands

| Command | Description |
|---|---|
| `/fast-apply` | Show plugin status, active model, and session stats |

## Safety Guards

The plugin validates every merge before writing to disk:

| Guard | What it catches |
|---|---|
| **Marker leakage** | Merge model left `// ... existing code ...` in the output instead of expanding it |
| **Catastrophic truncation** | Merged output lost >60% chars AND >50% lines vs original |
| **Missing markers** | Agent forgot markers on a file >10 lines |
| **Readonly blocking** | Blocks `fast_apply` in explore/plan agents |

On any guard failure, the file is NOT modified and the agent gets an error with fallback instructions.

## Routing

The plugin injects a system prompt hint (~50 tokens) that teaches agents when to use `fast_apply`:

- **Use `fast_apply`**: existing files >30 lines with scattered changes
- **Use native `edit`**: small exact replacements (<5 lines)
- **Use `write`**: new files

## Benchmark

Tested 19 models on the CI&T proxy across 8 scenarios (6 fast-apply + 2 compaction), 10 runs per model per scenario (1520 total API calls). Scoring uses exact byte-for-byte match against hand-written golden files. Full results in [BENCHMARK.md](./BENCHMARK.md).

### Fast Apply — Top 5 (100% exact match across ALL 6 scenarios, 10 runs each)

| Model | Exact Match | Avg Time | Tok/s |
|---|---:|---:|---:|
| **anthropic.claude-4-5-haiku** | **100% (60/60)** | **4.8s** | 142.8 |
| gpt-4.1 | 100% (60/60) | 5.1s | 113.8 |
| DeepSeek-V4-Pro | 100% (60/60) | 8.3s | 81.3 |
| anthropic.claude-4-6-opus | 100% (60/60) | 8.6s | 78.3 |
| anthropic.claude-4-5-sonnet | 100% (60/60) | 8.8s | 78.6 |

### Models that failed at scale (10 runs exposed inconsistency)

| Model | Exact Match | Failure scenario |
|---|---:|---|
| gpt-5.1 | 60% on large-complex | 4/10 runs produce incorrect merge on 200+ line files |
| gpt5.5 | 70% on small-single | 3/10 runs fail even on simple 30-line merges |
| gpt-5-nano | 10-70% across scenarios | Unreliable, frequent truncation |

### Compaction — Top 3 (100% keyword preservation)

| Model | Keywords | Compression Ratio | Avg Time |
|---|---:|---:|---:|
| **mistral-small-2503** | **100%** | **0.166** | **3.1s** |
| anthropic.claude-4-6-opus | 100% | 0.192 | 9.1s |
| gpt-4o-mini | 100% | 0.193 | 8.8s |

### Key Findings

- **Haiku 4.5 is the most reliable merge model** — 100% exact match over 60 runs across all difficulty levels
- **Multiple runs matter** — GPT-5.1 appeared perfect in 1-run tests but failed 40% on complex merges at 10 runs
- **Gemini models fail compaction** (0-10% keyword preservation) despite strong fast-apply performance
- **Mistral Small dominates compaction** — best compression ratio (0.166) at fastest speed (3.1s)

### Running the Benchmark

```bash
# Full run (1520 calls, ~1h45min with 6 threads)
python3 benchmark.py --runs 10 --save

# Quick validation (1 run, ~5min)
python3 benchmark.py --runs 1

# Resume after crash
python3 benchmark.py --runs 10 --save --resume

# Single scenario
python3 benchmark.py --scenario small-single --runs 1

# Fast-apply only / compaction only
python3 benchmark.py --fast-apply-only --save
python3 benchmark.py --compaction-only --save

# Clean checkpoint and start fresh
python3 benchmark.py --clean
```

Requires `FLOW_API_KEY` in environment. Results saved to `BENCHMARK.md`. Checkpoints survive crashes — resume with `--resume`.

### Changing the Merge Model

Set the `FAST_APPLY_MODEL` environment variable:

```bash
export FAST_APPLY_MODEL=gpt-4.1  # second-best in benchmarks
```

Or use the default (`anthropic.claude-4-5-haiku`) — benchmarked as the most reliable.

## How the Merge Model Works

The plugin sends a structured prompt to the merge model:

```
System: You are a code merge specialist. Replace each "// ... existing code ..."
marker with the corresponding section from the original file. Return ONLY the
complete merged file.

User:
<original>
{full original file}
</original>

<edit>
{snippet with lazy markers}
</edit>

Instructions: {what was changed}
```

The merge task is simple enough that a small, fast model (Haiku 4.5) handles it with 100% reliability — no need for expensive frontier models.

## License

MIT
