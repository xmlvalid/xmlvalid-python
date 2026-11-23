# Changelog

## 1.4.0

- `create_invoice()` (sync and async): an e-invoice written from JSON (XRechnung, Peppol BIS,
  ZUGFeRD / Factur-X, France CTC; `format="pdf"` for a PDF with the XML inside) and checked
  against its profile's rules; `Validation.invoice` says what was written, `invoice_document()`
  downloads it.

## 1.3.0

- `fix=True` and `fix_values=` on `validate()` and `submit()` (Pro): the invoice fixed as the
  validator fixes it and checked again; `Result.fix` (`Fix`: `status`, `changes`, `asks`,
  `problems`, `result`) says what was done, and `fixed()` downloads the fixed document.
- Test keys (`xv_test_…`): `Validation.test`, and `Usage.test_used`, `test_limit`, `test_reset_at`
  for the day's test validations. `test_quota_exceeded` raises `QuotaExceededError` without retries.

## 1.2.0

- `Diagnostic.path`: where a business rule fired, as an XPath with the document's prefixes
  (`/Invoice/cac:InvoiceLine[2]/cbc:LineExtensionAmount`).
- `sha256` and `engine` on `Result` and `ArchiveItem`: the SHA-256 of the file as sent and what
  checked it, as `Engine` (`xmlvalid`, `libxml2`, `saxonjs`), for an audit trail.

## 1.1.0

- `rules_version=` on `validate()` and `submit()` pins catalog rule sets to releases
  (`peppol-bis-3-ubl@3.0.21`, one or several); a pinned set at another release raises
  `RulesVersionMismatchError` (409 `rules_version_mismatch`, with `rule_set`, `pinned`, `current`).
- `rule_sets` on `Validation`, `ArchiveItem` and `Schema`: the business rules with their keys and
  releases, as `RuleSet` (`key`, `name`, `version`, `label`, `pin`).

## 1.0.0

- First release: `Client` and `AsyncClient` with `validate()`, `submit()`, `wait_for()`,
  `validation()`, `cancel()`, `report()`, `share()`, `usage()`, `schemas()`; typed results and
  exceptions; `webhooks.verify()`.
