"""Rail Inspection Console backend application package.

Layout (see ``backend/app/``):

* ``settings``  - environment driven configuration, the single source of truth
* ``db``        - stdlib ``sqlite3`` access + repository (no ORM)
* ``parser``    - configurable line parser driven by ``config/parser.yaml``
* ``services``  - ``SerialService`` (all serial logic) + realtime WS bridge
* ``api``       - thin HTTP/WS routes: validate, delegate, return models
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
