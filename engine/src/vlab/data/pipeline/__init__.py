"""Build steps of the reproducible data pipeline (``scripts/build_data.py``).

These modules are only needed to *rebuild* ``data/processed``; the runtime
loaders in :mod:`vlab.data` do not import them. Some steps need the optional
``data`` dependency group (``osmium``, ``requests``).
"""
