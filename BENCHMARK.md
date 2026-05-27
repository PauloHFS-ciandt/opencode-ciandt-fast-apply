# OpenCode Benchmark Results

> Generated: 2026-05-27 19:38 UTC
> Proxy: `https://flow.ciandt.com/flow-llm-proxy`
> Models tested: 19
> Concurrency: 6 threads, 2 retries, circuit breaker at 3 failures

## Fast Apply — Small (30 lines, 1 edit)

| Model | Time | Tokens In | Tokens Out | Tok/s | Quality |
|---|---:|---:|---:|---:|---|
| gpt-5.1 | 2.2s | 258 | 148 | 67.3 | PERFECT |
| mistral-small-2503 | 2.2s | 256 | 138 | 62.7 | PERFECT |
| gpt-4.1 | 2.6s | 259 | 139 | 53.5 | PERFECT |
| anthropic.claude-4-5-haiku | 2.8s | 301 | 168 | 60.0 | PERFECT |
| anthropic.claude-4-5-sonnet | 3.5s | 301 | 168 | 48.0 | PERFECT |
| gpt5.5 | 3.6s | 258 | 181 | 50.3 | PERFECT |
| gpt5.2 | 3.7s | 258 | 142 | 38.4 | PERFECT |
| anthropic.claude-4-6-sonnet | 3.9s | 302 | 168 | 43.1 | PERFECT |
| anthropic.claude-4-6-opus | 4.1s | 302 | 168 | 41.0 | PERFECT |
| gpt-5-nano | 5.1s | 258 | 596 | 116.9 | PERFECT |
| DeepSeek-V4-Pro | 5.1s | 257 | 139 | 27.3 | PERFECT |
| gemini-2.5-pro | 5.7s | 288 | 811 | 142.3 | PERFECT |
| gpt-5-mini | 6.3s | 258 | 404 | 64.1 | PERFECT |
| gpt-5 | 6.5s | 258 | 596 | 91.7 | PERFECT |
| gemini-2.0-flash | 8.8s | 288 | 922 | 104.8 | PERFECT |
| gemini-2.5-flash | 9.1s | 288 | 916 | 100.7 | PERFECT |
| DeepSeek-R1 | 9.2s | 258 | 626 | 68.0 | PERFECT |
| o3-mini | 10.3s | 258 | 853 | 82.8 | PERFECT |
| gpt-4o-mini | 11.2s | 259 | 139 | 12.4 | PERFECT |

## Fast Apply — Medium (80 lines, 3 edits)

| Model | Time | Tokens In | Tokens Out | Tok/s | Quality |
|---|---:|---:|---:|---:|---|
| gpt5.2 | 4.6s | 1,051 | 756 | 164.3 | PERFECT |
| gpt-5.1 | 4.7s | 1,051 | 766 | 163.0 | PERFECT |
| anthropic.claude-4-5-haiku | 5.2s | 1,247 | 903 | 173.7 | PERFECT |
| mistral-small-2503 | 5.9s | 1,062 | 763 | 129.3 | PERFECT |
| gemini-2.5-pro | 6.5s | 1,204 | 1,065 | 163.8 | PERFECT |
| gpt5.5 | 7.6s | 1,051 | 786 | 103.4 | PERFECT |
| o3-mini | 8.1s | 1,051 | 1,403 | 173.2 | PERFECT |
| anthropic.claude-4-5-sonnet | 8.8s | 1,247 | 898 | 102.0 | PERFECT |
| anthropic.claude-4-6-sonnet | 9.4s | 1,248 | 898 | 95.5 | PERFECT |
| anthropic.claude-4-6-opus | 9.8s | 1,248 | 898 | 91.6 | PERFECT |
| gpt-4.1 | 11.3s | 1,052 | 753 | 66.6 | PERFECT |
| DeepSeek-V4-Pro | 14.6s | 1,032 | 743 | 50.9 | PERFECT |
| DeepSeek-R1 | 16.1s | 1,033 | 1,151 | 71.5 | PERFECT |
| gemini-2.5-flash | 16.3s | 1,204 | 2,175 | 133.4 | PERFECT |
| gemini-2.0-flash | 16.5s | 1,204 | 2,175 | 131.8 | PERFECT |
| gpt-5-mini | 19.9s | 1,051 | 1,530 | 76.9 | PERFECT |
| gpt-5 | 28.8s | 1,051 | 1,914 | 66.5 | PERFECT |
| gpt-5-nano | 29.5s | 1,051 | 4,096 | 138.8 | TRUNCATED |
| gpt-4o-mini | 60.2s | — | — | — | FAIL (The read operation timed out) |

## Fast Apply — Large (200+ lines, 5 edits)

| Model | Time | Tokens In | Tokens Out | Tok/s | Quality |
|---|---:|---:|---:|---:|---|
| gpt-5.1 | 8.6s | 2,236 | 1,850 | 215.1 | PERFECT |
| anthropic.claude-4-5-haiku | 11.3s | 2,793 | 2,307 | 204.2 | PERFECT |
| gpt5.2 | 13.2s | 2,236 | 1,875 | 142.0 | PERFECT |
| mistral-small-2503 | 14.8s | 2,281 | 1,880 | 127.0 | PERFECT |
| gpt5.5 | 17.7s | 2,236 | 1,938 | 109.5 | PERFECT |
| anthropic.claude-4-6-opus | 19.6s | 2,794 | 2,308 | 117.8 | PERFECT |
| anthropic.claude-4-5-sonnet | 20.0s | 2,793 | 2,312 | 115.6 | PERFECT |
| o3-mini | 21.0s | 2,236 | 3,067 | 146.0 | PERFECT |
| anthropic.claude-4-6-sonnet | 21.6s | 2,794 | 2,307 | 106.8 | PERFECT |
| gpt-4.1 | 25.0s | 2,237 | 1,841 | 73.6 | PERFECT |
| gpt-5-nano | 26.0s | 2,236 | 3,615 | 139.0 | PERFECT |
| gemini-2.5-flash | 26.6s | 2,676 | 5,540 | 208.3 | PERFECT |
| gemini-2.5-pro | 26.7s | 2,676 | 5,540 | 207.5 | PERFECT |
| DeepSeek-V4-Pro | 27.6s | 2,332 | 1,919 | 69.5 | PERFECT |
| gpt-5-mini | 30.5s | 2,236 | 2,426 | 79.5 | PERFECT |
| gemini-2.0-flash | 33.6s | 2,676 | 3,996 | 118.9 | PERFECT |
| DeepSeek-R1 | 33.9s | 2,333 | 2,674 | 78.9 | PERFECT |
| gpt-5 | 50.3s | 2,236 | 3,834 | 76.2 | PERFECT |
| gpt-4o-mini | 60.2s | — | — | — | FAIL (The read operation timed out) |

## Compaction

| Model | Time | Tokens In | Tokens Out | Tok/s | Ratio | Quality |
|---|---:|---:|---:|---:|---:|---|
| mistral-small-2503 | 3.8s | 1,040 | 271 | 71.3 | 0.26 | PERFECT |
| gpt-4o-mini | 18.9s | 981 | 262 | 13.9 | 0.27 | PERFECT |
| anthropic.claude-4-6-sonnet | 7.0s | 1,169 | 327 | 46.7 | 0.28 | PERFECT |
| anthropic.claude-4-6-opus | 8.3s | 1,169 | 364 | 43.9 | 0.31 | PERFECT |
| gpt-4.1 | 5.9s | 981 | 322 | 54.6 | 0.33 | PERFECT |
| anthropic.claude-4-5-sonnet | 9.6s | 1,168 | 402 | 41.9 | 0.34 | PERFECT |
| anthropic.claude-4-5-haiku | 5.0s | 1,168 | 421 | 84.2 | 0.36 | PERFECT |
| DeepSeek-V4-Pro | 5.4s | 1,023 | 381 | 70.6 | 0.37 | PERFECT |
| gpt5.2 | 7.3s | 980 | 497 | 68.1 | 0.51 | PERFECT |
| gpt5.5 | 8.0s | 980 | 553 | 69.1 | 0.56 | PERFECT |
| DeepSeek-R1 | 9.5s | 1,024 | 774 | 81.5 | 0.76 | PERFECT |
| o3-mini | 7.4s | 980 | 773 | 104.5 | 0.79 | PERFECT |
| gemini-2.5-pro | 6.7s | 1,113 | 1,020 | 152.2 | 0.92 | PARTIAL(7/9) |
| gemini-2.0-flash | 7.6s | 1,113 | 1,020 | 134.2 | 0.92 | PARTIAL(7/9) |
| gemini-2.5-flash | 11.9s | 1,113 | 1,020 | 85.7 | 0.92 | PARTIAL(8/9) |
| gpt-5-nano | 7.4s | 980 | 1,024 | 138.4 | 1.04 | EMPTY |
| gpt-5.1 | 8.2s | 980 | 1,024 | 124.9 | 1.04 | PARTIAL(7/9) |
| gpt-5-mini | 11.4s | 980 | 1,024 | 89.8 | 1.04 | EMPTY |
| gpt-5 | 14.6s | 980 | 1,024 | 70.1 | 1.04 | EMPTY |
