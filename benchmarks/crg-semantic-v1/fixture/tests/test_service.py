from python.service import run_service


def test_run_service() -> None:
    assert run_service(2) == 4
