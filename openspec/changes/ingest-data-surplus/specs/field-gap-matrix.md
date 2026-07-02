# Field gap matrix (empirical summary)

Comparison of provider list-endpoint surplus vs first-class `JobRecord` / `JobVersionRow` columns.

| Provider | Volume weight | List richness | Gap class | Examples buried in raw |
| -------- | ------------- | ------------- | --------- | ---------------------- |
| greenhouse | ~45k | Medium | S1 | `metadata`, `requisition_id`, `language`, dept/office trees |
| ashbyhq | ~21k | High | S1 | `isListed`, compensation blocks, `workplaceType` |
| lever | ~9.5k | High | S1 | category extras, epoch dates, list sections |
| workable | — | High | S1 + bug | industry/benefits; merged `raw_listing`/`raw_detail` |
| bamboohr | — | Medium-high | S1 | `jobOpening` fields, requisition IDs |
| workday | — | Medium-high | S1 | `postedOn` relative dates, `jobDescription` mapping |
| rippling | — | Medium-high | S1 | `payRangeDetails[]`, per-location `workplaceType` |
| teamtailor | — | Low | S1 | RSS subset only |
| wpjobmanager | — | Low | S1 | meta key expansion |

## Surplus classes

| Class | Location today | Action |
| ----- | -------------- | ------ |
| **S1 Raw-buried** | `raw_listing`, `raw_detail`, `job_payload_snapshots` | Promote to typed fields / `provider_extras`; keep full raw in DB |
| **S2 Fetchable-not-called** | Board detail APIs | Bounded optional fetches (e.g. GH pay transparency) |
| **S3 Derivable** | Title/description text | `seniority`, geo parse, skill catalog |
| **S4 Sync-evidence** | `job_sync_*` tables | Manifest `dashboard.sync` aggregates |

## Index projection gaps (pre-tiering)

| Field | DB | List chunk | Detail shard (old) |
| ----- | -- | ---------- | ------------------ |
| description | full | 200-char snippet | full for all open jobs |
| skills | child tables | 96-char tokens | JSON |
| closed jobs | yes | chunks | excluded |
| payloadSnapshots | yes | — | incorrectly eligible |
