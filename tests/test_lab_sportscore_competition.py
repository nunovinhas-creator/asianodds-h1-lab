import unittest
from datetime import datetime, timezone
from h1lab.lab_sportscore import SportScoreResults
from h1lab.lab_sportscore_competition import anchors

NOW = datetime(2026, 10, 31, 10, tzinfo=timezone.utc)
S = {'match_key': '2026-10-30,1,2', 'home': 'AS Roma', 'away': 'AC Milan',
     'kickoff_utc': '2026-10-30T19:00:00+00:00'}
C = {'provider': 'sportscore', 'provider_home': 'Roma', 'provider_away': 'Milan',
     'provider_kickoff_utc': S['kickoff_utc'], 'provider_competition': 'Italy Coppa Italia',
     'reference_url': 'https://sportscore.com/football/match/roma-vs-milan/test123/',
     'observed_competition_at_capture': 'Italy Coppa Italia',
     'last_seen_at': '2026-10-30T20:00:00+00:00', 'match_strength': 'STRONG',
     'orientation': 'SAME_ORDER'}
E = {'home': 'Roma', 'away': 'Milan', 'time': S['kickoff_utc'],
     'competition': 'Italy Coppa Italia', 'url': C['reference_url'],
     'status': 'finished', 'status_text': 'FT', 'home_score': 1, 'away_score': 0}


class CompetitionCoreTests(unittest.TestCase):
    def provider(self, observed='Italy Coppa Italia', source='Italy Coppa Italia',
                 signal=None, candidate=None, event=None):
        signal = dict(S) if signal is None else signal
        c = dict(C, provider_competition=source, observed_competition_at_capture=observed)
        c.update(candidate or {})
        r = {'games': [{**signal, 'ft_status': 'PENDING', 'observed_competition': observed,
                       'possible_duplicates': [], 'candidates': [c]}]}
        comp = {signal['match_key']: observed}
        self.assertEqual(anchors(r, comp, NOW), {})
        row = dict(E, competition=source)
        row.update(event or {})
        return SportScoreResults(comp, review=r, now=NOW, max_requests=1,
            getter=lambda endpoint, params: {'matches': [row]})

    def test_reproduced_initial_wrong_country_is_blocked(self):
        self.assertIsNone(self.provider(source='Kenya Cup').lookup(S)[0])

    def test_equal_generic_names_do_not_prove_country_or_tier(self):
        for label in ('Premier League', 'Division 1', 'Cup', 'National League'):
            with self.subTest(label=label):
                self.assertIsNone(self.provider(label, label).lookup(S)[0])

    def test_equal_country_qualified_names_are_not_independent_identity(self):
        self.assertIsNone(self.provider().lookup(S)[0])

    def test_unproven_competition_aliases_cannot_certify(self):
        for label in ('Italy Cup', 'Coppa Italia', 'Italian Cup', 'ITALY COPPA ITALIA'):
            with self.subTest(label=label):
                self.assertIsNone(self.provider(source=label).lookup(S)[0])

    def test_country_tier_gender_age_and_reserve_mismatches_are_blocked(self):
        for label in ('Kenya Cup', 'Italy Coppa Italia Serie C', 'Italy Coppa Italia Women',
                      'Italy Coppa Italia U21', 'Italy Coppa Italia Reserves'):
            with self.subTest(label=label):
                self.assertIsNone(self.provider(source=label).lookup(S)[0])

    def test_unverified_context_flags_and_ids_are_not_evidence(self):
        for context in ({'provider_country': 'Italy', 'observed_country': 'Kenya'},
                        {'competition_verified': True, 'provider_competition_id': 123},
                        {'provider_country': 'Italy', 'observed_country': 'Italy'}):
            with self.subTest(context=context):
                self.assertIsNone(self.provider(candidate=context).lookup(S)[0])

    def test_core_team_categories_do_not_bypass_quarantine(self):
        for observed, source in (('Benfica B', 'Benfica II'),
                                 ('Benfica Reserves', 'Benfica II'),
                                 ('Benfica Women', 'Benfica Ladies'),
                                 ('Benfica U21', 'Benfica'),
                                 ('Benfica B', 'Benfica Women')):
            signal = dict(S, home=observed)
            p = self.provider(signal=signal, candidate={'provider_home': source}, event={'home': source})
            self.assertIsNone(p.lookup(signal)[0])

    def test_legacy_exact_fixture_still_certifies_and_reuses_cache(self):
        signal = dict(S, home='Roma', away='Milan')
        p = self.provider(signal=signal)
        result, reason = p.lookup(signal)
        self.assertEqual(reason, 'verified_sportscore_ft')
        self.assertEqual((result['home_goals'], result['away_goals']), (1, 0))
        self.assertIsNotNone(p.lookup(signal)[0])
        self.assertEqual(p.requests, 1)
        self.assertEqual(p.summary()['competition_core_targets'], 0)
        self.assertEqual(p.summary()['competition_core_verified'], 0)

    def test_legacy_exact_requires_current_valid_regulation_ft(self):
        signal = dict(S, home='Roma', away='Milan')
        for event in ({'status': 'inprogress'}, {'status_text': 'After Extra Time'},
                      {'home_score': -1}, {'status_text': 'finished'}):
            with self.subTest(event=event):
                self.assertIsNone(self.provider(signal=signal, event=event).lookup(signal)[0])

    def test_legacy_exact_ambiguity_is_still_rejected(self):
        signal = dict(S, home='Roma', away='Milan')
        other = dict(E, url='https://sportscore.com/football/match/other/id/')
        p = SportScoreResults({S['match_key']: 'Italy Coppa Italia'}, max_requests=1,
                             getter=lambda endpoint, params: {'matches': [dict(E), other]})
        self.assertIsNone(p.lookup(signal)[0])
