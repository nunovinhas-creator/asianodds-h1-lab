"""Synthetic, fully offline fixtures for the autonomous research tests (no real data)."""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from h1lab.research_dataset import VARIABLES, dataset_digest

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def gate(science='SCIENTIFICALLY_BLOCKED', **cfg):
    config = {'schema_version': 1, 'exploration_enabled': True, 'offline_cycle_enabled': True,
              'llm_live_enabled': False, 'max_experiments_per_cycle': 40,
              'max_llm_plans_per_call': 3, 'max_llm_calls_per_cycle': 1}
    config.update(cfg)
    return {'gate': 'EXPLORATION_GATE', 'state': 'EXPLORATION_ALLOWED', 'config': config,
            'allowed_operations': ['competition_context', 'ft_outcomes', 'odds_trajectories',
                                   'scientific_context'],
            'blocked_operations': [], 'problems': [], 'source_sha256': {'synthetic': '0' * 64},
            'scientific_validation_gate': {'gate': 'SCIENTIFIC_VALIDATION_GATE', 'state': science,
                                           'promotion_allowed': False,
                                           'details': {'gates': {'7_days': {'status': 'BELOW_99_PERCENT',
                                                                            'ratio': 0.97}}}},
            'limitations': ['7_days source coverage BELOW_99_PERCENT (ratio=0.97)']}


def rows(n=600, *, days=20, effect=0.0, seed=7, ft_share=0.8, flag_share=0.3):
    """Synthetic matches. ``effect`` shifts P(Over) for matches with lambda_net >= 0.2."""
    rng = random.Random(seed)
    out = []
    start = datetime(2026, 10, 10, tzinfo=timezone.utc)
    for i in range(n):
        ko = start + timedelta(days=i % days, hours=12 + (i % 7))
        dec = ko - timedelta(minutes=30 + (i % 300))
        v = {k: None for k in VARIABLES}
        flagged = rng.random() < flag_share
        lam_first = 2.2 + rng.random()
        lam_net = (0.2 + rng.random() * 0.3) if flagged else (rng.random() * 0.15 - 0.1)
        v.update(n_messages=1 + i % 4, n_episodes=1 + i % 3, lead_first_min=60 + (i * 37) % 2000,
                 lead_last_min=30.0, span_min=float((i * 11) % 500), max_gap_min=float((i * 13) % 300),
                 kickoff_hour_utc=ko.hour, total_msgs=1 + i % 4, total_line_first=2.5,
                 total_line_last=2.5 + (0.25 if flagged else 0), total_line_net=0.25 if flagged else 0.0,
                 total_line_ups=1 if flagged else 0, total_line_downs=0,
                 lambda_first=round(lam_first, 4), lambda_last=round(lam_first + lam_net, 4),
                 lambda_net=round(lam_net, 4), lambda_abs_path=abs(round(lam_net, 4)), lambda_sd=0.05,
                 lambda_moves_up=1 if flagged else 0, lambda_moves_down=0, lambda_reversals=i % 2,
                 lambda_max_run=1 + i % 4, lambda_last_dir=1 if flagged else 0,
                 lambda_first_dir=1 if flagged else 0, total_unobserved_changes=i % 3,
                 lambda_unobserved_net=0.0, line_up_then_lambda_down=(i % 5 == 0),
                 line_down_then_lambda_up=(i % 7 == 0), total_overround_last=0.06, x12_msgs=0,
                 ah_msgs=1, ah_line_first=-0.5, ah_line_last=-0.5 - 0.25 * (i % 3 == 0),
                 ah_line_net=-0.25 * (i % 3 == 0), ah_line_moves=int(i % 3 == 0),
                 total_ah_same_msg=1, total_1x2_same_msg=0, trigger_total_share=1.0,
                 ctx_cup=(i % 9 == 0), ctx_youth_reserve=(i % 11 == 0),
                 ctx_league_other=not (i % 9 == 0 or i % 11 == 0))
        p = 1 / (1 + math.exp(-(lam_first + lam_net - 2.6) * 1.5))
        true_p = min(0.97, max(0.03, p + (effect if flagged else 0.0)))
        has_ft = rng.random() < ft_share
        outcome = None
        if has_ft:
            over = rng.random() < true_p
            h = 2 if over else 1
            a = 1 if over else (0 if rng.random() < 0.5 else 1)
            outcome = {'home': h, 'away': a, 'total_goals': h + a, 'OVER_2_5': int(h + a > 2),
                       'BTTS_YES': int(h > 0 and a > 0), 'HOME_WIN': int(h > a), 'DRAW': int(h == a),
                       'AWAY_WIN': int(h < a), 'AH_HOME_COVER': 1.0 if h - a - 0.5 > 0 else 0.0,
                       'ft_verified_at': (ko + timedelta(hours=3)).isoformat(), 'ft_sha256': 'f' * 64}
        out.append({'match_key': 'SYN-%04d' % i, 'kickoff_utc': ko.isoformat(),
                    'decision_at': dec.isoformat(), 'variables': v,
                    'baselines': {'p_over_2_5': round(p, 4), 'p_home': 0.45, 'p_draw': 0.27,
                                  'p_away': 0.28, 'p_ah_home': 0.5, 'ah_line_at_decision': -0.5},
                    'source_event_ids': ['syn:%d' % i],
                    'ft_status': 'VERIFIED_FT' if has_ft else 'PENDING', 'outcome': outcome})
    return out


def dataset(**kw):
    r = rows(**kw)
    return {'version': 1, 'rows': r, 'excluded': {}, 'excluded_source_events': 0,
            'digest': dataset_digest(r), 'as_of': NOW.isoformat()}


LLM_PLAN = {
    'question': 'Uma subida forte dos golos implícitos com AH a favorecer a casa diverge do mercado no Over?',
    'hypothesis': 'Movimentos conjuntos Total+AH na mesma direção ofensiva subestimam o Over.',
    'null_hypothesis': 'O residual Over destes jogos é igual ao dos restantes.',
    'market': 'TOTAL_GOALS', 'outcome': 'OVER_2_5',
    'indicators': [{'name': 'X_STRONG_LAMBDA_RISE', 'description': 'Golos implícitos sobem >= 0,2',
                    'expr': {'op': 'ge', 'args': [{'var': 'lambda_net'}, {'const': 0.2}]}}],
    'condition': {'op': 'and', 'args': [{'var': 'X_STRONG_LAMBDA_RISE'},
                                        {'op': 'is_known', 'args': [{'var': 'ah_line_net'}]}]},
    'rationale': 'Escolha autónoma do modelo: cruzamento Total e AH.',
    'alternative_explanations': ['A linha mais alta já incorpora o efeito'],
    'confounders': ['lead_bin', 'line_bin'],
}


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Records every request; returns one canned chat-completions envelope."""

    def __init__(self, content, status=200):
        import json
        self.calls = []
        self.status = status
        self.body = json.dumps({'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}],
                                'usage': {'prompt_tokens': 100, 'completion_tokens': 50,
                                          'total_tokens': 150}}).encode()

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        return FakeResponse(self.body, self.status)
