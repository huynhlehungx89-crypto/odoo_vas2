# -*- coding: utf-8 -*-
"""Fix R06 nuốt phiếu trả NCC — S01/S02 + regression nhập thường + 151.

  S01: nhận → R06 156/331; trả → R09s 331/156; COMBINED ≈ 0.
  S02: R06 không tạo JE trên return move.
  REG: nhận supplier→internal vẫn R06; HĐ→151 rồi nhận→156/151 không vỡ.

GIT × phiếu trả (R09s vẫn 331/156, chưa Có 151): ngoài scope — gắn cờ sau.
Dropship: domain chỉ loại dest=supplier — không whitelist hẹp.
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


DATE = '2099-08-15'
PRICE = 80_000.0


@tagged('connecta_vas', 'connecta_vas_stock_return', 'post_install', '-at_install')
class TestTt133PurchaseReturnStock(TransactionCase):
    """R06 loại chiều trả; R09s bù đúng."""

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
                'code': 'TT133',
                'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.company.vas_theo_doi_hang_di_duong = False
        cls._ensure_period()

        cls.partner = cls.env['res.partner'].create({
            'name': 'NCC Return Stock Fix',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.tax = cls.env['account.tax'].search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', 'purchase'),
            ('amount', '=', 10.0),
        ], limit=1)
        cls.cat = cls.env['product.category'].create({
            'name': 'HH Return Fix FIFO',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })
        acc156 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '156'),
        ], limit=1)
        assert acc156
        if not cls.env['vas.account.map'].search([
            ('regime_id', '=', cls.regime.id),
            ('company_id', '=', cls.company.id),
            ('category_id', '=', cls.cat.id),
        ], limit=1):
            cls.env['vas.account.map'].create({
                'regime_id': cls.regime.id,
                'apply_to': 'category',
                'company_id': cls.company.id,
                'category_id': cls.cat.id,
                'stock_account_id': acc156.id,
            })
        cls.product = cls.env['product.product'].create({
            'name': 'HH Return Fix',
            'is_storable': True,
            'categ_id': cls.cat.id,
            'standard_price': PRICE,
            'list_price': PRICE,
            'supplier_taxes_id': [Command.set(cls.tax.ids)] if cls.tax else [],
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'purchase_ok': True,
        })
        cls.purchase_j = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'purchase'),
        ], limit=1)
        assert cls.purchase_j

    @classmethod
    def _ensure_period(cls):
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', DATE),
            ('date_to', '>=', DATE),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        if not fy.period_ids:
            fy.action_generate_periods()
        else:
            fy.period_ids.write({'state': 'open'})

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += (line.debit or 0.0) - (line.credit or 0.0)
        return dict(bal)

    def _receive_po(self, qty=1.0, price=PRICE):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'date_order': DATE,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'product_qty': qty,
                'price_unit': price,
                'tax_ids': [Command.set(self.tax.ids)] if self.tax else [],
            })],
        })
        po.button_confirm()
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
        self.assertTrue(picking)
        for m in picking.move_ids:
            m.quantity = qty
        picking.button_validate()
        sm = picking.move_ids.filtered(lambda m: m.state == 'done')[:1]
        sm.write({'date': fields.Datetime.to_datetime(DATE)})
        if float_compare(sm.value or 0.0, 0.0, precision_digits=2) == 0:
            sm.value = price * qty
        return po, picking, sm

    def _return_picking(self, picking, qty=1.0):
        wiz = self.env['stock.return.picking'].with_context(
            active_id=picking.id,
            active_ids=picking.ids,
            active_model='stock.picking',
        ).create({})
        for line in wiz.product_return_moves:
            if 'quantity' in line._fields:
                line.quantity = qty
        act = wiz.action_create_returns()
        ret = self.env['stock.picking'].browse(act['res_id'])
        for m in ret.move_ids:
            m.quantity = qty
        ret.button_validate()
        ret_sm = ret.move_ids.filtered(lambda m: m.state == 'done')
        for m in ret_sm:
            m.write({'date': fields.Datetime.to_datetime(DATE)})
        return ret, ret_sm

    def _vas_stock(self, stock_move):
        return self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'),
            ('source_res_id', '=', stock_move.id),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])

    # ------------------------------------------------------------------
    # S01 / S02
    # ------------------------------------------------------------------

    def test_s01_s02_receipt_then_return_nets_zero(self):
        _po, picking, sm = self._receive_po()
        stats1 = self._sync()
        self.assertGreaterEqual(
            (stats1.get('purchase_receipt') or {}).get('created', 0), 1, stats1,
        )
        r06 = self._vas_stock(sm)
        self.assertEqual(len(r06), 1)
        self.assertEqual(r06.move_kind, 'stock')
        bal06 = self._net(r06)
        self.assertAlmostEqual(bal06.get('156', 0.0), PRICE, delta=1)
        self.assertAlmostEqual(bal06.get('331', 0.0), -PRICE, delta=1)
        print(f'\n=== S01 R06 receipt ===\n  {bal06}\n')

        _ret, ret_sm = self._return_picking(picking)
        self.assertTrue(ret_sm)
        self.assertEqual(ret_sm[:1].location_dest_id.usage, 'supplier')

        stats2 = self._sync()
        ret_stats = stats2.get('purchase_return_stock') or {}
        self.assertGreaterEqual(
            ret_stats.get('created', 0), 1,
            f'R09s phải tạo JE: {ret_stats} full={stats2}',
        )
        # S02: R06 không tạo trên return
        for m in ret_sm:
            on_ret = self._vas_stock(m)
            self.assertTrue(on_ret, 'Phải có JE R09s trên return')
            bal = self._net(on_ret)
            # R09s: Nợ 331 / Có 156 — không phải R06 (+156)
            self.assertAlmostEqual(bal.get('156', 0.0), -PRICE, delta=1, msg=bal)
            self.assertAlmostEqual(bal.get('331', 0.0), PRICE, delta=1, msg=bal)

        all_live = self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'),
            ('source_res_id', 'in', (sm | ret_sm).ids),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])
        combined = self._net(all_live)
        self.assertAlmostEqual(combined.get('156', 0.0), 0.0, delta=1, msg=combined)
        self.assertAlmostEqual(combined.get('331', 0.0), 0.0, delta=1, msg=combined)
        print(
            f'\n=== S01/S02 return ===\n  ret_stats={ret_stats}\n'
            f'  COMBINED={dict(sorted(combined.items()))}\n'
        )

    # ------------------------------------------------------------------
    # Regression
    # ------------------------------------------------------------------

    def test_reg_normal_receipt_still_r06(self):
        _po, _pick, sm = self._receive_po(price=50_000.0)
        self.assertEqual(sm.location_id.usage, 'supplier')
        self.assertEqual(sm.location_dest_id.usage, 'internal')
        self._sync()
        r06 = self._vas_stock(sm)
        self.assertEqual(len(r06), 1)
        bal = self._net(r06)
        self.assertAlmostEqual(bal.get('156', 0.0), 50_000.0, delta=1)
        self.assertAlmostEqual(bal.get('331', 0.0), -50_000.0, delta=1)
        print(f'\n=== REG normal receipt ===\n  {bal}\n')

    def test_reg_goods_in_transit_151_still_ok(self):
        """HĐ trước → R10 151; nhận → R06 156/151 — domain mới không vỡ."""
        self.company.vas_theo_doi_hang_di_duong = True
        try:
            po = self.env['purchase.order'].create({
                'partner_id': self.partner.id,
                'company_id': self.company.id,
                'date_order': DATE,
                'order_line': [Command.create({
                    'product_id': self.product.id,
                    'name': self.product.name,
                    'product_qty': 1,
                    'price_unit': PRICE,
                    'tax_ids': [Command.set(self.tax.ids)] if self.tax else [],
                })],
            })
            po.button_confirm()
            bill = self.env['account.move'].create({
                'move_type': 'in_invoice',
                'partner_id': self.partner.id,
                'invoice_date': DATE,
                'date': DATE,
                'journal_id': self.purchase_j.id,
                'company_id': self.company.id,
                'invoice_line_ids': [Command.create({
                    'product_id': self.product.id,
                    'name': self.product.name,
                    'quantity': 1,
                    'price_unit': PRICE,
                    'tax_ids': [Command.set(self.tax.ids)] if self.tax else [],
                    'purchase_line_id': po.order_line[:1].id,
                })],
            })
            bill.action_post()
            self._sync()
            git = self.env['vas.move'].search([
                ('source_model', '=', 'account.move'),
                ('source_res_id', '=', bill.id),
                ('move_kind', '=', 'goods_in_transit'),
                ('state', '=', 'posted'),
                ('is_reversal', '=', False),
            ])
            self.assertTrue(git, 'REG 151: thiếu R10')
            bal_git = self._net(git)
            self.assertAlmostEqual(bal_git.get('151', 0.0), PRICE, delta=1)

            picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
            for m in picking.move_ids:
                m.quantity = 1
            picking.button_validate()
            sm = picking.move_ids.filtered(lambda m: m.state == 'done')[:1]
            sm.write({'date': fields.Datetime.to_datetime(DATE)})
            if float_compare(sm.value or 0.0, 0.0, precision_digits=2) == 0:
                sm.value = PRICE
            self._sync()
            r06 = self._vas_stock(sm)
            self.assertTrue(r06)
            bal = self._net(r06)
            self.assertAlmostEqual(bal.get('156', 0.0), PRICE, delta=1)
            self.assertAlmostEqual(bal.get('151', 0.0), -PRICE, delta=1, msg=bal)
            print(f'\n=== REG 151 path ===\n  git={bal_git} r06={bal}\n')
        finally:
            self.company.vas_theo_doi_hang_di_duong = False
