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

Tested all 19 models on the CI&T proxy across 3 scenarios (small/medium/large files). Full results in [BENCHMARK.md](./BENCHMARK.md).

### Fast Apply — Top 5 (by average time, all PERFECT quality)

| Model | Small | Medium | Large | Avg |
|---|---:|---:|---:|---:|
| **gpt-5.1** | 2.2s | 4.7s | 8.6s | **5.2s** |
| anthropic.claude-4-5-haiku | 2.8s | 5.2s | 11.3s | 6.4s |
| gpt5.2 | 3.7s | 4.6s | 13.2s | 7.2s |
| mistral-small-2503 | 2.2s | 5.9s | 14.8s | 7.6s |
| gpt5.5 | 3.6s | 7.6s | 17.7s | 9.6s |

### Key Findings

- **13/19 models** achieve PERFECT merge quality (vs 0/19 on full rewrite)
- **GPT-5.1** is the fastest with PERFECT quality across all 3 scenarios
- Merge format produces **more accurate** results than asking models to rewrite entire files
- Token savings scale with file size (minimal on 30-line files, significant on 200+ lines)

### Running the Benchmark

```bash
# Full benchmark (fast-apply + compaction)
python3 benchmark.py --save

# Fast-apply only
python3 benchmark.py --fast-apply-only --save

# Compaction only
python3 benchmark.py --compaction-only --save
```

Requires `FLOW_API_KEY` in environment. Results saved to `BENCHMARK.md`.

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

The merge task is simple enough that fast/cheap models (GPT-5.1, Haiku 4.5) handle it perfectly — no need for expensive frontier models.

## License

MIT
