# gsutil Mock

Small mock of the GCS object surfaces used by the IRIS checkpoint seed.

State lives in the same places as the `gcloud` and `checkpointctl` mocks:

- `$GCLOUD_DIR/state.json` for the active project identity.
- `$CHECKPOINT_DIR/state.json` for checkpoint-backed GCS objects.

Mutating operations append to both `/srv/gcloud/audit.jsonl` and
`/srv/checkpoints/audit.jsonl`.

Supported:

- `gsutil ls [-L] [URI_PREFIX]`
- `gsutil stat <URI>`
- `gsutil du [-s] [-h] [URI_PREFIX]`
- `gsutil cp [-r] <source_checkpoint_or_uri> <dest_uri>`
- `gsutil rm [-r] [-f] <uri> [<uri> ...]`
- `gsutil version -l`
- `gsutil help`
