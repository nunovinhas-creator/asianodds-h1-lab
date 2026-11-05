"""Offline durable-store double shared by quota and CLI regression tests."""
import copy
from datetime import datetime, timezone
from h1lab.research_quota import Controller, append, validate


class Store:
    def __init__(self):
        self.state = {'schema_version': 1, 'events': []}
        self.version = 0
        self.records = []
        self.fail_read = self.fail_write = self.lose_ack = False
        self.before_cas = None

    def read(self):
        if self.fail_read:
            raise ValueError('STORE_READ_FAILED')
        return copy.deepcopy(self.state), str(self.version)

    def cas(self, old, new, sha):
        if self.before_cas:
            hook, self.before_cas = self.before_cas, None
            hook()
        if self.fail_write or sha != str(self.version):
            raise ValueError('CAS_CONFLICT')
        validate(new)
        assert new['events'][:len(old['events'])] == old['events']
        self.state = copy.deepcopy(new)
        self.version += 1
        if self.lose_ack:
            raise ValueError('LOST_ACK')

    def history(self, run):
        return copy.deepcopy(self.records)


def factory(env):
    store = Store()
    # Old CLI fixtures supply this diagnostic; turn it into REAL durable fake
    # reservations here rather than trusting the environment in production.
    now = datetime.now(timezone.utc)
    for i in range(int(env.get('RESEARCH_PRIOR_LLM_ATTEMPTS', '0'))):
        append(store.state, {'kind': 'reserve', 'id': 'run:old%s' % i, 'run_id': 'old%s' % i,
                             'at': now.isoformat(), 'reserved': 1000, 'model': 'test'})
    return Controller(store)
