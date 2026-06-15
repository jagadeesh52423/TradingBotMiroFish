from services.nubra_client.broker_types import OrderStatus
from services.nubra_client.order_state_tracker import OrderStateTracker


def test_record_and_has_open(tmp_path):
    t = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    t.record(client_tag="msl-1", broker_order_id="O1", symbol="SBIN",
             status=OrderStatus.SENT)
    assert t.has_open("msl-1") is True


def test_terminal_status_clears_open(tmp_path):
    t = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    t.record(client_tag="msl-1", broker_order_id="O1", symbol="SBIN",
             status=OrderStatus.SENT)
    t.mark("O1", OrderStatus.FILLED)
    assert t.has_open("msl-1") is False


def test_persists_across_instances(tmp_path):
    t = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    t.record(client_tag="msl-9", broker_order_id="O9", symbol="SBIN",
             status=OrderStatus.OPEN)
    t2 = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    assert t2.has_open("msl-9") is True


def test_upsert_from_ws_event(tmp_path):
    t = OrderStateTracker(env="UAT", base_dir=str(tmp_path))
    t.record(client_tag="msl-1", broker_order_id="O1", symbol="SBIN",
             status=OrderStatus.SENT)
    t.upsert_from_event({"order_id": "O1", "order_status": "ORDER_STATUS_FILLED"})
    assert t.has_open("msl-1") is False
