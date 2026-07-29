# Wealthfolio Tools

Curated catalogue of the Wealthfolio MCP tools exposed to this skill. Use it as a quick-reference when matching user intent to a tool call.

## Read-only tools

| Tool | When to use | Required args | Useful optional args | Common follow-ups |
|---|---|---|---|---|
| `get_accounts` | Resolve account IDs, list accounts, scope to portfolio scope. | — | `displayMode="compact"` (when feeding another tool) or `"full"` (for direct display) | `get_holdings`, `get_cash_balances`, `search_activities`, `get_performance` |
| `get_holdings` | Show positions and weights; "how is my portfolio today?". | — | `accountId`, `viewMode="table"|"treemap"|"both"` (default `treemap`) | `get_asset_allocation`, `get_asset_taxonomy_assignments` |
| `get_cash_balances` | Show uninvested cash per account and totals. | — | `accountId` | `get_accounts`, `get_holdings` |
| `get_net_worth` | Total assets vs liabilities plus history. | — | `date` (defaults today), `startDate` (to include history series) | `get_holdings`, `get_cash_balances` |
| `get_performance` | TWR, IRR, value return, attribution, drawdown. | — | `accountId`, `period="1M|3M|6M|YTD|1Y|ALL"` (default `YTD`) | `get_valuation_history` |
| `get_valuation_history` | Daily valuations for growth vs contributions chart. | `startDate`, `endDate` | `accountId` | `get_performance` |
| `get_income` | Dividends, interest, other income summary. | — | `period="YTD|LAST_YEAR|ALL"` (default `YTD`) | `search_activities` filtered to `DIVIDEND|INTEREST` |
| `get_goals` | Goal progress with deadline and current amount. | — | — | `get_net_worth`, `get_holdings` |
| `get_contribution_limits` | RRSP / TFSA / 401k-style limits with used vs remaining room. | — | — | `get_accounts` |
| `get_health_status` | Cached health check (severity, categories, staleness). | — | — | `list_asset_taxonomies` (for classification fixes), targeted re-fetch in app |
| `get_asset_allocation` | Composition by class / sector / region / risk / security type. | `taxonomyId` after `list_asset_taxonomies` | `groupBy="class|sector|region|risk|security_type"` (default `class`), `accountId`, `categoryId` (for drill-down) | `get_holdings`, `list_asset_taxonomies` |
| `list_asset_taxonomies` | Discover taxonomies and category IDs. | — | `taxonomyId` or `taxonomyName`, `includeCategories=true|false`, `categoryDepth="root|all"` | `get_asset_allocation`, `prepare_asset_classification` |
| `get_asset_taxonomy_assignments` | Read current asset-scoped classifications. | `assetQuery` (id / ticker / display code / name) | `taxonomyId` filter | `prepare_asset_classification` (only when changing) |
| `search_activities` | Filter transactions. | — | `accountId`, `activityType`, `dateFrom`, `dateTo`, `symbol`, `page`, `pageSize` (max 200) | `get_accounts`, `get_income` |
| `get_portfolios` | List saved reporting scopes (groups of accounts). | — | — | `get_holdings(accountId=...)`, `get_performance(accountId=...)` |
| `list_categorization_context` | Prerequisite for `propose_transaction_categories`. | status filter | `accountIds` (omit unless user named a specific account), `activityIds`, `startDate`, `endDate`, `limit` (default 100, max 100) | `propose_transaction_categories`, `create_categorization_rule` |
| `get_import_mapping` | Inspect a saved CSV import mapping for an account. | `accountId` | `contextKind` (defaults `CSV_ACTIVITY`) | `prepare_activity_import` |

## Mutating tools (always preview → confirm → commit)

| Tool | Role | Required contract |
|---|---|---|
| `record_activity` | Draft one activity from natural language. | Show preview; wait for explicit user approval before `commit_activity_draft`. |
| `record_activities` | Draft a batch from natural language. | Show preview; wait for explicit user approval before `commit_activity_drafts`. |
| `prepare_activity_import` | Validate mapped CSV rows + detect duplicates. Read-only draft. | Discuss duplicates with the user; only after explicit approval call `commit_activity_import` (set `forceImport=true` only on approved rows). |
| `get_import_mapping` (read-only helper) | Inspect a saved CSV mapping. | Use before `prepare_activity_import` when reusing a prior template. |
| `prepare_asset_classification` | Build a non-mutating classification draft for an asset. | Use category IDs from `list_asset_taxonomies`; pass `sourceLabel` exactly as supplied; empty `assignments` only when the user confirmed clearing the taxonomy. After approval → `commit_asset_classification_draft`. |
| `propose_transaction_categories` | Render the categorization review widget. | Run `list_categorization_context` first; pass `aiProposals` for rows not covered by rules / same-payee history; never claim categories were applied from the context call alone. |
| `create_categorization_rule` | Draft a persistent categorization rule. | Call when the user gives a generalizable hint; render confirmation widget and stop. |

## When to call `commit_*`

Never autonomously. Only call after:

1. The corresponding `prepare_*` / `record_*` preview has been surfaced to the user in the current turn.
2. The user has explicitly approved that exact preview (or, for batch imports, each row that should be force-imported).
3. The user has not rescinded approval.

If any of those conditions is unclear, re-summarise the preview and wait.

## When NOT to call a tool

- Don't call `get_holdings` / `get_cash_balances` / `search_activities` with a fabricated account ID. Resolve via `get_accounts` first or ask the user.
- Don't call `get_asset_allocation` before `list_asset_taxonomies` has returned a `taxonomyId`.
- Don't call `propose_transaction_categories` before `list_categorization_context` in the same filters.
- Don't call `prepare_activity_import` until you have a concrete CSV / mapped rows ready and the target account is resolved.
- Don't call `list_asset_taxonomies(categoryDepth="all")` for top-level screenshots; use `categoryDepth="root"`.
