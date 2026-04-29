# codesubflags
Programming Plugin with Subflags for ComSSA ATR (CTF).

Uses [Piston](https://github.com/engineer-man/piston) for sandboxing and execution

## Usage
1. Clone this repo into your CTFd `plugins/` directory.
2. Mount `challenge_files/` as a writable volume on the CTFd container so admin
   uploads/edits persist outside the read-only repo bind. Add to the `ctfd`
   service in `docker-compose.yml`:

   ```yaml
   volumes:
     - ./CTFd/plugins/codesubflags/challenge_files:/opt/CTFd/CTFd/plugins/codesubflags/challenge_files
   ```
3. Install [Piston](https://github.com/engineer-man/piston).
4. Start container with `docker compose up -d api`
5. Restart your CTFd instance to load the plugin, e.g. `docker compose down` && `docker compose up -d`
6. Attach to your ctfd network such as with `docker network connect ctfd_atr2025_default piston_api`
7. Check it's accessible such as with `docker exec -it ctfd_atr2025-nginx-1 curl http://piston_api:2000/api/v2/runtimes`
8. Sign in to CTFd as admin and visit **Plugins > Code Runner** to install
   the language runtimes you want challenges to use (Python 3.10, Java 15.0.2, etc.). The
   piston CLI still works as a fallback if you'd rather install runtimes
   from the host.

You can change the `RUNNER_URL` environment variable to point to a different
piston instance; `RUNTIMES_URL` and `PACKAGES_URL` are derived from it
automatically and can also be overridden individually.

## Code Runner settings page

Lives at `/admin/codesubflags/settings` (registered automatically under the
admin **Plugins** dropdown via `config.json`). Lists every installed piston
runtime alongside an Uninstall button, plus every available-but-not-installed
package with an Install button. Installs can take 30-90 seconds for some
runtimes; the page shows a status banner while a job is in flight and refreshes
both tables once piston returns.

## Admin configuration

When creating/editing a codesubflag challenge:

- **Languages** - one row per language the participant can run their
  submission against. Each row has its own template (`run_file`) and optional
  `data_file`, both relative to the plugin's `challenge_files/` directory. The
  language/version dropdown is populated from runtimes piston currently
  reports as installed; missing runtimes can be added via Plugins > Code
  Runner.
- **Max runtime (ms)** - per-submission runtime cap passed to Piston.
- **Run history size** - server-side retention of each user's Run
  submissions:
  - `-1` disabled (no server logging; browser localStorage draft only)
  - `0` unlimited (server still caps at 500 rows per user per challenge)
  - `N` keep only the most recent N runs per user per challenge

  Defaults to 10. Each stored row keeps the submitted code, stdout/stderr, and
  the language/version it was executed against.

## Participant UX

The challenge view renders a CodeMirror editor (dracula theme, 4-space
indentation). Behaviour:

- A language dropdown appears above the editor whenever the challenge has more
  than one language configured. Switching languages swaps the CodeMirror mode
  and loads the new language's template (or your previous draft for that
  language, if any).
- Drafts are autosaved per language under separate `localStorage` keys so
  switching back and forth never loses unsaved code.
- **Reset** restores the editor to the active language's original template.
- **Restore** (visible when `history_size != -1` and there is at least one
  stored run) reloads the code from a prior Run submission and switches the
  language dropdown to match the attempt.
