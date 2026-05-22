from hypothesis import given, settings, strategies as st

from openopps.examples import build_example_dataset
from openopps.models import ProviderSupport


def test_build_example_dataset_is_deterministic_for_stable_fields():
    first = build_example_dataset(seed=42, board_count=3, jobs_per_board=2)
    second = build_example_dataset(seed=42, board_count=3, jobs_per_board=2)

    assert first.as_dict() == second.as_dict()


def test_build_example_dataset_creates_coherent_records():
    dataset = build_example_dataset(seed=7, board_count=4, jobs_per_board=2)
    board_keys = {board.key for board in dataset.boards}
    route_board_keys = {route.board_key for route in dataset.routes}
    job_board_keys = {job.board_key for job in dataset.jobs}

    assert len(dataset.sources) == 1
    assert len(dataset.boards) == 4
    assert route_board_keys == board_keys
    assert job_board_keys <= board_keys
    assert all(board.raw_payload for board in dataset.boards)
    assert all(route.raw_payload for route in dataset.routes)
    assert all(job.raw_listing for job in dataset.jobs)
    assert any(
        route.support_level == ProviderSupport.DETECT for route in dataset.routes
    )
    assert any(route.support_level == ProviderSupport.JOBS for route in dataset.routes)


def test_example_dataset_serializes_to_docs_friendly_dict():
    dataset = build_example_dataset(seed=11, board_count=2, jobs_per_board=1)
    data = dataset.as_dict()

    assert sorted(data) == [
        "boards",
        "cacheRecords",
        "jobs",
        "plugins",
        "routes",
        "sources",
    ]
    assert data["sources"][0]["key"] == "example"
    assert data["boards"][0]["source_key"] == "example"
    assert data["cacheRecords"][0]["namespace"] == "example-source"
    assert data["plugins"][0]["name"] == "example-openopps-plugin"


@settings(max_examples=15)
@given(seed=st.integers(min_value=1, max_value=10_000))
def test_example_dataset_ids_are_unique(seed: int):
    dataset = build_example_dataset(seed=seed, board_count=5, jobs_per_board=3)

    assert len({board.key for board in dataset.boards}) == len(dataset.boards)
    assert len({route.id for route in dataset.routes}) == len(dataset.routes)
    assert len({job.id for job in dataset.jobs}) == len(dataset.jobs)
