import pytest

from everify.materials import load_material_library


@pytest.fixture(scope="session")
def library():
    return load_material_library()


def by_id(run):
    return {r.check_id: r for r in run.results}
