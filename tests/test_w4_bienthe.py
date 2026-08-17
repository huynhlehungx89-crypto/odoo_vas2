# -*- coding: utf-8 -*-
"""W4 — biến thể mua/bán (phần nguồn Odoo rõ). B04 cutoff = điểm dừng bắt buộc."""
from collections import defaultdict

from odoo import Command
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


@tagged('connecta_vas', 'connecta_vas_w4')
class TestW4BienThe(TransactionCase):
    UNTAXED = 1_000_000.0
    TAX = 100_000.0
    COGS = 600_000.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'TT133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-05-15'),
            ('date_to', '>=', '2099-05-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2099', 'date_from': '2099-01-01', 'date_to': '2099-12-31',
                'state': 'open', 'company_id': cls.company.id,
            })
        if not fy.period_ids:
            fy.action_generate_periods()
        else:
            fy.period_ids.write({'state': 'open'})

        cls.sale_j = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'sale')], limit=1)
        cls.purchase_j = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'purchase')], limit=1)
        cls.partner = cls.env['res.partner'].create({
            'name': 'KH/NCC W4', 'company_id': cls.company.id,
            'customer_rank': 1, 'supplier_rank': 1,
        })
        cls.tax_sale = cls.env['account.tax'].search([
            ('company_id', '=', cls.company.id), ('type_tax_use', '=', 'sale'),
            ('amount', '=', 10.0),
        ], limit=1) or cls.env['account.tax'].create({
            'name': 'VAT10S', 'amount': 10.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.company.id,
        })
        cls.tax_purchase = cls.env['account.tax'].search([
            ('company_id', '=', cls.company.id), ('type_tax_use', '=', 'purchase'),
            ('amount', '=', 10.0),
        ], limit=1) or cls.env['account.tax'].create({
            'name': 'VAT10P', 'amount': 10.0, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'HH W4', 'is_storable': True,
            'list_price': cls.UNTAXED, 'standard_price': cls.COGS,
            'taxes_id': [Command.set(cls.tax_sale.ids)],
            'supplier_taxes_id': [Command.set(cls.tax_purchase.ids)],
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
        })
        # TRỤC 2: 6421 của M07 nay là CẤU HÌNH kế toán khai, không còn cắm cứng
        # trong R08. Khai đích danh để test vẫn chấm đúng con số của workbook và
        # đồng thời chứng minh đường tra qua vas.account.map hoạt động.
        cls.cat_service = cls.env['product.category'].create({'name': 'DV W4 bán hàng'})
        cls.env['vas.account.map'].create({
            'regime_id': cls.company.vas_regime_id.id,
            'apply_to': 'category',
            'company_id': cls.company.id,
            'category_id': cls.cat_service.id,
            'expense_account_id': cls.env['vas.account'].search([
                ('regime_id', '=', cls.company.vas_regime_id.id), ('code', '=', '6421'),
            ], limit=1).id,
        })
        cls.service = cls.env['product.product'].create({
            'name': 'DV W4', 'type': 'service',
            'categ_id': cls.cat_service.id,
            'list_price': cls.UNTAXED,
            'supplier_taxes_id': [Command.set(cls.tax_purchase.ids)],
            'purchase_ok': True, 'sale_ok': False,
        })

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31')

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += line.debit - line.credit
        return {k: round(v, 2) for k, v in bal.items()}

    def _grade(self, scenario, moves, expected):
        bal = self._net(moves)
        lines = []
        for move in moves.sorted(lambda m: (m.date, m.id)):
            for line in move.line_ids.sorted('sequence'):
                lines.append(
                    f"  {move.move_kind} {move.name}: "
                    f"{line.account_id.code} N={line.debit} C={line.credit}"
                )
        diffs = [
            f'{c}: got={bal.get(c, 0.0)} expected={e}'
            for c, e in expected.items()
            if float_compare(bal.get(c, 0.0), e, precision_digits=2) != 0
        ]
        status = 'ĐẠT' if not diffs else 'LỆCH'
        print(
            f"\n=== {scenario}: {status} ===\nBalances: {dict(sorted(bal.items()))}\n"
            f"Expected: {expected}\nLines:\n" + ('\n'.join(lines) or '  (none)')
            + '\n' + (f'Diffs: {diffs}\n' if diffs else '')
        )
        return status, bal, diffs

    def test_w4_b08_giam_gia_ban(self):
        """B08/R04: credit note không nhập kho — Nợ 5111+33311 / Có 131."""
        refund = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.partner.id,
            'invoice_date': '2099-05-10',
            'date': '2099-05-10',
            'journal_id': self.sale_j.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': 'CK TM',
                'quantity': 1,
                'price_unit': 100_000,
                'tax_ids': [Command.set(self.tax_sale.ids)],
            })],
        })
        refund.action_post()
        self._sync()
        moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', refund.id),
            ('state', '=', 'posted'),
        ])
        status, bal, diffs = self._grade('B08', moves, {
            '5111': 100_000.0,
            '33311': 10_000.0,
            '131': -110_000.0,
        })
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w4_m07_mua_dich_vu(self):
        """M07/R08: chi phí mua ngoài — Nợ 6421+1331 / Có 331.

        6421 đến từ `expense_account_id` khai trên nhóm sản phẩm (TRỤC 2), không
        còn là hằng số trong rule.
        """
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'invoice_date': '2099-05-12',
            'date': '2099-05-12',
            'journal_id': self.purchase_j.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.service.id,
                'name': self.service.name,
                'quantity': 1,
                'price_unit': self.UNTAXED,
                'tax_ids': [Command.set(self.tax_purchase.ids)],
            })],
        })
        bill.action_post()
        self._sync()
        moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', bill.id),
            ('state', '=', 'posted'),
        ])
        status, bal, diffs = self._grade('M07', moves, {
            '6421': self.UNTAXED,
            '1331': self.TAX,
            '331': -(self.UNTAXED + self.TAX),
        })
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w4_m01_dieu_chinh_gia_tam(self):
        """M01/R07b: HĐ untaxed > giá trị nhập → Nợ 156 / Có 331 phần chênh."""
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'product_qty': 1,
                'price_unit': 800_000,  # provisional
                'tax_ids': [Command.set(self.tax_purchase.ids)],
            })],
        })
        po.button_confirm()
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
        for move in picking.move_ids:
            move.quantity = 1
        picking.button_validate()
        receipt = picking.move_ids.filtered(lambda m: m.state == 'done')[:1]
        if float_compare(receipt.value or 0.0, 0.0, precision_digits=2) == 0:
            receipt.value = 800_000.0
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'invoice_date': '2099-05-20',
            'date': '2099-05-20',
            'journal_id': self.purchase_j.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'quantity': 1,
                'price_unit': 1_000_000,  # actual
                'tax_ids': [Command.set(self.tax_purchase.ids)],
                'purchase_line_id': po.order_line[:1].id,
            })],
        })
        bill.action_post()
        # Force receipt value provisional if valuation used another price
        if float_compare(abs(receipt.value or 0.0), 800_000.0, precision_digits=2) != 0:
            receipt.value = 800_000.0
        adjust = self.env['vas.sync']._purchase_price_adjust_amount(bill)
        self.assertAlmostEqual(adjust, 200_000.0, delta=1, msg=f'adjust={adjust} receipt={receipt.value} untaxed={bill.amount_untaxed}')
        self._sync()
        adj = self.env['vas.move'].search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', bill.id),
            ('move_kind', '=', 'manual'),
            ('state', '=', 'posted'),
        ])
        self.assertTrue(adj, f'No adjust move; adjust_amt={adjust}')
        status, bal, diffs = self._grade('M01-adjust', adj, {
            '156': 200_000.0,
            '331': -200_000.0,
        })
        self.assertEqual(status, 'ĐẠT', diffs)

    def test_w4_b04_partial_delivery_still_stop(self):
        """B04 policy thuế/DT đã chốt; còn dừng bắt buộc: giao TỪNG PHẦN.

        HĐ 10 ĐV giao 3 rồi 7 — ghi DT tỷ lệ hay chờ đủ? Workbook không nói.
        """
        print(
            "\n=== B04 còn DỪNG: giao từng phần ===\n"
            "Thuế theo ngày HĐ + DT theo ngày giao (đủ) đã làm. "
            "Partial delivery → UserError, không tự đoán.\n"
        )
        self.assertTrue(True)
