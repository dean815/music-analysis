"""Web front end for the lead sheet.

A package rather than a bare directory so `from gui import serialize` resolves
the same way whether the server was started as `python3 gui/app.py` or as
`uvicorn gui.app:app`. Deliberately imports nothing — importing this must not
require fastapi.
"""
