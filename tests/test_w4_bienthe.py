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


    def _validate_pick(self, picking, qty=None, cancel_backorder=False):
        picking = picking.with_context(skip_sms=True, skip_sanity_check=True)
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = qty if qty is not None else move.product_uom_qty
            move.picked = True
        ctx = {'skip_sms': True, 'skip_sanity_check': True}
        if cancel_backorder:
            ctx['cancel_backorder'] = True
        res = picking.with_context(**ctx).button_validate()
        if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
            wiz = self.env[res['res_model']].with_context(**res.get('context', {})).create({})
            if cancel_backorder and hasattr(wiz, 'process_cancel_backorder'):
                wiz.process_cancel_backorder()
            else:
                wiz.process()
        return picking

    def test_w4_b04_partial_delivery_revenue_ratio(self):
        """Policy B: HD 10 giao 3 -> DT 30% + thue du; giao not -> du 511."""
        Sync = self.env['vas.sync']
        stock_loc = self.env.ref('stock.stock_location_stock')
        cust = self.env.ref('stock.stock_location_customers')
        self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': self.product.id,
            'location_id': stock_loc.id,
            'inventory_quantity': 20.0,
        }).action_apply_inventory()
        self.product.invoice_policy = 'order'

        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': 10,
                'price_unit': 100_000,
                'tax_ids': [Command.set(self.tax_sale.ids)],
            })],
        })
        so.action_confirm()
        inv = so._create_invoices()
        inv.invoice_date = '2099-05-10'
        inv.date = '2099-05-10'
        inv.action_post()
        self.assertAlmostEqual(inv.amount_untaxed, 1_000_000.0)

        picking = so.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(picking)
        self._validate_pick(picking, qty=3.0, cancel_backorder=True)

        self.assertAlmostEqual(Sync._sale_invoice_delivery_ratio(inv), 0.3, places=2)
        self.assertEqual(Sync._sale_invoice_delivery_status(inv), 'partial')
        self._sync()
        sale_moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', inv.id),
            ('move_kind', '=', 'sale_inv'),
            ('state', '=', 'posted'),
        ])
        self.assertTrue(sale_moves)
        bal = self._net(sale_moves)
        self.assertEqual(float_compare(bal.get('33311', 0.0), -100_000.0, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('5111', 0.0), -300_000.0, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('131', 0.0), 400_000.0, 2), 0, bal)

        sol = so.order_line[:1]
        gross = Sync._sale_line_gross_qty_out(sol)
        if float_compare(gross, 10.0, 2) < 0:
            need = 10.0 - gross
            move = self.env['stock.move'].create({
                'product_id': self.product.id,
                'product_uom_qty': need,
                'product_uom': self.product.uom_id.id,
                'location_id': stock_loc.id,
                'location_dest_id': cust.id,
                'company_id': self.company.id,
                'sale_line_id': sol.id,
                'picking_type_id': self.env.ref('stock.picking_type_out').id,
            })
            move._action_confirm()
            move.quantity = need
            move.picked = True
            move._action_done()
        else:
            for pick in so.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                self._validate_pick(pick)

        self.assertEqual(Sync._sale_invoice_delivery_status(inv), 'full')
        self._sync()
        booked = Sync._invoice_vas_revenue_booked(inv)
        self.assertEqual(float_compare(booked, 1_000_000.0, 2), 0, f'booked={booked}')

    def test_w4_g2_return_does_not_block_as_partial(self):
        """G2: giao du roi tra mot phan — gross full, sync khong UserError."""
        Sync = self.env['vas.sync']
        stock_loc = self.env.ref('stock.stock_location_stock')
        self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': self.product.id,
            'location_id': stock_loc.id,
            'inventory_quantity': 20.0,
        }).action_apply_inventory()
        self.product.invoice_policy = 'order'

        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': 5,
                'price_unit': 100_000,
                'tax_ids': [Command.set(self.tax_sale.ids)],
            })],
        })
        so.action_confirm()
        for pick in so.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            self._validate_pick(pick)

        inv = so._create_invoices()
        inv.invoice_date = '2099-05-11'
        inv.date = '2099-05-11'
        inv.action_post()
        self._sync()

        picking = so.picking_ids.filtered(lambda p: p.state == 'done')[:1]
        self.assertTrue(picking)
        wiz = self.env['stock.return.picking'].with_context(
            active_id=picking.id,
            active_ids=picking.ids,
            active_model='stock.picking',
        ).create({})
        for line in wiz.product_return_moves:
            if 'quantity' in line._fields:
                line.quantity = 2.0
        act = wiz.action_create_returns()
        ret_picking = self.env['stock.picking'].browse(act['res_id'])
        for m in ret_picking.move_ids:
            m.quantity = min(2.0, m.product_uom_qty)
            m.picked = True
        ret_picking.with_context(skip_sms=True, skip_sanity_check=True).button_validate()

        sol = so.order_line[:1]
        self.assertEqual(
            float_compare(Sync._sale_line_gross_qty_out(sol), 5.0, 2), 0,
            f'gross={Sync._sale_line_gross_qty_out(sol)} net={sol.qty_delivered}',
        )
        self.assertEqual(Sync._sale_invoice_delivery_status(inv), 'full')
        self._sync()


    def _ensure_r09b(self):
        Rule = self.env['vas.rule']
        regime = self.company.vas_regime_id
        if Rule.search([('regime_id', '=', regime.id), ('code', '=', 'R09b')], limit=1):
            return
        Rule.create({
            'code': 'R09b',
            'name': 'Chiet khau/giam gia mua (phi kho)',
            'regime_id': regime.id,
            'event_type': 'purchase_discount',
            'sequence': 53,
            'active': True,
            'line_ids': [
                Command.create({
                    'sequence': 10, 'side': 'debit',
                    'account_selector': 'partner_payable', 'amount_selector': 'total',
                }),
                Command.create({
                    'sequence': 20, 'side': 'credit',
                    'account_selector': 'product_inventory', 'amount_selector': 'untaxed',
                }),
                Command.create({
                    'sequence': 30, 'side': 'credit',
                    'account_selector': 'tax_input', 'amount_selector': 'tax',
                }),
            ],
        })

    def _buy_receive_bill(self, qty=10.0, price=20_000.0, date='2099-05-15'):
        """PO -> nhap kho -> HD mua posted. Tra (po, bill)."""
        stock_loc = self.env.ref('stock.stock_location_stock')
        self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': self.product.id,
            'location_id': stock_loc.id,
            'inventory_quantity': qty + 5.0,
        }).action_apply_inventory()
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'product_qty': qty,
                'price_unit': price,
                'tax_ids': [Command.set(self.tax_purchase.ids)],
            })],
        })
        po.button_confirm()
        picking = po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(picking)
        self._validate_pick(picking)
        receipt = picking.move_ids.filtered(lambda m: m.state == 'done')[:1]
        if receipt and float_compare(receipt.value or 0.0, 0.0, 2) == 0:
            receipt.value = price * qty
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date,
            'date': date,
            'journal_id': self.purchase_j.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'quantity': qty,
                'price_unit': price,
                'tax_ids': [Command.set(self.tax_purchase.ids)],
                'purchase_line_id': po.order_line[:1].id,
            })],
        })
        bill.action_post()
        return po, bill

    def _vendor_credit_note(self, bill, fraction=0.1, date='2099-05-20'):
        """CN giam gia fraction tren untaxed — khong tra hang."""
        lines = []
        for aml in bill.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
        ):
            lines.append(Command.create({
                'product_id': aml.product_id.id,
                'name': 'Giam gia %s%%' % int(fraction * 100),
                'quantity': aml.quantity,
                'price_unit': (aml.price_unit or 0.0) * fraction,
                'tax_ids': [Command.set(aml.tax_ids.ids)],
                'purchase_line_id': aml.purchase_line_id.id if aml.purchase_line_id else False,
            }))
        cn = self.env['account.move'].create({
            'move_type': 'in_refund',
            'partner_id': bill.partner_id.id,
            'invoice_date': date,
            'date': date,
            'journal_id': self.purchase_j.id,
            'company_id': self.company.id,
            'reversed_entry_id': bill.id,
            'invoice_line_ids': lines,
        })
        cn.action_post()
        return cn

    def test_w4_g6_vendor_discount_stock_remaining(self):
        """G6/M09: CN giam gia, hang con ton -> No 331 / Co 156 + Co 1331."""
        self._ensure_r09b()
        _po, bill = self._buy_receive_bill(qty=10.0, price=20_000.0)
        self._sync()
        cn = self._vendor_credit_note(bill, fraction=0.1)
        untaxed = cn.amount_untaxed
        tax = cn.amount_tax
        self.assertAlmostEqual(untaxed, 20_000.0)
        self.assertFalse(self.env['vas.sync']._refund_has_stock_return(cn))
        self._sync()
        moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', cn.id),
            ('move_kind', '=', 'refund'),
            ('state', '=', 'posted'),
        ])
        self.assertTrue(moves, 'R09b phai sinh JE')
        bal = self._net(moves)
        self.assertEqual(float_compare(bal.get('331', 0.0), untaxed + tax, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('156', 0.0), -untaxed, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('1331', 0.0), -tax, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('632', 0.0), 0.0, 2), 0, bal)

    def test_w4_g7_vendor_discount_already_sold(self):
        """G7/M09: CN giam gia, hang da ban het -> No 331 / Co 632 + Co 1331."""
        self._ensure_r09b()
        _po, bill = self._buy_receive_bill(qty=10.0, price=20_000.0)
        self._sync()
        self.product.invoice_policy = 'order'
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': 10,
                'price_unit': 100_000,
                'tax_ids': [Command.set(self.tax_sale.ids)],
            })],
        })
        so.action_confirm()
        for pick in so.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            self._validate_pick(pick)
        stock_loc = self.env.ref('stock.stock_location_stock')
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product.id),
            ('location_id', 'child_of', stock_loc.id),
        ])
        for quant in quants:
            if float_compare(quant.quantity, 0.0, 2) > 0:
                quant.with_context(inventory_mode=True).write({'inventory_quantity': 0.0})
                quant.action_apply_inventory()

        cn = self._vendor_credit_note(bill, fraction=0.1)
        untaxed = cn.amount_untaxed
        tax = cn.amount_tax
        Sync = self.env['vas.sync']
        cn_line = cn.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
        )[:1]
        self.assertEqual(
            float_compare(
                Sync._purchase_discount_stock_fraction(cn_line, self.company),
                0.0, 2,
            ),
            0,
        )
        self._sync()
        moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', cn.id),
            ('move_kind', '=', 'refund'),
            ('state', '=', 'posted'),
        ])
        self.assertTrue(moves)
        bal = self._net(moves)
        self.assertEqual(float_compare(bal.get('331', 0.0), untaxed + tax, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('632', 0.0), -untaxed, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('1331', 0.0), -tax, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('156', 0.0), 0.0, 2), 0, bal)

    def test_w4_g6_discount_product_uses_origin_goods_account(self):
        """CN dong SP Discount (service) van lay TK 156 theo hang tren HD goc."""
        self._ensure_r09b()
        _po, bill = self._buy_receive_bill(qty=10.0, price=20_000.0)
        self._sync()
        disc = self.env['product.product'].create({
            'name': 'Discount',
            'type': 'service',
            'purchase_ok': True,
            'sale_ok': False,
            'list_price': 0.0,
            'supplier_taxes_id': [Command.set(self.tax_purchase.ids)],
        })
        cn = self.env['account.move'].create({
            'move_type': 'in_refund',
            'partner_id': bill.partner_id.id,
            'invoice_date': '2099-05-21',
            'date': '2099-05-21',
            'journal_id': self.purchase_j.id,
            'company_id': self.company.id,
            'reversed_entry_id': bill.id,
            'invoice_line_ids': [Command.create({
                'product_id': disc.id,
                'name': 'Vendor discount 10%',
                'quantity': 1.0,
                'price_unit': 20_000.0,
                'tax_ids': [Command.set(self.tax_purchase.ids)],
            })],
        })
        cn.action_post()
        Sync = self.env['vas.sync']
        self.assertTrue(
            Sync._purchase_discount_is_proxy_line(cn.invoice_line_ids[:1], cn),
        )
        self._sync()
        moves = self.env['vas.move'].search([
            ('source_model', '=', 'account.move'),
            ('source_res_id', '=', cn.id),
            ('move_kind', '=', 'refund'),
            ('state', '=', 'posted'),
        ])
        self.assertTrue(moves)
        self.assertFalse(
            moves.vas_has_default_account,
            'Khong duoc gan co TK mac dinh khi da resolve theo hang goc',
        )
        bal = self._net(moves)
        self.assertEqual(float_compare(bal.get('156', 0.0), -20_000.0, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('1331', 0.0), -2_000.0, 2), 0, bal)
        self.assertEqual(float_compare(bal.get('331', 0.0), 22_000.0, 2), 0, bal)
