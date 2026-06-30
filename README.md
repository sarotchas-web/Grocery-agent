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
- A read-only Shufersal Online price and public-promotion search using the official transparency feeds for store 413.
- A process-local Shufersal basket estimate. It is not a retailer basket and is cleared when the portal restarts.

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
  shufersal_adapter.py   Read-only official Shufersal Online price feed
  shufersal_promotions.py Public promotion parsing and conservative price enrichment
  shufersal_basket.py    Process-local basket estimates
  cli.py                 Local command-line admin workflow
  web_app.py             Local browser portal
  order_portal.py        Shopping list, quote comparison and cart preparation flow

tests/                   Security, policy, CLI and portal tests
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

## Local browser portal

Set the master key, then start the local-only portal:

```powershell
$env:GROCERY_AGENT_MASTER_KEY = "replace-with-a-local-secret-generated-outside-source-control"
python .\grocery_agent_web.py
```

Open:

```text
http://127.0.0.1:8765
```

Use the `Delivery profile` page as Shay to enter or update the real address locally. The portal does not prefill or display the full address after saving; it shows only the masked profile text and delivery profile ID.

## Shufersal public catalog

Open `Shufersal prices` in the Hebrew portal to search the official Online store 413 price and promotion feeds. Products can be added to a process-local estimate basket for Shay or Michal. The basket applies only simple public single-item prices; club, coupon, and quantity promotions are shown but are not automatically deducted. Delivery fees, service fees, item availability, personal promotions, and checkout totals must still be confirmed at the retailer.

No retailer login, credential, payment detail, delivery address, or temporary signed feed URL is stored or rendered by this workflow.

## Testing the live public connection

1. Start the portal and open `http://127.0.0.1:8765`.
2. Select `הזמנה חדשה`, enter one search phrase per line such as `חלב`, and continue.
3. Select the exact live Shufersal product for every line. The app does not guess between similar products.
4. The Shufersal retailer name, public item subtotal, public promotion savings, and product list are then prefilled.
5. Confirm whole-basket availability and enter the current delivery and service fees from retailer checkout before comparing.
6. Use `מחירי שופרסל` and `מצב החיבור` to inspect the public catalog directly. Manual retailer comparison remains available when an item has no suitable public match.

This is a live read-only public-data connection. It does not sign in, transmit the delivery profile, create a retailer-side basket, reserve stock, select a real pickup window, place an order, or transmit payment data. Those actions require an authorized retailer API and separate user confirmation.

## Starting an order

Select `New order` in the local portal as Shay or Michal:

1. Enter one shopping item per line.
2. Add current basket quote figures for one or two retailers.
3. Include discounts, promotions, delivery and service fees.
4. Add pickup details only when the retailer currently offers pickup.
5. Review the eligible delivery and pickup comparison and its Hebrew recommendation.
6. Acknowledge the budget only when the selected estimate is greater than 800 ILS.
7. Approve cart preparation.

The local workflow does not log in to retailers, invent live prices, place a purchase, or handle payment data. Retailer checkout remains outside this project until an authorized live adapter is configured. See [RETAILER_INTEGRATION.md](RETAILER_INTEGRATION.md) for the approved connection process.

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


