# Ads OneShop — Content API Ingestion (Understanding Doc)

> Scope: This document explains **specifically how data is ingested from the Google
> Content API for Shopping** (`shoppingcontent.googleapis.com`, a.k.a. the "Merchant
> Center API", discovery name `content` `v2.1`) in this repo, where that data lands,
> and how it flows into BigQuery / Looker Studio. Google Ads API ingestion is covered
> only where it intersects with Content API data.
>
> Context: The README notes this solution currently uses the **Content API** and is
> slated to migrate to the new **Merchant API** (`merchant.googleapis.com`) in H1 2026.
> This doc is intended to be the reference for understanding the current Content API
> path before that migration.

---

## 1. High-level pipeline

The whole solution (the **ACIT** core — *Advanced Commerce Insights Tool*) runs as a
single linear shell pipeline, `acit/run_acit.sh`, with five stages:

```
pull_data        ->  run_pipeline      ->  upload_to_bq   ->  create_views  ->  run_extensions
(acit.py)            (create_base_         (bq.sh +            (BQ views)        (MEX4P, optional)
                      tables.py / Beam)     schemas)
```

| Stage           | Entry point                       | What it does                                                                 |
|-----------------|-----------------------------------|------------------------------------------------------------------------------|
| `pull_data`     | `acit/acit.py`                    | Calls **Content API** + **Google Ads API**, writes raw JSONL to disk/GCS     |
| `run_pipeline`  | `acit/create_base_tables.py`      | Apache Beam job that joins/denormalizes the raw JSONL into a wide table      |
| `upload_to_bq`  | `acit/bq.sh`                      | Loads JSONL files into BigQuery tables using fixed schemas                   |
| `create_views`  | `acit/views/*.sql`                | Creates the `acit` and `disapprovals` BQ views consumed by Looker Studio     |
| `run_extensions`| `extensions/merchant_excellence/` | Optional MEX4P best-practices dashboard tables (BQ-only transforms)          |

Deployment wrapper: `deploy_job.sh` packages this as a **Cloud Run job** (`ads-oneshop-job`)
that, when `USE_DATAFLOW_RUNNER=true`, offloads the Beam stage to **Dataflow**. Secrets
(OAuth client id/secret, refresh token, Ads developer token) come from **Secret Manager**.
`run_job.sh` triggers it; `schedule_job.sh` schedules it.

The Content API is exercised entirely in **stage 1 (`pull_data` → `acit.py`)**. Everything
after that operates on the JSONL files it produced.

---

## 2. The Content API client

Defined in `acit/acit.py`:

```python
def _get_merchant_center_api():
    creds = _get_credentials()
    merchant_api = discovery.build('content', 'v2.1', credentials=creds)
    return merchant_api
```

- Uses the **Google API Python client** (`googleapiclient.discovery`) — a generic,
  discovery-document-driven client, *not* a hand-written SDK. This is why the downloader
  code is fully generic (see §4).
- `('content', 'v2.1')` selects the **Content API for Shopping v2.1**.
- It is constructed lazily via a **factory** (`_get_merchant_center_api`) and called fresh
  inside each worker, because the client is not picklable / not process-safe and the leaf
  pulls run in a `ProcessPoolExecutor` (§5.4).

### Authentication (`_get_credentials`)

Two mutually exclusive modes, chosen by presence of env vars:

1. **OAuth user credentials** — if `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_CLIENT_ID`,
   `GOOGLE_ADS_CLIENT_SECRET` are all set, build an `oauth2.credentials.Credentials` that
   refreshes against `https://oauth2.googleapis.com/token`.
2. **Application Default Credentials** — otherwise fall back to `google.auth.default()`
   (the **service account** flow; the SA email must be added as a user on the Merchant
   Center + Google Ads accounts).

Note: even though the env vars are named `GOOGLE_ADS_*`, the same OAuth credential is reused
for **both** the Ads API and the Content API. The OAuth consent flow (`acit/auth/oauth.py`,
run during setup) requests both the `adwords` and `content` scopes.

---

## 3. Account topology discovery (the first Content API call)

Merchant Center accounts come in two shapes, and the pipeline must figure out which is which
before it can pull product data. This is done in `acit.py:main()` using the
**`accounts.authinfo`** method:

```python
for result in resource_downloader.download_resources(
        client=merchant_api,
        resource_name='accounts',
        resource_method='authinfo',   # GET accounts/authinfo
        is_scalar=True, ...):
    for account_identifier in result.get('accountIdentifiers', []):
        if 'merchantId' in account_identifier:
            standalone_ids.add(account_identifier['merchantId'])
        else:
            aggregator_ids.add(account_identifier['aggregatorId'])
```

This classifies every account the credential can see into:

- **`aggregator_ids`** — MCAs (Multi-Client Accounts / "parent" accounts).
- **`standalone_ids`** — standalone leaf merchant accounts.

The `--merchant_id` flags passed by the operator (`MERCHANT_IDS` env var) are intersected
with these sets to decide what to actually pull. Accounts in the input but in none of the
discovered sets are logged as inaccessible/unprocessed (data may be missing).

---

## 4. The generic resource downloader (`acit/resource_downloader.py`)

All Content API reads go through one generic helper, `download_resources()`, which wraps the
discovery client. Key mechanics:

- **Method dispatch**: `getattr(client, resource_name)` gets the collection (e.g.
  `client.products`), then `getattr(collection(), resource_method)(**params)` invokes the
  method (`list`, `get`, `authinfo`, …).
- **Pagination**: for list calls it loops using the discovery client's `<method>_next`
  helper (`products.list_next(request, response)`) until there are no more pages, yielding
  each item out of the response's `result_path` (e.g. `"resources"`).
- **Scalar vs collection**: `is_scalar=True` means "single object, execute once, no paging"
  (used for `get` and `authinfo`); otherwise it pages a collection.
- **Retries**: every `.execute()` uses `num_retries=3`.
- **Metadata injection**: every yielded record gets a `downloaderMetadata` key
  (`METADATA_KEY`) stamped onto it — crucially `{'accountId': ...}` — so that downstream
  Beam joins know which merchant each row came from (the API payloads don't always carry it).
- **Parent/child expansion + `@`-substitution**: supports querying a parent resource and
  substituting parent fields into child params (`@field_name` placeholders). Not heavily used
  by the MC path here, but it's the same engine.

`resource_downloader.py` is also runnable standalone (CLI with `--api_name/--api_version/...`)
for ad-hoc dumps of any discovery API.

---

## 5. What Content API resources are pulled, and how

`acit.py` defines the resource sets near the top:

```python
_ACIT_MC_RESOURCES            = ['products', 'productstatuses']  # per-leaf collections
_ACIT_MC_ACCOUNT_RESOURCE     = 'accounts'
_ACIT_MC_SHIPPINGSETTINGS_RESOURCE = 'shippingsettings'
_ACIT_ACCOUNT_RESOURCES       = ['accounts']
_ACIT_ACCOUNT_ADMIN_RESOURCES = ['liasettings', 'shippingsettings']   # only if --admin
```

Whether the admin-only resources are pulled is controlled by the `--admin` flag
(`ADMIN` env var). Below is each resource and its call pattern.

### 5.1 `accounts` — account settings, rolled down from MCA to children

For each **aggregator** in scope, the pipeline:
1. `accounts.get` (scalar) for the aggregator itself → the parent settings object.
2. `accounts.list` (paged) for the aggregator → all sub-accounts, appended as `children`.

The result is written as a **single JSON object** with shape:

```json
{ "settings": { ...aggregator account... }, "children": [ { ...sub-account... }, ... ] }
```

While listing children it also builds two in-memory maps used later:
- `leaf_to_parent[child_id] = aggregator_id`
- `leaf_ids` — the set of all leaf accounts to process for products.

Account-level settings include things like links to Google Ads, automatic image
improvements, item updates, etc. (see `acit/schemas/acit/accounts.schema`).

### 5.2 `liasettings` (admin only) — Local Inventory Ads settings

Pulled the same way as `accounts` for aggregators (`get` for parent + `list` for children).
Has special downstream handling: in the Beam stage a row may arrive as either a raw
`LiaSettings` or a `CombinedLiaSettings` and is normalized via protobuf parsing
(`convert_lia_settings` in `create_base_tables.py`).

### 5.3 `shippingsettings` (admin only) — special-cased

Shipping settings behave differently from other account resources, so they get dedicated code:
- For an **aggregator**: `_list_mca_resource()` → `shippingsettings.list` over the MCA,
  wrapping all children under a synthetic `{settings:{accountId:<mca>}, children:[...]}` parent.
- For a **standalone** account: `_pull_standalone_account_resource()` → `shippingsettings.get`
  with `{'merchantId': parent_id, 'accountId': account_id}`. A **404 is tolerated** (logged as
  a warning) because an account may simply have no shipping settings.

### 5.4 `products` and `productstatuses` — the core per-leaf collections

These are the heart of the product data and are pulled for **every leaf** account
(`leaf_ids ∪ (standalone_ids ∩ input_ids)`), in **parallel** via a
`ProcessPoolExecutor` (spawn context). Each leaf/resource pair is one task running
`_pull_leaf_collection()`:

```python
resource_downloader.download_resources(
    client=merchant_api,
    resource_name=resource,                     # 'products' or 'productstatuses'
    params={'merchantId': account_id, 'maxResults': 250},  # note: 'merchantId', not 'accountId'
    resource_method='list',
    result_path='resources',
    metadata={'accountId': account_id})
```

- `products.list` → the full product catalog (offer attributes: title, description, price,
  brand, gtin, google_product_category, custom labels, channel, feed label, etc.).
- `productstatuses.list` → per-offer status: destination statuses, approval/disapproval per
  country, item-level issues, etc.
- `maxResults=250` is the page size; the downloader pages through all of them.
- Each row is metadata-stamped with `{'accountId': account_id}` so products and statuses
  can be joined later.

> Quirk noted in code: the products endpoint uses the param name `merchantId` (inconsistent
> with the rest of the API which uses `accountId`).

---

## 6. On-disk layout produced by ingestion

`acit.py` writes everything under `--output` (default `/tmp/acit`, or the
`${STAGING_DIR}/${RUN_ID}/sources` GCS path in the deployed job). Two top-level dirs:

```
<output>/
├── ads/all/<resource>/*.jsonlines          # Google Ads API (GAQL) results
└── merchant_center/
    └── <accountId>/
        ├── accounts/rows.jsonlines         # one rolled-up parent+children object
        ├── liasettings/rows.jsonlines      # (admin)
        ├── shippingsettings/rows.jsonlines # (admin)
        ├── products/rows.jsonlines         # one JSON object per product
        └── productstatuses/rows.jsonlines  # one JSON object per product status
```

All files are **newline-delimited JSON (JSONL)**. This is the contract between the ingestion
stage and the Beam/BQ stages — both consume these globs.

---

## 7. How Content API data is transformed (Beam — `create_base_tables.py`)

The Beam pipeline reads the JSONL globs and builds the denormalized **`Products`** wide table.
The Content-API-derived steps:

1. **Read** `merchant_center/*/products/*.jsonlines` and `.../productstatuses/*.jsonlines`.
2. **Join products ↔ statuses** on the composite key `(accountId, offerId/productId)` via
   `CoGroupByKey`, producing `{accountId, offerId, product, status}`. (The join is defensive
   — items missing either side are dropped, since downloaders can race.)
3. **Enrich from the product itself**:
   - `set_product_approved` — inspects `status.destinationStatuses` (destination `Shopping`)
     to populate `approved/pending/disapproved_countries`.
   - `set_product_in_stock` — `availability == 'in stock'`.
4. **Cross-reference with Google Ads targeting** (`product.py`): each product is tested
   against Shopping listing-group trees and Performance Max asset-group listing filters to
   set `hasShoppingTargeting` / `hasPerformanceMaxTargeting` and the matching campaign IDs.
   This is where Content API product data meets Ads API campaign/criteria data.
5. **Serialize via protobuf** (`schema_pb2.WideProduct`, defined in
   `acit/api/v0/storage/schema.proto`) to enforce the BQ schema, then write
   `wide_products_table.jsonlines`. LIA settings are normalized to `liasettings.jsonlines`.

The `WideProduct` proto (and generated `Products.schema`) is the canonical shape of the
product table: nested `Product`, `ProductStatus`, targeting booleans/IDs, country arrays,
`offer_id`, `account_id`.

---

## 8. Loading into BigQuery (`bq.sh`, invoked by `run_acit.sh:upload_to_bq`)

JSONL files are loaded into BQ tables via the BigQuery REST API (token from the GCE metadata
server or ADC). Each load uses `WRITE_TRUNCATE`, `ignoreUnknownValues`, a fixed JSON schema
where available, and a 60-day table TTL. Tables created from the Content API path:

| BQ table          | Source file                                  | Schema                                  | Origin                |
|-------------------|----------------------------------------------|-----------------------------------------|-----------------------|
| `accounts`        | `merchant_center/*/accounts/rows.jsonlines`  | `schemas/acit/accounts.schema`          | Content API           |
| `shippingsettings`| `merchant_center/*/shippingsettings/...`     | `schemas/acit/shippingsettings.schema`  | Content API (admin)   |
| `liasettings`     | Beam `liasettings.jsonlines`                 | `api/v0/storage/liasettings.schema`     | Content API (admin)   |
| `products`        | Beam `wide_products_table.jsonlines`         | `api/v0/storage/Products.schema`        | Content API + Ads API |
| `performance`     | `ads/all/shopping_performance_view/...`      | `schemas/acit/performance.schema`       | Ads API               |
| `language`        | `ads/all/language_constant/...`              | autodetect                              | Ads API               |

(In `USE_DATAFLOW_RUNNER=true` mode, BQ loads directly from the GCS wildcard paths; in local
mode `bq.sh` first `cat`s the matching files into a single file under `BQ_DIR`.)

---

## 9. Views and dashboards

`acit/views/main_view.sql` builds the **`acit`** view that Looker Studio consumes. It:
- Flattens the Content-API-derived `products` table (product types, google product categories,
  custom labels, in-stock, is_approved from the country arrays, is_targeted from campaign IDs).
- Joins to the Ads `performance` table on the Merchant Center FK
  `channel:language:feed_label:item_id` (+ merchant id) to attach impressions/clicks/cost/
  conversions.
- Joins to `language` to map language resource names ↔ codes.

`disapprovals_view.sql` is the second view. The **ACIT** Looker Studio template reads these.

`extensions/merchant_excellence/` (MEX4P, optional, gated by `RUN_MERCHANT_EXCELLENCE`) is a
set of **BQ-only SQL transforms** on top of the same ingested tables (offer funnel, benchmark
scores, ML data, etc.) — it does **not** call the Content API itself; it reuses the
`products`/`accounts`/etc. tables already loaded.

---

## 10. Summary cheat-sheet (Content API surface used)

| Content API call                  | Method     | Where (`acit.py`)                          | Output table |
|-----------------------------------|------------|--------------------------------------------|--------------|
| `accounts.authinfo`               | scalar GET | `main()` topology discovery                | — (control)  |
| `accounts.get` + `accounts.list`  | get + list | aggregator loop / `_list_mca_resource`     | `accounts`   |
| `liasettings.get` + `.list`       | get + list | aggregator loop (admin)                    | `liasettings`|
| `shippingsettings.get`            | get        | `_pull_standalone_account_resource` (admin)| `shippingsettings` |
| `shippingsettings.list`           | list       | `_list_mca_resource` (admin)               | `shippingsettings` |
| `products.list`                   | list       | `_pull_leaf_collection` (parallel)         | `products` (joined) |
| `productstatuses.list`            | list       | `_pull_leaf_collection` (parallel)         | `products` (joined) |

**Key files to read for the migration to Merchant API:**
- `acit/acit.py` — all Content API call sites, account topology, output layout.
- `acit/resource_downloader.py` — the generic discovery-client wrapper (pagination, retries,
  metadata stamping). The Merchant API uses a different (gRPC/REST resource-name) model, so
  this is the main abstraction that will need rework.
- `acit/create_base_tables.py` + `acit/api/v0/storage/schema.proto` — the field shapes the
  rest of the system depends on; whatever the Merchant API returns must be mapped back to
  these `Product` / `ProductStatus` / `WideProduct` fields.
- `acit/schemas/acit/*.schema` and `acit/views/*.sql` — the BQ contract and the consumer
  queries.
