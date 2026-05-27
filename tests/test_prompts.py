from pathlib import Path
import unittest
import uuid

from image_factory.prompts import build_prompt_records, load_scenes


def temp_root() -> Path:
    base = Path.cwd() / ".tmp" / "test_runs"
    base.mkdir(parents=True, exist_ok=True)
    root = base / uuid.uuid4().hex
    root.mkdir()
    return root


class PromptTests(unittest.TestCase):
    def test_build_prompt_records(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "characters").mkdir(parents=True)
        (specs / "references").mkdir(parents=True)
        (specs / "style_bible.md").write_text("style", encoding="utf-8")
        (specs / "negative_rules.md").write_text("negative", encoding="utf-8")
        (specs / "characters" / "index.json").write_text('{"高松灯":"tomori.md"}', encoding="utf-8")
        (specs / "characters" / "tomori.md").write_text("tomori", encoding="utf-8")
        ref_image = root / "tomori.jpg"
        ref_image.write_bytes(b"fake image bytes")
        ref_path = str(ref_image).replace("\\", "/")
        (specs / "references" / "index.json").write_text(
            '{"images":[{"id":"tomori_ref","path":"' + ref_path + '","characters":["高松灯"],"priority":100}]}',
            encoding="utf-8",
        )
        scenes_csv = root / "scenes.csv"
        scenes_csv.write_text(
            "id,character,scene,mood,shot,lighting,color_palette\n001,高松灯,练习室,安静,近景,暖光,自然偏暖色彩\n",
            encoding="utf-8",
        )

        scenes = load_scenes(scenes_csv)
        records = build_prompt_records(scenes, specs, "batch_001")

        self.assertEqual(records[0]["custom_id"], "batch_001_001")
        self.assertIn("高松灯", records[0]["prompt"])
        self.assertIn("tomori", records[0]["prompt"])
        self.assertIn("练习室", records[0]["prompt"])
        self.assertIn("色彩/曝光：自然偏暖色彩", records[0]["prompt"])
        self.assertEqual(records[0]["color_palette"], "自然偏暖色彩")
        self.assertEqual(records[0]["reference_image_ids"], "tomori_ref")
        self.assertEqual(records[0]["reference_images"][0]["path"], str(ref_image))

    def test_explicit_reference_ids(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "characters").mkdir(parents=True)
        (specs / "references").mkdir(parents=True)
        (specs / "style_bible.md").write_text("style", encoding="utf-8")
        (specs / "negative_rules.md").write_text("negative", encoding="utf-8")
        (specs / "characters" / "index.json").write_text('{"高松灯":"tomori.md"}', encoding="utf-8")
        (specs / "characters" / "tomori.md").write_text("tomori", encoding="utf-8")
        ref_image = root / "manual.jpg"
        ref_image.write_bytes(b"fake image bytes")
        ref_path = str(ref_image).replace("\\", "/")
        (specs / "references" / "index.json").write_text(
            '{"images":[{"id":"manual_ref","path":"' + ref_path + '","characters":["其他"],"priority":100}]}',
            encoding="utf-8",
        )
        scenes_csv = root / "scenes.csv"
        scenes_csv.write_text(
            "id,character,scene,mood,shot,lighting,refs\n001,高松灯,练习室,安静,近景,暖光,manual_ref\n",
            encoding="utf-8",
        )

        scenes = load_scenes(scenes_csv)
        records = build_prompt_records(scenes, specs, "batch_001")

        self.assertEqual(records[0]["reference_image_ids"], "manual_ref")

    def test_group_character_expands_to_member_specs(self):
        root = temp_root()
        specs = root / "specs"
        (specs / "characters").mkdir(parents=True)
        (specs / "references").mkdir(parents=True)
        (specs / "style_bible.md").write_text("style", encoding="utf-8")
        (specs / "negative_rules.md").write_text("negative", encoding="utf-8")
        (specs / "characters" / "index.json").write_text(
            """
            {
              "高松灯": "tomori.md",
              "千早爱音": "anon.md",
              "要乐奈": "raana.md",
              "长崎素世": "soyo.md",
              "椎名立希": "taki.md"
            }
            """,
            encoding="utf-8",
        )
        for filename, text in {
            "tomori.md": "tomori spec",
            "anon.md": "anon spec",
            "raana.md": "raana spec",
            "soyo.md": "soyo spec",
            "taki.md": "taki spec",
        }.items():
            (specs / "characters" / filename).write_text(text, encoding="utf-8")
        (specs / "references" / "index.json").write_text('{"images":[]}', encoding="utf-8")
        scenes_csv = root / "scenes.csv"
        scenes_csv.write_text(
            "id,character,scene,mood,shot,lighting\n001,MyGO,团队直播,真诚,中景,屏幕光\n",
            encoding="utf-8",
        )

        records = build_prompt_records(load_scenes(scenes_csv), specs, "batch_001")

        self.assertIn("tomori spec", records[0]["prompt"])
        self.assertIn("anon spec", records[0]["prompt"])
        self.assertIn("raana spec", records[0]["prompt"])
        self.assertIn("soyo spec", records[0]["prompt"])
        self.assertIn("taki spec", records[0]["prompt"])


if __name__ == "__main__":
    unittest.main()
