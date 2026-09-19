import json
from pathlib import Path

from hypothesis import given, settings, strategies as st

from ai_workflow.provider_runner import CommandProviderSpec, _result_from_bytes
from ai_workflow.retrieval_contracts import RetrievalRequest


def _parse(raw: bytes):
    return _result_from_bytes(
        CommandProviderSpec("fuzz", ("provider",)),
        RetrievalRequest("query", Path("."), 8),
        "external:fuzz",
        None,
        raw,
        1.0,
        0,
    )


@settings(max_examples=250, deadline=None)
@given(st.binary(max_size=4096))
def test_arbitrary_provider_bytes_never_escape_typed_failure_boundary(raw):
    result = _parse(raw)
    assert result.provider == "fuzz"
    if not result.ok:
        assert result.items == ()
        assert result.error_kind in {"empty_output", "invalid_payload"}


@settings(max_examples=250, deadline=None)
@given(
    st.floats(
        allow_nan=True,
        allow_infinity=True,
        width=64,
    )
)
def test_score_domain_is_finite_normalized_or_rejected(score):
    raw = json.dumps(
        {"items": [{"text": "evidence", "score": score}]},
        allow_nan=True,
    ).encode("utf-8")
    result = _parse(raw)

    if 0.0 <= score <= 1.0:
        assert result.ok
        assert len(result.items) == 1
        assert 0.0 <= result.items[0].score <= 1.0
    else:
        assert not result.ok
        assert result.items == ()
        assert result.error_kind == "invalid_payload"


@settings(max_examples=200, deadline=None)
@given(
    st.recursive(
        st.none()
        | st.booleans()
        | st.integers(min_value=-(2**63), max_value=2**63 - 1)
        | st.floats(
            allow_nan=True,
            allow_infinity=True,
            width=64,
        )
        | st.text(max_size=128),
        lambda children: (
            st.lists(children, max_size=8)
            | st.dictionaries(
                st.text(min_size=1, max_size=24),
                children,
                max_size=8,
            )
        ),
        max_leaves=40,
    )
)
def test_metadata_fuzz_is_either_bounded_valid_data_or_typed_rejection(metadata):
    raw = json.dumps(
        {
            "items": [
                {
                    "text": "evidence",
                    "score": 0.5,
                    "metadata": metadata,
                }
            ]
        },
        allow_nan=True,
    ).encode("utf-8")
    result = _parse(raw)
    if result.ok:
        assert len(result.items) == 1
    else:
        assert result.items == ()
        assert result.error_kind == "invalid_payload"
