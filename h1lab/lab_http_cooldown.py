"""Durable, evidence-only 429 deadlines. Reads never renew a deadline."""
import copy
import re
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from .lab_results import utc

DEFAULT_WAIT = timedelta(hours=4)


def validate(state):
    if not isinstance(state, dict) or len(state)>16:
        raise ValueError('Invalid HTTP cooldown journal')
    for provider,row in state.items():
        if (not isinstance(provider,str) or not re.fullmatch(r'[a-z_]{1,32}',provider)
                or not isinstance(row,dict) or row.get('http_status')!=429
                or utc(row.get('attempted_at_utc')) is None
                or utc(row.get('blocked_until_utc')) is None
                or utc(row['blocked_until_utc'])<utc(row['attempted_at_utc'])):
            raise ValueError('Invalid HTTP cooldown record')
    return copy.deepcopy(state)


def active(state,provider,now):
    row=validate(state).get(provider)
    if row and utc(row['attempted_at_utc'])>now+timedelta(minutes=2):
        raise ValueError('HTTP cooldown record is in the future')
    return bool(row and now<utc(row['blocked_until_utc']))


def record_429(state,provider,now,retry_after=None):
    out=validate(state)
    if active(out,provider,now):
        raise ValueError('HTTP request must not execute during cooldown')
    until=now+DEFAULT_WAIT;basis='CONSERVATIVE_4H_WITHOUT_VALID_RETRY_AFTER'
    text=str(retry_after or '').strip()
    if re.fullmatch(r'\d{1,8}',text):
        until=now+timedelta(seconds=int(text));basis='HTTP_RETRY_AFTER_SECONDS'
    elif text:
        try:
            value=parsedate_to_datetime(text)
            if value.tzinfo is not None and value>=now:
                until=value.astimezone(timezone.utc);basis='HTTP_RETRY_AFTER_DATE'
        except (ValueError,TypeError,OverflowError):
            pass
    out[provider]={'http_status':429,'attempted_at_utc':now.isoformat(timespec='seconds'),
        'blocked_until_utc':until.isoformat(timespec='seconds'),'basis':basis}
    return validate(out)
