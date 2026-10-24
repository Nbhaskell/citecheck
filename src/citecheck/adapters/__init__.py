from .base import AdapterError, TargetAdapter
from .mock import MockAdapter
from .rag_project import RagProjectAdapter

# name -> class, for the CLI's --target
TARGETS = {"rag-project": RagProjectAdapter}

__all__ = ["AdapterError", "TargetAdapter", "MockAdapter", "RagProjectAdapter", "TARGETS"]
