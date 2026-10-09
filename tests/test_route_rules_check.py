import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import route_rules_check  # noqa: E402

# The file the website writes for the WSSS A464 rule. `eec26c79` is the id the
# website computes (src/lib/contribute/route-rules.ts); the test pins it so the
# two hashes cannot drift apart.
WSSS = {
    "schema_version": 1,
    "id": "eec26c79",
    "airport": "WSSS",
    "flights": "arrivals",
    "on_airway": "A464",
    "at_fix": "ARAMA",
    "action": "direct",
    "value": "TEBUN",
    "star_from": "TEBUN",
    "source": {
        "document": "AIP Singapore AD 2 WSSS 19.2.1",
        "url": "https://aim-sg.caas.gov.sg/",
        "quote": "Arrivals into Changi to flight plan via A464 - ARAMA – TEBUN. After TEBUN, to join the TEBUN STAR.",
    },
    "created_at": "2026-10-09T13:00:00Z",
    "creation_airac": "2610",
}


def with_id(rule: dict) -> dict:
    rule = copy.deepcopy(rule)
    rule["id"] = route_rules_check.rule_id(rule)
    return rule


def errors(rule: dict, folder: str = "WSSS") -> list[str]:
    return route_rules_check.validate_rule(rule, folder, rule.get("id", ""))


class RouteRulesCheckTests(unittest.TestCase):
    def test_the_website_file_is_valid(self) -> None:
        self.assertEqual([], errors(WSSS))

    def test_the_id_is_the_website_hash(self) -> None:
        self.assertEqual("eec26c79", route_rules_check.rule_id(WSSS))

    def test_the_id_must_match_the_body(self) -> None:
        rule = copy.deepcopy(WSSS)
        rule["value"] = rule["star_from"] = "TERUS"
        self.assertIn("is not the hash of the rule", " ".join(errors(rule)))

    def test_the_id_must_be_the_file_name(self) -> None:
        self.assertIn(
            "id eec26c79 is not the file name 00000000",
            route_rules_check.validate_rule(WSSS, "WSSS", "00000000"),
        )

    def test_the_airport_must_be_the_folder(self) -> None:
        self.assertIn("airport WSSS is not the folder WMKK", errors(WSSS, "WMKK"))

    def test_a_must_rule_needs_a_source(self) -> None:
        rule = copy.deepcopy(WSSS)
        del rule["source"]
        self.assertIn("a must rule needs a source", errors(with_id(rule)))

    def test_a_prefer_rule_needs_no_source(self) -> None:
        rule = copy.deepcopy(WSSS)
        del rule["source"], rule["star_from"]
        rule.update(action="prefer", value="TOPOR A464 ARAMA")
        self.assertEqual([], errors(with_id(rule)))

    def test_the_star_starts_at_the_direct_fix(self) -> None:
        rule = copy.deepcopy(WSSS)
        rule["star_from"] = "ARAMA"
        self.assertIn("the STAR must start at the direct fix TEBUN", errors(with_id(rule)))

    def test_sequences_alternate_fixes_and_airways(self) -> None:
        self.assertEqual([], route_rules_check.sequence_errors("TOPOR A464 ARAMA DCT TEBUN"))
        self.assertTrue(route_rules_check.sequence_errors("TOPOR A464"))
        self.assertTrue(route_rules_check.sequence_errors("TOPOR A464 ARAMA DCT"))
        self.assertTrue(route_rules_check.sequence_errors("TOPOR ARAMA TEBUN"))

    def test_kind_specific_fields(self) -> None:
        departures = copy.deepcopy(WSSS)
        del departures["star_from"]
        departures.update(flights="departures", action="entry", origins="WMKK")
        found = errors(with_id(departures))
        self.assertIn("only arrivals have origins", found)
        self.assertIn("only arrivals have entry fixes", found)

    def test_values_are_normalized(self) -> None:
        rule = copy.deepcopy(WSSS)
        rule["at_fix"] = "arama"
        self.assertIn("at_fix is not normalized (uppercase, single spaces)", errors(rule))

    def test_unknown_keys_are_refused(self) -> None:
        rule = copy.deepcopy(WSSS)
        rule["author"] = "someone"
        self.assertIn("unknown keys: author", errors(rule))

    def test_the_cycle_is_required(self) -> None:
        rule = copy.deepcopy(WSSS)
        rule["creation_airac"] = ""
        self.assertIn("creation_airac must be a four-digit AIRAC cycle", errors(rule))

    def test_lengths_count_like_javascript(self) -> None:
        self.assertEqual(4, route_rules_check.js_length("\U0001F600\U0001F600"))

    def test_the_tree_walk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "ROUTES" / "rules" / "WSSS"
            folder.mkdir(parents=True)
            (folder / "eec26c79.json").write_text(json.dumps(WSSS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual([], route_rules_check.validate_tree(root))

            (root / "ROUTES" / "rules" / "README.md").write_text("contract", encoding="utf-8")
            self.assertEqual([], route_rules_check.validate_tree(root))

            (folder / "notes.txt").write_text("x", encoding="utf-8")
            self.assertEqual(
                ["ROUTES/rules/WSSS/notes.txt: rule files are ROUTES/rules/<ICAO>/<id>.json"],
                route_rules_check.validate_tree(root),
            )

    def test_no_rules_folder_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], route_rules_check.validate_tree(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
