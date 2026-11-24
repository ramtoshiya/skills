"""List the Python tests under a directory as units that can run in parallel, or run one unit.

A unit is one test method. A class that shares a fixture through setUpClass or tearDownClass is one unit, so
the fixture is built once for its tests as unittest would.

    unittest_units.py list <dir>            print the units as JSON
    unittest_units.py run <dir> <id>...     run the named tests with <dir> importable, as discover would
"""

import json
import sys
import unittest


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def shares_a_fixture(cls):
    return any(getattr(cls, name).__func__ is not getattr(unittest.TestCase, name).__func__
               for name in ("setUpClass", "tearDownClass"))


def units(start):
    loader = unittest.TestLoader()
    tests = list(flatten(loader.discover(start, pattern="test_*.py")))
    if loader.errors:
        sys.exit("\n".join(loader.errors))
    grouped = {}
    for test in tests:
        cls = type(test)
        name = f"{cls.__module__}.{cls.__qualname__}" if shares_a_fixture(cls) else test.id()
        grouped.setdefault(name, []).append(test.id())
    return [{"name": name, "ids": ids} for name, ids in grouped.items()]


def main():
    command, start, *ids = sys.argv[1:]
    if command == "list":
        print(json.dumps(units(start)))
        return
    sys.path.insert(0, start)
    unittest.main(module=None, argv=["unittest", *ids])


if __name__ == "__main__":
    main()
