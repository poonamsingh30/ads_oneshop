-- Copyright 2024 Google LLC
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Phase 3: native Merchant API v1 omnichannel settings. FLAT shape -- one row per
-- (sub-/standalone) account with a repeated per-region `omnichannel_settings`
-- list (the old {settings, children[]} envelope is gone). Mirrors the proto
-- `OmnichannelLiaSettings` (acit/api/v0/storage/schema.proto); the production
-- table is created from the generated `liasettings.schema`, so this fallback DDL
-- only needs to match column names/types.
CREATE TABLE IF NOT EXISTS ${PROJECT_NAME}.${DATASET_NAME}.liasettings (
    account_id INT64,
    omnichannel_settings ARRAY<
        STRUCT<
            name STRING,
            region_code STRING,
            lsf_type STRING,
            in_stock STRUCT<uri STRING, state STRING>,
            pickup STRUCT<uri STRING, state STRING>,
            lfp_link STRUCT<
                lfp_provider STRING,
                external_account_id STRING,
                state STRING
            >,
            odo STRUCT<uri STRING, state STRING>,
            about STRUCT<uri STRING, state STRING>,
            inventory_verification STRUCT<
                state STRING,
                contact STRING,
                contact_email STRING,
                contact_state STRING
            >
        >
    >
);

CREATE TABLE IF NOT EXISTS ${PROJECT_NAME}.${DATASET_NAME}.shippingsettings (
    children ARRAY<
        STRUCT<
            settings STRUCT<
                accountId INT64,
                services ARRAY<
                    STRUCT<
                        deliveryTime STRUCT<
                            handlingBusinessDayConfig STRUCT<businessDays ARRAY<STRING>>,
                            maxTransitTimeInDays INT64,
                            minTransitTimeInDays INT64,
                            maxHandlingTimeInDays INT64,
                            minHandlingTimeInDays INT64,
                            cutoffTime STRUCT<timezone STRING, minute INT64, hour INT64>
                        >,
                        rateGroups ARRAY<
                            STRUCT<
                                applicableShippingLabels ARRAY<STRING>,
                                name STRING,
                                mainTable STRUCT<
                                    name STRING,
                                    `rows` ARRAY<
                                        STRUCT<
                                            cells ARRAY<
                                                STRUCT<
                                                    flatRate STRUCT<currency STRING, value FLOAT64>
                                                >
                                            >
                                        >
                                    >,
                                    rowHeaders STRUCT<
                                        prices ARRAY<
                                            STRUCT<currency STRING, value FLOAT64>
                                        >
                                    >,
                                    columnHeaders STRUCT<
                                        prices ARRAY<
                                            STRUCT<currency STRING, value FLOAT64>
                                        >
                                    >
                                >,
                                singleValue STRUCT<
                                    flatRate STRUCT<currency STRING, value FLOAT64>
                                >
                            >
                        >,
                        eligibility STRING,
                        shipmentType STRING,
                        currency STRING,
                        deliveryCountry STRING,
                        active BOOL,
                        name STRING
                    >
                >
            >
        >
    >,
    settings STRUCT<
        accountId INT64,
        services ARRAY<
            STRUCT<
                deliveryTime STRUCT<
                    handlingBusinessDayConfig STRUCT<businessDays ARRAY<STRING>>,
                    maxTransitTimeInDays INT64,
                    minTransitTimeInDays INT64,
                    maxHandlingTimeInDays INT64,
                    minHandlingTimeInDays INT64,
                    cutoffTime STRUCT<timezone STRING, minute INT64, hour INT64>
                >,
                rateGroups ARRAY<
                    STRUCT<
                        applicableShippingLabels ARRAY<STRING>,
                        name STRING,
                        mainTable STRUCT<
                            name STRING,
                            `rows` ARRAY<
                                STRUCT<
                                    cells ARRAY<
                                        STRUCT<
                                            flatRate STRUCT<currency STRING, value FLOAT64>
                                        >
                                    >
                                >
                            >,
                            rowHeaders STRUCT<
                                prices ARRAY<
                                    STRUCT<currency STRING, value FLOAT64>
                                >
                            >,
                            columnHeaders STRUCT<
                                prices ARRAY<
                                    STRUCT<currency STRING, value FLOAT64>
                                >
                            >
                        >,
                        singleValue STRUCT<
                            flatRate STRUCT<currency STRING, value FLOAT64>
                        >
                    >
                >,
                eligibility STRING,
                shipmentType STRING,
                currency STRING,
                deliveryCountry STRING,
                active BOOL,
                name STRING
            >
        >
    >
);