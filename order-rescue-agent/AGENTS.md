# Order Rescue Agent subproject

- Keep all case data synthetic. Do not add carrier APIs, real buyer messaging, dispatch, address changes, refunds, or returns.
- Treat any future file under the repository's `sources/` directory as read-only synced project material.
- Keep the root React Observatory intact; the Python agent is a separate subproject.
- Keep the BI workbook fallback status explicit until the versioned workbook is provided.
- Deterministic policy checks remain the authority for recommendations; never let mock reasoning override them.
