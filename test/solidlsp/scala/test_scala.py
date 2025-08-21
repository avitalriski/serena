"""
Tests for Scala Language Server using Metals
"""

import os

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.ls_logger import LanguageServerLogger
from solidlsp.settings import SolidLSPSettings

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "repos", "scala")


@pytest.mark.scala
def test_scala_initialization():
    """Test that Scala/Metals language server initializes correctly"""
    config = LanguageServerConfig(code_language=Language.SCALA)
    logger = LanguageServerLogger()

    # Create language server instance
    ls = SolidLanguageServer.create(config, logger, REPO_ROOT, solidlsp_settings=SolidLSPSettings())

    try:
        assert ls is not None
        assert ls.language_id == "scala"
    finally:
        ls.cleanup()


@pytest.mark.scala
def test_scala_symbols():
    """Test document symbols for a Scala file"""
    config = LanguageServerConfig(code_language=Language.SCALA)
    logger = LanguageServerLogger()
    ls = SolidLanguageServer.create(config, logger, REPO_ROOT, solidlsp_settings=SolidLSPSettings())

    try:
        # Get symbols from Calculator.scala
        calc_file = os.path.join(REPO_ROOT, "src", "main", "scala", "com", "example", "Calculator.scala")
        symbols = ls.get_document_symbols(calc_file)

        assert len(symbols) > 0

        # Check that we can find the Calculator class
        class_symbols = [s for s in symbols if s.name == "Calculator"]
        assert len(class_symbols) > 0

        # Check that we can find methods (if available)
        # Metals may categorize methods differently
        all_symbol_names = {s.name for s in symbols}
        # At least verify we got some symbols from the file
        assert "Calculator" in all_symbol_names or "add" in all_symbol_names
    finally:
        ls.cleanup()
