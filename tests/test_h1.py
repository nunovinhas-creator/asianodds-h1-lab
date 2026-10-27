import unittest
from datetime import datetime,timedelta,timezone
from h1lab.core import asian_under,empty_state,parse_alert,classify_message,incorporate,public_data

UTC=timezone.utc
OBS=datetime(2026,10,26,18,0,tzinfo=UTC)

def message(name="Clube A vs Clube B",was="2.50   1.69    2.02",now="2.75   1.81    1.89",typ="Total: 2.50 ↑ 2.75"):
    return "\n".join(["🔵 "+name,"🏆 Example League","🕒 28 Oct 19:45 UTC",typ,
       "Was   "+was,"Now   "+now,
       "https://asianodds.com/en/live-dropping-odds?match=2026-10-28%2C123%2C456&market=ou"])

class ParseTest(unittest.TestCase):
    def test_h1_true(self):
        a=parse_alert(message(),OBS,10,"x")
        self.assertTrue(a["h1"])
        self.assertEqual(a["match_key"],"2026-10-28,123,456")
        self.assertEqual(a["total_after"],2.75)
        self.assertEqual(a["under_after"],1.89)

    def test_falling_line_not_h1(self):
        a=parse_alert(message(was="2.75 1.80 1.90",now="2.50 1.70 2.00",typ="Total: 2.75 ↓ 2.50"),OBS,1)
        self.assertFalse(a["h1"])

    def test_over_not_rising(self):
        a=parse_alert(message(now="2.75 1.60 1.90"),OBS,1)
        self.assertFalse(a["h1"])

    def test_1x2_cannot_be_h1(self):
        a=parse_alert(message(typ="1x2 (1): 2.40 ↓ 2.20"),OBS,1)
        self.assertFalse(a["h1"])

    def test_no_match_returns_none(self):
        self.assertIsNone(parse_alert("spam",OBS,1))

    def test_non_alert_diagnostic(self):
        self.assertEqual(classify_message("AsianOdds service message"), "other_channel_message")

    def test_missing_kickoff_diagnostic(self):
        self.assertEqual(classify_message("Clube A vs Clube B\nWas 2.50 1.80 1.90\nNow 2.75 1.90 1.80"), "missing_kickoff")

    def test_structured_alert_is_not_a_diagnostic(self):
        self.assertTrue(parse_alert(message(), OBS, 10)["h1"])

class AsianSettlement(unittest.TestCase):
    def test_quarter_under(self):
        # Under 3.25 with exactly 3 goals: half stake refunded, half wins
        self.assertAlmostEqual(asian_under(3.25,1.90,3),1.45)
        self.assertAlmostEqual(asian_under(3.75,2.00,4),0.5)
        self.assertAlmostEqual(asian_under(2.25,2.00,3),0.0)
        self.assertAlmostEqual(asian_under(2.0,2.00,2),1.0)
        self.assertAlmostEqual(asian_under(2.5,2.00,2),2.0)

    def test_invalid_line(self):
        with self.assertRaises(ValueError): asian_under(2.4,1.9,2)

class TriplesTest(unittest.TestCase):
    def test_frozen_and_no_duplication(self):
        state=empty_state()
        events=[]
        for i in range(3):
            text=message(name="Clube "+str(i)+" vs Equipa "+str(i))
            text=text.replace("123%2C456",str(123+i)+"%2C"+str(456+i))
            events.append(parse_alert(text,OBS+timedelta(minutes=i),i+1))
        self.assertEqual(incorporate(state,events,OBS+timedelta(hours=1)),3)
        self.assertEqual(len(state["signals"]),3)
        self.assertEqual(len(state["tickets"]),1)
        self.assertEqual(incorporate(state,events,OBS+timedelta(hours=1)),0)
        self.assertEqual(len(state["tickets"]),1)

    def test_expired_not_tickets(self):
        state=empty_state()
        events=[parse_alert(message(),OBS,1)]
        incorporate(state,events,OBS+timedelta(days=3))
        self.assertEqual(len(state["signals"]),1)
        self.assertEqual(len(state["tickets"]),0)

    def test_result_still_pending_without_verified_final(self):
        state=empty_state()
        incorporate(state,[parse_alert(message(),OBS,1)],OBS)
        pub=public_data(state,{},OBS)
        self.assertEqual(pub["singles"]["pending"],1)
        self.assertIsNone(pub["singles"]["roi_pct"])

    def test_single_roi_from_final_only(self):
        state=empty_state()
        incorporate(state,[parse_alert(message(),OBS,1)],OBS)
        result={state["signals"][0]["match_key"]:{"home_goals":1,"away_goals":0}}
        pub=public_data(state,result,OBS)
        self.assertAlmostEqual(pub["singles"]["roi_pct"],89.0)

if __name__=="__main__": unittest.main()
