import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def airport_file(icao: str) -> dict[str, object]:
    matches = list(ROOT.glob(f"**/{icao}/visual_procedures.json"))
    if len(matches) != 1:
        raise AssertionError(f"expected one {icao} visual file, found {len(matches)}")
    return json.loads(matches[0].read_text(encoding="utf-8"))


class VisualProceduresPortfolioTests(unittest.TestCase):
    def test_launch_portfolio_counts_are_stable(self) -> None:
        files = list(ROOT.glob("**/visual_procedures.json"))
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in files]
        procedures = [procedure for payload in payloads for procedure in payload["procedures"]]
        variants = [variant for procedure in procedures for variant in procedure["variants"]]
        self.assertEqual(24, len(files))
        self.assertEqual(30, len(procedures))
        self.assertEqual(54, len(variants))

    def test_washington_has_one_forward_river_route_per_procedure(self) -> None:
        procedures = {item["id"]: item for item in airport_file("KDCA")["procedures"]}
        self.assertEqual({"MOUNT_VERNON_VISUAL_01", "RIVER_VISUAL_19"}, set(procedures))
        for procedure in procedures.values():
            self.assertEqual(1, len(procedure["variants"]))
            variant = procedure["variants"][0]
            self.assertEqual("forward_route", variant["join_policy"])
            self.assertEqual(
                {"name": "the river", "aliases": ["river"], "scope": "route"},
                variant["sight_reference"],
            )
        river_ids = [
            leg["id"]
            for leg in procedures["RIVER_VISUAL_19"]["variants"][0]["legs"]
        ]
        self.assertEqual(
            [
                "AMERICAN_LEGION_DAVID_TAYLOR_TRACE",
                "DARIC",
                "CHAIN_BRIDGE_TRACE",
                "KEY_BRIDGE_TRACE",
                "ROOSEVELT_MEMORIAL_BRIDGES_TRACE",
                "ROCHAMBEAU_BRIDGE_TRACE",
            ],
            river_ids,
        )

    def test_sweetwater_east_branch_runs_east_to_west(self) -> None:
        procedure = airport_file("KSAN")["procedures"][0]
        variants = {variant["id"]: variant for variant in procedure["variants"]}
        east = variants["MZB_R084_EAST_BRANCH"]["legs"]
        self.assertEqual(
            [
                "MZB_R084_EAST_TRACE",
                "MOUNT_HELIX_TRACE",
                "SR125_BASE_TRACE",
                "KLOMN",
                "STADIUM_TRACE",
                "STEPN",
            ],
            [leg["id"] for leg in east],
        )
        self.assertTrue(
            all(
                east[index]["longitude"] > east[index + 1]["longitude"]
                for index in range(len(east) - 1)
            )
        )
        self.assertEqual(
            ["OKAIN", "CIJHI"],
            [leg["id"] for leg in variants["OKAIN_ENTRY"]["legs"]],
        )

    def test_roaring_fork_contains_all_seven_published_arms(self) -> None:
        procedure = airport_file("KASE")["procedures"][0]
        self.assertEqual(
            {
                "DBL_R163_ENTRY",
                "CARBONDALE_BASALT_ENTRY",
                "MT_SOPRIS_ENTRY",
                "CAPITAL_PEAK_ENTRY",
                "CASTLE_PEAK_ENTRY",
                "INDEPENDENCE_PASS_ENTRY",
                "HOLY_CROSS_RUEDI_ENTRY",
            },
            {variant["id"] for variant in procedure["variants"]},
        )
        expected_altitudes = {
            "MT_SOPRIS_ENTRY": 14500,
            "CAPITAL_PEAK_ENTRY": 15500,
            "CASTLE_PEAK_ENTRY": 16000,
            "INDEPENDENCE_PASS_ENTRY": 14500,
            "HOLY_CROSS_RUEDI_ENTRY": 11500,
        }
        for variant in procedure["variants"]:
            if variant["id"] in expected_altitudes:
                self.assertEqual(
                    expected_altitudes[variant["id"]],
                    variant["legs"][0]["altitude"]["value_ft"],
                )


if __name__ == "__main__":
    unittest.main()
