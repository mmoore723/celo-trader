# Celo Trader Research Workspace

This folder is the local workspace for strategy research and tuning. It is
deliberately excluded from production deployment staging. The reusable
`engine/`, `jobs/`, and documentation may be versioned; raw data and generated
study artifacts are local-only.

## Layout

- `archives/` — raw paid-vendor downloads, including Databento archives.
- `data/` — normalized underlying and option datasets used by a study.
- `reports/` — generated study outputs, holdouts, and comparison results.
- `logs/` — long-running research worker output.
- `work/` — temporary extracted files and intermediate calculations.

The reusable research engine lives in `engine/` and the command-line studies
live in `jobs/`. Production code must import neither the engine nor the jobs.

## Rules

1. Never put a broker secret, account file, or customer data here.
2. Keep raw paid vendor data inside `archives/` or `data/`; do not add it to
   Git.
3. Every report should name the source data and configuration used to produce
   it.
4. A result does not alter bot settings automatically.  A reviewed strategy
   must be wired to production code separately and validated in paper trading.
