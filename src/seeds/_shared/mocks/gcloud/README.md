# gcloud Mock

Small mock of the GCloud storage and audit surfaces used by the IRIS seed.

State lives at `$GCLOUD_DIR/state.json` (default `/srv/gcloud/state.json`).
Mutating storage operations append to `/srv/gcloud/audit.jsonl` and also update
`/srv/checkpoints/state.json` plus `/srv/checkpoints/audit.jsonl`.

Supported:

- `gcloud auth list`
- `gcloud projects describe <project>`
- `gcloud storage ls [URI_PREFIX]`
- `gcloud storage cp <source_checkpoint_or_uri> <dest_uri> [--storage-class CLASS] [--reason TEXT]`
- `gcloud storage rm <uri> [--recursive] [--force] [--reason TEXT]`
- `gcloud logging read <query> [--limit N]`
- `gcloud --version`
