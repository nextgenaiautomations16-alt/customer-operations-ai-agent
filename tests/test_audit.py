"""Audit hash chain: pure-function tests and tamper detection on a real SQLite file."""

from app.audit.service import append_event, events_for_case, verify_audit_log
from app.core.audit_chain import GENESIS_HASH, compute_event_hash, verify_chain
from app.core.enums import ActorType
from app.db.database import write_tx


def add(conn, n, case_id="case_a"):
    with write_tx(conn):
        return append_event(
            conn,
            case_id=case_id,
            event_type=f"test.event{n}",
            actor_type=ActorType.SYSTEM,
            outcome="success",
            correlation_id="corr-000001",
            details={"n": n},
        )


def seeded(db, count=5):
    conn = db.connect()
    for n in range(count):
        add(conn, n)
    return conn


def test_empty_log_is_valid(db):
    with db.session() as conn:
        result = verify_audit_log(conn)
    assert result.valid and result.events_checked == 0 and result.head_hash == GENESIS_HASH


def test_events_are_chained(db):
    conn = db.connect()
    first, second = add(conn, 1), add(conn, 2)
    assert first["prev_hash"] == GENESIS_HASH
    assert second["prev_hash"] == first["event_hash"]
    assert second["event_hash"] == compute_event_hash(second)


def test_untouched_log_verifies(db):
    conn = seeded(db)
    result = verify_audit_log(conn)
    assert result.valid and result.events_checked == 5


def test_modifying_an_event_is_detected(db):
    conn = seeded(db)
    conn.execute("UPDATE audit_events SET outcome = 'failure' WHERE seq = 3")
    result = verify_audit_log(conn)
    assert not result.valid and result.first_invalid_seq == 3
    assert "modified" in result.reason


def test_modifying_details_is_detected(db):
    conn = seeded(db)
    conn.execute("""UPDATE audit_events SET details = '{"n":99}' WHERE seq = 2""")
    assert verify_audit_log(conn).first_invalid_seq == 2


def test_deleting_a_middle_event_is_detected(db):
    conn = seeded(db)
    conn.execute("DELETE FROM audit_events WHERE seq = 3")
    result = verify_audit_log(conn)
    assert not result.valid and result.first_invalid_seq == 4
    assert "removed" in result.reason


def test_deleting_the_first_event_is_detected(db):
    conn = seeded(db)
    conn.execute("DELETE FROM audit_events WHERE seq = 1")
    assert not verify_audit_log(conn).valid


def test_known_limit_truncating_the_tail_is_not_detected_by_the_chain_alone(db):
    """Documented limitation: keep head_hash outside the database to catch this."""
    conn = seeded(db)
    head_before = verify_audit_log(conn).head_hash
    conn.execute("DELETE FROM audit_events WHERE seq = 5")
    after = verify_audit_log(conn)
    assert after.valid  # the chain itself still looks fine...
    assert after.head_hash != head_before  # ...but an externally stored head hash would differ


def test_events_for_case_filters_and_parses_details(db):
    conn = seeded(db, 2)
    add(conn, 9, case_id="case_b")
    events = events_for_case(conn, "case_a")
    assert [e["details"]["n"] for e in events] == [0, 1]


def test_verify_chain_works_on_plain_dicts():
    assert verify_chain([]).valid
    bad = {"seq": 1, "prev_hash": "x" * 64, "event_hash": "y" * 64}
    assert not verify_chain([bad]).valid
