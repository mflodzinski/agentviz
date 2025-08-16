import json
import logging

from agentviz.observability import LOGGER_NAME, emit_event


def test_emit_event_writes_sorted_json_payload(caplog) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    emit_event("query_execution.completed", run_id="run-1", row_count=3)

    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].message)
    assert payload == {
        "event": "query_execution.completed",
        "row_count": 3,
        "run_id": "run-1",
    }
