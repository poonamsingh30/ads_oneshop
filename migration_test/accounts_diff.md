# Steps 4–5 — Old vs New comparison + gap analysis (`accounts`)

> Produced by `compare_accounts.py` against the real MCA `120436857` (35 accounts).
> Old = Content API v2.1 rollup; New = Merchant API v1 flat rows.

## Step 4 — Comparison results

### Topology / coverage — ✅ exact
- old accounts: **35**, new accounts: **35**, in both: **35**, only-in-old: **0**, only-in-new: **0**.
- `list_accounts`/`list_sub_accounts` reproduce the `authinfo`+`list` account set exactly; advanced/child relationship correctly captured (`is_advanced`, `parent_account`).

### MEX-critical fields (the ONLY account fields consumed downstream) — ✅ 0 mismatches / 35
| Field (new) | mismatches |
|---|---|
| `automatic_improvements.image_improvements.effective_allow_automatic_image_improvements` | 0/35 |
| `automatic_improvements.item_updates.effective_allow_price_updates` | 0/35 |
| `automatic_improvements.item_updates.effective_allow_availability_updates` | 0/35 |
| `automatic_improvements.item_updates.effective_allow_strict_availability_updates` | 0/35 |
| `automatic_improvements.item_updates.effective_allow_condition_updates` | 0/35 |

**Everything the MEX4P dashboards actually read migrates with perfect parity.**

### Other fields — values agree (semantically), representation differs
- `id/account_id`, `name/account_name`, `adultContent`, `websiteUrl→homepage.uri`: **exact**.
- `#users`: exact (46 parent / 3 child). `#adsLinks → #account_services[GOOGLE_ADS]`: **exact** (8 parent / 1 child) — strong confirmation that ads links fully carry over.
- `address.country → address.region_code`: exact (`US`).

## Step 5 — Gap log (finalized)

Every gap below is in a field that **no downstream consumer reads today** (MEX only uses
`automatic_improvements`). They are representation/normalization items + 2 true drops.

| # | Gap | Old | New | Type | Resolution (for Step 6/7) |
|---|-----|-----|-----|------|---------------------------|
| G1 | `shipping_improvements` omitted when unset | `False` | `None` (absent) | normalization | Treat absent as `false` (coalesce in Beam / `IFNULL` in SQL). Nullable BOOLEAN in schema. |
| G2 | `promotions_consent` is an enum, not bool | `False` | `0` (`*_UNSPECIFIED`) | representation | Store as STRING enum name (or INT). Equivalent to old false. Not consumed. |
| G3 | unset address strings | `None`/absent | `""` (empty string) | normalization | Native v1 behavior; keep as-is (nullable STRING). Harmless. |
| G4 | `kind` (`content#account`) | present | dropped | cosmetic | Drop — no v1 equivalent, no consumer. |
| G5 | `accountManagement` scalar (`manual`/`aggregator`) | `manual` | n/a | remodeled | Derive from `account_services` oneof (`account_management` vs `account_aggregation`) IF ever needed; otherwise omit. Not consumed. |
| G6 | `conversionSettings.freeListingsAutoTaggingEnabled` | `False` | — | **true drop** | No accounts-v1 home (lives in a separate Conversion Sources API). Drop for Phase 1; revisit only if a consumer needs it. Not consumed. |
| G7 | `googleMyBusinessLink` | `null` in test data | not pulled | optional | Lives in separate `GbpAccountsService`. Null in test data; skip for Phase 1 unless required. Not consumed. |
| G8 | `users` shape: `admin`/`reportingManager` booleans | booleans | `access_rights[]` enum + `state` | remodel | Map `ADMIN`→admin, `PERFORMANCE_REPORTING`→reportingManager only if a consumer needs them. Counts already match. Not consumed. |

### Verdict
- **No blocking gaps.** All parity-critical data (account set + `automatic_improvements`) matches exactly.
- The remaining gaps are (a) cosmetic/representation differences inherent to the native v1 shape, or (b) two fields (`conversionSettings`, `googleMyBusinessLink`) with no accounts-v1 home that **nothing downstream consumes** → safe to drop in Phase 1.
- Action items carried into Step 6 (schema design): G1 coalesce shipping to false; G2 enum representation; otherwise adopt native v1 field names verbatim (no legacy aliasing, per the migration mandate).
