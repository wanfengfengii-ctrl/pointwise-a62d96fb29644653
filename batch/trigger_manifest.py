from dataclasses import dataclass

from batch.identity import TriggerKey


class UnknownTrigger(LookupError):
    pass


@dataclass(frozen=True)
class TriggerManifest:
    batch_id: str
    _triggers: tuple[str, ...]

    def contains(self, trigger_id: str) -> bool:
        return trigger_id in self._triggers

    @property
    def ordered_triggers(self) -> tuple[str, ...]:
        return self._triggers

    def key_for(self, trigger_id: str) -> TriggerKey:
        if not self.contains(trigger_id):
            raise UnknownTrigger((self.batch_id, trigger_id))
        return TriggerKey(self.batch_id, trigger_id)
