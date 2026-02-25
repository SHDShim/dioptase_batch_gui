#!/usr/bin/env python
"""Compatibility launcher for batch processor module."""

import runpy

if __name__ == "__main__":
    runpy.run_module("dioptas_batch_gui.batch_processor", run_name="__main__")

