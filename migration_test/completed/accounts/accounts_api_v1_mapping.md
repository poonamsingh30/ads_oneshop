# Step 2 — Merchant API v1 `accounts` endpoint study + old→new field map

> Authoritative: derived by introspecting the installed stable client
> `google.shopping.merchant_accounts_v1` (not docs) and by fetching the real test MCA
> `120436857`. Pairs with `fetch_accounts_new.py` (Step 3).

## 1. The core structural change

Content API's **one monolithic `Account`** object is split into **many sub-resources**, each
its own endpoint with **no bulk/cross-account variant**. "An account" in v1 = a fan-out:

```
accounts/{id}                              (AccountsService.get_account)        core
accounts/{id}/homepage                     (HomepageService.get_homepage)       websiteUrl
accounts/{id}/businessInfo                 (BusinessInfoService.get_business_info)
accounts/{id}/businessIdentity             (BusinessIdentityService.get_business_identity)
accounts/{id}/automaticImprovements        (AutomaticImprovementsService.get_automatic_improvements)
accounts/{id}/users           (list)       (UserService.list_users)
accounts/{id}/relationships   (list)       (AccountRelationshipsService.list_account_relationships)
accounts/{id}/services        (list)       (AccountServicesService.list_account_services)
```

Resource-name format everywhere: **`accounts/{account}`** / `accounts/{account}/{sub}`.

## 2. Topology (replaces `accounts.authinfo` + `accounts.list`)

| Content API v2.1 | Merchant API v1 | Notes |
|---|---|---|
| `accounts.authinfo` (aggregator vs merchant split) | `AccountsService.list_accounts` (accessible accounts) | lists all accounts the caller can access |
| `accounts.list` (MCA children) | `AccountsService.list_sub_accounts(provider="accounts/{mca}")` | **the list response already carries each child's full core `Account`** → no per-child `get_account` |
| aggregator vs standalone | "advanced account" (MCA) = one whose `list_sub_accounts` returns children | confirmed: `120436857` returns 34 children |

> Efficiency note: only the **parent** MCA needs a `get_account` (the list returns children but
> not the provider itself). Children get their core for free from the list page.

## 3. Field-by-field map (Content API `Account` → Merchant API v1)

| Old field (`accounts.schema`) | New location | New field(s) | Status |
|---|---|---|---|
| `id` | `Account` | `account_id` | ✅ confirmed |
| `name` | `Account` | `account_name` | ✅ |
| `adultContent` | `Account` | `adult_content` | ✅ |
| `kind` (`content#account`) | — | (dropped; no equivalent) | ✅ gap (cosmetic) |
| — (new) | `Account` | `test_account`, `time_zone{id}`, `language_code` | ✅ new fields |
| `websiteUrl` | `Homepage` | `uri` (+ new `claimed`) | ✅ |
| `businessInformation.address` | `BusinessInfo.address` | `street_address, city, administrative_area, postal_code, region_code` | ⚠️ **field renames** (old: `streetAddress, locality, region, postalCode, country`) |
| `businessInformation.phoneNumber` | `BusinessInfo` | `phone` | ✅ |
| `businessInformation.phoneVerificationStatus` | `BusinessInfo` | `phone_verification_state` | ✅ |
| `businessInformation.customerService` | `BusinessInfo.customer_service` | `uri, email, phone` | ✅ |
| `businessIdentity.includeForPromotions` | `BusinessIdentity` | `promotions_consent` (+ new `black_owned/women_owned/veteran_owned/latino_owned/small_business`) | ⚠️ rename |
| `automaticImprovements.itemUpdates.*` | `AutomaticImprovements.item_updates` | `effective_allow_{price,availability,strict_availability,condition}_updates` + `account_item_updates_settings` | ✅ confirmed (snake_case) |
| `automaticImprovements.imageImprovements.*` | `AutomaticImprovements.image_improvements` | `effective_allow_automatic_image_improvements` + `account_image_improvements_settings` | ✅ confirmed |
| `automaticImprovements.shippingImprovements.allowShippingImprovements` | `AutomaticImprovements.shipping_improvements` | `allow_shipping_improvements` | ⚠️ often absent when unset |
| `users[]` (`emailAddress, admin, reportingManager`) | `User` (list) | resource `name`=`accounts/{id}/users/{email}`, `state`(PENDING/VERIFIED), `access_rights[]`(STANDARD/READ_ONLY/ADMIN/PERFORMANCE_REPORTING/API_DEVELOPER) | ⚠️ **remodeled**: admin→`ADMIN` in access_rights; reportingManager→`PERFORMANCE_REPORTING`; email moves into resource name |
| `adsLinks[]` (`adsId, status`) | `AccountService` (list) | `provider="providers/GOOGLE_ADS"`, `external_account_id`(=adsId), `handshake.approval_state`, `campaigns_management` | ✅ **confirmed on real data** |
| `accountManagement` (`manual`/`aggregator`) | `AccountService` / `AccountRelationship` | `account_management` / `account_aggregation` service oneof | ⚠️ derived from services, not a scalar |
| `conversionSettings.freeListingsAutoTaggingEnabled` | — (not in accounts v1) | likely separate Conversion Sources API | ⛔ **gap — confirm in Step 4/5** |
| `googleMyBusinessLink` | `GbpAccount` (separate `GbpAccountsService`) | `LinkGbpAccount` / `list_gbp_accounts` | ⚠️ separate sub-API (not fetched yet) |

## 4. Other available v1 sub-APIs (not in scope for accounts phase, noted for later phases)
`ShippingSettings`, `OnlineReturnPolicy`, `Regions`, `Programs`, `TermsOfService*`,
`AutofeedSettings`, `CheckoutSettings`, `OmnichannelSettings`, `LfpProviders`,
`EmailPreferences`, `AccountIssues`, `DeveloperRegistration`.

## 5. Gaps to resolve in Steps 4–6
1. `conversionSettings` — confirm whether it has any v1 home (Conversion Sources API) or is dropped.
2. `googleMyBusinessLink` — decide whether to pull `GbpAccountsService` (adds calls) or drop.
3. `shipping_improvements` frequently absent — confirm default semantics vs old `allowShippingImprovements`.
4. `users` remodel — map old `admin`/`reportingManager` booleans onto `access_rights` enum for any consumer that needs them (none in MEX today).
5. Address field renames — ensure the new BQ schema uses native v1 names (no legacy aliasing).
