"""Keep lightweight import stubs from contaminating other tests."""

import sys

import pytest


@pytest.fixture(autouse=True)
def restore_import_stubs():
    prefixes = ("homeassistant", "paho", "custom_components", "voluptuous")

    def relevant(name):
        return name.split(".")[0] in prefixes

    original = {name: module for name, module in sys.modules.items() if relevant(name)}
    yield
    for name in list(sys.modules):
        if relevant(name) and name not in original:
            sys.modules.pop(name)
    sys.modules.update(original)
