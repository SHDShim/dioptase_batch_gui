#!/usr/bin/env python
"""Compatibility launcher for file watcher module."""

import runpy

if __name__ == "__main__":
    runpy.run_module("dioptas_batch_gui.file_watcher", run_name="__main__")

