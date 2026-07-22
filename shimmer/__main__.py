"""Entry point so `python -m shimmer ...` runs the CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
