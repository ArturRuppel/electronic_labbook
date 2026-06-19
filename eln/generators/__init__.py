"""Static page generators (Roadmap step 5, includes Plan F).

Each generator reads from a data-repo *root* (holding ``experiments.db``, the
optional ``sdgl.db`` build artifact, ``reports/`` and ``presentations/``) and
writes a static HTML page into ``root/catalog`` (or an explicit ``catalog_out``).

Regeneration is byte-identical for unchanged inputs: no timestamp churn (static
footers; the home page's "Last updated" is date-only). Experiment start dates are
always derived from earliest raw-file mtimes via SDGL, never stored in the DB.
"""

from eln.generators.catalog import generate_catalog
from eln.generators.home import generate_home
from eln.generators.presentations import generate_presentations
from eln.generators.protocols import generate_protocol_catalog
from eln.generators.reports import generate_reports

__all__ = [
    "generate_catalog",
    "generate_home",
    "generate_presentations",
    "generate_protocol_catalog",
    "generate_reports",
    "generate_all",
]


def generate_all(root, catalog_out=None):
    """Run every generator against the data-repo *root*.

    Returns a dict mapping each page name to the path it was written to.
    """
    return {
        "experiments": generate_catalog(root, catalog_out),
        "protocols": generate_protocol_catalog(root, catalog_out),
        "reports": generate_reports(root, catalog_out),
        "presentations": generate_presentations(root, catalog_out),
        "home": generate_home(root, catalog_out),
    }
