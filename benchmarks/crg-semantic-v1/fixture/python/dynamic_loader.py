import importlib


def load_plugin():
    return importlib.import_module("python.plugins.audit")
