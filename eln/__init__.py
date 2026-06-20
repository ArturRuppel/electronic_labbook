"""Electronic Lab Notebook — filesystem-centric ELN with a Scientific Data Graph Layer.

Subpackages:

- ``eln.db``         schema, migrations, dump_db / rebuild_db
- ``eln.sdgl``       scan engine + naming grammar
- ``eln.generators`` catalog / reports / home / protocol pages
- ``eln.server``     Flask API, overlay/admin, publish flow
- ``eln.plugins``    plugin API + extension points
"""

__version__ = "0.0.1"
