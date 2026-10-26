from .base import AdapterError, TargetAdapter
from .citewise import CitewiseAdapter
from .mock import MockAdapter
from .rag_project import RagProjectAdapter

# name -> class, for the CLI's --target
TARGETS = {"rag-project": RagProjectAdapter, "citewise": CitewiseAdapter}

__all__ = ["AdapterError", "TargetAdapter", "MockAdapter", "RagProjectAdapter", "CitewiseAdapter", "TARGETS"]
