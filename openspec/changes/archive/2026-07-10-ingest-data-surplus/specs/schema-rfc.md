# Schema RFC — version `extra_payload` extensions

Serial gate for provider promotion lanes. Fields on `JobRecord` that are not `JobVersionRow` columns flow into `job_versions.extra_payload` via `storage._job_version_row_data`.

## New `JobRecord` fields

| Field | Type | Storage |
| ----- | ---- | ------- |
| `posting_kind` | `standard \| prospect \| unlisted` | `extra_payload.posting_kind` |
| `seniority` | string (deterministic) | `extra_payload.seniority` |
| `provider_extras` | object | `extra_payload.provider_extras` |

## Illustrative `version.extra_payload` shape

```json
{
  "provider_extras": {
    "greenhouse": {
      "requisitionId": "50",
      "language": "en",
      "metadata": [{"name": "level", "value": "staff"}],
      "departments": [{"id": 1, "name": "Engineering", "parentId": null}],
      "offices": [{"id": 2, "name": "New York", "location": "..."}]
    }
  },
  "posting_kind": "standard",
  "seniority": "Senior"
}
```

## `posting_kind` policy

| Value | When |
| ----- | ---- |
| `standard` | Default public posting |
| `prospect` | Greenhouse list item with `internal_job_id` null |
| `unlisted` | Reserved for direct-link / non-listed surfaces (Ashby policy TBD) |

## `seniority` derivation

`derive_seniority(record)` inspects `title` and `experience` with the same alias catalog used for skill levels: Executive, Principal, Senior, Manager, Junior.

## Index manifest extensions

- `JOB_COLUMNS`: `seniority`, `daysOpen` (derived from `first_seen_at` vs snapshot time).
- `facets.seniorities`: from job rows when `seniority` present.
- `detailShards.tierCounts`: `{ "T1": n, "T2": m }`.
- Detail shard `detailTier`: `T1` metadata-only, `T2` full body for indexable jobs.
- `dashboard.sync`: optional when `job_sync_runs` table exists.

## Forbidden in public index

- `payloadSnapshots` on committed detail shards (remain DB/Kaggle only).
- Application-form schemas (`questions`, demographics).
