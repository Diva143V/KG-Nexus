import contracts
import core
import infrastructure
import plugins
import policies
import sdk


def test_core_imports() -> None:
    assert core.__version__


def test_sdk_imports() -> None:
    assert sdk.__name__ == "sdk"


def test_contracts_imports() -> None:
    assert contracts.__name__ == "contracts"


def test_policies_imports() -> None:
    assert policies.__name__ == "policies"


def test_plugins_imports() -> None:
    assert plugins.__name__ == "plugins"


def test_infrastructure_imports() -> None:
    assert infrastructure.__name__ == "infrastructure"
