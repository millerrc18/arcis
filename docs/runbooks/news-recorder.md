# News Recorder Runbook (S01)

Operator guide for the forward news recorder. The recorder polls Alpaca's
news API every 15 minutes and stores articles append-only under a data root
outside the repo.

## Install

```bash
uv sync
```

Requires Python 3.12. This installs runtime and dev dependencies from
`uv.lock`.

## Configure

1. Copy and edit the config (all fields required, no defaults):

   ```bash
   # config/recorder.yaml is committed; edit data_root for your machine.
   ```

2. Set secrets from the environment (never in the file):

   ```bash
   export ALPACA_API_KEY="..."
   export ALPACA_API_SECRET="..."
   ```

3. `data_root` must be outside the repo checkout and outside cloud-sync
   folders (Dropbox, Google Drive, OneDrive, iCloud Drive). The process
   refuses to start otherwise (I-7).

4. If you are behind a TLS-intercepting proxy, point at its CA bundle:

   ```bash
   export ARCIS_CA_BUNDLE=/path/to/ca-bundle.crt
   ```

5. Build today's universe snapshot:

   ```bash
   uv run arcis-recorder universe
   # -> <data_root>/universe/2026-10-02.csv (503 symbols)
   ```

## Cron

```cron
# Daily universe snapshot, before the first poll of the day.
5 0 * * * cd /path/to/arcis && uv run arcis-recorder universe >> /var/log/arcis/universe.log 2>&1
# Poll every 15 minutes.
*/15 * * * * cd /path/to/arcis && uv run arcis-recorder poll >> /var/log/arcis/poll.log 2>&1
```

`poll` prints a JSON summary to stdout on success. On failure it prints
`error: ...` to stderr and exits non-zero, leaving the previous
`heartbeat.json` untouched.

## Data layout

```
<data_root>/
  universe/2026-10-02.csv          # dated, immutable universe snapshot
  articles/AAPL/2026-10-02.jsonl   # raw article JSON, one per line
  articles/AAPL/2026-10-02.jsonl.manifest.json
  index/AAPL.jsonl                 # article_id -> version_hash
  heartbeat.json                   # last successful poll
  recorder.lock                    # OS-exclusive poll lock (held during polls)
```

## Daily operations

- Check `arcis-recorder gaps` for coverage. Exit code is 1 when days are
  missing or no poll has succeeded.
- Check `heartbeat.json` `last_poll_at`; alert if older than 30 minutes.
- Poll logs: each run logs one JSON line with `articles_fetched` and
  `pairs_stored`.

## Failure modes and recovery

| Symptom | Cause | Recovery |
|---|---|---|
| `error: ... universe/....csv is missing` | Daily `universe` cron didn't run | Run `arcis-recorder universe`, then `poll` |
| `error: another poll holds .../recorder.lock` | Previous poll still running (>15 min) or crashed holding the lock | Investigate the stuck poll; the lock releases when it exits |
| `error: clock skew ... exceeds 300s` | Local clock or Alpaca clock drift | Fix NTP; polls resume automatically |
| `error: alpaca rejected the credentials` | Bad/rotated keys | Set correct `ALPACA_API_KEY`/`ALPACA_API_SECRET` |
| `error: rate limited after ... attempts` | Budget exceeded | Wait; lower poll frequency if recurrent |
| `gaps` shows missing days | Poller was down | `arcis-recorder sweep --start YYYY-MM-DD --end YYYY-MM-DD` to backfill |

## Verification

```bash
# Verify every JSONL against its manifest:
uv run arcis-recorder verify

# Rebuild every version index from scratch (tamper-evident):
uv run arcis-recorder rebuild
```

Both exit non-zero with a report on stderr when they find a problem.

## Notes

- Article `content` may be null and may contain HTML; it is stored as-is.
- The recorder is capture-only: no tags, no features, no decisions.
- Never commit `data_root` contents, `config/recorder.yaml` secrets (there
  are none — secrets are env-only), or API keys.

## Rights reversal (D-018)

The recorder stores full article text by the operator's decision (2026-09-23).
If Alpaca issues a written refusal to retain text, revert to fingerprint mode:

1. Stop the poll cron.
2. Delete all `articles/` JSONL and manifests under the data root (text must
   not remain).
3. Keep `index/` — version hashes were computed on the complete article before
   any text handling and remain valid tamper evidence.
4. The fingerprint-mode writer (per-field hashes, no text) is built at that
   time, not speculatively.

Do not build the fingerprint writer until the refusal arrives.
