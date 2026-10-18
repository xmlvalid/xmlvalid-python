# Changelog

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
