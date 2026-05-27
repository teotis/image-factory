from pathlib import Path
import unittest
import uuid

from image_factory.references import select_reference_images, validate_reference_path_ownership


def temp_root() -> Path:
    base = Path.cwd() / ".tmp" / "test_runs"
    base.mkdir(parents=True, exist_ok=True)
    root = base / uuid.uuid4().hex
    root.mkdir()
    return root


class ReferenceTests(unittest.TestCase):
    def test_project_relative_reference_path(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "references").mkdir(parents=True)
        image = root / "assets" / "references" / "test" / "tomori.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"fake image bytes")
        (specs / "references" / "index.json").write_text(
            '{"images":[{"id":"tomori_ref","path":"assets/references/test/tomori.jpg","characters":["高松灯"]}]}',
            encoding="utf-8",
        )

        refs = select_reference_images("高松灯", specs)

        self.assertEqual(refs[0]["project_path"], "assets/references/test/tomori.jpg")
        self.assertEqual(refs[0]["path"], str(image))

    def test_group_context_prefers_group_references(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "references").mkdir(parents=True)
        group_image = root / "assets" / "group.jpg"
        closeup_image = root / "assets" / "closeup.jpg"
        group_image.parent.mkdir(parents=True)
        group_image.write_bytes(b"group")
        closeup_image.write_bytes(b"closeup")
        (specs / "references" / "index.json").write_text(
            """
            {
              "images": [
                {
                  "id": "single_closeup",
                  "path": "assets/closeup.jpg",
                  "groups": ["MyGO"],
                  "roles": ["character", "closeup"],
                  "priority": 100
                },
                {
                  "id": "group_lineup",
                  "path": "assets/group.jpg",
                  "groups": ["MyGO"],
                  "roles": ["group", "lineup"],
                  "priority": 50
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        refs = select_reference_images("MyGO", specs, context="MyGO 五人群像")

        self.assertEqual([ref["id"] for ref in refs], ["group_lineup"])

    def test_original_identity_reference_outranks_realized_sample(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "references").mkdir(parents=True)
        original_image = root / "assets" / "tomori_original.jpg"
        realized_image = root / "assets" / "tomori_realized.jpg"
        original_image.parent.mkdir(parents=True)
        original_image.write_bytes(b"original")
        realized_image.write_bytes(b"realized")
        (specs / "references" / "index.json").write_text(
            """
            {
              "images": [
                {
                  "id": "tomori_realized",
                  "path": "assets/tomori_realized.jpg",
                  "characters": ["高松灯"],
                  "roles": ["realized", "photo_style", "character", "closeup"],
                  "priority": 150
                },
                {
                  "id": "tomori_original",
                  "path": "assets/tomori_original.jpg",
                  "characters": ["高松灯"],
                  "roles": ["character", "closeup", "hair", "expression"],
                  "priority": 100
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        refs = select_reference_images("高松灯", specs, context="高松灯近景")

        self.assertEqual([ref["id"] for ref in refs], ["tomori_original", "tomori_realized"])
        self.assertEqual(refs[0]["reference_tier"], "identity_anchor")
        self.assertEqual(refs[1]["reference_tier"], "realized_translation")

    def test_multi_character_selection_keeps_identity_anchor_per_character(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "references").mkdir(parents=True)
        assets = root / "assets"
        assets.mkdir()
        for name in [
            "tomori.jpg",
            "tomori_extra.jpg",
            "raana.jpg",
            "raana_extra.jpg",
            "soyo.jpg",
            "group.jpg",
        ]:
            (assets / name).write_bytes(name.encode("utf-8"))
        (specs / "references" / "index.json").write_text(
            """
            {
              "images": [
                {
                  "id": "raana_primary",
                  "path": "assets/raana.jpg",
                  "characters": ["要乐奈"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 300
                },
                {
                  "id": "raana_extra",
                  "path": "assets/raana_extra.jpg",
                  "characters": ["要乐奈"],
                  "roles": ["character", "outfit"],
                  "priority": 290
                },
                {
                  "id": "tomori_primary",
                  "path": "assets/tomori.jpg",
                  "characters": ["高松灯"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 120
                },
                {
                  "id": "tomori_extra",
                  "path": "assets/tomori_extra.jpg",
                  "characters": ["高松灯"],
                  "roles": ["character", "expression"],
                  "priority": 110
                },
                {
                  "id": "soyo_primary",
                  "path": "assets/soyo.jpg",
                  "characters": ["长崎素世"],
                  "roles": ["character", "fullbody", "outfit"],
                  "priority": 20
                },
                {
                  "id": "group_lineup",
                  "path": "assets/group.jpg",
                  "characters": ["高松灯", "要乐奈", "长崎素世"],
                  "groups": ["MyGO"],
                  "roles": ["group", "lineup"],
                  "priority": 250
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        refs = select_reference_images(
            "高松灯/要乐奈/长崎素世",
            specs,
            max_auto_refs=4,
            context="MyGO 三人同框，避免角色同脸",
        )

        self.assertEqual(
            [ref["id"] for ref in refs[:3]],
            ["tomori_primary", "raana_primary", "soyo_primary"],
        )
        self.assertIn(refs[3]["id"], {"raana_extra", "group_lineup"})

    def test_multi_character_selection_reserves_realized_translation(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "references").mkdir(parents=True)
        assets = root / "assets"
        assets.mkdir()
        for name in [
            "tomori.jpg",
            "tomori_extra.jpg",
            "anon.jpg",
            "anon_extra.jpg",
            "pair.jpg",
            "realized.jpg",
        ]:
            (assets / name).write_bytes(name.encode("utf-8"))
        (specs / "references" / "index.json").write_text(
            """
            {
              "images": [
                {
                  "id": "tomori_primary",
                  "path": "assets/tomori.jpg",
                  "characters": ["高松灯"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 300
                },
                {
                  "id": "tomori_extra",
                  "path": "assets/tomori_extra.jpg",
                  "characters": ["高松灯"],
                  "roles": ["character", "expression"],
                  "priority": 290
                },
                {
                  "id": "anon_primary",
                  "path": "assets/anon.jpg",
                  "characters": ["千早爱音"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 280
                },
                {
                  "id": "anon_extra",
                  "path": "assets/anon_extra.jpg",
                  "characters": ["千早爱音"],
                  "roles": ["character", "outfit"],
                  "priority": 270
                },
                {
                  "id": "pair_identity",
                  "path": "assets/pair.jpg",
                  "characters": ["高松灯", "千早爱音"],
                  "roles": ["character", "pair", "relationship"],
                  "priority": 260
                },
                {
                  "id": "realized_pair",
                  "path": "assets/realized.jpg",
                  "characters": ["高松灯", "千早爱音"],
                  "roles": ["realized", "photo_style", "pair", "faces"],
                  "priority": 100
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        refs = select_reference_images(
            "千早爱音、高松灯",
            specs,
            max_auto_refs=4,
            context="千早爱音和高松灯海边旅行，人物保真",
        )

        self.assertEqual([ref["id"] for ref in refs[:2]], ["anon_primary", "tomori_primary"])
        self.assertIn("realized_pair", [ref["id"] for ref in refs])
        self.assertEqual(refs[-1]["reference_tier"], "realized_translation")

    def test_mygo_group_selection_keeps_single_identity_anchor_for_each_member(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "references").mkdir(parents=True)
        assets = root / "assets"
        assets.mkdir()
        for name in [
            "group_closeup.jpg",
            "group_lineup.jpg",
            "member_intro.jpg",
            "realized_group.jpg",
            "tomori.jpg",
            "anon.jpg",
            "raana.jpg",
            "soyo.jpg",
            "taki.jpg",
        ]:
            (assets / name).write_bytes(name.encode("utf-8"))
        (specs / "references" / "index.json").write_text(
            """
            {
              "images": [
                {
                  "id": "group_closeup",
                  "path": "assets/group_closeup.jpg",
                  "groups": ["MyGO"],
                  "roles": ["group", "closeup", "faces"],
                  "priority": 300
                },
                {
                  "id": "group_lineup",
                  "path": "assets/group_lineup.jpg",
                  "groups": ["MyGO"],
                  "roles": ["group", "lineup", "fullbody"],
                  "priority": 290
                },
                {
                  "id": "member_intro",
                  "path": "assets/member_intro.jpg",
                  "groups": ["MyGO"],
                  "roles": ["group", "member_intro", "lineup"],
                  "priority": 280
                },
                {
                  "id": "realized_group",
                  "path": "assets/realized_group.jpg",
                  "groups": ["MyGO"],
                  "roles": ["realized", "group", "photo_style", "relationship"],
                  "priority": 270
                },
                {
                  "id": "tomori_identity",
                  "path": "assets/tomori.jpg",
                  "characters": ["高松灯"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 200
                },
                {
                  "id": "anon_identity",
                  "path": "assets/anon.jpg",
                  "characters": ["千早爱音"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 190
                },
                {
                  "id": "raana_identity",
                  "path": "assets/raana.jpg",
                  "characters": ["要乐奈"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 180
                },
                {
                  "id": "soyo_identity",
                  "path": "assets/soyo.jpg",
                  "characters": ["长崎素世"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 170
                },
                {
                  "id": "taki_identity",
                  "path": "assets/taki.jpg",
                  "characters": ["椎名立希"],
                  "roles": ["character", "closeup", "face"],
                  "priority": 160
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        refs = select_reference_images("MyGO", specs, context="MyGO 五人群像，避免角色同脸")

        self.assertEqual(
            [ref["id"] for ref in refs[:5]],
            [
                "tomori_identity",
                "anon_identity",
                "raana_identity",
                "soyo_identity",
                "taki_identity",
            ],
        )
        self.assertEqual(refs[5]["id"], "group_closeup")
        self.assertEqual(refs[6]["id"], "group_lineup")
        self.assertEqual(refs[7]["id"], "realized_group")


class ReferencePathContractTests(unittest.TestCase):
    def test_valid_path_under_assets_references_passes(self):
        entries = [{"id": "ref1", "project_path": "assets/references/test/img.png", "path": "/tmp/img.png"}]
        issues = validate_reference_path_ownership(entries)
        self.assertEqual(issues, [])

    def test_empty_project_path_fails(self):
        entries = [{"id": "ref2", "project_path": "", "path": "/external/img.png"}]
        issues = validate_reference_path_ownership(entries)
        self.assertEqual(len(issues), 1)
        self.assertIn("outside the project", issues[0])

    def test_path_outside_assets_references_fails(self):
        entries = [{"id": "ref3", "project_path": "outputs/some/img.png", "path": "/proj/outputs/some/img.png"}]
        issues = validate_reference_path_ownership(entries)
        self.assertEqual(len(issues), 1)
        self.assertIn("must be under assets/references/", issues[0])

    def test_multiple_entries_mixed(self):
        entries = [
            {"id": "ok1", "project_path": "assets/references/a.png", "path": "/x/a.png"},
            {"id": "bad1", "project_path": "other/b.png", "path": "/x/other/b.png"},
            {"id": "bad2", "project_path": "", "path": "/outside/c.png"},
        ]
        issues = validate_reference_path_ownership(entries)
        self.assertEqual(len(issues), 2)


if __name__ == "__main__":
    unittest.main()
