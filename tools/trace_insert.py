"""Run the insert perftest with renderer stats enabled; print the report."""
from time import time

from ptedit.controller import Controller
from ptedit.screen import Screen
from ptedit.stats import stats


def main(scenario: str = "insert", duration: float = 1.0) -> None:
    ctrl = Controller("tests/alice1flow.asc", Screen(24, 80))
    stats.enabled = True
    stats.reset()
    print(ctrl.perftest(scenario, max_time=duration))
    print()
    print(stats.report())


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "insert")
