"""Electronic Lab Notebook — filesystem-centric ELN with a Scientific Data Graph Layer.

This package is being ported from the original in-place project in the order laid
out in ``docs/ROADMAP.md``. Subpackages are scaffolding until their step lands:

- ``eln.db``         schema, migrations, dump_db / rebuild_db   (Roadmap step 2)
- ``eln.sdgl``       scan engine + naming grammar               (Roadmap step 4)
- ``eln.generators`` catalog / reports / home / protocol pages  (Roadmap step 5)
- ``eln.server``     Flask API, overlay/admin, publish flow     (Roadmap step 6)
- ``eln.plugins``    plugin API + extension points              (Roadmap step 8)
"""

__version__ = "0.0.1"
