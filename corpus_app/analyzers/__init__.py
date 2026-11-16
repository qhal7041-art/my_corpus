"""Extension boundary for real analyzer adapters (not implemented in stage 1).

UI must never claim an engine is usable solely because it appears in this list.
Future adapters must probe their runtime and expose only supported options.
"""
from dataclasses import dataclass
from typing import Protocol, Iterable


@dataclass(frozen=True)
class Morpheme:
    form: str
    pos: str


@dataclass(frozen=True)
class AnalyzerStatus:
    name: str
    available: bool
    instructions: str


class Analyzer(Protocol):
    def status(self) -> AnalyzerStatus: ...
    def supported_options(self) -> dict: ...
    def analyze(self, text: str) -> Iterable[Morpheme]: ...


PLANNED_ENGINES = ("Kiwi", "바른", "UTagger")
