# -*- coding: utf-8 -*-
"""Chặng 1A-2 — khóa số hiệu chỉ tiêu 01/GTGT trên seed vas.tax.

Bảng EXPECTED viết cứng theo mẫu 01/GTGT TT 80/2021
(PDF docs/nguon/TT 80/2021_969 + 970_80-2021-TT-BTC.pdf, trang 18).
Sửa seed sai → ca này gãy ngay, không đợi lập tờ khai.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


# code → (declaration_value_tag, declaration_tax_tag|False)
# False = trống có chủ đích (không ghi '0').
EXPECTED_01_GTGT_TAGS = {
    'GTGT_EXEMPT': ('26', False),       # II.1 không chịu — chỉ cột giá trị
    'GTGT_NON_TAXABLE': ('32a', False), # II.2.d không tính thuế
    'GTGT_0': ('29', False),            # II.2.a 0% — mẫu chỉ có [29]
    'GTGT_5': ('30', '31'),             # II.2.b 5%
    'GTGT_8': ('32', '33'),             # NQ 204: giảm từ 10% → [32]/[33] + phụ lục
    'GTGT_10': ('32', '33'),            # II.2.c 10%
}


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_1a2')
class TestGtgtChang1A2DeclarationTags(TransactionCase):
    """Khóa số hiệu chỉ tiêu seed ↔ bảng cứng từ mẫu 01/GTGT."""

    def setUp(self):
        super().setUp()
        self.regime = self.env.ref('connecta_vas.vas_regime_tt133')
        self.Tax = self.env['vas.tax']

    def _tags_of(self, tax):
        value = tax.declaration_value_tag or False
        tax_tag = tax.declaration_tax_tag or False
        return (value, tax_tag)

    def test_1a2_lock_seed_matches_01_gtgt(self):
        """Mỗi mức seed khớp bảng số hiệu cứng (giá trị + tiền thuế)."""
        taxes = self.Tax.search([('regime_id', '=', self.regime.id)])
        by_code = {t.code: t for t in taxes}
        self.assertTrue(
            set(EXPECTED_01_GTGT_TAGS) <= set(by_code),
            'Thiếu mức trong seed: %s' % (set(EXPECTED_01_GTGT_TAGS) - set(by_code)),
        )
        for code, expected in EXPECTED_01_GTGT_TAGS.items():
            actual = self._tags_of(by_code[code])
            self.assertEqual(
                actual, expected,
                'Sai chỉ tiêu %s: seed=%s expected=%s' % (code, actual, expected),
            )
        tax8 = by_code['GTGT_8']
        self.assertEqual(
            tax8.declaration_annex_tag, 'NQ204',
            '8% phải gắn phụ lục NQ204 đồng thời với [32]/[33]',
        )

    def test_1a2_lock_detects_wrong_seed_edit(self):
        """Cố tình sửa sai một mức → assert khóa gãy (rồi rollback)."""
        tax = self.Tax.search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', 'GTGT_10'),
        ], limit=1)
        self.assertTrue(tax)
        # Sai kiểu cũ: nhầm chỉ tiêu mua vào [23]
        tax.write({
            'declaration_value_tag': '23',
            'declaration_tax_tag': '24',
        })
        with self.assertRaises(AssertionError):
            expected = EXPECTED_01_GTGT_TAGS['GTGT_10']
            self.assertEqual(self._tags_of(tax), expected)
