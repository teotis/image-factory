from pathlib import Path
import unittest
import uuid

from image_factory.prompt_docs import (
    ContextSnippet,
    CHARACTER_FACE_GUIDE_SHORT,
    BODY_INTEGRITY_NEGATIVE,
    BODY_INTEGRITY_POSITIVE,
    _parse_scene_list,
    body_integrity_guardrail,
    build_copy_prompt,
    build_negative_prompt,
    get_platform_profile,
    infer_aspect_ratio,
    infer_scene_fields,
    retrieve_context_snippets,
)


def temp_root() -> Path:
    base = Path.cwd() / ".tmp" / "test_runs"
    base.mkdir(parents=True, exist_ok=True)
    root = base / uuid.uuid4().hex
    root.mkdir()
    return root


class PromptDocFactoryTests(unittest.TestCase):
    def test_infers_scene_fields_from_user_theme(self):
        fields = infer_scene_fields("高松灯在雨天便利店门口抱着歌词本等人")

        self.assertIn("等待", fields["mood"])
        self.assertIn("街灯", fields["lighting"])
        self.assertIn("不要整张蓝灰", fields["color_palette"])
        self.assertIn("雨痕", fields["outfit"])
        self.assertEqual(infer_aspect_ratio("MyGO 五人团队直播", "MyGO"), "16:9")

    def test_infers_bright_palette_for_daylight_theme(self):
        fields = infer_scene_fields("千早爱音和高松灯在白天步行街旅行约会")

        self.assertIn("明亮自然曝光", fields["color_palette"])
        self.assertIn("避免灰雾滤镜", fields["color_palette"])
        self.assertIn("旅行街拍", fields["shot"])
        self.assertIn("明亮自然日光", fields["lighting"])
        self.assertNotIn("雨痕", fields["outfit"])

    def test_specific_palette_beats_general_travel_keyword(self):
        fields = infer_scene_fields("千早爱音和高松灯黄昏旅行散步")

        self.assertIn("黄金时刻", fields["lighting"])
        self.assertIn("暖金色高光", fields["color_palette"])

    def test_retrieves_relevant_context_snippets(self):
        root = temp_root()
        specs = root / "specs"
        specs.mkdir()
        (specs / "story_bible.md").write_text(
            "# 素材库\n\n- 直播陪伴：弹幕反光、切片视频、半开摄像头但不露脸。\n"
            "- 雨：便利店门口、湿地反光和街灯适合表达等待。\n",
            encoding="utf-8",
        )

        snippets = retrieve_context_snippets(specs, "高松灯雨天便利店门口等人", max_snippets=2)

        self.assertTrue(any("便利店门口" in snippet.text for snippet in snippets))

    def test_build_copy_prompt_includes_delivery_details(self):
        profile = get_platform_profile("generic")
        snippets = [ContextSnippet("story_bible.md", 3, "雨：便利店门口、湿地反光和街灯适合表达等待。", 20)]
        record = {
            "character": "高松灯",
            "scene": "高松灯在雨天便利店门口抱着歌词本等人",
            "mood": "安静等待",
            "shot": "50mm 中近景",
            "lighting": "便利店白光和雨夜街灯",
            "color_palette": "雨天偏冷但保留街灯暖色和自然肤色，不要整张蓝灰",
            "reference_images": [{"id": "tomori_ref", "notes": "紫灰短发、柔软圆脸"}],
        }

        prompt = build_copy_prompt(record, record["scene"], profile, "3:2", snippets)

        self.assertIn("3:2", prompt)
        self.assertIn("tomori_ref", prompt)
        self.assertIn("二次元/原作图优先锁定角色相似度", prompt)
        self.assertIn("便利店门口", prompt)
        self.assertIn("色彩和曝光", prompt)
        self.assertIn("不要整张蓝灰", prompt)
        self.assertIn("全局冷灰低饱和", prompt)

    def test_build_copy_prompt_prefers_social_media_style_and_character_identity(self):
        profile = get_platform_profile("generic")
        record = {
            "character": "MyGO",
            "scene": "MyGO 五人练习室日常，像朋友随手拍的打卡照",
            "mood": "温馨日常",
            "shot": "35mm 中景",
            "lighting": "傍晚窗光",
            "color_palette": "",
            "reference_images": [],
        }

        prompt = build_copy_prompt(record, record["scene"], profile, "16:9", [])

        self.assertIn("社交媒体日常打卡风格照片", prompt)
        self.assertIn("脸型、眉眼气质、表情习惯、动作姿态", prompt)
        self.assertIn("乐器物件只作辅助", prompt)
        for name in ["高松灯", "千早爱音", "要乐奈", "长崎素世", "椎名立希"]:
            self.assertIn(name, prompt)
        self.assertIn("角色分槽锁定", prompt)
        self.assertIn("高松灯：灰紫色短层次", prompt)
        self.assertIn("muted gray-violet short layered bob", prompt)
        self.assertIn("长崎素世：蜂蜜棕顺滑长发", prompt)
        self.assertIn("蜂蜜棕顺滑长发", prompt)
        for banned in [
            "电影纪录片风格",
            "realistic cinematic documentary photo",
            "natural skin texture",
            "restrained emotional storytelling",
            "关键道具色块",
            "道具锚点",
        ]:
            self.assertNotIn(banned, prompt)

    def test_build_negative_prompt_omits_legacy_negative_terms(self):
        root = temp_root()
        specs = root / "specs"
        specs.mkdir()
        (specs / "negative_rules.md").write_text(
            "\n".join(
                [
                    "# 负面规则",
                    "- 欧美脸。",
                    "- 情侣写真感。",
                    "- 过度亲密肢体接触。",
                    "- 挑逗姿势。",
                    "- 泳装性化。",
                    "- 臀胸特写。",
                    "- 写真棚感。",
                    "- 商业偶像营业。",
                    "- 不要把红色吉他或吉他包省掉。",
                    "- 动漫脸。",
                ]
            ),
            encoding="utf-8",
        )

        negative = build_negative_prompt(specs)

        self.assertEqual(negative, "欧美脸、动漫脸")

    def test_copy_prompt_uses_compact_ordered_budget(self):
        profile = get_platform_profile("generic")
        record = {
            "character": "MyGO",
            "scene": "MyGO 五人中国城市旅行自拍，爱音举手机，灯靠近看屏幕，乐奈背吉他包，素世整理饮料，立希看路线",
            "mood": "明亮旅行、朋友随手拍",
            "shot": "35mm 手机广角中景",
            "lighting": "明亮自然日光",
            "color_palette": "",
            "reference_images": [
                {
                    "id": "mygo_group_closeup",
                    "notes": "MyGO 五人近景群像：头发颜色、脸部气质、蓝白黑主配色、队伍密度。",
                    "reference_tier": "identity_anchor",
                    "roles": ["group", "faces"],
                },
                {
                    "id": "mygo_realized_group_selfie",
                    "notes": "满意现实化群像自拍：手机广角、前后层次、边缘人物可见。",
                    "reference_tier": "realized_translation",
                    "roles": ["realized", "group", "photo_style"],
                },
            ],
        }

        prompt = build_copy_prompt(record, record["scene"], profile, "3:4", [])

        self.assertLess(len(prompt), 3000)
        self.assertLess(prompt.index("角色分槽锁定"), prompt.index("色彩和曝光"))
        self.assertLess(prompt.index("角色分槽锁定"), prompt.index("参考图权重策略"))
        self.assertIn("mygo_group_closeup（二次元/原作图优先锁定角色相似度）", prompt)
        self.assertIn("mygo_realized_group_selfie（现实化辅助：只转译材质/比例）", prompt)

    def test_copy_prompt_filters_incompatible_context_snippets(self):
        profile = get_platform_profile("generic")
        record = {
            "character": "MyGO",
            "scene": "mygo五人在中国的午后日常",
            "mood": "",
            "shot": "35mm 中景",
            "lighting": "",
            "color_palette": "",
            "reference_images": [],
        }
        snippets = [
            ContextSnippet(
                "references/mygo_realized_good_results.md",
                161,
                "舞台、Live House 与演出近景：主唱握麦克风，舞台冷蓝光。",
                20,
            ),
            ContextSnippet(
                "references/mygo_realized_good_results.md",
                286,
                "总体成功规律：场景越具体越稳：露天咖啡桌、江边栏杆、夜市台阶。",
                12,
            ),
        ]

        prompt = build_copy_prompt(record, record["scene"], profile, "16:9", snippets)

        self.assertNotIn("Live House", prompt)
        self.assertNotIn("舞台冷蓝光", prompt)
        self.assertIn("露天咖啡桌", prompt)

    def test_build_negative_prompt_adds_context_specific_rules(self):
        root = temp_root()
        specs = root / "specs"
        specs.mkdir()
        (specs / "negative_rules.md").write_text(
            "\n".join(["# rules", "- 动漫脸。", "- 同脸。"]),
            encoding="utf-8",
        )

        negative = build_negative_prompt(specs, context="舞台 live 演出 麦克风", character="MyGO")

        self.assertIn("舞台图不要变成夸张偶像营业照或海报式摆拍", negative)

    def test_generic_profile_uses_full_face_guide(self):
        """Generic platform should use full CHARACTER_FACE_GUIDE, not short."""
        profile = get_platform_profile("generic")
        record = {
            "character": "千早爱音",
            "scene": "爱音在外滩自拍",
            "reference_images": [],
        }
        prompt = build_copy_prompt(record, record["scene"], profile, "3:4", [])
        # Full guide includes hair texture details; age/bone-structure is in global "年龄/骨相" line
        self.assertIn("东亚高中少女感", prompt)
        self.assertIn("柔和圆润青春骨相", prompt)
        self.assertIn("真实发丝质感", prompt)

    def test_midjourney_profile_uses_short_face_guide(self):
        """Midjourney platform should use CHARACTER_FACE_GUIDE_SHORT."""
        profile = get_platform_profile("midjourney")
        record = {
            "character": "千早爱音",
            "scene": "爱音在外滩自拍",
            "reference_images": [],
        }
        prompt = build_copy_prompt(record, record["scene"], profile, "3:4", [])
        # Short guide omits age prefix and detailed texture
        self.assertNotIn("15-16岁东亚高中少女", prompt)
        self.assertIn("soft sakura-pink long hair", prompt)

    def test_short_guide_has_four_minimum_anchors(self):
        """Each character's short guide must contain hair color, eye color/expression, bone structure, and anti-drift."""
        face_roles_keywords = {
            "高松灯": {"发色": ["灰紫", "gray-violet"], "瞳色": ["灰紫偏蓝灰眼眸"], "骨相": ["短圆软脸"], "反漂移": ["不要"]},
            "千早爱音": {"发色": ["樱粉", "sakura-pink"], "瞳色": ["灰蓝眼眸"], "骨相": ["圆润短脸"], "反漂移": ["不要"]},
            "要乐奈": {"发色": ["银白", "silver-white"], "瞳色": ["异色瞳"], "骨相": ["小圆脸"], "反漂移": ["不要"]},
            "长崎素世": {"发色": ["蜂蜜棕"], "瞳色": ["蓝色杏仁形眼"], "骨相": ["端正"], "反漂移": ["不要"]},
            "椎名立希": {"发色": ["烟紫黑", "长直发"], "瞳色": ["灰棕"], "骨相": ["利落"], "反漂移": ["不要"]},
            "若叶睦": {"发色": ["浅绿"], "瞳色": ["金棕"], "骨相": ["稚气柔软脸"], "反漂移": ["不要"]},
            "丰川祥子": {"发色": ["silver-gold", "ash-blonde"], "瞳色": ["灰蓝"], "骨相": ["精致克制"], "反漂移": ["不要"]},
            "三角初华": {"发色": ["暖棕", "深棕"], "瞳色": ["深棕眼眸"], "骨相": ["温柔从容"], "反漂移": ["不要"]},
        }
        for name, anchors in face_roles_keywords.items():
            guide = CHARACTER_FACE_GUIDE_SHORT.get(name, "")
            for anchor_type, keywords in anchors.items():
                found = any(kw in guide for kw in keywords)
                self.assertTrue(
                    found,
                    f"{name} short guide missing {anchor_type} anchor (expected one of {keywords}): {guide[:80]}...",
                )

    def test_generic_prompt_includes_body_integrity(self):
        """build_copy_prompt 输出包含身体结构约束和肢体负面项。"""
        profile = get_platform_profile("generic")
        record = {
            "character": "高松灯",
            "scene": "高松灯在咖啡馆窗边写歌词",
            "mood": "安静创作",
            "shot": "50mm 中近景",
            "lighting": "柔和窗光",
            "color_palette": "",
            "reference_images": [],
        }

        prompt = build_copy_prompt(record, record["scene"], profile, "3:4", [])

        self.assertIn("每人只有两条手臂", prompt)
        self.assertIn("关节连续自然", prompt)
        self.assertIn("多余手臂", prompt)
        self.assertIn("肢体和衣服", prompt)

    def test_sitting_scene_triggers_enhanced_guardrail(self):
        """含坐姿关键词的场景触发加强版身体约束。"""
        guardrail = body_integrity_guardrail("高松灯坐在草地台阶上抱膝")

        self.assertIn("每人只有两条手臂", guardrail)
        self.assertIn("复杂姿态", guardrail)
        self.assertIn("不得裁掉", guardrail)

    def test_standing_scene_uses_base_guardrail(self):
        """普通站姿场景只使用基础身体约束，不触发加强。"""
        guardrail = body_integrity_guardrail("高松灯在便利店门口等人")

        self.assertIn("每人只有两条手臂", guardrail)
        self.assertNotIn("复杂姿态", guardrail)

    def test_negative_prompt_includes_body_terms(self):
        """build_negative_prompt 输出包含肢体融合/缺失项。"""
        root = temp_root()
        specs = root / "specs"
        specs.mkdir()
        (specs / "negative_rules.md").write_text(
            "\n".join(["# rules", "- 动漫脸。"]),
            encoding="utf-8",
        )

        negative = build_negative_prompt(specs, context="日常", character="高松灯")

        self.assertIn("多余手臂", negative)
        self.assertIn("关节断裂", negative)

    def test_parse_scene_list_numbered_scenes(self):
        """编号场景 (1)-(10) 应被正确解析为独立场景。"""
        theme = "场景覆盖：(1)故宫红墙前五人合照。(2)上海外滩夜景霓虹灯下自拍。(3)成都大熊猫基地抱熊猫玩偶。(4)西安古城墙骑双人自行车。(5)丽江古城石板路上逛街。(6)桂林漓江竹筏上弹吉他。(7)北京胡同里吃糖葫芦。(8)杭州西湖断桥边撑伞。(9)重庆洪崖洞夜景阶梯合影。(10)厦门鼓浪屿海边弹琴。"

        scenes = _parse_scene_list(theme)

        self.assertEqual(len(scenes), 10)
        self.assertIn("故宫红墙", scenes[0])
        self.assertIn("厦门鼓浪屿", scenes[-1])

    def test_parse_scene_list_multi_sentence_scenes(self):
        """多句非编号场景应被正确拼合，过滤尾部全局指令。"""
        theme = "场景覆盖：故宫红墙前五人合照、上海外滩夜景霓虹灯下自拍、成都大熊猫基地抱熊猫玩偶。场景覆盖：丽江古城石板路上逛街、桂林漓江竹筏上弹吉他、北京胡同里吃糖葫芦。每张图都要可爱"

        scenes = _parse_scene_list(theme)

        self.assertEqual(len(scenes), 6)
        self.assertIn("故宫红墙", scenes[0])
        self.assertIn("北京胡同", scenes[-1])
        # Trailing global marker should be filtered out
        for scene in scenes:
            self.assertFalse(scene.startswith("每张"), f"Global marker leaked into scenes: {scene}")


if __name__ == "__main__":
    unittest.main()
