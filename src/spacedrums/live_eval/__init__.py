"""Phase 18 evaluation package: the confirmatory analysis layer and the live-experiment tooling.

The Phase 09 harness (``spacedrums.eval``) is frozen. This package builds on it without changing
any of its rules. Modules:

* ``prereg``: pre-registration hash record, frozen-inputs locks, the execute-once ledger.
* ``stats`` / ``hypotheses``: participant bootstrap and the declared decision rules.
* ``offline``: participant / pooled regrouping, strata, sensitivity S1, trajectory error.
* ``causality``: TEST-CAUSAL-1 on the exact evaluated arm versions.
* ``counterbalance`` / ``protocol`` / ``metadata``: Williams arm orders, the live protocol with its
  arm switcher, and ``LiveSessionMetadata``.
* ``sync`` / ``acoustic`` / ``video`` / ``software``: external-recording alignment and the M1 (pad
  + microphone), M2 (high-frame-rate video) and M3 (software stamps) timing methods.

Layering (``.importlinter``): a sibling of ``spacedrums.app`` in the top layer. It may import the
evaluation, data and pipeline packages, and never the application. The live runner script composes
both.
"""
