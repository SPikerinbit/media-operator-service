"""Pipeline stages loaded into app.main.

These modules are not imported as a normal package API. app.main executes
them in its own namespace so DATA_DIR, credentials, and stage functions stay
the names the desktop shell and the tests already patch.
"""
