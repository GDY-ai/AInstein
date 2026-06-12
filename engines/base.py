"""Research engine base classes."""
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ResearchContext:
    """Context passed to a research engine for a single session."""
    project_id: int
    mission: str
    domain: str
    topic: str
    config: dict = field(default_factory=dict)
    datasets_summary: str = ''
    recent_findings: list = field(default_factory=list)
    directives: list = field(default_factory=list)
    session_id: Optional[int] = None
    queue_id: Optional[int] = None


@dataclass
class SessionResult:
    """Result returned by a research engine after a session."""
    status: str = 'completed'
    hypotheses: str = ''
    verification: str = ''
    findings: list = field(default_factory=list)
    next_directions: list = field(default_factory=list)
    data_summary: str = ''
    duration_seconds: int = 0


class ResearchEngine(ABC):
    """Abstract base class for research engines."""

    @property
    @abstractmethod
    def engine_type(self) -> str:
        pass

    @abstractmethod
    def run(self, ctx: ResearchContext) -> SessionResult:
        pass
