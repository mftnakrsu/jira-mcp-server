"""Put the vendor server root on sys.path so tests can `import tools` / `import models`
without installing the project as a package."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
