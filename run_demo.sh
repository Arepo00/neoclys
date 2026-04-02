#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${1:-neocly_os.db}"
SEED="${2:-19}"
VERIFY_DB="${DB_PATH%.db}_verify.db"

rm -f "$DB_PATH" "$VERIFY_DB"

python neocly_os.py --db "$DB_PATH" --seed "$SEED" init
python neocly_os.py --db "$DB_PATH" --seed "$SEED" seed-leads 3000
python neocly_os.py --db "$DB_PATH" --seed "$SEED" run 60 > /tmp/neocly_run_output.json
python neocly_os.py --db "$DB_PATH" --seed "$SEED" report
python neocly_os.py --db "$VERIFY_DB" --seed "$SEED" verify

echo "Demo complete. Main DB: $DB_PATH | Verify DB: $VERIFY_DB"
