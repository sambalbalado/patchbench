# Benchmark coverage matrix

This document describes the 24-case PatchBench corpus as of 2026-09-20. The source of truth for
the case-level metadata is [`benchmark/coverage.json`](../benchmark/coverage.json), which is loaded
through the same Pydantic validation approach as the benchmark labels.

## Coverage targets

The current corpus is already within the original 20–30 case scope. The 30-case target is a ceiling
for deliberate future additions, not a reason to add cases automatically. Technical areas are
mutually exclusive so their counts sum to the corpus total. Safe changes are a cross-cutting class:
a safe security hardening, for example, counts under security and safe changes.

| Coverage category | Current | Target | Gap | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Logic | 4 | 5 | 1 | Data flow, state, and behavior-preserving changes |
| Validation | 1 | 4 | 3 | Input rejection and guard behavior |
| Security | 12 | 12 | 0 | Vulnerabilities and safe hardening changes |
| Resources | 4 | 5 | 1 | Files, async work, and shared mutable state |
| Boundaries | 3 | 4 | 1 | Empty values, ranges, indexing, and limits |
| Safe changes | 12 | 15 | 3 | Cross-cutting negative examples used to measure false positives |
| **Total cases** | **24** | **30** | **6** | 12 buggy and 12 safe today; target is 15 of each |

The 12 safe cases are half of the current corpus. That makes the false-positive denominator large
enough to be meaningful for this small benchmark: one false positive changes the rate by 8.3
percentage points. The first baseline's four false positives therefore produce the recorded 33.3%
rate without being hidden by an undersized negative set.

## Difficulty targets

Difficulty describes how much context or language knowledge a reviewer needs to judge the patch,
not the severity of a defect.

| Difficulty | Current | Target | Definition |
| --- | ---: | ---: | --- |
| Easy | 10 | 10 | The changed line directly exposes the behavior or known unsafe operation |
| Medium | 12 | 15 | Requires tracing local control flow or knowing a Python/API semantic |
| Hard | 2 | 5 | Requires reasoning about implicit context, equivalence, or cross-input behavior |

## Case matrix

For buggy cases, `Expected finding` is the exact category stored in `expected.json`. Safe cases use
`none`, which makes an invented finding a false positive.

| Case | Kind | Area | Difficulty | Expected finding |
| --- | --- | --- | --- | --- |
| `authorization_bypass` | Buggy | Security | Medium | `authorization_bypass` |
| `cache_key_omits_locale` | Buggy | Logic | Hard | `cache_key_collision` |
| `data_loss_write_mode` | Buggy | Resources | Easy | `data_loss` |
| `division_by_zero` | Buggy | Boundaries | Easy | `division_by_zero` |
| `missing_await` | Buggy | Resources | Medium | `missing_await` |
| `mutable_default_argument` | Buggy | Resources | Medium | `mutable_default_argument` |
| `off_by_one_slice` | Buggy | Boundaries | Easy | `off_by_one` |
| `path_traversal` | Buggy | Security | Medium | `path_traversal` |
| `safe_constant_extraction` | Safe | Logic | Easy | none |
| `safe_constant_time_compare` | Safe | Security | Medium | none |
| `safe_context_manager` | Safe | Resources | Easy | none |
| `safe_enumerate_refactor` | Safe | Boundaries | Medium | none |
| `safe_guard_clause` | Safe | Validation | Medium | none |
| `safe_json_deserialization` | Safe | Security | Hard | none |
| `safe_membership_refactor` | Safe | Logic | Easy | none |
| `safe_parameterized_query` | Safe | Security | Easy | none |
| `safe_path_validation` | Safe | Security | Medium | none |
| `safe_redacted_logging` | Safe | Security | Medium | none |
| `safe_refactor` | Safe | Logic | Easy | none |
| `safe_secrets_token` | Safe | Security | Medium | none |
| `secret_logging` | Buggy | Security | Easy | `sensitive_data_exposure` |
| `sql_injection` | Buggy | Security | Easy | `sql_injection` |
| `unsafe_deserialization` | Buggy | Security | Medium | `unsafe_deserialization` |
| `weak_token_generation` | Buggy | Security | Medium | `weak_randomness` |

## What the matrix says

The corpus has enough safe changes to measure false positives and strong coverage of security
review behavior. Its largest gap is validation, followed by hard cases. The
[2026-09-20 label audit](label-audit-2026-09-20.md) reviewed every expected answer and corrected
ambiguous safe patches without changing the distribution. Any future case must update the
machine-readable matrix; automated tests reject missing case IDs, duplicated IDs, incorrect
safe/buggy classifications, and expected findings that drift from `expected.json`.
