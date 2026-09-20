# Benchmark label audit — 2026-09-20

This audit reviews every bundled case against only the code visible in its patch. A label is fair
when a careful reviewer can reach the expected answer without relying on unstated application
behavior. The corpus remains balanced at 12 buggy and 12 safe cases.

## Audit decisions

| Case | Kind | Difficulty | Expected finding | Decision |
| --- | --- | --- | --- | --- |
| `authorization_bypass` | Buggy | Medium | `authorization_bypass` | Keep; removing the only authorization guard clearly enables an unauthorized delete. |
| `cache_key_omits_locale` | Buggy | Hard | `cache_key_collision` | Keep; the omitted locale creates cross-locale cache reuse. |
| `data_loss_write_mode` | Buggy | Easy | `data_loss` | Keep; write mode visibly truncates the audit file. |
| `division_by_zero` | Buggy | Easy | `division_by_zero` | Keep; the zero guard is removed from the divisor. |
| `missing_await` | Buggy | Medium | `missing_await` | Keep; attributes are read from the unawaited coroutine. |
| `mutable_default_argument` | Buggy | Medium | `mutable_default_argument` | Keep; the list persists across calls. |
| `off_by_one_slice` | Buggy | Easy | `off_by_one` | Keep; the new endpoint returns one extra item. |
| `path_traversal` | Buggy | Medium | `path_traversal` | Keep; resolution and containment checks are removed. |
| `secret_logging` | Buggy | Easy | `sensitive_data_exposure` | Keep; the added log line emits a plaintext password. |
| `sql_injection` | Buggy | Easy | `sql_injection` | Keep; untrusted input is interpolated into SQL. |
| `unsafe_deserialization` | Buggy | Medium | `unsafe_deserialization` | Keep; attacker-controlled bytes are passed to `pickle.loads`. |
| `weak_token_generation` | Buggy | Medium | `weak_randomness` | Keep; a reset token loses entropy and cryptographic randomness. |
| `safe_constant_extraction` | Safe | Easy | none | Keep; the limit value is unchanged. |
| `safe_constant_time_compare` | Safe | Medium | none | Corrected; both strings are now UTF-8 encoded before `compare_digest`, preserving equality for non-ASCII input. |
| `safe_context_manager` | Safe | Easy | none | Keep; the file is still read and closed on every exit. |
| `safe_enumerate_refactor` | Safe | Medium | none | Keep; `start=1` preserves numbering, including empty input. |
| `safe_guard_clause` | Safe | Medium | none | Keep; valid and invalid branches retain the same effects and returns. |
| `safe_json_deserialization` | Safe | Hard | none | Clarified; visible context now states the client-supplied UTF-8 JSON contract. |
| `safe_membership_refactor` | Safe | Easy | none | Keep; string membership in the two literals is equivalent to the former comparisons. |
| `safe_parameterized_query` | Safe | Easy | none | Clarified; visible SQLite typing makes the `?` placeholder contract explicit. |
| `safe_path_validation` | Safe | Medium | none | Corrected; the old patch already returns resolved paths, and the new guard permits the root while rejecting escapes. |
| `safe_redacted_logging` | Safe | Medium | none | Keep; logging exposes no more data than before and the gateway still receives the full value. |
| `safe_refactor` | Safe | Easy | none | Keep; for the declared string input, the f-string preserves the result. |
| `safe_secrets_token` | Safe | Medium | none | Corrected; `secrets.randbelow` preserves the existing numeric-string range while strengthening randomness. |

No case was removed. Five safe patches were corrected or clarified with stronger visible context;
the changes remove plausible behavior-regression objections without adding comments that merely
declare a patch safe.

## Canonical finding categories

The original response contract accepted any string for `category`. That made semantically similar
wording score as incorrect and produced six category mismatches in the first baseline. The audited
contract now exposes these canonical categories as an enum:

- `authorization_bypass`
- `cache_key_collision`
- `data_loss`
- `division_by_zero`
- `missing_await`
- `mutable_default_argument`
- `off_by_one`
- `path_traversal`
- `sensitive_data_exposure`
- `sql_injection`
- `unsafe_deserialization`
- `weak_randomness`
- `other` for a concrete finding outside the current taxonomy

Ground truth may not use `other`; expected cases must keep a specific, reproducible label. Model
reviews may use it when a real defect does not fit the current taxonomy. Prompt `review-v2` asks the
model to select the most specific allowed category, and the Structured Outputs schema prevents
arbitrary category wording. This follows the official
[OpenAI Structured Outputs guidance](https://developers.openai.com/api/docs/guides/structured-outputs),
which supports Pydantic response schemas and enum constraints.

The historical `review-v1` baseline remains unchanged. Its result file stores whether each category
matched, but not the raw category strings, so retroactively rescoring those six mismatches would not
be reproducible. A future live run can compare `review-v2` fairly using the new contract.

## Distribution summary

| Dimension | Distribution | Audit result |
| --- | --- | --- |
| Safe versus buggy | 12 safe / 12 buggy | Balanced; keep unchanged |
| Technical areas | 12 security, 4 logic, 4 resources, 3 boundaries, 1 validation | Valid but validation remains the clearest future gap |
| Difficulty | 10 easy, 12 medium, 2 hard | Valid; future additions should emphasize medium and hard cases |
| Positive labels | 12 specific categories across 12 buggy cases | Clear after constraining the response vocabulary |

## Scoring edge cases

The audit also tightened the scoring contract:

- A reported bug must include a canonical category, file, and line.
- A safe review must leave category, file, and line empty.
- Missing a seeded bug now earns zero of its four points; contradictory details cannot receive
  partial credit.
- A line exactly two lines from the expected location remains accepted, while a three-line miss is
  rejected.
- Unknown free-form categories fail validation before scoring.

Automated tests cover each of these rules and continue checking that all coverage entries match the
case directories and expected labels.
