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
