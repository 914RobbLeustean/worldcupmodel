"""Market layer (Phase 4): manual lines, de-vig, edges, ledger, CLV.

Architecture rule: this package never computes model probabilities — the CLI
obtains them from wc26.models and passes plain floats in. Everything here is
odds math and bookkeeping (decimal-only internals, D005 de-vig, D006 ledger).
"""
