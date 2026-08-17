# -*- coding: utf-8 -*-
"""Chặng 2 — điều kiện khấu trừ thuế đầu vào."""
from odoo import Command
from odoo.tests import tagged
from odoo.tools import float_compare

from odoo.addons.connecta_vas.tests.fixtures.gtgt.test_gtgt_chang1a import (
    TestGtgtChang1A,
)


DATE = '2026-08-10'
DUE_LATER = '2026-09-20'
DUE_PAST = '2026-08-01'
AS_OF = '2026-08-15'


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_gtgt_c2')
class TestGtgtChang2Deduction(TestGtgtChang1A):
    """Gieo ca khấu trừ + khóa máy kiểm / phân bổ / chặn tờ khai."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_chang2()

    def setUp(self):
        super().setUp()
        # Mỗi ca độc lập: mặc định tắt bán không chịu thuế.
        self.company.vas_has_exempt_sales = False

    @classmethod
    def _c2_partner(cls, name, vat):
        return cls.env['res.partner'].create({
            'name': name,
            'vat': vat,
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })

    @classmethod
    def _seed_chang2(cls):
        # Mỗi ca một NCC riêng — tránh cộng dồn / trả chậm lẫn nhau.
        p_cash = cls._c2_partner('NCC C2 tiền mặt', '0200111001')
        inv_cash = cls._make_bill(
            'C2-CASH', p_cash, 5_000_000.0, cls.tax_purchase[10],
            DATE,
        )
        cls._pay_bill(inv_cash, cls.cash_journal, 'c2_cash_pay')
        cls.seed['c2_cash'] = inv_cash

        p_cum = cls._c2_partner('NCC C2 cộng dồn', '0200555666')
        inv_a = cls._make_bill(
            'C2-CUM-A', p_cum, 3_000_000.0, cls.tax_purchase[10], DATE,
        )
        inv_b = cls._make_bill(
            'C2-CUM-B', p_cum, 3_000_000.0, cls.tax_purchase[10], DATE,
        )
        cls._pay_bill(inv_a, cls.cash_journal, 'c2_cum_a_pay')
        cls._pay_bill(inv_b, cls.cash_journal, 'c2_cum_b_pay')
        cls.seed['c2_cum_a'] = inv_a
        cls.seed['c2_cum_b'] = inv_b

        p_wait = cls._c2_partner('NCC C2 chờ hạn', '0200111002')
        p_over = cls._c2_partner('NCC C2 quá hạn', '0200111003')
        cls.seed['c2_wait'] = cls._make_bill(
            'C2-WAIT', p_wait, 6_000_000.0, cls.tax_purchase[10],
            DATE, invoice_date_due=DUE_LATER,
        )
        cls.seed['c2_over'] = cls._make_bill(
            'C2-OVER', p_over, 6_000_000.0, cls.tax_purchase[10],
            DATE, invoice_date_due=DUE_PAST,
        )

        car = cls.env['product.product'].create({
            'name': 'Ô tô 5 chỗ C2',
            'default_code': 'VAS_CAR_LTE9',
            'type': 'consu',
            'categ_id': cls.cat.id,
            'list_price': 2_000_000_000.0,
            'purchase_ok': True,
            'sale_ok': False,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
        })
        p_car = cls._c2_partner('NCC C2 ô tô', '0200111004')
        inv_car = cls.env['account.move'].create({
            'move_type': 'in_invoice',
            'company_id': cls.company.id,
            'journal_id': cls.purchase_journal.id,
            'partner_id': p_car.id,
            'invoice_date': DATE,
            'date': DATE,
            'ref': 'C2-CAR',
            'invoice_line_ids': [Command.create({
                'product_id': car.id,
                'name': car.name,
                'quantity': 1,
                'price_unit': 2_000_000_000.0,
                'tax_ids': [Command.set(cls.tax_purchase[10].ids)],
            })],
        })
        inv_car.action_post()
        cls.seed['c2_car'] = inv_car

        # Doanh thu chịu + không chịu — bật cờ chỉ trong ca phân bổ / chặn tờ khai.
        cls.seed['c2_sale_tax'] = cls._make_sale(
            'C2-SALE-10', cls.partner_customer, 10_000_000.0,
            cls.tax_sale[10], DATE,
        )
        inv_sale_ex = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'company_id': cls.company.id,
            'journal_id': cls.sale_journal.id,
            'partner_id': cls.partner_customer.id,
            'invoice_date': DATE,
            'date': DATE,
            'ref': 'C2-SALE-EX',
            'invoice_line_ids': [Command.create({
                'name': 'Hàng không chịu thuế',
                'quantity': 1,
                'price_unit': 10_000_000.0,
                'tax_ids': [Command.clear()],
            })],
        })
        inv_sale_ex.action_post()
        cls.seed['c2_sale_ex'] = inv_sale_ex

        p_mixed = cls._c2_partner('NCC C2 mixed', '0200111005')
        inv_mixed = cls._make_bill(
            'C2-MIXED', p_mixed, 4_000_000.0, cls.tax_purchase[10],
            DATE,
        )
        cls._pay_bill(inv_mixed, cls.bank_journal, 'c2_mixed_pay')
        cls.seed['c2_mixed'] = inv_mixed
        cls.company.vas_has_exempt_sales = False

    @classmethod
    def _make_bill(cls, ref, partner, untaxed, tax, date, invoice_date_due=None):
        inv = cls.env['account.move'].create({
            'move_type': 'in_invoice',
            'company_id': cls.company.id,
            'journal_id': cls.purchase_journal.id,
            'partner_id': partner.id,
            'invoice_date': date,
            'invoice_date_due': invoice_date_due or date,
            'date': date,
            'ref': ref,
            'invoice_line_ids': [Command.create({
                'name': ref,
                'quantity': 1,
                'price_unit': untaxed,
                'tax_ids': [Command.set(tax.ids)],
            })],
        })
        inv.action_post()
        return inv

    @classmethod
    def _make_sale(cls, ref, partner, untaxed, tax, date):
        inv = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'company_id': cls.company.id,
            'journal_id': cls.sale_journal.id,
            'partner_id': partner.id,
            'invoice_date': date,
            'date': date,
            'ref': ref,
            'invoice_line_ids': [Command.create({
                'name': ref,
                'quantity': 1,
                'price_unit': untaxed,
                'tax_ids': [Command.set(tax.ids)],
            })],
        })
        inv.action_post()
        return inv

    def _input_tax_lines(self, invoice):
        moves = self._vas_for_invoice(invoice)
        return moves.mapped('line_ids').filtered(lambda l: l._vas_is_input_vat_line())

    def test_c2_rules_are_data_not_hardcoded(self):
        Rule = self.env['vas.tax.deduction.rule']
        cash = Rule.search([('code', '=', 'CASH_NONCASH')], limit=1)
        self.assertTrue(cash)
        self.assertEqual(cash.amount_threshold, 5_000_000)
        car = Rule.search([('code', '=', 'PASSENGER_CAR')], limit=1)
        self.assertEqual(car.amount_threshold, 1_600_000_000)
        cash.amount_threshold = 9_999_999
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        lines = self._input_tax_lines(self.seed['c2_cash'])
        self.assertTrue(lines)
        self.assertEqual(lines[0].deduction_check, 'pass')
        cash.amount_threshold = 5_000_000

    def test_c2_cash_over_threshold_fail(self):
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        lines = self._input_tax_lines(self.seed['c2_cash'])
        self.assertTrue(lines)
        self.assertEqual(lines[0].deduction_check, 'fail')
        self.assertEqual(lines[0].deduction_rule_id.code, 'CASH_NONCASH')
        self.assertEqual(lines[0].deductible_amount, 0.0)

    def test_c2_cumulative_both_fail(self):
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        for key in ('c2_cum_a', 'c2_cum_b'):
            lines = self._input_tax_lines(self.seed[key])
            self.assertTrue(lines, key)
            self.assertEqual(lines[0].deduction_check, 'fail', key)
            self.assertEqual(lines[0].deduction_rule_id.code, 'CASH_CUMULATIVE', key)

    def test_c2_deferred_wait_and_overdue(self):
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        wait = self._input_tax_lines(self.seed['c2_wait'])
        over = self._input_tax_lines(self.seed['c2_over'])
        self.assertTrue(wait and over)
        self.assertEqual(wait[0].deduction_check, 'wait_due')
        self.assertEqual(wait[0].deduction_rule_id.code, 'DEFERRED_PAYMENT')
        self.assertGreater(wait[0].deductible_amount, 0.0)
        self.assertEqual(over[0].deduction_check, 'fail')
        self.assertEqual(over[0].deduction_rule_id.code, 'DEFERRED_PAYMENT')
        self.assertEqual(over[0].deductible_amount, 0.0)

    def test_c2_config_off_hides_purpose_still_checks(self):
        self.company.vas_has_exempt_sales = False
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        lines = self._input_tax_lines(self.seed['c2_cash'])
        self.assertEqual(lines[0].use_purpose, 'taxable_only')
        self.assertEqual(lines[0].deduction_check, 'fail')
        self.assertFalse(self.company.vas_gtgt_declaration_block_reason())

    def test_c2_config_on_allocate_mixed(self):
        self.company.vas_has_exempt_sales = True
        self._sync()
        mixed = self._input_tax_lines(self.seed['c2_mixed'])
        self.assertTrue(mixed)
        mixed.write({'use_purpose': 'mixed'})
        self.env['vas.move.line'].recompute_input_vat_deduction(
            lines=mixed, as_of_date=AS_OF,
        )
        info = self.company._vas_gtgt_taxable_revenue_ratio(DATE)
        self.assertGreater(info['denominator'], 0.0)
        expected = mixed[0].debit * info['ratio']
        self.assertEqual(
            float_compare(mixed[0].deductible_amount, expected, precision_digits=0),
            0,
            'num=%s den=%s ratio=%s debit=%s got=%s' % (
                info['numerator'], info['denominator'], info['ratio'],
                mixed[0].debit, mixed[0].deductible_amount,
            ),
        )

    def test_c2_unset_blocks_declaration(self):
        self.company.vas_has_exempt_sales = True
        self._sync()
        mixed = self._input_tax_lines(self.seed['c2_mixed'])
        mixed.write({'use_purpose': 'unset'})
        self.env['vas.move.line'].recompute_input_vat_deduction(
            lines=mixed, as_of_date=AS_OF,
        )
        reason = self.company.vas_gtgt_declaration_block_reason()
        self.assertTrue(reason)
        self.assertIn('CHƯA XÁC ĐỊNH', reason)

    def test_c2_passenger_car_limited(self):
        self._sync()
        self.env['vas.move.line'].recompute_input_vat_deduction(
            company=self.company, as_of_date=AS_OF,
        )
        lines = self._input_tax_lines(self.seed['c2_car'])
        self.assertTrue(lines)
        self.assertEqual(lines[0].deduction_check, 'fail')
        self.assertEqual(lines[0].deduction_rule_id.code, 'PASSENGER_CAR')
        self.assertEqual(
            float_compare(lines[0].deductible_amount, 160_000_000.0, precision_digits=0),
            0,
        )
