# Phase 1 — `accounts` Migration: Understanding Doc

> Companion to `content_api_ingestion.md`. This doc confirms my understanding of the
> task before any code changes. The tracking/plan lives in `accounts_migration_plan.md`.

---

## 1. The goal (as I understand it)

Migrate Ads OneShop's Google Merchant data ingestion from the **Content API for Shopping
v2.1** (`shoppingcontent.googleapis.com`, discovery `content`/`v2.1`) to the new
**Merchant API, stable `v1`** (`merchantapi.googleapis.com`) — **phased, one resource group
at a time**, starting with **`accounts`** and nothing else in Phase 1.

The migration must be **end-to-end** for the resource in scope:

```
ingestion (acit.py)  ->  Beam processing  ->  BQ load (bq.sh + schema)  ->  views/final tables
```

**Critical constraint:** the new Merchant API data must **NOT** be re-shaped back into the
legacy Content API schema. We adopt the **native Merchant API v1 shape** at every layer —
new field names, new nesting, new BQ schema, and updated downstream SQL. No compatibility
shim/adapter that pretends the old schema still exists.

Other hard constraints:
- **Stable `v1` only** — not `v1beta` (v1beta was shut down 2026-02-28).
- **Fresh conda env** for any local testing / test scripts.
- Keep test/throwaway artifacts under `migration_test/`.

## 2. The strict 7-step method I will follow (per phase)

| # | Step | Phase-1 meaning |
|---|------|-----------------|
| 1 | Fetch from **old** Content API | Pull `accounts` exactly as the prod pipeline does today, save the raw output as the baseline. |
| 2 | Read & understand the **new** Merchant API endpoints/params | Map every old `accounts` field to its new v1 home (sub-resources). |
| 3 | Fetch from **new** Merchant API via a test script mirroring the current one | Build a small fetcher (like `resource_downloader`) for the v1 accounts sub-API; save output. |
| 4 | **Compare** old vs new data | Field-by-field diff for the same real account(s). |
| 5 | Understand the **gaps** | Note dropped/renamed/relocated/added fields, structural differences. |
| 6 | **Resolve** the issues | Decide final field set + new BQ schema; handle missing equivalents. |
| 7 | Change the **main code end-to-end** | ingestion → Beam → BQ schema/load → views/MEX SQL. |

## 3. What "accounts" is today (the baseline to migrate)

From `content_api_ingestion.md` + code, the current `accounts` path is:

- **Discovery:** `accounts.authinfo` → splits accessible accounts into aggregators (MCAs) vs
  standalone (`acit/acit.py:main`).
- **Per aggregator:** `accounts.get` (parent) + `accounts.list` (children), assembled into a
  **single rolled-up object** `{ "settings": <parent>, "children": [<child>, ...] }` and
  written to `merchant_center/<accountId>/accounts/rows.jsonlines`.
- **Generic engine:** `acit/resource_downloader.py` (discovery client, pagination via
  `list_next`, 3 retries, stamps `downloaderMetadata`).
- **BQ load:** `acit/bq.sh:upload_to_bq` loads it into table **`accounts`** using fixed schema
  `acit/schemas/acit/accounts.schema`.
- **Downstream consumers** (must change too): the **MEX4P** extension SQL reads the `accounts`
  table and its nested `settings.*` / `children[].*`:
  - `extensions/merchant_excellence/ml_data.sql`
  - `extensions/merchant_excellence/account_list.sql`
  - `extensions/merchant_excellence/all_metrics.sql`
  - `extensions/merchant_excellence/offer_list.sql`
  - `extensions/merchant_excellence/offer_funnel.sql`
  - Mostly read `settings.automaticImprovements.imageImprovements.effectiveAllowAutomaticImageImprovements`
    and `settings.automaticImprovements.itemUpdates.effectiveAllow*Updates` (parent **and** child rows).

The current monolithic Content API `Account` object carries (per `accounts.schema`):
`id`, `name`, `kind`, `websiteUrl`, `adultContent`, `accountManagement`, `adsLinks[]`,
`users[]`, `googleMyBusinessLink`, `conversionSettings`, `businessIdentity`,
`businessInformation` (address, phone, customer service), and `automaticImprovements`
(shipping/image/item-update settings).

## 4. What the new Merchant API v1 `accounts` looks like (key finding)

The single biggest structural change: **the Content API's one big `Account` object is
decomposed into many sub-resources in Merchant API v1.** A single `accounts.get` no longer
returns links, users, business info, or automatic improvements — each is its own endpoint.

Resource name format everywhere: **`accounts/{account}`** (and `accounts/{account}/<sub>`).

| Old Content API field (monolithic `Account`) | New Merchant API v1 location |
|---|---|
| core (`id`, `name`, `adultContent`) | **`Account`** → `accountId`, `accountName`, `adultContent`, plus new `testAccount`, `timeZone`, `languageCode` |
| `businessInformation` (address, phone, customer service) | **`accounts/{account}/businessInfo`** (BusinessInfo) |
| `websiteUrl` | **`accounts/{account}/homepage`** (Homepage; `uri`, `claimed`) |
| `users[]` | **`accounts/{account}/users`** (User, `list`/`get`) |
| `automaticImprovements` | **`accounts/{account}/automaticImprovements`** (AutomaticImprovements) |
| `businessIdentity` | **`accounts/{account}/businessIdentity`** (BusinessIdentity) |
| `adsLinks`, `accountManagement`, `conversionSettings`, `googleMyBusinessLink` | Re-modeled via **`AccountRelationship`** / **`AccountService`** (and Homepage claiming); no longer simple fields on the account |

Discovery / topology equivalents:
- `accounts.authinfo` → **`accounts.list`** (lists all accounts the caller can access).
- `accounts.list` (MCA children) → **`accounts.listSubaccounts`** (`accounts/{advanced}:listSubaccounts`).
- Advanced (MCA) vs standalone is determined via relationships/listSubaccounts rather than the
  old aggregator/merchant identifier split — **to be confirmed in Step 2/3**.

### Implication for ingestion
Pulling "an account" in v1 is a **fan-out of several endpoint calls** (core + businessInfo +
homepage + users + automaticImprovements + businessIdentity), reassembled into one record.
The current `resource_downloader` calls one method per resource; for accounts we'll either
issue several sub-resource calls per account and merge, or model each sub-resource as its own
output/table. The plan picks the approach in Step 6 after the gap analysis.

### Client library question (to settle in Step 3)
Two options for the new calls, to be decided during the test-script step:
1. **Discovery client** (`googleapiclient.discovery.build('merchantapi', 'accounts_v1', …)`) —
   smallest change vs the existing generic `resource_downloader` pattern.
2. **Dedicated Merchant API Python client** (`google-shopping-merchant-accounts`) — Google's
   recommended path, gRPC-based, but a bigger departure from the current discovery-based code.

## 5. Open questions to resolve during Steps 2–5 (tracked in the plan)

- Exact OAuth scope for Merchant API v1 (likely `https://www.googleapis.com/auth/content` still
  works) and whether existing refresh token / SA works unchanged.
- The discovery doc name/version strings for each accounts sub-API (`accounts_v1`).
- Precise advanced-vs-standalone detection in v1 (relationships? `listSubaccounts` behavior?).
- Which old fields have **no** v1 equivalent (e.g. `kind`, `accountManagement` semantics) and
  whether any MEX metric depends on them.
- Whether the rolled-up `{settings, children[]}` shape is kept (and just re-typed) or replaced
  by a flat per-account table keyed by `accountId` with a `parent`/relationship column.

## 6. Definition of done for Phase 1

- A test script under `migration_test/` fetches v1 `accounts` data into JSONL for real
  account(s), runnable in a fresh conda env.
- A documented old↔new field comparison + gap resolution.
- `acit/acit.py` ingests `accounts` from Merchant API v1 (native shape).
- Beam (`create_base_tables.py`) — if it touches accounts — and the BQ load (`bq.sh`) updated.
- New BQ schema replacing `acit/schemas/acit/accounts.schema` (native v1 field names).
- MEX SQL (the 5 files above) updated to the new shape; views still build.
- All other resources (products, productstatuses, liasettings, shippingsettings, ads) remain on
  their **current** path — only `accounts` moves in Phase 1.
