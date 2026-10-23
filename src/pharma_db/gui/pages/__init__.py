"""GUI pages for the Pharma DBMS."""
from .compositions import CompositionsPage
from .console import SqlConsolePage
from .dashboard import DashboardPage
from .manufacturers import ManufacturersPage
from .medicines import MedicinesPage
from .schema import SchemaPage
from .tools import ToolsPage

__all__ = [
    "CompositionsPage",
    "DashboardPage",
    "ManufacturersPage",
    "MedicinesPage",
    "SchemaPage",
    "SqlConsolePage",
    "ToolsPage",
]
