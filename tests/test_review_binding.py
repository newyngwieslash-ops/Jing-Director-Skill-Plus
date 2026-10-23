"""Synthetic byte-binding declarations are not genuine human approvals."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_integrity_regressions import fixture, media, png
from director_core import digest
from director_render import render_html, render_png, review_label


class ReviewBindingTests(unittest.TestCase):
    def test_matching_bytes_identifies_only_binding_not_real_approval(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); root=Path(t); media(d,root)
            label=review_label(d['shots'][0]['keyframes'][0],d,root)
            self.assertIn('字节绑定已核验',label)
            self.assertIn('不认证审核人',label)
            self.assertIn(digest(png()),label)

    def test_stale_output_is_not_shown_as_verified(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); root=Path(t); media(d,root); k=d['shots'][0]['keyframes'][0]
            changed=png()+b'changed'; (root/k['image_path']).write_bytes(changed)
            label=review_label(k,d,root)
            self.assertIn('未核验/已失效',label)
            self.assertNotIn('字节绑定已核验',label)
            self.assertIn(digest(changed),label)
            html=render_html(d,root)
            self.assertIn('未核验/已失效',html)
            self.assertIn('合同审批声明（未独立核验）',html)

    def test_stale_input_also_invalidates_binding_label(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); root=Path(t); media(d,root)
            (root/d['assets'][0]['path']).write_bytes(png()+b'changed')
            self.assertIn('未核验/已失效',review_label(d['shots'][0]['keyframes'][0],d,root))

    def test_missing_review_hash_is_not_verified(self):
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); root=Path(t); media(d,root); k=d['shots'][0]['keyframes'][0]
            del k['visual_review']['reviewed_sha256']
            self.assertNotIn('字节绑定已核验',review_label(k,d,root))

    def test_missing_draft_images_still_render(self):
        with tempfile.TemporaryDirectory() as t:
            html=render_html(fixture(),t)
            self.assertIn('未生成',html)
            self.assertIn('合同声明 unreviewed（未核验）',html)

    def test_png_uses_same_label_helper(self):
        font=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        if not font.exists(): self.skipTest('Local font unavailable')
        with tempfile.TemporaryDirectory() as t:
            d=fixture(); root=Path(t)
            with patch('director_render.review_label',return_value='TEST_ONLY unverified') as label:
                render_png(d,root,root/'review.png',str(font))
                self.assertEqual(label.call_count,len(d['shots'][0]['keyframes']))
            self.assertTrue((root/'review.png').is_file())


if __name__=='__main__': unittest.main()
