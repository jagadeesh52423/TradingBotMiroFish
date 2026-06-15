import sys
from pathlib import Path

# Make market-swarm-lab the import root so `from services.nubra_client.X import Y` works.
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
