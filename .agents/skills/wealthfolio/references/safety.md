# Mutation Safety

Hard guardrails for any Wealthfolio MCP tool that writes data. The default mode is **read-only**; every mutating flow must follow the prepare → confirm → commit contract.

## Core contract

1. **Prepare only via read-only or draft tools.** `prepare_activity_import`, `prepare_asset_classification`, `record_activity`, `record_activities`, `propose_transaction_categories`, and `create_categorization_rule` are preview / draft tools. Their output is shown to the user; nothing has been written yet.
2. **Confirm explicitly in the current turn.** The user must say "yes", "commit", "import", "save", or otherwise clearly approve the preview shown. Silence, implied consent, or a generic "thanks" does not count.
3. **Commit only via the matching `commit_*` tool.** Pair each draft with its specific commit tool. Never call a commit tool without the matching preview in the same conversation turn.
4. **Re-summarise if anything changes.** If the draft was edited (price, quantity, account, date, category), surface the updated preview and re-confirm before committing.

## Account resolution

- **Single account**: pass the resolved account name or ID directly.
- **Multiple accounts, user named one**: use that account.
- **Multiple accounts, user did not name one**: ask which account before any per-account tool call (`get_holdings`, `get_cash_balances`, `search_activities`, `record_activity`, etc.).
- **Multiple accounts, generic mention ("the credit card")**: do NOT pass `accountIds` filters. The Wealthfolio spending settings already restrict the scope.
- **No accounts at all**: stop and ask the user to set up an account inside Wealthfolio before continuing.

Never pass an empty `account` / `accountId` to a tool that requires it just to see what happens.

## Symbol handling

- Pass the symbol verbatim — ticker, company name, or freeform ("my rental property").
- Do NOT hand-convert names to tickers. The backend resolves names and marks unresolvable symbols as custom assets. Models routinely hallucinate stale tickers (e.g. "Facebook" → META, not FB).
- If the backend reports an unresolvable symbol, surface it in the preview and ask the user to confirm the custom-asset path.

## Date handling

- Resolve relative phrases ("yesterday", "last Friday", "2 days ago") to ISO 8601 locally before calling `record_activity` / `record_activities` / `prepare_activity_import`. Do not pass relative phrases to the tool.
- For `search_activities`, `list_categorization_context`, and `propose_transaction_categories`, resolve any relative bounds the user supplied.

## Taxonomy / classification residuals

- Never map residual buckets (`Other`, `Unknown`, `Unclassified`, `N/A`, residual region/country/sector labels) to a plausible country, region, sector, or industry.
- Never invent category IDs. Only use IDs returned by `list_asset_taxonomies` for the selected taxonomy.
- For sector / top-level region screenshots, use `categoryDepth="root"` so only root categories are returned.
- For detailed industry / subindustry requests, use `categoryDepth="all"` and pick leaf categories; aggregate to root regions only when the user explicitly asks for top-level.
- Pass `sourceLabel` exactly as the user or screenshot supplied. Do not rewrite residual labels into a country or category unless the source label exactly matches an available category.
- When `prepare_asset_classification.assignments` should be empty, only do so after the user has explicitly confirmed clearing the taxonomy.

## Stale-cache and data-quality disclosure

- `get_health_status` returns a cached snapshot. Always read `isStale` and `overallSeverity`.
- When `isStale=true`, tell the user the cache is older than five minutes and recommend refreshing inside Wealthfolio before drawing conclusions.
- Each `category` issue includes a title, message, `affectedCount`, and optional `affectedMvPct`. Quote them faithfully; do not invent counts.
- Do not promote a stale health status to a current one, and do not let any other tool's earlier result override a fresh `get_health_status` call.

## Categorization flow

- Always run `list_categorization_context` first to retrieve `taxonomies`, `examples`, and `unproposed` rows.
- If `summary.total > 0` and `needsAiJudgement > 0`, infer the best `taxonomyId` + `categoryKey` per row from `taxonomies` + `examples` + merchant-name knowledge, then call `propose_transaction_categories` with `aiProposals` filled in.
- If `needsAiJudgement = 0` but `summary.total > 0`, still call `propose_transaction_categories` with `aiProposals: []` so the rule + same-payee-history draft proposals appear in the review widget.
- Never claim categories were applied from the context call alone. The widget is the source of truth; the user confirms there.
- When the user gives a generalizable hint ("T&T is groceries", "treat coffee shops as food"), call `create_categorization_rule` and stop. Use `taxonomyId` + `categoryKey` from the prior `list_categorization_context`. Prefer `matchType="contains"` with a distinctive merchant fragment unless the user asked otherwise.

## Import flow

- When the user reuses a prior CSV template, call `get_import_mapping` first to recover column mappings, symbol mappings, and parse config.
- Map the new CSV, then call `prepare_activity_import` with the resolved `accountId` and the mapped rows. Read the returned validity / errors / duplicates.
- Discuss each duplicate with the user. Only set `forceImport=true` on rows the user has approved.
- Call `commit_activity_import` once, after explicit approval of the prepared batch (and any force-import decisions).

## Failure handling

- **Empty preview result**: state that no draft was produced and ask the user to clarify the request.
- **Validation errors from `prepare_*`**: surface each row's errors; do not commit. Suggest fixing the row or skipping it.
- **Duplicate warnings**: confirm with the user whether to skip, force-import, or correct the row. Never assume.
- **Tool error during commit**: stop. Do not retry silently with assumed data. Ask the user how to proceed.
- **User rescinds approval mid-flow**: drop the draft; do not commit. Offer to start a new draft.

## Prohibitions (restated)

- No trading, no orders, no brokerage connections, no position-sizing or stop-loss instructions.
- No silent writes. No "I'll just go ahead and save that".
- No bypassing the preview widget. No fabricated category IDs or account resolutions.
- No mapping residual labels to real countries / regions / sectors / industries.
- No stale-cache laundering — disclose `isStale` and ask the user to refresh when relevant.
