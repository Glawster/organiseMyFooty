import sys
from pathlib import Path

from organiseMyProjects.logUtils import getLogger, setApplication

sys.path.insert(0, str(Path(__file__).parent / "src"))

thisApplication = Path(__file__).parent.name
setApplication(thisApplication)

logger = getLogger(includeConsole=False)

from exportAttendance import main as runApp  # noqa: E402


def main():
    global logger

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    dryRun = not args.confirm

    logger = getLogger(includeConsole=True, dryRun=dryRun)

    _name = Path(__file__).stem
    logger.doing(_name)
    runApp()
    logger.done(_name)


if __name__ == "__main__":
    main()
