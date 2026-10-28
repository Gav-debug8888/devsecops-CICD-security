# Pipeline Overview: Deep Dive

This document explains each stage of `security-scan.yml`, why each tool was chosen, and how to run the gate day to day: handling false positives and tuning thresholds.

## Design principles

1. **Shift left, but fail fast.** Scans run on every PR, in parallel, and the whole gate takes a few minutes. A slow gate gets bypassed.
2. **Report broadly, block narrowly.** Every finding goes to the GitHub Security tab (SARIF), but only high-confidence high/critical issues block a merge. This keeps trust in the gate high.
3. **One required check.** Branch protection depends on a single `Security Gate` job. Scanners can be added or swapped without editing protection rules.
4. **Fail closed.** `continue-on-error: false` everywhere, plus `if: always()` on the aggregator. A crashed scanner counts as a failure, not a pass.

## Stage 1: Semgrep (SAST)

| | |
|---|---|
| Job | `semgrep-sast` |
| Runs in | `semgrep/semgrep` container |
| Rules | `--config=auto` (Semgrep Registry rules picked for the detected languages: Python and Flask here) |
| Blocks on | `--severity=ERROR --error` |
| Output | `semgrep.sarif` → Security tab (category `semgrep`) |

**Why Semgrep?** It is fast (seconds, not minutes), and its rules look like the code they match, so developers can read them. It is free for CI and has strong Flask and Django rule packs. CodeQL is a strong alternative for deeper data-flow analysis, but it is slower and harder to customise. Bandit is Python-only and noisier.

**Two-pass pattern.** The first run produces the full SARIF report and never fails (`|| true`). The second run uses `--severity=ERROR`, so only high and critical findings can block. Developers see every finding without being blocked on INFO or WARNING items.

## Stage 2: Trivy (container scanning)

| | |
|---|---|
| Job | `trivy-container-scan` |
| Action | `aquasecurity/trivy-action` (pinned version) |
| Target | Image built from the PR's `Dockerfile` |
| Blocks on | `severity: HIGH,CRITICAL`, `exit-code: 1`, `ignore-unfixed: true` |
| Output | `trivy-image.sarif` → Security tab (category `trivy-image`) |

**Why Trivy?** One tool covers OS packages, language packages, IaC misconfiguration and secrets. It is fast, has an actively updated vulnerability database, and needs no account. Grype and Docker Scout are alternatives. Snyk Container is strong but commercial.

**Why `ignore-unfixed`?** Blocking on CVEs with no available fix only teaches people to bypass the gate. Unfixed CVEs still appear in the SARIF report and should be tracked as accepted risk.

**Image hardening that keeps Trivy quiet:** a slim base, `apt-get upgrade` at build time, no compilers, a non-root `USER`, and pinned dependencies.

## Stage 3: Dependency check (SCA)

| | |
|---|---|
| Job | `dependency-check` |
| Tools | `pip-audit --strict` (PyPA, OSV/PyPI advisory data) + `trivy fs requirements.txt` |
| Blocks on | pip-audit: any known vulnerability. Trivy fs: HIGH/CRITICAL. |

**Why two tools?** pip-audit is the official PyPA tool and has the most accurate Python advisory data. But advisories don't always include a CVSS score, so it cannot filter by severity and fails on *any* known CVE. That is stricter than the high/critical policy. Trivy fs adds a severity-filtered second opinion. If pip-audit is too strict for your team, remove the pip-audit step and rely on Trivy fs alone.

## Stage 4: Unit tests

Security tests are first-class tests. `tests/test_app.py` checks that SQL injection payloads return no rows, that write endpoints require a token, that invalid input is rejected, and that security headers are present. A regression in any of these blocks the merge just like a scanner finding.

## Stage 5: Security gate (aggregator)

```yaml
needs: [unit-tests, semgrep-sast, trivy-container-scan, dependency-check]
if: always()
```
`if: always()` matters. Without it, GitHub *skips* the gate when an upstream job fails. Depending on configuration, a skipped required check can count as passing. The gate checks every `needs.<job>.result == "success"` and exits `1` otherwise.

---

## Handling false positives

Every suppression should be **visible, justified and reviewable** in a PR.

| Tool | How to suppress | Example |
|------|-----------------|---------|
| Semgrep (line) | Inline comment with rule ID and reason | `cursor.execute(q)  # nosemgrep: python.lang.security.audit.formatted-sql-query -- q is a constant` |
| Semgrep (path) | `.semgrepignore` | `tests/` (dummy tokens in fixtures) |
| Trivy (CVE) | `.trivyignore` with an expiry | `CVE-2024-12345 exp:2026-12-31  # not reachable: we never call the vulnerable API` |
| pip-audit | `--ignore-vuln` | `pip-audit --ignore-vuln GHSA-xxxx-xxxx-xxxx` |

**Process**
1. The developer adds the suppression with a short justification.
2. CODEOWNERS sends changes to `.semgrepignore`, `.trivyignore` and workflow files to the security team for review.
3. Trivy ignores use `exp:` dates, so accepted risk is reviewed again automatically.
4. Review suppressions quarterly. Remove any whose justification is no longer true.

## Tuning severity thresholds

| Maturity | Semgrep | Trivy | Dependencies | Notes |
|----------|---------|-------|--------------|-------|
| **Starting out** (legacy code) | Report only | `CRITICAL` | Trivy fs `CRITICAL` | Build trust and fix the backlog first |
| **Default** (this repo) | `ERROR` | `HIGH,CRITICAL` + `ignore-unfixed` | pip-audit strict + Trivy `HIGH,CRITICAL` | Balanced for most teams |
| **High assurance** (fintech, health) | `WARNING,ERROR` | `MEDIUM,HIGH,CRITICAL` | Any CVE | Expect more triage work |

Where to change them:
- Semgrep: `--severity=ERROR` → add `--severity=WARNING` (the flag can repeat).
- Trivy: the `severity:` input on the gate step. Remove `ignore-unfixed` to also block on unfixed CVEs.
- New-code-only: on PRs, run `semgrep ci` with `SEMGREP_BASELINE_REF=main` so it only reports findings *introduced* by the PR. This is useful for adopting the gate on legacy code.

## Securing the pipeline itself (supply chain)

Security tools run with access to your code and CI secrets, so they are high-value targets. In **March 2026** the `aquasecurity/trivy-action` and `aquasecurity/setup-trivy` actions were hit by a tag-poisoning attack ([GHSA-69fq-xp46-6x23](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23)). Attackers force-pushed existing version tags to malicious commits that stole runner secrets. Any workflow using `@0.x.y` tags ran the malware.

This repository's mitigations:
- **Every third-party action is pinned to a full commit SHA**, with the human-readable version in a comment (e.g. `aquasecurity/trivy-action@57a97c7e… # v0.35.0`). A SHA cannot be moved by force-pushing a tag.
- **The Trivy binary and the Semgrep container are version-pinned** (`version: v0.76.1`, `semgrep/semgrep:1.182.1`) instead of `latest`.
- **Least-privilege `permissions:`**. The default is `contents: read`. `security-events: write` is granted only to jobs that upload SARIF.
- **No `curl | sh` installers.** Semgrep's own `gha-curl-pipe-shell` rule caught one in an early draft of `trivy-scan.yml`, and it was replaced with the official setup action.
- **Keep pins current.** Enable Dependabot for `github-actions` so SHA bumps arrive as reviewable PRs.

## Extending the pipeline
- **Secrets scanning:** add `gitleaks/gitleaks-action` or `trivy fs --scanners secret`.
- **IaC:** `trivy config .` for Terraform, Kubernetes and Dockerfile misconfigurations.
- **DAST:** an OWASP ZAP baseline scan against the container started with `docker compose up`.
- **SBOM and signing:** `trivy image --format cyclonedx` + `cosign sign` for supply-chain integrity.
