"""Reusable analysis library + provenance.

Importable from experiment notebooks. The governing rule: **if it produces an
artifact, it gets committed** — the code that makes a derived file lives in git
(this library + the data repo's ``notebooks/``), and SDGL stores only a *graph
link* from the file to that recipe. Nothing executable is ever written into the
graph.
"""

from eln.analysis.provenance import stamp, verify_provenance

__all__ = ["stamp", "verify_provenance"]
