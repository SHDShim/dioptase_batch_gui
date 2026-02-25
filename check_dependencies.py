#!/usr/bin/env python
"""
Dependency Checker for Dioptas Batch GUI
Verifies that all required packages are installed.
"""

import sys

def check_dependency(module_name, package_name=None, import_name=None):
    """Check if a module can be imported."""
    if package_name is None:
        package_name = module_name
    if import_name is None:
        import_name = module_name
        
    try:
        __import__(import_name)
        print(f"✓ {module_name} - OK")
        return True
    except ImportError:
        print(f"✗ {module_name} - NOT FOUND")
        print(f"  Install with: pip install {package_name}")
        return False

def main():
    """Check all dependencies."""
    print("=" * 60)
    print("Dioptas Batch GUI - Dependency Checker")
    print("=" * 60)
    print()
    
    all_ok = True
    
    # Core dependencies
    print("Core Dependencies:")
    all_ok &= check_dependency("dioptas")
    all_ok &= check_dependency("PyQt6")
    all_ok &= check_dependency("watchdog")
    all_ok &= check_dependency("numpy")
    all_ok &= check_dependency("h5py")
    print()
    
    # Dioptas dependencies
    print("Dioptas Dependencies:")
    all_ok &= check_dependency("pyFAI")
    all_ok &= check_dependency("scipy")
    all_ok &= check_dependency("pyqtgraph")
    print()
    
    # Optional but recommended
    print("Optional:")
    check_dependency("scikit-image", "scikit-image", "skimage")
    print()
    
    print("=" * 60)
    if all_ok:
        print("✓ All required dependencies are installed!")
        print()
        print("You can now run the GUI with:")
        print("  dbgui")
    else:
        print("✗ Some dependencies are missing.")
        print()
        print("To install Dioptas from source:")
        print('  cd "/Users/danshim/ASU Dropbox/Sang-Heon Shim/Python/Dioptas-2026-01-10"')
        print("  pip install -e .")
        print()
        print("To install other missing packages:")
        print("  pip install watchdog")
    print("=" * 60)
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
