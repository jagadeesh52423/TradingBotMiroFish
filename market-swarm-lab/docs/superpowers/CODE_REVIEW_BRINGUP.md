# CODE_REVIEW — Nubra SDK Wiring (Task #2)

**Reviewer:** reviewer-bringup  
**Branch reviewed:** nubra-bringup  
**Commit range:** Task #2 wiring commits (pre-C2 through is_blocking/funds/positions)

---

## Summary

Logic verified correct across units/paise boundary, positions, funds, `is_blocking`, and single-source whitelist. The wiring is sound. Issues below are cleanliness/safety items only.

**Verdict: APPROVED with required fixes (C2–C4) and one optional improvement (N1).**

---

## C1 — auth_data.db gitignore ✅ ALREADY FIXED

`auth_data.db` and `auth_data.db.*` were already added to `.gitignore` in commit `c2d2adf` before this review.  
No action needed.

---

## C2 — Delete dead NubraSession ✅ FIXED (commit c611c0e)

`nubra_session.py` and `tests/nubra/test_nubra_session.py` were dead code superseded by the SDK's own shelve session.

**Action taken:** Both files deleted; references removed.

---

## C3 — Drop misleading `session_token` param ✅ FIXED (commits 868e3d3)

`NubraClient.from_session` accepted a `session_token` arg that was always ignored (SDK reads credentials from `.env` + shelve). The param was misleading and a maintenance hazard.

**Action taken:**
- Removed `session_token` from `NubraClient.from_session(cls, config)` signature
- Removed `session_token` param from `build_equity_stack` and `_nubra_uat_components`
- Updated callers: `equity_assembly.py` and `scripts/nubra_uat_smoke.py`

---

## C4 — No fabricated capital on live path ✅ FIXED (commit 868e3d3)

`_account_from_funds` on the `nubra_uat` path returned `Decimal("100000")` when `net_margin_available <= 0`, which could cause the qty sizer to place orders with fabricated capital against a live broker.

**Action taken:**  
On live path, zero/negative margin now logs a `WARNING` and returns `Decimal("0")`.  
Result: translator computes `qty = 0` → `SignalToEquityOrder.translate()` returns `(None, reason)` → no order submitted.

```python
# equity_assembly.py — _account_from_funds
if paise <= 0:
    _log.warning(
        "net_margin_available is %d paise on live path — sizing will produce qty 0", paise
    )
    return Decimal("0")
```

---

## N1 — client_factory seam for testability ✅ DONE (commit 868e3d3)

`_nubra_uat_components` called `NubraClient.from_session` directly, making it impossible to unit-test without a live SDK.

**Action taken:**  
Added `client_factory: Callable | None = None` kwarg to `build_equity_stack` and `_nubra_uat_components`.  
Default: `NubraClient.from_session`. Tests inject `_FakeClient` via `client_factory=lambda cfg: _FakeClient(cfg)`.

Two tests added in `tests/nubra/test_equity_assembly.py`:
- `test_nubra_uat_uses_injected_client_factory` — verifies nubra_uat assembles without live SDK
- `test_nubra_uat_c4_zero_margin_yields_zero_account` — verifies C4 behaviour via fake client

---

## Test suite

All 112 tests pass after fixes:

```
python3.11 -m pytest tests/nubra/ -q
112 passed in 0.12s
```
