# Example: A PR Blocked by the Security Gate

> This is an **illustrative** run that shows what the gate reports when insecure code is submitted. The CVE and rule IDs are real. The run numbers, timings and line numbers are representative.

## The pull request

**PR #7: `feat: add advanced item search`** (branch `feature/advanced-search` → `main`)

The PR makes two changes:

```diff
 # app.py
+    @app.get("/items/search")
+    def advanced_search():
+        term = request.args.get("term", "")
+        sql = f"SELECT id, name, quantity FROM items WHERE name = '{term}'"
+        rows = get_db().execute(sql).fetchall()
+        return jsonify([dict(r) for r in rows])
```
```diff
 # Dockerfile
-FROM python:3.12-slim
+FROM python:3.9-slim-bullseye
```

## Checks summary (PR page)

```
Some checks were not successful
3 failing, 2 successful checks

  ✅ Security Gate / Unit tests                       Successful in 21s
  ❌ Security Gate / Semgrep SAST                     Failing after 38s
  ❌ Security Gate / Trivy container scan             Failing after 1m 52s
  ✅ Security Gate / Dependency audit (pip-audit)     Successful in 29s
  ❌ Security Gate / Security Gate                    Failing after 3s   — Required

Merging is blocked
The base branch requires all required status checks to pass.
```

## Semgrep SAST: job log

```text
$ semgrep scan --config=auto --severity=ERROR --error

┌──────────────────┐
│ 2 Code Findings  │
└──────────────────┘

    app.py
   ❯❯❱ python.flask.security.injection.tainted-sql-string.tainted-sql-string
          Detected user input used to manually construct a SQL string. This is
          usually bad practice because manual construction could accidentally
          result in a SQL injection. An attacker could use a SQL injection to
          steal or modify contents of the database. Instead, use a
          parameterized query.
          Details: https://sg.run/JxZW

           97┆ sql = f"SELECT id, name, quantity FROM items WHERE name = '{term}'"

   ❯❯❱ python.lang.security.audit.formatted-sql-query.formatted-sql-query
          Detected possible formatted SQL query. Use parameterized queries
          instead.
          Details: https://sg.run/EkWw

           98┆ rows = get_db().execute(sql).fetchall()

┌──────────────┐
│ Scan Summary │
└──────────────┘
Ran 312 rules on 1 file: 2 findings (2 blocking).
Error: Process completed with exit code 1.
```

The same findings appear as annotations on the PR's **Files changed** tab and under **Security → Code scanning** (from the SARIF upload).

## Trivy container scan: job log

```text
$ trivy image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed inventory-api:3f9c2e1

inventory-api:3f9c2e1 (debian 11.9)
===================================
Total: 4 (HIGH: 3, CRITICAL: 1)

┌──────────────┬────────────────┬──────────┬─────────┬───────────────────┬───────────────┬──────────────────────────────────────────────┐
│   Library    │ Vulnerability  │ Severity │ Status  │ Installed Version │ Fixed Version │                    Title                     │
├──────────────┼────────────────┼──────────┼─────────┼───────────────────┼───────────────┼──────────────────────────────────────────────┤
│ libssl1.1    │ CVE-2024-5535  │ CRITICAL │ fixed   │ 1.1.1w-0+deb11u1  │ 1.1.1w-0+deb11u2 │ openssl: SSL_select_next_proto buffer overread │
│ zlib1g       │ CVE-2023-45853 │ HIGH     │ fixed   │ 1:1.2.11.dfsg-2   │ 1:1.2.11.dfsg-2+deb11u2 │ zlib: integer overflow in MiniZip     │
│ libexpat1    │ CVE-2024-45491 │ HIGH     │ fixed   │ 2.2.10-2+deb11u5  │ 2.2.10-2+deb11u6 │ libexpat: integer overflow in dtdCopy   │
│ libexpat1    │ CVE-2024-45492 │ HIGH     │ fixed   │ 2.2.10-2+deb11u5  │ 2.2.10-2+deb11u6 │ libexpat: integer overflow in nextScaffoldPart │
└──────────────┴────────────────┴──────────┴─────────┴───────────────────┴───────────────┴──────────────────────────────────────────────┘

Python (python-pkg)
===================
Total: 0 (HIGH: 0, CRITICAL: 0)

Error: Process completed with exit code 1.
```

## Security Gate: job summary

| Job | Result |
|-----|--------|
| unit-tests | success |
| semgrep-sast | **failure** |
| trivy-container-scan | **failure** |
| dependency-check | success |

```text
Error: Security gate FAILED - 2 job(s) did not pass. Merge blocked.
```

**❌ Merge blocked**

Note that the unit tests **passed**. The new endpoint worked for normal input. Functional tests alone would have let a SQL injection reach `main`.

---

## The fix (second commit on the PR)

```diff
-        sql = f"SELECT id, name, quantity FROM items WHERE name = '{term}'"
-        rows = get_db().execute(sql).fetchall()
+        rows = get_db().execute(
+            "SELECT id, name, quantity FROM items WHERE name = ?", (term[:100],)
+        ).fetchall()
```
```diff
-FROM python:3.9-slim-bullseye
+FROM python:3.12-slim
```

## Re-run result

```
All checks have passed
5 successful checks

  ✅ Security Gate / Unit tests                       Successful in 20s
  ✅ Security Gate / Semgrep SAST                     Successful in 35s
  ✅ Security Gate / Trivy container scan             Successful in 1m 41s
  ✅ Security Gate / Dependency audit (pip-audit)     Successful in 27s
  ✅ Security Gate / Security Gate                    Successful in 2s   — Required

This branch has no conflicts with the base branch
Merging can be performed automatically.
```

## Takeaways
- The gate caught a **critical injection flaw** and **4 fixable image CVEs** before they reached `main`.
- The developer got file and line annotations and a fix link, and needed no security-team involvement.
- Fix time was under 10 minutes. Fixing the same issue after release would mean incident response.
