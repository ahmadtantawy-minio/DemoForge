# Claude Code — Report Current Scripts, Naming, and Env Patterns

I need a snapshot of the current project structure so another AI assistant can write instructions that match exactly. Focus on scripts, env files, Makefile targets, and how FA identity is currently handled (if at all).

## What to report

### 1. Scripts directory
- Run: `find scripts/ -type f -name "*.sh" | sort`
- Run: `ls -la scripts/hub/ 2>/dev/null || echo "no hub/ subdir"`
- For each .sh file found, show the first 10 lines (shebang + description + key variables).

### 2. Top-level scripts and entry points
- Run: `ls -la *.sh 2>/dev/null`
- Run: `ls -la minio-gcp.sh demoforge.sh 2>/dev/null`
- If `minio-gcp.sh` has been renamed, find it: `grep -rl "minio-demoforge\|DEMOFORGE" *.sh scripts/*.sh 2>/dev/null | head -10`
- Show the first 20 lines of the main GCP management script (whatever it's called now).

### 3. Makefile targets
- Run: `cat Makefile` (full contents)
- Or if no Makefile: `cat demoforge.sh | head -50` to see the task runner

### 4. Env files
- Run: `ls -la .env* 2>/dev/null`
- Run: `cat .env.local.example 2>/dev/null || echo "not found"`
- Run: `cat .env.hub 2>/dev/null | sed 's/=.*/=<REDACTED>/'` (show keys, hide values)
- Run: `grep -rn "DEMOFORGE_" docker-compose*.yml 2>/dev/null | head -20`

### 5. Hub connector
- Run: `find . -path "*/hub-connector*" -o -path "*/connector*" | head -10`
- Run: `find . -name "Caddyfile" | head -5`
- Does the committed connector source exist? Show its directory structure if yes.

### 6. FA identity — current state
- Run: `grep -rn "FA_ID\|fa_id\|FA_EMAIL\|fa_email\|user_email\|identity\|IDENTITY" backend/ frontend/src/ scripts/ docker-compose*.yml .env* 2>/dev/null | head -15`
- Run: `grep -rn "git.*config\|git.*email" scripts/ backend/ 2>/dev/null | head -10`
- Is there any existing concept of "who is this user" in the codebase?

### 7. Template management — current state
- Run: `ls -la user-templates/ synced-templates/ demo-templates/ 2>/dev/null`
- Run: `grep -rn "user.templates\|synced.templates\|SYNC_ENABLED\|save.*template\|save-from-demo" backend/app/api/ 2>/dev/null | head -15`
- Has the multi-source template loader been implemented? Is save-as-template working?

### 8. Docker compose — current env vars
- Run: `cat docker-compose.yml` (or docker-compose.dev.yml) — full file, we need to see all volume mounts and env vars

## Output format
Organize by the 8 sections. For each: actual command output verbatim. No summaries — I need the raw output to match file names and variable names exactly.
