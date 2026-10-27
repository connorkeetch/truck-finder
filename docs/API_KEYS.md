# Get API keys and connect a provider

Auto.dev and MarketCheck are optional listing providers. One configured provider is enough to start.
**Try demo**, manual entry, and CSV/JSON/paste/email imports work without listing API keys.

The public provider instructions below were checked on **October 27, 2026**. Confirm current access and
billing in your own provider account before running searches.

## Auto.dev

1. Open [Auto.dev sign-in / account creation](https://www.auto.dev/signin).
2. Complete account setup and select a plan with **Vehicle Listings** access. Auto.dev's setup guide says
   its Free option needs email verification and no payment-card checkout.
3. Open the [Auto.dev dashboard](https://www.auto.dev/dashboard), choose **API Keys**, then **Create New Key**.
4. Copy the key for MotorSift's **Auto.dev API key** field.

Auto.dev currently documents Vehicle Listings on Free, Growth, and Scale. Its published Free allowance is
1,000 calls per month. Listing page sizes and other limits depend on the plan; check your account before
estimating vehicles per call. See [account/key setup](https://docs.auto.dev/v2/getting-started),
[Vehicle Listings](https://docs.auto.dev/v2/products/vehicle-listings), and
[current pricing](https://www.auto.dev/pricing).

## MarketCheck

1. [Create a Developers Portal account](https://developers.marketcheck.com/sign-up), or
   [sign in](https://developers.marketcheck.com/login).
2. Explicitly subscribe to an API package that permits **Cars → Inventory Search**. An account alone is
   insufficient; MarketCheck's authentication guide says even a free trial needs a package subscription.
3. Open [API Keys](https://developers.marketcheck.com/api-keys) and generate a key.
4. Copy the **API Key** into MotorSift's **MarketCheck API key** field. MotorSift does not need the accompanying
   **Client Secret** or an OAuth token.

The portal currently lists Free at 500 calls per month with a 100-mile search-radius restriction. Paid packages
also have radius and pagination limits; paying does not automatically permit nationwide searches. Paid plans
can add per-call data fees. Check your package and any endpoint/IP restrictions for the key. See
[authentication](https://docs.marketcheck.com/docs/get-started/api/authentication),
[portal plans](https://developers.marketcheck.com/), and
[access controls](https://docs.marketcheck.com/docs/get-started/api/access-control).

MotorSift's optional specification lookup uses [NeoVIN](https://docs.marketcheck.com/docs/api/cars/vehicle-specs/neovin).
If you restrict the key to individual endpoints, allow that separately when you want those lookups.

## Save the key in MotorSift

**On your computer:** open **Settings → API credentials**, paste the provider's key, and choose **Save to OS
credential store**. This uses Windows Credential Manager, macOS Keychain, or Linux Secret Service. If no
credential-store backend is available, add the relevant variable to the project's ignored `.env` file and
restart the app:

```ini
AUTODEV_API_KEY=replace-with-your-autodev-key
MARKETCHECK_API_KEY=replace-with-your-marketcheck-key
```

Only set the providers you use. Environment variables / `.env` take precedence over saved credential-store
keys; Settings shows which source is configured. Keys are not stored in the inventory database or exports.
Keep keys out of Git, screenshots, issue reports, and shared URLs.

**On Railway:** set `AUTODEV_API_KEY` and/or `MARKETCHECK_API_KEY` in the service's **Variables**, then apply
the updated deployment. Manage hosted keys there rather than in your computer's credential store. See
[private cloud setup](CLOUD_DEPLOYMENT.md).

## Make the first search

Saving a key does not test it or fetch listings. Set your home ZIP and make/model pairs in **Settings**;
for example, Toyota Camry, Honda CR-V, Ford F-150, or a minivan. Choose whether **Used vehicles only** applies.
The current connectors use automotive listing endpoints: cars, SUVs, vans, and pickups where the provider has
coverage. MarketCheck's separate RV, motorcycle, and heavy-equipment APIs are not integrated into MotorSift.

In **Sources → Automatic connectors**, enable the provider you configured. Start with one make/model and a
small **Max pages per connector per run**, then choose **Inventory → Refresh listings → Start search**.
The provider controls which endpoints, fields, areas, and vehicles your account can access.

MotorSift's monthly safety budgets are **1,000 Auto.dev calls** and **500 MarketCheck calls**. These are local
app limits, not a reading of your subscription or remaining credit. Other apps' usage is absent from these
counters, and paid-account charges remain governed by your provider. Check the provider dashboard for the
account-wide total. See [MarketCheck quota rules](https://docs.marketcheck.com/docs/get-started/api/quota-and-rate-limits).

If requests are denied, check the key, package subscription, endpoint permissions, and any IP restrictions.
If requests are throttled, check the provider's quota/rate-limit response and dashboard. An app safety-budget
message is a separate local limit. Incomplete or failed searches do not mark unseen listings missing.
