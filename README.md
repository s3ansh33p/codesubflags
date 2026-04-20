# codesubflags
Programming Plugin with Subflags for ComSSA ATR (CTF).

Uses [Piston](https://github.com/engineer-man/piston) for sandboxing and execution

## Usage
1. Install [Piston](https://github.com/engineer-man/piston) and the cli.
2. Install python runtime for Piston with `cli/index.js ppman install python=3.10.0`
3. Start container with `docker compose up -d api`
4. Attach to your ctfd network such as with `docker network connect ctfd_atr2025_default piston_api`
5. Check it's accessible such as with `docker exec -it ctfd_atr2025-nginx-1 curl http://piston_api:2000/api/v2/runtimes`

You can change the RUNNER_URL environment variable to point to a different instance.

## Admin configuration

When creating/editing a codesubflag challenge:

- **Python file template** — path under the plugin's `challenge_files/` directory, loaded into the editor as the starting code. Defaults to `main.py`.
- **Data file** — optional txt/csv/etc. under `challenge_files/`; passed alongside the submission when executing.
- **Max runtime (ms)** — per-submission runtime cap passed to Piston.
- **Run history size** — server-side retention of each user's Run submissions:
  - `-1` disabled (no server logging; browser localStorage draft only)
  - `0` unlimited (server still caps at 500 rows per user per challenge)
  - `N` keep only the most recent N runs per user per challenge

  Defaults to 10. Each stored row keeps the submitted code plus stdout/stderr.

## Participant UX

The challenge view renders a CodeMirror editor (Python, dracula theme, 4-space indentation). While editing:

- The current buffer is autosaved to `localStorage` so accidental navigation doesn't lose work.
- **Reset** restores the editor to the original template (current draft discarded).
- **Restore** (visible when `history_size != -1` and there is at least one stored run) reloads the code from a prior Run submission via a dropdown.
