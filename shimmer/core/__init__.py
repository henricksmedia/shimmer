"""shimmer.core — the engine.

Everything that changes or measures sound lives here, built once:

    audio/     reading and writing files, filters, meters
    analyze/   findings: what the song has (measures, never alters)
    repair/    one module per card that fixes something
    master/    loudness, tone and the limiter
    catalog    the rules the screens show (cards, loudness choices, formats)
    settings   one settings object, and migrate() for old saved settings
    render     render(source, settings, window=None): the one sound path
    export     the one way a file is written

The web layer (shimmer/api) talks to the engine only through this package.
Nothing here imports the web layer or the old engine (docs/ARCHITECTURE.md
§18.3, tests/api/test_api_contract.py).
"""
