# -*- coding: utf-8 -*-
"""Post W2–W4 fixes: B04 tax/revenue split, R17/R18 partials, R23 writeoff, R22 offset."""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


@tagged('connecta_vas', 'connecta_vas_fix')
class TestPostW4Fixes(TransactionCase):
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
            cls.regime = cls.env['vas.regime'].create({'code': 'TT133', 'name': 'TT133'})
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-06-15'),
            ('date_to', '>=', '2099-06-15'),
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
        cls.bank_j = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1)
        cls.tax_sale = cls.env['account.tax'].search([
            ('company_id', '=', cls.company.id), ('type_tax_use', '=', 'sale'),
            ('amount', '=', 10.0),
        ], limit=1) or cls.env['account.tax'].create({
            'name': 'VAT10S-F', 'amount': 10.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'HH FIX', 'is_storable': True,
            'invoice_policy': 'order',
            'list_price': cls.UNTAXED, 'standard_price': cls.COGS,
            'taxes_id': [Command.set(cls.tax_sale.ids)],
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
        })
        cls.wo_expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id), ('account_type', '=', 'expense'),
        ], limit=1)

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31')

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += line.debit - line.credit
        return {k: round(v, 2) for k, v in bal.items()}

    def test_fix_b04_tax_on_invoice_revenue_on_delivery(self):
        """B04: 33311 theo ngày HĐ; 5111 theo ngày giao (kế toán chốt, workbook thuế SAI)."""
        partner = self.env['res.partner'].create({
            'name': 'KH B04', 'company_id': self.company.id, 'customer_rank': 1,
        })
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': self.UNTAXED,
                'tax_ids': [Command.set(self.tax_sale.ids)],
            })],
        })
        so.action_confirm()
        # Invoice BEFORE delivery
        inv = so._create_invoices()
        inv.invoice_date = '2099-06-01'
        inv.action_post()
        self._sync()
        inv_moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.move'), ('source_res_id', '=', inv.id),
            ('state', '=', 'posted'),
        ])
        bal1 = self._net(inv_moves)
        print(f"\n=== B04 after invoice: {bal1} ===")
        # Tax only — no 5111 yet
        self.assertAlmostEqual(bal1.get('33311', 0.0), -self.TAX)
        self.assertAlmostEqual(bal1.get('5111', 0.0), 0.0)
        self.assertAlmostEqual(bal1.get('131', 0.0), self.TAX)

        # Deliver later — hết mọi chặng (kể cả kho pick_ship trên DB demo)
        pickings = so.picking_ids
        for _round in range(6):
            pending = pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
            if not pending:
                break
            for pick in pending:
                pick.action_assign()
                for m in pick.move_ids:
                    m.quantity = m.product_uom_qty
                    m.picked = True
                pick.button_validate()
            pickings |= pickings.mapped('move_ids.move_dest_ids.picking_id')
        sm = pickings.mapped('move_ids').filtered(
            lambda m: m.state == 'done' and m.location_dest_usage == 'customer'
        )[:1]
        self.assertTrue(sm, 'B04 cần chặng done đi khách')
        sm.write({'date': fields.Datetime.to_datetime('2099-07-15')})
        self._sync()
        all_moves = inv_moves | self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'), ('source_res_id', '=', sm.id),
            ('state', '=', 'posted'),
        ])
        bal2 = self._net(all_moves)
        print(f"=== B04 after delivery: {bal2} ===")
        # Revenue on delivery + COGS; tax still from invoice
        self.assertAlmostEqual(bal2.get('5111', 0.0), -self.UNTAXED)
        self.assertAlmostEqual(bal2.get('33311', 0.0), -self.TAX)
        self.assertAlmostEqual(bal2.get('632', 0.0), self.COGS)
        rev = all_moves.filtered(lambda m: m.move_kind == 'revenue')
        self.assertTrue(rev)
        self.assertEqual(str(rev[:1].date), '2099-07-15')
        tax_move = inv_moves[:1]
        self.assertEqual(str(tax_move.date), '2099-06-01')

    def test_fix_r17_a_one_payment_three_invoices(self):
        """(a) 1 payment 500 → 3 HĐ 200+200+100; residuals → 0."""
        partner = self.env['res.partner'].create({
            'name': 'KH multi', 'company_id': self.company.id, 'customer_rank': 1,
        })
        invs = self.env['account.move']
        for amt in (200.0, 200.0, 100.0):
            inv = self.env['account.move'].create({
                'move_type': 'out_invoice', 'partner_id': partner.id,
                'invoice_date': '2099-06-10', 'date': '2099-06-10',
                'journal_id': self.sale_j.id, 'company_id': self.company.id,
                'invoice_line_ids': [Command.create({
                    'name': f'L{amt}', 'quantity': 1, 'price_unit': amt, 'tax_ids': [],
                })],
            })
            inv.action_post()
            invs |= inv
        self._sync()
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invs.ids, force_payment_move=True,
        ).create({'amount': 500, 'journal_id': self.bank_j.id, 'payment_date': '2099-06-11'})
        payment = wiz.with_context(force_payment_move=True)._create_payments()[:1]
        self._sync()
        residuals = []
        for inv in invs:
            lines = self.env['vas.sync']._vas_all_131_331_lines(inv, '131')
            residuals.append(round(sum(lines.mapped('amount_residual')), 2) if lines else None)
        print(f"\n=== R17(a) residuals after 500: {residuals} ===")
        self.assertEqual(residuals, [0.0, 0.0, 0.0])

    def test_fix_r17_b_two_payments_one_invoice(self):
        """(b) HĐ 300 trả 100 rồi 200 → residual 200 rồi 0."""
        partner = self.env['res.partner'].create({
            'name': 'KH instalment', 'company_id': self.company.id, 'customer_rank': 1,
        })
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_date': '2099-06-12', 'date': '2099-06-12',
            'journal_id': self.sale_j.id, 'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'Inst', 'quantity': 1, 'price_unit': 300, 'tax_ids': [],
            })],
        })
        inv.action_post()
        self._sync()
        line = self.env['vas.sync']._vas_find_131_331_line(inv, '131')
        self.assertAlmostEqual(line.amount_residual, 300.0)

        def pay(amount, day):
            wiz = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=inv.ids, force_payment_move=True,
            ).create({
                'amount': amount, 'journal_id': self.bank_j.id, 'payment_date': day,
                'payment_difference_handling': 'open',
            })
            return wiz.with_context(force_payment_move=True)._create_payments()[:1]

        pay(100, '2099-06-13')
        self._sync()
        line.invalidate_recordset()
        line = self.env['vas.sync']._vas_find_131_331_line(inv, '131')
        print(f"\n=== R17(b) after 100: residual={line.amount_residual} ===")
        self.assertAlmostEqual(line.amount_residual, 200.0)

        pay(200, '2099-06-14')
        self._sync()
        line = self.env['vas.sync']._vas_find_131_331_line(inv, '131')
        print(f"=== R17(b) after 200: residual={line.amount_residual} ===")
        self.assertAlmostEqual(line.amount_residual, 0.0)

    def test_fix_r17_c_advance_no_invoice(self):
        """(c) Ứng trước không reconcile HĐ — vẫn ghi 112/131, không lỗi."""
        partner = self.env['res.partner'].create({
            'name': 'KH advance', 'company_id': self.company.id, 'customer_rank': 1,
        })
        pmt = self.env['account.payment'].with_context(force_payment_move=True).create({
            'payment_type': 'inbound', 'partner_type': 'customer',
            'partner_id': partner.id, 'amount': 500_000,
            'date': '2099-06-15', 'journal_id': self.bank_j.id,
            'company_id': self.company.id, 'currency_id': self.vnd.id,
        })
        pmt.with_context(force_payment_move=True).action_post()
        self._sync()
        moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.payment'), ('source_res_id', '=', pmt.id),
            ('state', '=', 'posted'),
        ])
        bal = self._net(moves)
        print(f"\n=== R17(c) advance: {bal} ===")
        self.assertAlmostEqual(bal.get('112', 0.0), 500_000.0)
        self.assertAlmostEqual(bal.get('131', 0.0), -500_000.0)

    def test_fix_r23_no_false_discount_on_partial(self):
        """Trả 98/100 còn nợ 2 → KHÔNG ghi chiết khấu."""
        partner = self.env['res.partner'].create({
            'name': 'KH partial', 'company_id': self.company.id, 'customer_rank': 1,
        })
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_date': '2099-06-16', 'date': '2099-06-16',
            'journal_id': self.sale_j.id, 'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'P', 'quantity': 1, 'price_unit': 100, 'tax_ids': [],
            })],
        })
        inv.action_post()
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids, force_payment_move=True,
        ).create({
            'amount': 98, 'journal_id': self.bank_j.id, 'payment_date': '2099-06-17',
            'payment_difference_handling': 'open',
        })
        payment = wiz.with_context(force_payment_move=True)._create_payments()[:1]
        disc = self.env['vas.sync']._payment_discount_amount(payment)
        print(f"\n=== R23 partial: discount_amount={disc} residual={inv.amount_residual} ===")
        self.assertEqual(disc, 0.0)
        self.assertAlmostEqual(inv.amount_residual, 2.0)

    def test_fix_r23_writeoff_when_closed(self):
        """Đánh dấu trả hết + write-off → R23 = 2."""
        partner = self.env['res.partner'].create({
            'name': 'KH wo', 'company_id': self.company.id, 'customer_rank': 1,
        })
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_date': '2099-06-18', 'date': '2099-06-18',
            'journal_id': self.sale_j.id, 'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'W', 'quantity': 1, 'price_unit': 100, 'tax_ids': [],
            })],
        })
        inv.action_post()
        assert self.wo_expense
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids, force_payment_move=True,
        ).create({
            'amount': 98, 'journal_id': self.bank_j.id, 'payment_date': '2099-06-19',
            'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.wo_expense.id,
            'writeoff_label': 'FIX-R23',
        })
        payment = wiz.with_context(force_payment_move=True)._create_payments()[:1]
        disc = self.env['vas.sync']._payment_discount_amount(payment)
        print(f"\n=== R23 writeoff closed: discount={disc} residual={inv.amount_residual} ===")
        self.assertAlmostEqual(disc, 2.0)
        self.assertAlmostEqual(inv.amount_residual, 0.0)

    def test_fix_r22_t09_debt_offset(self):
        """T09: PT 150 (100+50), PT 100 → bù 100; còn dư thu 50."""
        partner = self.env['res.partner'].create({
            'name': 'Dual T09', 'company_id': self.company.id,
            'customer_rank': 1, 'supplier_rank': 1,
        })
        inv1 = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_date': '2099-06-20', 'date': '2099-06-20',
            'journal_id': self.sale_j.id, 'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'A', 'quantity': 1, 'price_unit': 100, 'tax_ids': [],
            })],
        })
        inv2 = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_date': '2099-06-20', 'date': '2099-06-20',
            'journal_id': self.sale_j.id, 'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'B', 'quantity': 1, 'price_unit': 50, 'tax_ids': [],
            })],
        })
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': partner.id,
            'invoice_date': '2099-06-20', 'date': '2099-06-20',
            'journal_id': self.purchase_j.id, 'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'name': 'C', 'quantity': 1, 'price_unit': 100, 'tax_ids': [],
            })],
        })
        (inv1 + inv2 + bill).action_post()
        self._sync()
        # Service bill? bill is goods-less without storable — may go R08.
        # Force: ensure 331 residual exists from bill VAS move
        line_131_a = self.env['vas.sync']._vas_find_131_331_line(inv1, '131')
        line_131_b = self.env['vas.sync']._vas_find_131_331_line(inv2, '131')
        line_331 = self.env['vas.sync']._vas_find_131_331_line(bill, '331')
        self.assertTrue(line_131_a and line_131_b and line_331, 'Need VAS AR/AP lines')
        offset = self.env['vas.debt.offset'].create({
            'partner_id': partner.id,
            'date': '2099-06-21',
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': 'T09 test',
            'line_ids': [
                Command.create({
                    'side': 'receivable', 'move_line_id': line_131_a.id, 'amount': 100,
                }),
                Command.create({
                    'side': 'payable', 'move_line_id': line_331.id, 'amount': 100,
                }),
            ],
        })
        offset.action_post()
        line_131_a.invalidate_recordset()
        line_131_b.invalidate_recordset()
        line_331.invalidate_recordset()
        print(
            f"\n=== T09: move={offset.move_id.name} "
            f"131a={line_131_a.amount_residual} 131b={line_131_b.amount_residual} "
            f"331={line_331.amount_residual} ==="
        )
        bal = self._net(offset.move_id)
        self.assertAlmostEqual(bal.get('331', 0.0), 100.0)
        self.assertAlmostEqual(bal.get('131', 0.0), -100.0)
        self.assertAlmostEqual(line_131_a.amount_residual, 0.0)
        self.assertAlmostEqual(line_131_b.amount_residual, 50.0)
        self.assertAlmostEqual(line_331.amount_residual, 0.0)
