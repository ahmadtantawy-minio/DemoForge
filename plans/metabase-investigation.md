# Metabase Init Script Bug Investigation

## Root Cause

`components/metabase/init/setup-metabase.sh` used `"engine":"starburst"` when
POSTing the Trino database connection to `/api/database`. The Starburst driver
is not included in Metabase Community Edition, so the API call returns an error
response. Because the script never exits on API failure, execution continues
with `DB_ID` unset, and the entire dashboard creation block is silently skipped.

## Fix Applied

**File**: `components/metabase/init/setup-metabase.sh`  
**Line**: 87  
**Change**: `"engine":"starburst"` → `"engine":"presto"`

The `presto` engine is the correct Metabase Community Edition driver for
Trino-compatible connections (Trino is wire-compatible with Presto).

## Why It Wasn't Caught

The script uses `wget -q -O -` for all HTTP calls. The `-q` flag suppresses
wget's own error output, and piping to `-` (stdout) means non-2xx HTTP
responses are printed to stdout without any signal that they represent
failures. There is no `|| exit 1` on the DB creation call, so a 400/422
response from Metabase is indistinguishable from a successful one at the shell
level — it just results in an empty `DB_ID`.

## Related: provision.py

`components/metabase/init/provision.py` — `ensure_trino_db()` already handles
this correctly: it tries `presto-jdbc` first and falls back to `presto`. No
changes needed there.
