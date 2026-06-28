# Security Notes

## Sensitive data rules

Do not place any real street address, passwords, OAuth credentials, retailer login credentials, access tokens, payment data, or real personal delivery details in:

- Source code
- Tests
- Seed files
- Logs
- URLs
- Emails
- Screenshots
- Git history

The only approved user-facing address string is:

```text
כתובת משלוח: פרדסיה, כתובת מאומתת
```

## Encrypted local storage

`DeliveryProfileStore` stores the household delivery profile as an encrypted local envelope. The encryption provider is abstracted behind `CryptoProvider`, and the default local provider loads its master key only from `GROCERY_AGENT_MASTER_KEY`.

The decrypted address may exist only inside the local profile store workflow. It must not be serialized into API responses, audit records, logs, email fragments, or URLs.

## Logging and audit

Audit events must include only the delivery profile ID. Example:

```json
{"event":"delivery_profile_used","delivery_profile_id":"dp_example"}
```

Application logs must never print decrypted delivery fields. Use `RedactingLogger.info_delivery_profile_used(profile_id)` for delivery profile usage logs.

## Key rotation

Recommended rotation procedure:

1. Stop local jobs that may read or write the profile.
2. Back up the encrypted profile file.
3. Set the old key in `GROCERY_AGENT_MASTER_KEY`.
4. Load and decrypt the profile locally.
5. Set a newly generated key in `GROCERY_AGENT_MASTER_KEY`.
6. Save the profile again so it is re-encrypted with the new key.
7. Verify the old key can no longer decrypt the new file.
8. Delete temporary plaintext variables and shell history entries that may contain sensitive material.

Never write the old or new key to source control, documentation examples, tickets, chat logs, or screenshots.

## Public retailer feeds

The Shufersal adapter reads only the official public price-transparency feed for Online store 413. The feed page generates a temporary public download link. The adapter validates the HTTPS host and file path, uses the link only in memory, and never stores or logs it. Raw feed responses are not exposed through portal responses.

The adapter does not authenticate to a retailer account, create a basket, access personal promotions, select delivery or pickup windows, or perform checkout.

## Production note

The current provider is dependency-free for local development. For production, implement `CryptoProvider` with an audited cryptography library or operating-system key store while preserving the same no-logging and masked-rendering contracts.
