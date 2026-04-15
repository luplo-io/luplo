"""JSON Schema files for the system-seeded item types.

Loaded at migration time (0003) and at app startup. Adding a new file
here does not by itself register a type — the migration must be updated
to seed it, or a user must INSERT a row into ``item_types`` directly.
"""
