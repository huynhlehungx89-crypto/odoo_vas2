# -*- coding: utf-8 -*-
"""Chặng 1A — thuế suất lên sổ VAS (danh mục + engine + backfill)."""
from odoo import fields
from odoo.tests import tagged

from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang0 import (
    TestGtgtChang0SeedAndMeasure,
)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_1a')
class TestGtgtChang1A(TestGtgtChang0SeedAndMeasure):
    """Kế thừa bộ gieo C0 (đã dời 08/2026) + ca nghiệm thu 1A."""

    def test_1a_a_period_2026_and_jan_2027(self):
        """A — bộ thử kỳ 08/2026 + HĐ 01/2027."""
        self.assertEqual(str(self.seed['sale_10'].invoice_date), '2026-08-10')
        self.assertEqual(
            str(self.seed['sale_10_after_nq204'].invoice_date), '2027-01-15',
        )
        self.assertEqual(
            str(self.seed['sale_8_expired'].invoice_date), '2027-01-15',
        )
        rates = {
            t.amount
            for line in self.seed['sale_10_after_nq204'].invoice_line_ids
            for t in line.tax_ids
        }
        self.assertEqual(rates, {10.0})

    def test_1a_b_tax_catalog_six_levels(self):
        """B — danh mục đủ 6 mức + suất/phạm vi/hiệu lực/chỉ tiêu."""
        Tax = self.env['vas.tax']
        taxes = Tax.search([('regime_id', '=', self.regime.id)])
        by_code = {t.code: t for t in taxes}
        required = {
            'GTGT_EXEMPT', 'GTGT_NON_TAXABLE', 'GTGT_0',
            'GTGT_5', 'GTGT_8', 'GTGT_10',
        }
        self.assertTrue(required <= set(by_code), set(by_code))
        for code in required:
            t = by_code[code]
            self.assertTrue(t.declaration_value_tag, code)
            # declaration_tax_tag có thể trống có chủ đích (không phát sinh tiền thuế)
            self.assertTrue(t.tax_scope, code)
            self.assertTrue(t.date_start, code)
            self.assertIn(t.match_mode, ('empty_line', 'rate'), code)
        self.assertEqual(str(by_code['GTGT_8'].date_end), '2026-12-31')
        self.assertFalse(by_code['GTGT_10'].date_end)
        self.assertEqual(by_code['GTGT_EXEMPT'].match_mode, 'empty_line')
        self.assertEqual(by_code['GTGT_0'].rate, 0.0)
        self.assertEqual(by_code['GTGT_5'].rate, 5.0)
        self.assertEqual(by_code['GTGT_8'].rate, 8.0)
        self.assertEqual(by_code['GTGT_10'].rate, 10.0)

    def test_1a_c_sale_multi_split(self):
        """C — HĐ bán đa suất → đúng số dòng thuế + tax_id."""
        self._sync()
        inv = self.seed['sale_multi']
        moves = self._vas_for_invoice(inv)
        tax_lines = self._tax_lines(moves)
        self.assertEqual(len(tax_lines), 2, tax_lines.mapped('credit'))
        codes = set(tax_lines.mapped('tax_id.code'))
        self.assertEqual(codes, {'GTGT_5', 'GTGT_10'})
        by_code = {l.tax_id.code: l.credit for l in tax_lines}
        self.assertAlmostEqual(by_code['GTGT_10'], 100_000.0)
        self.assertAlmostEqual(by_code['GTGT_5'], 100_000.0)
        rev = moves.mapped('line_ids').filtered(
            lambda l: (l.account_id.code or '').startswith('511')
        )
        self.assertEqual(len(rev), 2)
        self.assertEqual(set(rev.mapped('tax_id.code')), {'GTGT_5', 'GTGT_10'})

    def test_1a_d_purchase_multi_split(self):
        """D — HĐ mua đa suất → tách dòng + tax_id."""
        self._sync()
        inv = self.seed['purchase_multi']
        moves = self._vas_for_invoice(inv)
        tax_lines = self._tax_lines(moves)
        self.assertEqual(len(tax_lines), 2)
        codes = set(tax_lines.mapped('tax_id.code'))
        self.assertEqual(codes, {'GTGT_5', 'GTGT_10'})
        exp = moves.mapped('line_ids').filtered(
            lambda l: (l.account_id.code or '').startswith('642')
        )
        self.assertGreaterEqual(len(exp), 2)
        self.assertTrue(all(l.tax_id for l in exp), exp.mapped('tax_id'))

    def test_1a_e_zero_and_exempt_revenue_tagged(self):
        """E — 0% và không chịu: dòng DT có tax_id dù không có dòng thuế."""
        self._sync()
        for key, code in (('sale_0_export', 'GTGT_0'), ('sale_exempt', 'GTGT_EXEMPT')):
            inv = self.seed[key]
            moves = self._vas_for_invoice(inv)
            self.assertTrue(moves, key)
            tax_lines = self._tax_lines(moves)
            self.assertFalse(tax_lines, f'{key} không được sinh dòng thuế')
            rev = moves.mapped('line_ids').filtered(
                lambda l: (l.account_id.code or '').startswith('511')
            )
            self.assertTrue(rev, key)
            self.assertTrue(all(l.tax_id.code == code for l in rev), rev.mapped('tax_id.code'))
            self.assertTrue(all(l.tax_status == 'resolved' for l in rev))

    def test_1a_f_tax_amount_matches_odoo(self):
        """F — tổng thuế theo dòng VAS = amount_tax Odoo."""
        self._sync()
        deltas = []
        for key, inv in sorted(
            ((k, v) for k, v in self.seed.items() if v._name == 'account.move'),
            key=lambda x: x[0],
        ):
            moves = self._vas_for_invoice(inv)
            vas_tax = sum(
                abs(l.debit - l.credit) for l in self._tax_lines(moves)
            )
            delta = round(vas_tax - abs(inv.amount_tax or 0.0), 2)
            if delta:
                deltas.append((key, inv.amount_tax, vas_tax, delta))
        self.assertFalse(deltas, f'Lệch tiền thuế: {deltas}')

    def test_1a_g_backfill_invariant(self):
        """G — backfill: số bút toán + tổng thuế theo TK trước/sau bằng nhau."""
        self._sync()
        Sync = self.env['vas.sync']
        before = Sync._snapshot_tax_ledger(
            self.company, '2026-01-01', '2027-12-31',
        )
        # Gỡ tax_id giả lập sổ cũ rồi backfill lại
        moves = self.env['vas.move'].search([
            ('company_id', '=', self.company.id),
            ('state', '=', 'posted'),
            ('source_model', '=', 'account.move'),
            ('date', '>=', '2026-01-01'),
            ('date', '<=', '2027-12-31'),
        ])
        lines = moves.mapped('line_ids').filtered('tax_id')
        lines.with_context(
            vas_allow_posted_write=True,
            vas_skip_period_check=True,
        ).write({'tax_id': False, 'tax_status': 'none'})
        result = Sync.backfill_line_tax_ids(
            self.company, '2026-01-01', '2027-12-31',
        )
        self.assertEqual(result['before']['move_count'], result['after']['move_count'])
        self.assertEqual(
            result['before']['tax_by_account'], result['after']['tax_by_account'],
        )
        self.assertEqual(before['move_count'], result['after']['move_count'])
        self.assertEqual(before['tax_by_account'], result['after']['tax_by_account'])
        self._dump('1A_G_backfill', result)

    def test_1a_h_eight_percent_expired_undetermined(self):
        """H — HĐ 8% ngày 01/2027: ngoài hiệu lực, không gán lặng lẽ."""
        self._sync()
        inv = self.seed['sale_8_expired']
        moves = self._vas_for_invoice(inv)
        self.assertTrue(moves)
        tagged = moves.mapped('line_ids').filtered(
            lambda l: (l.account_id.code or '').startswith('511')
            or (l.account_id.code or '') == '33311'
        )
        self.assertTrue(tagged)
        self.assertTrue(
            all(l.tax_status == 'undetermined' for l in tagged),
            tagged.mapped('tax_status'),
        )
        self.assertFalse(any(l.tax_id for l in tagged), tagged.mapped('tax_id'))
        # Đối chứng: 10% cùng ngày vẫn resolve
        ok = self.seed['sale_10_after_nq204']
        ok_moves = self._vas_for_invoice(ok)
        ok_tax = self._tax_lines(ok_moves)
        self.assertEqual(ok_tax.tax_id.code, 'GTGT_10')
