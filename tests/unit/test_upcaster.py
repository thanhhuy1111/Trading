from typing import Any, Dict

from packages.events.registry import EventUpcaster


class SampleV1ToV2Upcaster(EventUpcaster):
    @property
    def event_type(self) -> str:
        return "sample.event"

    @property
    def source_version(self) -> int:
        return 1

    @property
    def target_version(self) -> int:
        return 2

    def upcast(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        upcasted = dict(payload)
        upcasted["upcasted_v2_field"] = True
        return upcasted


def test_upcaster_v1_to_v2_transformation():
    upcaster = SampleV1ToV2Upcaster()
    assert upcaster.event_type == "sample.event"
    assert upcaster.source_version == 1
    assert upcaster.target_version == 2

    v1_payload = {"name": "test_payload", "value": 100}
    v2_payload = upcaster.upcast(v1_payload)

    assert v2_payload["name"] == "test_payload"
    assert v2_payload["value"] == 100
    assert v2_payload["upcasted_v2_field"] is True
