"""PyInstaller entry point; package-relative imports stay inside the package."""
from vehicle_installer.gui import main
if __name__ == '__main__':
    main()
