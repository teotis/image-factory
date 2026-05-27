import base64
import importlib.util
from pathlib import Path
import unittest
import uuid


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "make_prompt_doc.py"
SPEC = importlib.util.spec_from_file_location("make_prompt_doc", SCRIPT_PATH)
make_prompt_doc = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(make_prompt_doc)

from image_factory.prompt_docs import build_copy_prompt, build_variant_prompts, get_platform_profile


def temp_root() -> Path:
    base = Path.cwd() / ".tmp" / "test_runs"
    base.mkdir(parents=True, exist_ok=True)
    root = base / uuid.uuid4().hex
    root.mkdir()
    return root


class PromptDocScriptTests(unittest.TestCase):
    def test_default_output_name_uses_series_date_and_topic(self):
        path = make_prompt_doc.default_output_path("MyGO live stream", doc_date="20260430")

        self.assertEqual(path.name, "20260430_mygo_live_stream_1162a9bf.md")

    def test_default_output_name_allows_explicit_filename_parts(self):
        path = make_prompt_doc.default_output_path(
            "ignored theme",
            doc_series="MyGO!!!!!",
            doc_date="20260430",
            doc_topic="China Travel",
        )

        self.assertEqual(path.name, "20260430_mygo_china_travel_94536634.md")

    def test_default_output_name_preserves_explicit_topic_hash(self):
        path = make_prompt_doc.default_output_path(
            "ignored theme",
            doc_series="MyGO!!!!!",
            doc_date="20260430",
            doc_topic="china_travel_1234abcd",
        )

        self.assertEqual(path.name, "20260430_mygo_china_travel_1234abcd.md")

    def test_default_output_name_extracts_chinese_topic_keywords(self):
        path = make_prompt_doc.default_output_path("MyGO 中国旅行", doc_date="20260430")

        self.assertEqual(path.name, "20260430_mygo_china_travel_86d3c313.md")

    def test_default_output_name_rejects_invalid_date(self):
        with self.assertRaises(ValueError):
            make_prompt_doc.default_output_path("MyGO live stream", doc_date="2026-04-30")

    def test_markdown_uses_previewable_relative_images_and_html_embeds_data(self):
        root = temp_root()
        image = root / "assets" / "references" / "mygo" / "ref.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"fake image bytes")
        out = root / "prompts" / "docs" / "prompt_doc.md"
        record = {
            "prompt": "生成一张团队直播图片",
            "reference_images": [
                {
                    "id": "mygo_ref",
                    "path": str(image),
                    "project_path": "assets/references/mygo/ref.jpg",
                    "notes": "参考图说明",
                    "width": 640,
                    "height": 360,
                }
            ],
        }

        markdown = make_prompt_doc.render_doc(record, "MyGO 团队直播", out)
        embedded_html = make_prompt_doc.render_html(record, "MyGO 团队直播")

        self.assertIn("![mygo_ref](../../assets/references/mygo/ref.jpg)", markdown)
        self.assertIn("同名 `_embedded.html` 是自包含版本", markdown)
        self.assertIn("data:image/jpeg;base64,", embedded_html)
        self.assertIn(base64.b64encode(b"fake image bytes").decode("ascii"), embedded_html)

    def test_html_embeds_compressed_preview_when_pillow_can_read_image(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Pillow is not available")

        root = temp_root()
        image = root / "assets" / "references" / "mygo" / "ref.png"
        image.parent.mkdir(parents=True)
        Image.effect_noise((800, 600), 75).convert("RGB").save(image)
        record = {
            "prompt": "生成一张团队直播图片",
            "reference_images": [
                {
                    "id": "mygo_ref",
                    "path": str(image),
                    "project_path": "assets/references/mygo/ref.png",
                    "roles": ["character", "closeup"],
                    "notes": "参考图说明",
                    "width": 800,
                    "height": 600,
                }
            ],
        }

        embedded_html = make_prompt_doc.render_html(
            record,
            "MyGO 团队直播",
            image_max_edge=120,
            image_quality=50,
        )

        self.assertIn("data:image/jpeg;base64,", embedded_html)
        self.assertIn("二次元/原作图优先锁定角色相似度", embedded_html)

    def test_multi_scene_mygo_theme_generates_explicit_variants_by_default(self):
        theme = (
            "MyGO全员中国行卖萌照。二次元人物现实化，5位东亚高中女生乐队成员在中国10个城市地标打卡卖萌。"
            "场景：(1)上海外滩灯捧着歌词本对镜头歪头微笑。"
            "(2)成都火锅店爱音举着筷子辣到吐舌头。"
            "(3)广州早茶店乐奈举着虾饺对镜头张嘴。"
            "(4)西安兵马俑前立希双手插兜酷酷表情。"
            "(5)厦门鼓浪屿素世优雅品尝奶茶。"
            "(6)北京故宫红墙前全员合影。"
            "(7)重庆洪崖洞夜景前灯和爱音贴脸自拍。"
            "(8)武汉樱花树下乐奈仰头看花瓣。"
            "(9)哈尔滨冰雪大世界立希被冻到捂脸。"
            "(10)三亚海边全员戏水尖叫。每张都要突出各自眼眸颜色的特写。"
        )
        record = {
            "character": "高松灯、千早爱音、要乐奈、长崎素世、椎名立希",
            "scene": theme,
            "mood": "自然可爱",
            "shot": "中景",
            "lighting": "自然光",
            "color_palette": "清透明亮",
        }

        variants = build_variant_prompts(record, theme, "3:4", count=0)

        self.assertEqual(len(variants), 10)
        self.assertIn("上海外滩", variants[0]["scene"])
        self.assertIn("三亚海边", variants[-1]["scene"])
        self.assertNotIn("每张", variants[-1]["scene"])
        self.assertIn("本张场景：(1)上海外滩", variants[0]["prompt"])
        self.assertIn("contact sheet", variants[0]["prompt"])
        self.assertNotIn("成都火锅店", variants[0]["prompt"])

    def test_main_prompt_contains_single_image_collage_guardrail(self):
        record = {
            "character": "MyGO",
            "scene": "MyGO全员中国行卖萌照。场景：(1)上海外滩。(2)成都火锅店。",
            "reference_images": [],
        }

        prompt = build_copy_prompt(record, record["scene"], get_platform_profile("generic"), "3:4", [])

        self.assertIn("单图硬约束", prompt)
        self.assertIn("严禁拼贴画、多宫格、九宫格", prompt)
        self.assertIn("contact sheet", prompt)


if __name__ == "__main__":
    unittest.main()
