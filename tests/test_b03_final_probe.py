# -*- coding: utf-8 -*-
"""Probe B03 on W11 — chạy qua --test-tags=connecta_vas_b03_probe."""
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('post_install', '-at_install', 'connecta_vas_b03_probe')
class TestB03FinalProbe(TransactionCase):

    def test_probe_w11(self):
        self.env['res.company']._vas_w11_ensure_bctc_demo()
        company = self.env['res.company'].search(
            [('name', '=', 'W11-Thử BCTC')], limit=1,
        )
        p01 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-01-01'),
        ], limit=1)
        p12 = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '=', '2026-12-01'),
        ], limit=1)
        Snap = self.env['vas.report.snapshot']
        b01a = Snap.generate_b01a(company, p01, p12, hide_reversed=True)
        b02 = Snap.generate_b02(company, p01, p12, hide_reversed=True)
        b09 = Snap.generate_b09(company, p01, p12, hide_reversed=True)
        b03 = Snap.generate_b03(company, p01, p12, hide_reversed=True)

        codes = sorted(b03.line_ids.mapped('code'))
        print('B03_N', len(codes))
        by = {l.code: l.amount_closing for l in b03.line_ids}
        for c in codes:
            print('B03', c, '{:,.0f}'.format(by.get(c) or 0.0))
        print('L1_DIFF', b03.check_b03_l1_diff)
        print('L2_DIFF', b03.check_b03_l2_diff)
        print('L4_DIFF', b03.check_b03_l4_diff)
        self.assertEqual(float_compare(b03.check_b03_l1_diff or 0, 0, 2), 0)
        self.assertEqual(float_compare(b03.check_b03_l2_diff or 0, 0, 2), 0)
        self.assertEqual(float_compare(b03.check_b03_l4_diff or 0, 0, 2), 0)
        # L3 embedded in warning — print full warn
        print('WARN_LEVEL', b03.warning_level)
        print('WARN_TEXT_BEGIN')
        print(b03.warning_text or '(none)')
        print('WARN_TEXT_END')
        print(
            'B01A_110',
            b01a.line_ids.filtered(lambda l: l.code == '110').amount_closing,
        )
        print(
            'B01A_200',
            b01a.line_ids.filtered(lambda l: l.code == '200').amount_closing,
        )
        print(
            'B02_50',
            b02.line_ids.filtered(lambda l: l.code == '50').amount_closing,
        )
        print('B09_N', len(b09.line_ids))
        print(
            'VII1_KIND',
            b09.line_ids.filtered(lambda l: l.code == 'VII.1').b09_fill_kind,
        )
        print('DONE')
