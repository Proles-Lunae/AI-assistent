import pytest


@pytest.fixture(autouse=True)
def forget_location():
    from assistant import weather

    weather._location_cache.clear()
    yield
    weather._location_cache.clear()
