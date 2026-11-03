# Contract capture storage repair

Production record call13:35:12 Eastern failed with contract_storage_budget_reached.
The separate contract_selection_evidence.sqlite3 had16129 pages of4096 bytes,
no free pages,98 selections and67338 quote samples, newest session September29.
The64MiB cap minus1MiB reserve prevented every connection, including capture.

Raise the bounded limit to512MiB, leaving the1MiB reserve and per-snapshot/chain/
watch bounds unchanged. Existing volume has11GiB free; no infrastructure purchase.
Count used pages excluding reusable free pages and warn at80percent before the
hard stop. Preserve all existing evidence, do not backfill absent past quotes.
Tests cover restoration after an exhausted budget and unchanged earlier rows.

Deploy after contract-evidence, capture and risk regression. Verify actual new
worker selections and quotes, not a manual enrollment. Rollback by reverting
this commit; a return to the64MiB cap can intentionally block new capture again.
Never truncate the database to make a rollback pass. Trading rules unchanged.
