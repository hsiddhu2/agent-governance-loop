import sys
from pathlib import Path

# Scripts and stacks are run as plain modules, not as a package. Import them the same way.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "infra"))
