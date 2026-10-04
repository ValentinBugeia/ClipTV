import os

import pytest


@pytest.fixture(autouse=True)
def _restore_environ():
    """Les clés saisies dans l'interface sont appliquées à os.environ : on isole les tests."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
