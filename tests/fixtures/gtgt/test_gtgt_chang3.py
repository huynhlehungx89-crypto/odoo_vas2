# -*- coding: utf-8 -*-
"""Chặng 3 — tờ khai 01/GTGT lần đầu."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import float_compare

from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang2 import (
    TestGtgtChang2Deduction,
    DATE,
    AS_OF,
)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_c3')
class TestGtgtChang3Declaration(TestGtgtChang2Deduction):
    """Đăng ký · mẫu TT80/89 · chỉ tiêu · chuyển kỳ · ngoại lệ ô tô."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form_01 = cls.env.ref('connecta_vas.vas_gtgt_form_01')
        cls.act_sxkd = cls.env.ref('connecta_vas.vas_gtgt_act_sxkd')
        cls.act_dadt = cls.env.ref('connecta_vas.vas_gtgt_act_dadt')
        cls.ver_tt89 = cls.env.ref('connecta_vas.vas_gtgt_version_tt89')
        cls.ver_tt80 = cls.env.ref('connecta_vas.vas_gtgt_version_tt80')
        Reg = cls.env['vas.gtgt.registration']
        if not Reg.search([
            ('company_id', '=', cls.company.id),
            ('form_type_id', '=', cls.form_01.id),
        ], limit=1):
            Reg.create({
                'company_id': cls.company.id,
                'form_type_id': cls.form_01.id,
                'period_kind': 'month',
            })
        cls._seed_chang3()

    @classmethod
    def _seed_chang3(cls):
        # Kỳ 07/2026 — doanh thu/mua để có [43] chuyển sang 08
        cls.seed['c3_sale_jul'] = cls._make_sale(
            'C3-JUL-SALE', cls.partner_customer, 20_000_000.0,
            cls.tax_sale[10], '2026-07-15',
        )
        inv_jul_buy = cls._make_bill(
            'C3-JUL-BUY', cls._c2_partner('NCC C3 Jul', '0200333001'),
            50_000_000.0, cls.tax_purchase[10], '2026-07-20',
        )
        cls._pay_bill(inv_jul_buy, cls.bank_journal, 'c3_jul_buy_pay')
        cls.seed['c3_buy_jul'] = inv_jul_buy

        # Kỳ 05/2026 — mẫu TT80
        cls.seed['c3_sale_may'] = cls._make_sale(
            'C3-MAY-SALE', cls.partner_customer, 5_000_000.0,
            cls.tax_sale[10], '2026-05-10',
        )

        # Xe có / không ngoại lệ
        car_ex = cls.env['product.product'].create({
            'name': 'Ô tô KD vận tải C3',
            'default_code': 'VAS_CAR_LTE9',
            'type': 'consu',
            'categ_id': cls.cat.id,
            'list_price': 2_000_000_000.0,
            'purchase_ok': True,
            'sale_ok': False,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'vas_passenger_car_business_exception': True,
        })
        p_ex = cls._c2_partner('NCC C3 xe ngoại lệ', '0200333002')
        inv_ex = cls.env['account.move'].create({
            'move_type': 'in_invoice',
            'company_id': cls.company.id,
            'journal_id': cls.purchase_journal.id,
            'partner_id': p_ex.id,
            'invoice_date': DATE,
            'date': DATE,
            'ref': 'C3-CAR-EX',
            'invoice_line_ids': [Command.create({
                'product_id': car_ex.id,
                'name': car_ex.name,
                'quantity': 1,
                'price_unit': 2_000_000_000.0,
                'tax_ids': [Command.set(cls.tax_purchase[10].ids)],
            })],
        })
        inv_ex.action_post()
        cls._pay_bill(inv_ex, cls.bank_journal, 'c3_car_ex_pay')
        cls.seed['c3_car_ex'] = inv_ex

        # Công ty khai QUÝ
        cls.company_q = cls.env['res.company'].create({
            'name': 'C3 GTGT Quý Co',
            'currency_id': cls.vnd.id,
        })
        cls.company_q.vas_regime_id = cls.regime
        cls.company_q.vas_start_date = '2000-01-01'
        cls.env['vas.gtgt.registration'].create({
            'company_id': cls.company_q.id,
            'form_type_id': cls.form_01.id,
            'period_kind': 'quarter',
        })

    def _amt(self, decl, code):
        line = decl.line_ids.filtered(lambda l: l.code == code)[:1]
        self.assertTrue(line, 'thiếu chỉ tiêu %s' % code)
        return line.amount

    def _make_decl(self, company, year, month=None, quarter=None,
                   period_kind='month', activity=None, **extra):
        activity = activity or self.act_sxkd
        vals = {
            'company_id': company.id,
            'form_type_id': self.form_01.id,
            'period_kind': period_kind,
            'year': year,
            'month': month,
            'quarter': quarter,
            'activity_id': activity.id,
            'declaration_round': 0,
        }
        vals.update(extra)
        if period_kind == 'month':
            start, end = self.env['vas.gtgt.declaration']._period_bounds(
                'month', year, month=month,
            )
        else:
            start, end = self.env['vas.gtgt.declaration']._period_bounds(
                'quarter', year, quarter=quarter,
            )
        vals['date_start'] = start
        vals['date_end'] = end
        ver = self.env['vas.gtgt.form.version'].find_for_period_start(
            self.form_01, start,
        )
        vals['form_version_id'] = ver.id
        return self.env['vas.gtgt.declaration'].create(vals)

    def test_c3_a_no_registration_blocks(self):
        other = self.env['res.company'].create({
            'name': 'C3 No Reg',
            'currency_id': self.vnd.id,
        })
        other.vas_regime_id = self.regime
        with self.assertRaises(UserError):
            self._make_decl(other, 2026, month=8)

    def test_c3_b_month_and_quarter(self):
        d_m = self._make_decl(self.company, 2026, month=8)
        self.assertEqual(d_m.period_kind, 'month')
        d_q = self._make_decl(
            self.company_q, 2026, quarter=3, period_kind='quarter',
        )
        self.assertEqual(d_q.period_kind, 'quarter')
        self.assertEqual(str(d_q.date_start), '2026-07-01')
        self.assertEqual(str(d_q.date_end), '2026-09-30')

    def test_c3_c_template_tt89_vs_tt80(self):
        d89 = self._make_decl(self.company, 2026, month=8)
        self.assertEqual(d89.form_version_id.code, 'TT89')
        self.assertIn('89', d89.circular_label)
        d80 = self._make_decl(self.company, 2026, month=5)
        self.assertEqual(d80.form_version_id.code, 'TT80')
        self.assertIn('80', d80.circular_label)

    def test_c3_d_two_activities_same_period(self):
        a = self._make_decl(self.company, 2026, month=8, activity=self.act_sxkd)
        b = self._make_decl(self.company, 2026, month=8, activity=self.act_dadt)
        self.assertNotEqual(a.id, b.id)

    def test_c3_e_f_g_indicators_and_formulas(self):
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        decl = self._make_decl(self.company, 2026, month=8)
        decl.action_recompute_amounts()
        codes = set(decl.line_ids.mapped('code'))
        expected = {
            '21', '22', '23', '23a', '24', '24a', '25', '26', '27', '28',
            '29', '30', '31', '32', '32a', '32b', '33', '34', '34a', '35',
            '36', '37', '38', '39a', '40', '40a', '40b', '41', '42', '43',
        }
        self.assertTrue(expected <= codes, 'thiếu %s' % (expected - codes))
        n_val = len(decl.line_ids)
        self.assertGreaterEqual(n_val, 30)

        a29, a30, a32, a32a, a32b = (
            self._amt(decl, c) for c in ('29', '30', '32', '32a', '32b')
        )
        a27 = self._amt(decl, '27')
        self.assertEqual(
            float_compare(a27, a29 + a30 + a32 + a32a - a32b, 0), 0,
            '27=%s parts=%s' % (a27, (a29, a30, a32, a32a, a32b)),
        )
        a26, a34a = self._amt(decl, '26'), self._amt(decl, '34a')
        a34 = self._amt(decl, '34')
        self.assertEqual(
            float_compare(a34, a26 + a27 + a34a, 0), 0,
            '34=%s' % a34,
        )
        a36, a22, a37, a38, a39a = (
            self._amt(decl, c) for c in ('36', '22', '37', '38', '39a')
        )
        a40a = self._amt(decl, '40a')
        e = a36 - a22 + a37 - a38 - a39a
        self.assertEqual(
            float_compare(a40a, max(e, 0.0), 0), 0,
            '40a=%s e=%s' % (a40a, e),
        )
        a40b = self._amt(decl, '40b')
        a40 = self._amt(decl, '40')
        self.assertEqual(float_compare(a40, a40a - a40b, 0), 0)

        a24, a25 = self._amt(decl, '24'), self._amt(decl, '25')
        self.assertNotEqual(
            float_compare(a24, a25, 0), 0,
            '24=%s phải khác 25=%s khi có HĐ không đủ ĐKKT' % (a24, a25),
        )
        import logging
        logging.getLogger(__name__).info(
            'C3-EFG 27=%s (29=%s+30=%s+32=%s+32a=%s-32b=%s) 34=%s 40=%s 24=%s 25=%s n_lines=%s',
            a27, a29, a30, a32, a32a, a32b, a34, a40, a24, a25, n_val,
        )

    def test_c3_h_carry_forward_22_from_43(self):
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date='2026-07-31',
        )
        jul = self._make_decl(self.company, 2026, month=7)
        jul.amount_22_manual = True
        jul.amount_22 = 0.0
        jul.action_recompute_amounts()
        jul.action_prepare()
        v43 = self._amt(jul, '43')
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        aug = self._make_decl(self.company, 2026, month=8)
        aug.action_recompute_amounts()
        v22 = self._amt(aug, '22')
        self.assertEqual(
            float_compare(v22, v43, 0), 0,
            '22=%s 43_jul=%s' % (v22, v43),
        )
        import logging
        logging.getLogger(__name__).info('C3-H 22_aug=%s 43_jul=%s', v22, v43)

    def test_c3_i_unset_blocks(self):
        self.company.vas_has_exempt_sales = True
        self._sync()
        mixed = self._input_tax_lines(self.seed['c2_mixed'])
        mixed.write({'use_purpose': 'unset'})
        decl = self._make_decl(self.company, 2026, month=8)
        with self.assertRaises(UserError) as err:
            decl.action_recompute_amounts()
        self.assertIn('CHƯA XÁC ĐỊNH', str(err.exception))

    def test_c3_j_car_exception_flag(self):
        self.company.vas_has_exempt_sales = False
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        limited = self._input_tax_lines(self.seed['c2_car'])
        full = self._input_tax_lines(self.seed['c3_car_ex'])
        self.assertTrue(limited and full)
        self.assertEqual(limited[0].deduction_rule_id.code, 'PASSENGER_CAR')
        self.assertEqual(
            float_compare(limited[0].deductible_amount, 160_000_000.0, 0), 0,
        )
        self.assertEqual(full[0].deduction_check, 'pass')
        self.assertEqual(
            float_compare(full[0].deductible_amount, full[0].debit, 0), 0,
            'ex=%s debit=%s' % (full[0].deductible_amount, full[0].debit),
        )
        import logging
        logging.getLogger(__name__).info(
            'C3-J limited=%s full=%s',
            limited[0].deductible_amount, full[0].deductible_amount,
        )

    def test_c3_k_recompute_stable(self):
        self.company.vas_has_exempt_sales = False
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        decl = self._make_decl(self.company, 2026, month=8)
        decl.action_recompute_amounts()
        snap = {l.code: l.amount for l in decl.line_ids}
        decl.action_recompute_amounts()
        for code, amt in snap.items():
            self.assertEqual(
                float_compare(self._amt(decl, code), amt, 0), 0, code,
            )
