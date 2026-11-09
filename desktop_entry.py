
"""Entry point shared by the windowed application and its console worker."""
import sys
from pathlib import Path


if __name__ == "__main__":
    if Path(sys.executable).stem.lower() == "mediawhisper":
        from app.whisper_worker import main
    else:
        from app.desktop import main
    main()
