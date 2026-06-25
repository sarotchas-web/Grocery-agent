# Grocery Agent

A local household grocery policy engine for comparing delivery and pickup options without storing real delivery details in source code.

## What is implemented

- Shared household delivery profile stored through an encryption abstraction.
- Owner-only local admin form boundary for creating or updating the delivery profile.
- Masked delivery address rendering only: `כתובת משלוח: פרדסיה, כתובת מאומתת`.
- Audit records include only `delivery_profile_id`, never decrypted address fields.
- Household budget threshold of 800 ILS.
- Mandatory acknowledgement only when the final estimated amount is greater than 800 ILS.
- Hebrew budget acknowledgement text: `אני מאשר/ת חריגה מעל ₪800`.
- Fulfillment modes: `DELIVERY` and `PICKUP`.
- Pickup eligibility checks for real pickup availability, Emek Hefer area, overlap with 16:30-18:30 Israel time, and full basket availability.
- Recommendation logic comparing delivery first, then eligible pickup, then split baskets only when savings after all fees are at least 25 ILS.
- Permission rules for Shay and Michal, including Michal's independent workflow permissions.

## Project layout

```text
src/grocery_agent/
  budget.py              Budget threshold and acknowledgement policy
  crypto.py              Local encryption abstraction using env-loaded master key
  delivery_profile.py    Encrypted profile store and masked rendering
  logging_safety.py      Safe logging helper for profile usage
  models.py              Shared domain models
  permissions.py         Owner/member permission policy
  pickup.py              Pickup eligibility and summaries
  recommendation.py      Delivery, pickup and split-basket recommendation rules
  retailer_adapter.py    Runtime adapter boundary for retailer data
  cli.py                 Local command-line admin workflow

tests/                   Security, policy and CLI tests
```

## Running tests

From this folder:

```powershell
python -m unittest discover -s tests -v
```

The tests use only synthetic placeholder data. Do not add real street addresses, credentials, tokens, payment data, or retailer account details to tests or source files.

## Local master key

Set the local master key in the environment before using the encrypted profile store:

```powershell
$env:GROCERY_AGENT_MASTER_KEY = "replace-with-a-local-secret-generated-outside-source-control"
```

Never commit this value. Never put it in screenshots, logs, URLs, emails, seed files, or test fixtures.

## Delivery profile workflow

Only Shay has permission to edit the delivery profile. Shay enters the real address manually through the local admin form boundary. The current city is Pardesiya, but the street and number must never be hardcoded.

Shay and Michal may both use the shared profile for cart preparation. User-facing surfaces must render only:

```text
כתובת משלוח: פרדסיה, כתובת מאומתת
```


### Local admin commands

Set the master key in the same PowerShell session:

```powershell
$env:GROCERY_AGENT_MASTER_KEY = "replace-with-a-local-secret-generated-outside-source-control"
```

Create or update the encrypted profile locally:

```powershell
python .\grocery_agent_cli.py delivery-profile-update --actor shay --city Pardesiya --address-line "TYPE_REAL_ADDRESS_ONLY_IN_YOUR_LOCAL_TERMINAL"
```

Show the profile safely:

```powershell
python .\grocery_agent_cli.py delivery-profile-show --actor michal
```

The command output prints only the masked address and delivery profile ID. Do not paste the real address into chat, source code, tests, Git, screenshots, URLs, logs, or emails.
## Pickup workflow

Retailer adapters must fetch pickup points and collection windows dynamically during comparison. The engine must not assume a fixed store or pickup point.

Pickup is shown only when:

- The retailer offers actual pickup.
- The pickup point is in Emek Hefer.
- The collection window overlaps the configured preference, initially 16:30-18:30 Israel time.
- All selected basket items are available.

Pickup summaries include retailer, pickup point name, window, pickup fee, final basket price after discounts, and difference versus delivery.

## Weighted products

Weighted products are included in the estimated total. User-facing output should include the Hebrew notice that the final charge may change according to actual weight.

