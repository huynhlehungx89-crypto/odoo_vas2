# -*- coding: utf-8 -*-
"""Chặng 6 — khai bổ sung · [37]/[38] · trả chậm · khóa kỳ · tổng hợp năm."""
import logging

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import float_compare

from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang3 import (
    TestGtgtChang3Declaration,
)
from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang2 import AS_OF

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_c6')
class TestGtgtChang6Supplement(TestGtgtChang3Declaration):
    """KHBS · giải trình · kỳ điều chỉnh · trả chậm · quyết toán năm."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_chang6()

    @classmethod
    def _seed_chang6(cls):
        # Chuỗi 3 kỳ 09–11/2026 cho bảng tổng hợp
        for mon, sale, buy, tag in (
            (9, 10_000_000.0, 30_000_000.0, 'SEP'),
            (10, 12_000_000.0, 25_000_000.0, 'OCT'),
            (11, 8_000_000.0, 20_000_000.0, 'NOV'),
        ):
            d = '2026-%02d-15' % mon
            cls.seed['c6_sale_%s' % tag] = cls._make_sale(
                'C6-%s-S' % tag, cls.partner_customer, sale,
                cls.tax_sale[10], d,
            )
            bill = cls._make_bill(
                'C6-%s-B' % tag,
                cls._c2_partner('NCC C6 %s' % tag, '03006%04d' % mon),
                buy, cls.tax_purchase[10], d,
            )
            cls._pay_bill(bill, cls.bank_journal, 'c6_%s_pay' % tag.lower())
            cls.seed['c6_buy_%s' % tag] = bill

        # Hóa đơn trả chậm quá hạn (kỳ 08) — chưa thanh toán
        p_def = cls._c2_partner('NCC C6 deferred', '0300666001')
        cls.seed['c6_deferred'] = cls._make_bill(
            'C6-DEF-OVER', p_def, 7_000_000.0, cls.tax_purchase[10],
            '2026-08-05', invoice_date_due='2026-08-01',
        )

    def _file_decl(self, decl, as_of=None):
        self._sync()
        as_of = as_of or decl.date_end or AS_OF
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=decl.company_id, as_of_date=as_of,
        )
        if not decl._previous_declaration():
            decl.amount_22_manual = True
            decl.amount_22 = 0.0
        decl.action_prepare()
        decl.action_set_state_filed()
        return decl

    def _line(self, decl, code):
        return decl.line_ids.filtered(lambda l: l.code == code)[:1]

    def _set_amt(self, decl, code, amount):
        line = self._line(decl, code)
        self.assertTrue(line, 'thiếu [%s]' % code)
        line.amount = amount

    def _make_khbs_reduce_carry(self, origin, reduce_25=500_000.0):
        """Tạo KHBS làm giảm [25] → giảm [43]."""
        action = origin.action_create_supplementary()
        khbs = self.env['vas.gtgt.declaration'].browse(action['res_id'])
        cur25 = self._amt(khbs, '25')
        self._set_amt(khbs, '25', max(cur25 - reduce_25, 0))
        khbs.action_prepare()
        return khbs

    def test_c6_a_adjust_rules_documented(self):
        """Ca A — quy tắc ba tình huống có trong máy (lý do + mã chọn)."""
        Decl = self.env['vas.gtgt.declaration']
        # Giảm [43]
        self.assertEqual(
            Decl._fields['adjust_choice'].selection[0][0], 'discovery_37',
        )
        # Tăng phải nộp
        codes = [c for c, _ in Decl._fields['adjust_choice'].selection]
        self.assertIn('amend_origin', codes)
        self.assertIn('amend_origin_refund', codes)

    def test_c6_b_c_supplement_keeps_first_and_explanation(self):
        """Ca B+C — không đè lần đầu; giải trình chỉ chỉ tiêu lệch."""
        jul = self._make_decl(self.company, 2026, month=7)
        self._file_decl(jul)
        first_43 = self._amt(jul, '43')
        self.assertGreater(first_43, 0)

        khbs = self._make_khbs_reduce_carry(jul, 500_000)
        self.assertEqual(khbs.declaration_round, 1)
        self.assertEqual(khbs.base_declaration_id, jul)
        self.assertEqual(jul.state, 'filed')
        self.assertEqual(self._amt(jul, '43'), first_43)
        self.assertTrue(khbs.explanation_ids)
        for row in khbs.explanation_ids:
            self.assertNotEqual(
                float_compare(row.difference, 0.0, 2), 0,
                'giải trình không được chứa chỉ tiêu khớp',
            )
            self.assertEqual(
                float_compare(row.difference, row.amount_new - row.amount_old, 0),
                0,
            )
        self.assertNotEqual(self._amt(khbs, '43'), first_43)
        _logger.info(
            'C6-BC first_id=%s khbs_id=%s first_43=%s khbs_43=%s expl_n=%s codes=%s',
            jul.id, khbs.id, first_43, self._amt(khbs, '43'),
            len(khbs.explanation_ids),
            khbs.explanation_ids.mapped('code'),
        )

    def test_c6_d_decrease_carry_to_37(self):
        """Ca D — giảm chuyển kỳ sau → [37] kỳ phát hiện."""
        jul = self._make_decl(self.company, 2026, month=7)
        self._file_decl(jul)
        old_43 = self._amt(jul, '43')
        self.assertGreater(old_43, 0)

        khbs = self._make_khbs_reduce_carry(jul, 400_000)
        self.assertEqual(khbs.adjust_choice, 'discovery_37')
        self.assertIn('[37]', khbs.adjust_reason_auto or '')
        self.assertLess(khbs.delta_43, 0)

        aug = self._make_decl(self.company, 2026, month=8)
        khbs.discovery_declaration_id = aug
        khbs.action_set_state_filed()
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=aug.date_end,
        )
        aug.action_recompute_amounts()
        self.assertEqual(
            float_compare(self._amt(aug, '37'), abs(khbs.delta_43), 0), 0,
            ' [37] phải = |delta_43| = %s, got %s' % (
                abs(khbs.delta_43), self._amt(aug, '37'),
            ),
        )
        self.assertAlmostEqual(old_43, self._amt(jul, '43'), places=0)
        _logger.info(
            'C6-D old_43=%s delta_43=%s aug_37=%s choice=%s reason=%s',
            old_43, khbs.delta_43, self._amt(aug, '37'),
            khbs.adjust_choice, (khbs.adjust_reason_auto or '')[:120],
        )

    def test_c6_e_increase_payable_amend_origin(self):
        """Ca E — phát sinh thuế phải nộp → chọn khai bổ sung kỳ gốc."""
        jul = self._make_decl(self.company, 2026, month=7)
        self._file_decl(jul)
        khbs = self.env['vas.gtgt.declaration'].browse(
            jul.action_create_supplementary()['res_id'],
        )
        # Tăng thuế đầu ra đủ để phát sinh [40] phải nộp (lật từ [43])
        self._set_amt(khbs, '33', self._amt(khbs, '33') + 5_000_000)
        khbs.action_prepare()
        self.assertEqual(khbs.adjust_choice, 'amend_origin')
        self.assertIn('phải nộp', (khbs.adjust_reason_auto or '').lower())
        self.assertTrue(khbs.late_interest_note)
        self.assertGreater(khbs.delta_40, 0)
        _logger.info(
            'C6-E delta_40=%s delta_43=%s choice=%s late=%s',
            khbs.delta_40, khbs.delta_43, khbs.adjust_choice,
            bool(khbs.late_interest_note),
        )

    def test_c6_f_22_from_first_filing_not_khbs(self):
        """Ca F — [22] kỳ sau = [43] lần đầu, không theo KHBS."""
        jul = self._make_decl(self.company, 2026, month=7)
        self._file_decl(jul)
        first_43 = self._amt(jul, '43')
        self.assertGreater(first_43, 0)

        khbs = self._make_khbs_reduce_carry(jul, 300_000)
        khbs.action_set_state_filed()
        khbs_43 = self._amt(khbs, '43')
        self.assertNotEqual(first_43, khbs_43)

        aug = self._make_decl(self.company, 2026, month=8)
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=aug.date_end,
        )
        aug.action_recompute_amounts()
        aug_22 = self._amt(aug, '22')
        self.assertEqual(
            float_compare(aug_22, first_43, 0), 0,
            '[22]=%s phải = [43] lần đầu=%s (KHBS [43]=%s)' % (
                aug_22, first_43, khbs_43,
            ),
        )
        _logger.info(
            'C6-F first_43=%s khbs_43=%s aug_22=%s',
            first_43, khbs_43, aug_22,
        )

    def test_c6_g_deferred_reduce_then_restore(self):
        """Ca G — quá hạn giảm đúng kỳ; thanh toán CK khôi phục đúng kỳ."""
        from odoo import fields as odoo_fields

        Line = self.env['vas.move.line']
        Adj = self.env['vas.gtgt.deferred.adjustment']
        inv = self.seed['c6_deferred']
        self._sync()
        Line.recompute_input_vat_deduction(
            company=self.company, as_of_date=date(2026, 8, 25),
        )
        lines = self._input_tax_lines(inv)
        self.assertTrue(lines, 'cần dòng 1331 từ HĐ trả chậm')
        self.assertEqual(lines[0].deduction_check, 'fail')
        self.assertEqual(lines[0].deduction_rule_id.code, 'DEFERRED_PAYMENT')
        tax_amt = lines[0].debit
        self.assertGreater(tax_amt, 0)

        created = Adj.cron_scan_deferred()
        self.assertGreaterEqual(created, 1)
        reduce = Adj.search([
            ('source_move_line_id', '=', lines[0].id),
            ('kind', '=', 'reduce'),
            ('state', '=', 'draft'),
        ], limit=1)
        self.assertTrue(reduce)
        self.assertEqual(reduce.period_date_start, date(2026, 8, 1))
        self.assertEqual(reduce.period_date_end, date(2026, 8, 31))
        reduce.action_confirm()
        reduce_amt = reduce.amount_tax

        # Thanh toán chuyển khoản ngày 15/09 → khôi phục kỳ 09
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=inv.ids,
        ).create({
            'payment_date': '2026-09-15',
            'journal_id': self.bank_journal.id,
            'amount': inv.amount_residual,
        })
        payment = wiz._create_payments()[:1]
        if payment.state in ('draft', 'in_process'):
            payment.action_post()
        self._sync()
        pay_date = odoo_fields.Date.to_date('2026-09-15')
        restore = Adj.action_restore_after_non_cash(lines[0], pay_date, self.company)
        self.assertTrue(restore)
        restore.action_confirm()
        self.assertEqual(restore.period_date_start, date(2026, 9, 1))
        self.assertEqual(float_compare(reduce_amt, restore.amount_tax, 0), 0)

        aug = self._make_decl(self.company, 2026, month=8)
        aug.action_recompute_amounts()
        self.assertEqual(
            float_compare(self._amt(aug, '37'), reduce_amt, 0), 0,
            '[37] kỳ 08=%s phải = giảm %s' % (self._amt(aug, '37'), reduce_amt),
        )

        sep = self._make_decl(self.company, 2026, month=9)
        sep.action_recompute_amounts()
        self.assertEqual(
            float_compare(self._amt(sep, '38'), restore.amount_tax, 0), 0,
            '[38] kỳ 09=%s phải = khôi phục %s' % (
                self._amt(sep, '38'), restore.amount_tax,
            ),
        )
        _logger.info(
            'C6-G reduce_amt=%s reduce_period=%s→%s restore_amt=%s restore_period=%s→%s aug37=%s sep38=%s',
            reduce_amt, reduce.period_date_start, reduce.period_date_end,
            restore.amount_tax, restore.period_date_start, restore.period_date_end,
            self._amt(aug, '37'), self._amt(sep, '38'),
        )

    def test_c6_h_filed_lock(self):
        """Ca H — kỳ đã nộp: sửa số bị chặn."""
        jul = self._make_decl(self.company, 2026, month=7)
        self._file_decl(jul)
        with self.assertRaises(UserError):
            self._set_amt(jul, '25', 1.0)
        with self.assertRaises(UserError):
            jul.write({'amount_22': 999.0})

    def test_c6_i_j_annual_summary_and_red(self):
        """Ca I+J — ba kỳ khớp; cố tình lệch → đỏ đúng dòng."""
        decls = []
        for mon in (9, 10, 11):
            d = self._make_decl(self.company, 2026, month=mon)
            self._file_decl(d)
            decls.append(d)
        # Kiểm chuyển kỳ
        for i in range(1, 3):
            self.assertEqual(
                float_compare(self._amt(decls[i], '22'), self._amt(decls[i - 1], '43'), 0),
                0,
            )
        Summary = self.env['vas.gtgt.annual.summary']
        summary = Summary.create({
            'company_id': self.company.id,
            'year': 2026,
            'period_kind': 'month',
        })
        summary.action_rebuild()
        c6_lines = summary.line_ids.filtered(
            lambda l: l.declaration_id in decls,
        ).sorted('date_start')
        self.assertEqual(len(c6_lines), 3)
        self.assertFalse(any(c6_lines.mapped('is_carry_mismatch')))
        carry_snap = [
            (l.period_label, l.amount_22, l.amount_43)
            for l in c6_lines
        ]

        fake = self._make_decl(self.company, 2026, month=12)
        fake.amount_22_manual = True
        fake.amount_22 = self._amt(decls[2], '43') + 123_456
        fake.action_prepare()
        summary.action_rebuild()
        red = summary.line_ids.filtered(
            lambda l: l.declaration_id == fake and l.is_carry_mismatch,
        )
        self.assertTrue(red, 'phải đánh dấu đỏ dòng kỳ lệch')
        self.assertEqual(len(red), 1)
        _logger.info(
            'C6-IJ carries=%s red_22=%s prev_43=%s',
            carry_snap, red.amount_22, red.prev_43,
        )

    def test_c6_purpose_review_three_choices(self):
        """Việc 5 — sinh việc rà soát, ghi lựa chọn."""
        lines = self.env['vas.move.line'].search([
            ('move_id.company_id', '=', self.company.id),
            ('account_id.code', '=like', '1331%'),
            ('debit', '>', 0),
        ], limit=1)
        self.assertTrue(lines)
        review = self.env['vas.gtgt.declaration'].action_open_purpose_review(
            lines, 'taxable_only', 'exempt_only',
        )
        self.assertEqual(review.state, 'open')
        review.choice = 'no_adjust'
        review.choice_reason = 'Mục đích đổi sau ngày mua — không điều chỉnh tờ cũ.'
        review.action_set_choice()
        self.assertEqual(review.state, 'done')
