"""Add navigation indexes to an existing book without reimporting it.

Run from the repository root: python -m gerby.tools.indexes
"""

import argparse
from pathlib import Path

from gerby.configuration import DATABASE
from gerby.database import Tag, db


def ensure_indexes():
    with db.atomic():
        Tag._schema.create_indexes(safe=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=DATABASE)
    args = parser.parse_args()
    if not Path(args.database).is_file():
        parser.error("book database does not exist: " + args.database)
    db.init(args.database)
    try:
        ensure_indexes()
        print("Navigation indexes ready in " + args.database)
    finally:
        db.close()


if __name__ == "__main__":
    main()
