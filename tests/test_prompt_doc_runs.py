from pathlib import Path
import unittest
import uuid

from image_factory import prompt_doc_runs


def temp_root() -> Path:
    base = Path.cwd() / ".tmp" / "test_runs"
    base.mkdir(parents=True, exist_ok=True)
    root = base / uuid.uuid4().hex
    root.mkdir()
    return root


class PromptDocRunsTests(unittest.TestCase):
    def test_parses_project_embedded_html_prompt_and_metadata(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<!doctype html>
<html><head><title>MyGO 团队直播 - 图片生成 Prompt 文档</title></head>
<body>
<p class="lead">主题：MyGO 团队直播</p>
<span>通用外站</span><span>画幅：16:9</span><span>角色/对象：MyGO</span>
<h2>推荐主 Prompt</h2><pre>main prompt text</pre>
<h2>完整规格 Prompt</h2><pre>full prompt text</pre>
</body></html>""",
            encoding="utf-8",
        )

        doc = prompt_doc_runs.parse_prompt_doc_html(html)
        naming = prompt_doc_runs.infer_output_naming(html, doc.theme)

        self.assertEqual(doc.theme, "MyGO 团队直播")
        self.assertEqual(doc.prompt, "main prompt text")
        self.assertEqual(doc.aspect_ratio, "16:9")
        self.assertEqual(doc.character, "MyGO")
        self.assertEqual(naming.prefix, "20260430_mygo_live_stream")

    def test_parses_variant_prompt_blocks(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_china_checkin_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<!doctype html>
<html><body>
<h2>推荐主 Prompt</h2><pre>main prompt</pre>
<h2>分镜/变体</h2>
<section class="variant"><h3>01 北京故宫</h3><pre>forbidden city prompt</pre></section>
<section class="variant"><h3>02 长城</h3><pre>great wall prompt</pre></section>
</body></html>""",
            encoding="utf-8",
        )

        doc = prompt_doc_runs.parse_prompt_doc_html(html)

        self.assertEqual(doc.prompt, "main prompt")
        self.assertEqual([variant.title for variant in doc.variants], ["01 北京故宫", "02 长城"])
        self.assertEqual([variant.prompt for variant in doc.variants], ["forbidden city prompt", "great wall prompt"])

    def test_plans_paths_without_api_calls(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text("<h2>推荐主 Prompt</h2><pre>prompt</pre>", encoding="utf-8")
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream_e8ce0150"
        out.mkdir(parents=True)
        (out / "20260430_mygo_live_stream_e8ce0150_001.png").write_bytes(b"old")

        manifest = prompt_doc_runs.generate_until_target(html, target_count=3, output_dir=out)

        self.assertEqual(manifest["status"], "planned")
        self.assertEqual(manifest["provider"], prompt_doc_runs.DEFAULT_PROVIDER)
        self.assertEqual(manifest["existing_count"], 1)
        self.assertEqual(manifest["remaining_count"], 2)
        self.assertEqual(manifest["review"]["status"], "not_reviewed")
        self.assertIn("character_identity", manifest["review"]["criteria"])
        self.assertIn("body_integrity", manifest["review"]["criteria"])
        self.assertEqual(
            [Path(path).name for path in manifest["planned_paths"]],
            ["20260430_mygo_live_stream_e8ce0150_002.png", "20260430_mygo_live_stream_e8ce0150_003.png"],
        )
        self.assertTrue((out / "manifest.json").exists())

    def test_resolves_popular_size_from_explicit_doc_aspect_ratio(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<span>画幅：16:9</span>
<h2>推荐主 Prompt</h2><pre>prompt</pre>""",
            encoding="utf-8",
        )
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream"

        manifest = prompt_doc_runs.generate_until_target(html, target_count=1, output_dir=out)

        self.assertEqual(manifest["requested_size"], prompt_doc_runs.DEFAULT_SIZE)
        self.assertEqual(manifest["size"], "3840x2160")
        self.assertEqual(manifest["size_source"], "aspect_ratio:16:9")

    def test_resolves_custom_supported_size_from_doc_aspect_ratio(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_pair_daily_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<span>画幅：3:4</span>
<h2>推荐主 Prompt</h2><pre>prompt</pre>""",
            encoding="utf-8",
        )
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_pair_daily"

        manifest = prompt_doc_runs.generate_until_target(html, target_count=1, output_dir=out)

        self.assertEqual(manifest["size"], "2448x3264")
        self.assertEqual(manifest["size_source"], "aspect_ratio:3:4")

    def test_execute_passes_effective_size_to_provider(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<span>画幅：16:9</span>
<h2>推荐主 Prompt</h2><pre>prompt</pre>""",
            encoding="utf-8",
        )
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream"
        seen = {}

        original_generate_images = prompt_doc_runs.generate_images
        try:
            def fake_generate_images(*args, **kwargs):
                seen["size"] = kwargs.get("size")
                seen["aspect_ratio"] = kwargs.get("aspect_ratio")
                return {"data": [{"b64_json": "aW1hZ2U=", "revised_prompt": "revised"}]}

            prompt_doc_runs.generate_images = fake_generate_images
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=1,
                output_dir=out,
                execute=True,
                allow_api=True,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images

        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(seen["size"], "3840x2160")
        self.assertIsNone(seen["aspect_ratio"])

    def test_auto_plan_uses_variant_prompts_when_available(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260506_mygo_china_checkin_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<h2>推荐主 Prompt</h2><pre>main prompt</pre>
<h2>分镜/变体</h2>
<section class="variant"><h3>01 北京故宫</h3><pre>forbidden city prompt</pre></section>
<section class="variant"><h3>02 长城</h3><pre>great wall prompt</pre></section>""",
            encoding="utf-8",
        )
        out = root / "outputs" / "prompt_docs" / "20260506_mygo_china_checkin"

        manifest = prompt_doc_runs.generate_until_target(html, target_count=2, output_dir=out)

        self.assertEqual(manifest["prompt_source"], "variants")
        self.assertEqual(manifest["available_variant_count"], 2)
        self.assertEqual([item["prompt_title"] for item in manifest["prompt_plan"]], ["01 北京故宫", "02 长城"])
        self.assertNotIn("main prompt", manifest["prompt_plan"][0]["prompt_preview"])

    def test_existing_count_ignores_non_sequence_files(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text("<h2>推荐主 Prompt</h2><pre>prompt</pre>", encoding="utf-8")
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream_e8ce0150"
        out.mkdir(parents=True)
        (out / "20260430_mygo_live_stream_e8ce0150_001.png").write_bytes(b"old")
        (out / "20260430_mygo_live_stream_e8ce0150_draft.png").write_bytes(b"draft")
        (out / "20260430_mygo_live_stream_e8ce0150_abc.png").write_bytes(b"abc")

        manifest = prompt_doc_runs.generate_until_target(html, target_count=2, output_dir=out)

        self.assertEqual(manifest["existing_count"], 1)
        self.assertEqual(
            [Path(path).name for path in manifest["planned_paths"]],
            ["20260430_mygo_live_stream_e8ce0150_002.png"],
        )

    def test_corrupt_html_metadata_falls_back_to_filename(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "raana_outdoor_daily_external_prompt_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            "<title>???????? - ???? Prompt ??</title><p>???????????</p><h2>推荐主 Prompt</h2><pre>prompt</pre>",
            encoding="utf-8",
        )

        doc = prompt_doc_runs.parse_prompt_doc_html(html)
        naming = prompt_doc_runs.infer_output_naming(html, doc.theme, date="20260430")

        self.assertEqual(doc.theme, "raana_outdoor_daily_external_prompt")
        self.assertEqual(naming.prefix, "20260430_raana_outdoor_daily_external")

    def test_execute_saves_images_until_target(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text("<h2>推荐主 Prompt</h2><pre>prompt</pre>", encoding="utf-8")
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream_e8ce0150"

        original_generate_images = prompt_doc_runs.generate_images
        try:
            prompt_doc_runs.generate_images = lambda *args, **kwargs: {
                "data": [{"b64_json": "aW1hZ2U=", "revised_prompt": "revised"}]
            }
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=2,
                output_dir=out,
                execute=True,
                allow_api=True,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images

        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["existing_count"], 2)
        self.assertEqual((out / "20260430_mygo_live_stream_e8ce0150_001.png").read_bytes(), b"image")
        self.assertEqual((out / "20260430_mygo_live_stream_e8ce0150_002.png").read_bytes(), b"image")

    def test_execute_writes_running_manifest_before_first_api_response(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text("<h2>推荐主 Prompt</h2><pre>prompt</pre>", encoding="utf-8")
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream_e8ce0150"
        seen = {}

        original_generate_images = prompt_doc_runs.generate_images
        try:
            def fake_generate_images(*args, **kwargs):
                seen["status_before_response"] = prompt_doc_runs.read_json(out / "manifest.json")["status"]
                return {"data": [{"b64_json": "aW1hZ2U=", "revised_prompt": "revised"}]}

            prompt_doc_runs.generate_images = fake_generate_images
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=1,
                output_dir=out,
                execute=True,
                allow_api=True,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images

        self.assertEqual(seen["status_before_response"], "running")
        self.assertEqual(manifest["status"], "complete")

    def test_execute_sends_each_variant_prompt_separately(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260506_mygo_china_checkin_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<h2>推荐主 Prompt</h2><pre>main prompt that should not be sent</pre>
<h2>分镜/变体</h2>
<section class="variant"><h3>01 北京故宫</h3><pre>forbidden city prompt</pre></section>
<section class="variant"><h3>02 长城</h3><pre>great wall prompt</pre></section>""",
            encoding="utf-8",
        )
        out = root / "outputs" / "prompt_docs" / "20260506_mygo_china_checkin"
        calls = []

        original_generate_images = prompt_doc_runs.generate_images
        try:
            def fake_generate_images(prompt, *args, **kwargs):
                calls.append((prompt, kwargs.get("images_per_prompt")))
                return {"data": [{"b64_json": "aW1hZ2U=", "revised_prompt": prompt}]}

            prompt_doc_runs.generate_images = fake_generate_images
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=2,
                output_dir=out,
                execute=True,
                allow_api=True,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images

        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(calls, [("forbidden city prompt", 1), ("great wall prompt", 1)])
        self.assertEqual([item["prompt_title"] for item in manifest["generated"]], ["01 北京故宫", "02 长城"])
        self.assertEqual(manifest["images_per_call"], 1)

    def test_execute_retries_transient_generation_errors(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260506_mygo_china_checkin_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<h2>推荐主 Prompt</h2><pre>main prompt</pre>
<h2>分镜/变体</h2>
<section class="variant"><h3>01 北京故宫</h3><pre>forbidden city prompt</pre></section>""",
            encoding="utf-8",
        )
        out = root / "outputs" / "prompt_docs" / "20260506_mygo_china_checkin"
        calls = []

        class TransientImageError(Exception):
            status_code = 520

        original_generate_images = prompt_doc_runs.generate_images
        original_sleep = prompt_doc_runs.time.sleep
        try:
            def fake_generate_images(prompt, *args, **kwargs):
                calls.append(prompt)
                if len(calls) == 1:
                    raise TransientImageError("retryable origin error")
                return {"data": [{"b64_json": "aW1hZ2U=", "revised_prompt": prompt}]}

            prompt_doc_runs.generate_images = fake_generate_images
            prompt_doc_runs.time.sleep = lambda seconds: None
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=1,
                output_dir=out,
                execute=True,
                allow_api=True,
                max_attempts=2,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images
            prompt_doc_runs.time.sleep = original_sleep

        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(calls, ["forbidden city prompt", "forbidden city prompt"])
        self.assertEqual(manifest["errors"][0]["status_code"], 520)
        self.assertEqual(manifest["errors"][0]["prompt_title"], "01 北京故宫")

    def test_execute_falls_back_to_plan_after_retryable_api_errors(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260506_mygo_china_checkin_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text(
            """<h2>推荐主 Prompt</h2><pre>main prompt</pre>
<h2>分镜/变体</h2>
<section class="variant"><h3>01 北京故宫</h3><pre>forbidden city prompt</pre></section>""",
            encoding="utf-8",
        )
        out = root / "outputs" / "prompt_docs" / "20260506_mygo_china_checkin"

        class TransientImageError(Exception):
            status_code = 520

        original_generate_images = prompt_doc_runs.generate_images
        original_sleep = prompt_doc_runs.time.sleep
        try:
            prompt_doc_runs.generate_images = lambda *args, **kwargs: (_ for _ in ()).throw(
                TransientImageError("retryable origin error")
            )
            prompt_doc_runs.time.sleep = lambda seconds: None
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=1,
                output_dir=out,
                execute=True,
                allow_api=True,
                max_attempts=1,
                fallback_to_plan_on_api_error=True,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images
            prompt_doc_runs.time.sleep = original_sleep

        self.assertEqual(manifest["status"], "fallback_planned")
        self.assertEqual(manifest["existing_count"], 0)
        self.assertEqual(manifest["remaining_count"], 1)
        self.assertEqual(manifest["prompt_plan"][0]["prompt_title"], "01 北京故宫")
        self.assertIn("Provider API remained unavailable", manifest["fallback_reason"])

    def test_execute_passes_request_timeout_to_provider(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text("<h2>推荐主 Prompt</h2><pre>prompt</pre>", encoding="utf-8")
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream"
        seen = {}

        original_generate_images = prompt_doc_runs.generate_images
        try:
            def fake_generate_images(*args, **kwargs):
                seen["timeout"] = kwargs.get("timeout")
                return {"data": [{"b64_json": "aW1hZ2U=", "revised_prompt": "revised"}]}

            prompt_doc_runs.generate_images = fake_generate_images
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=1,
                output_dir=out,
                execute=True,
                allow_api=True,
                request_timeout_seconds=12.5,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images

        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(seen["timeout"], 12.5)

    def test_auto_increment_run_dir_on_collision(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text("<h2>推荐主 Prompt</h2><pre>prompt</pre>", encoding="utf-8")
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream_e8ce0150"
        out.mkdir(parents=True)
        (out / "20260430_mygo_live_stream_e8ce0150_001.png").write_bytes(b"old1")
        (out / "20260430_mygo_live_stream_e8ce0150_002.png").write_bytes(b"old2")
        (out / "20260430_mygo_live_stream_e8ce0150_003.png").write_bytes(b"old3")

        original_generate_images = prompt_doc_runs.generate_images
        try:
            prompt_doc_runs.generate_images = lambda *args, **kwargs: {
                "data": [{"b64_json": "bmV3", "revised_prompt": "new"}]
            }
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=2,
                output_dir=out,
                execute=True,
                allow_api=True,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images

        # Auto-incremented to _r2 to avoid overwriting old images
        self.assertIn("_r2", manifest["output_dir"])
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["existing_count"], 2)
        # Old directory untouched
        self.assertTrue((out / "20260430_mygo_live_stream_e8ce0150_001.png").exists())

    def test_execute_requires_explicit_resume_for_partial_base_run(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text("<h2>推荐主 Prompt</h2><pre>prompt</pre>", encoding="utf-8")
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream_e8ce0150"
        out.mkdir(parents=True)
        (out / "20260430_mygo_live_stream_e8ce0150_001.png").write_bytes(b"old")
        prompt_doc_runs.write_json(
            out / "manifest.json",
            {
                "status": "planned",
                "existing_count": 1,
                "target_count": 3,
                "review": {"status": "not_reviewed"},
            },
        )

        original_generate_images = prompt_doc_runs.generate_images
        try:
            prompt_doc_runs.generate_images = lambda *args, **kwargs: {
                "data": [{"b64_json": "bmV3", "revised_prompt": "new"}]
            }
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=2,
                output_dir=out,
                execute=True,
                allow_api=True,
            )
            resumed = prompt_doc_runs.generate_until_target(
                html,
                target_count=2,
                output_dir=out,
                execute=True,
                allow_api=True,
                resume=True,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images

        self.assertIn("_r2", manifest["output_dir"])
        self.assertEqual(resumed["output_dir"], str(out.resolve()))
        self.assertEqual(resumed["existing_count"], 2)

    def test_force_cleans_existing_and_regenerates_in_place(self):
        root = temp_root()
        html = root / "prompts" / "docs" / "20260430_mygo_live_stream_e8ce0150_embedded.html"
        html.parent.mkdir(parents=True)
        html.write_text("<h2>推荐主 Prompt</h2><pre>prompt</pre>", encoding="utf-8")
        out = root / "outputs" / "prompt_docs" / "20260430_mygo_live_stream_e8ce0150"
        out.mkdir(parents=True)
        (out / "20260430_mygo_live_stream_e8ce0150_001.png").write_bytes(b"stale")
        (out / "20260430_mygo_live_stream_e8ce0150_002.png").write_bytes(b"stale")

        original_generate_images = prompt_doc_runs.generate_images
        try:
            prompt_doc_runs.generate_images = lambda *args, **kwargs: {
                "data": [{"b64_json": "ZnJlc2g=", "revised_prompt": "fresh"}]
            }
            manifest = prompt_doc_runs.generate_until_target(
                html,
                target_count=1,
                output_dir=out,
                execute=True,
                allow_api=True,
                force=True,
            )
        finally:
            prompt_doc_runs.generate_images = original_generate_images

        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["existing_count"], 1)
        self.assertEqual((out / "20260430_mygo_live_stream_e8ce0150_001.png").read_bytes(), b"fresh")
        self.assertFalse((out / "20260430_mygo_live_stream_e8ce0150_002.png").exists())
        self.assertEqual(len(manifest["generated"]), 1)
        self.assertIn("generated_at", manifest["generated"][0])


if __name__ == "__main__":
    unittest.main()
