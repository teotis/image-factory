import unittest

from image_factory.batch import build_requests


class BatchTests(unittest.TestCase):
    def test_build_request_shape(self):
        requests = build_requests(
            [{"custom_id": "batch_001_001", "prompt": "hello", "reference_images": [{"path": "/tmp/ref.jpg"}]}],
            model="gpt-image-1.5",
            size="1024x1536",
            quality="medium",
            output_format="png",
        )

        self.assertEqual(requests[0]["method"], "POST")
        self.assertEqual(requests[0]["url"], "/v1/images/generations")
        self.assertEqual(requests[0]["body"]["model"], "gpt-image-1.5")
        self.assertEqual(requests[0]["body"]["prompt"], "hello")
        self.assertNotIn("reference_images", requests[0]["body"])


if __name__ == "__main__":
    unittest.main()
