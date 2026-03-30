# Claude Code — Explain Current Template Management Setup

I need you to investigate how DemoForge manages templates today and produce a detailed technical summary. This summary will be shared with another AI assistant to design new features, so be precise and include actual code — not descriptions.

## What to investigate

### 1. Template files on disk
- Run: `find . -name "*.yaml" -path "*/template*" | head -40`
- Run: `find . -name "*.yaml" -path "*/demo*" | head -40`
- Run: `find . -name "*.yml" -path "*/template*" | head -40`
- Run: `ls -la backend/app/demo_templates/ 2>/dev/null || echo "not found"`
- Run: `ls -la demo-templates/ 2>/dev/null || echo "not found"`
- Run: `ls -la templates/ 2>/dev/null || echo "not found"`
- Show the exact directory where template YAML files live.
- Count how many template files exist.

### 2. How templates are loaded
- Find the Python code that reads/parses template YAML files. Show the full function(s).
- Is it a one-time load on startup, or read on every request?
- Is there a registry, cache, or in-memory dict?
- Show the relevant imports and class/function signatures.

### 3. Template data model
- Find the Pydantic model(s) for templates (likely in models.py or schemas.py). Show the FULL class definition(s) — every field, every nested model.
- Show the TypeScript type(s) on the frontend side too.

### 4. Show one complete template YAML
- Pick the smallest/simplest template file and `cat` it in full.
- Then pick one medium-complexity template and `cat` it too.

### 5. Runtime state — what happens after a user modifies the diagram?
- Find the Zustand store(s) that hold diagram state (nodes, edges, selections, demo config). Show the full store definition.
- When a user drags a node, changes a setting, or adds/removes a component — trace where that state lives. Is it purely in-browser memory? Written to localStorage? Sent to the backend?
- Find any API endpoints that accept modified demo state (PUT/POST/PATCH on demos or templates). Show them.
- What happens to modifications on browser refresh? On demo stop? On DemoForge restart?

### 6. Demo lifecycle — deploy flow
- Trace the full deploy flow: user clicks Deploy → what frontend function fires → what API endpoint is called → what backend functions execute → containers start.
- Show each function signature and the key lines (not full implementations, just the flow).

### 7. Template creation/update
- Is there ANY existing code for saving a modified demo back as a template? Search for: `save`, `export`, `publish`, `create_template`, `update_template`, `save_as`.
- Run: `grep -rn "save.*template\|export.*template\|publish.*template\|create.*template\|template.*save\|template.*create\|template.*update\|template.*write" backend/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" | head -30`
- Is there any API endpoint for writing template YAML files?

### 8. Docker packaging
- Show how templates get into the Docker image. Check:
  - `cat Dockerfile` or `cat backend/Dockerfile` — look for COPY commands involving templates
  - `cat docker-compose.yml` or `cat docker-compose.dev.yml` — look for volume mounts involving templates
  - Are templates baked in (COPY) or mounted (volumes)?

### 9. Any existing sync/remote logic
- Search for anything related to remote templates, syncing, S3, GCS, hub, or centralized storage:
- Run: `grep -rn "sync\|remote.*template\|s3.*template\|gcs\|hub.*url\|TEMPLATE_SOURCE\|TEMPLATE_URL" backend/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" --include="*.env*" --include="*.yaml" | head -20`

### 10. Frontend template gallery
- Find the component that displays the template list/gallery. Show its full source.
- How does the frontend fetch available templates? Show the API call.
- Is there any UI for creating or editing templates?

## Output format
Organize by the 10 sections above. For each section:
1. One-paragraph answer summarizing the finding
2. The actual code/output (verbatim, not summarized)
3. Any gotchas or surprises you found

Keep it factual. No recommendations — just describe exactly what exists today.
