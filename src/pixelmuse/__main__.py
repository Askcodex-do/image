"""Allow ``python -m pixelmuse ...`` from a checkout without installing."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
