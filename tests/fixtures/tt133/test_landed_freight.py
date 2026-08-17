# -*- coding: utf-8 -*-
"""Fixtures TT133 — phần cước landed cost (R25 / R26 / R08 exclude).

Ca nghiệm thu:
  (a) LC có hóa đơn → vốn hóa 156 + thuế cước 1331
  (b) LC không vendor_bill → gắn cờ, không bút toán
  (c) cước quốc tế 0% → R26 không sinh 1331, không lỗi
  (d) R08 / R25 / R26 không chồng lấn (mỗi tiền một lần)

Ngoài phạm vi (không giả phủ): thuế NK 3333, GTGT NK 33312, TK 151, R24 FX.
"""
from collections import defaultdict

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools import float_compare


DATE = '2099-08-15'
GOODS_NET = 10_000_000.0
FREIGHT_NET = 2_000_000.0
TAX_RATE = 10.0


@tagged('connecta_vas', 'connecta_vas_landed', 'post_install', '-at_install')
class TestTt133LandedFreight(TransactionCase):
    """Định kỳ: vốn hóa cước + thuế HĐ cước + chống double-count R08."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'stock.landed.cost' not in cls.env:
            cls._landed_ready = False
            return
        cls._landed_ready = True

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
        cls._ensure_rules()
        cls._ensure_period()

        cls.partner_goods = cls.env['res.partner'].create({
            'name': 'NCC HH Landed',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })
        cls.partner_freight = cls.env['res.partner'].create({
            'name': 'NCC Cước Landed',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })

        cls.cat_hh = cls.env['product.category'].create({
            'name': 'HH Landed FIFO',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
        })
        cls._map(cls.cat_hh, stock='156')

        cls.tax_10 = cls._make_purchase_tax(10.0, 'GTGT 10% landed')
        cls.tax_0 = cls._make_purchase_tax(0.0, 'GTGT 0% landed QT')

        uom = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.product'].create({
            'name': 'HH Landed Test',
            'is_storable': True,
            'categ_id': cls.cat_hh.id,
            'list_price': GOODS_NET,
            'standard_price': GOODS_NET,
            'uom_id': uom.id,
            'purchase_ok': True,
            'supplier_taxes_id': [Command.set(cls.tax_10.ids)],
        })
        cls.freight = cls.env['product.product'].create({
            'name': 'Cước VC Landed',
            'type': 'service',
            'landed_cost_ok': True,
            'list_price': FREIGHT_NET,
            'standard_price': FREIGHT_NET,
            'purchase_ok': True,
            'sale_ok': False,
            'supplier_taxes_id': [Command.set(cls.tax_10.ids)],
            'split_method_landed_cost': 'equal',
        })
        cls.freight_0 = cls.env['product.product'].create({
            'name': 'Cước QT 0%',
            'type': 'service',
            'landed_cost_ok': True,
            'list_price': FREIGHT_NET,
            'standard_price': FREIGHT_NET,
            'purchase_ok': True,
            'sale_ok': False,
            'supplier_taxes_id': [Command.set(cls.tax_0.ids)],
            'split_method_landed_cost': 'equal',
        })

        cls.purchase_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'purchase'),
        ], limit=1)
        cls.lc_journal = (
            cls.company.lc_journal_id
            or cls.env['account.journal'].search([
                ('company_id', '=', cls.company.id),
                ('type', '=', 'general'),
            ], limit=1)
        )
        assert cls.purchase_journal and cls.lc_journal, 'Need purchase + LC journals'
        if not cls.company.lc_journal_id:
            cls.company.lc_journal_id = cls.lc_journal

        cls.FREIGHT_TAX = FREIGHT_NET * TAX_RATE / 100.0

    @classmethod
    def _acc(cls, code):
        account = cls.env['vas.account'].search([
            ('regime_id', '=', cls.company.vas_regime_id.id),
            ('code', '=', code),
        ], limit=1)
        assert account, f'Thiếu tài khoản VAS {code}'
        return account

    @classmethod
    def _map(cls, category, stock=None):
        vals = {
            'regime_id': cls.company.vas_regime_id.id,
            'apply_to': 'category',
            'company_id': cls.company.id,
            'category_id': category.id,
        }
        if stock:
            vals['stock_account_id'] = cls._acc(stock).id
        return cls.env['vas.account.map'].create(vals)

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

    @classmethod
    def _ensure_rules(cls):
        Rule = cls.env['vas.rule']
        regime = cls.company.vas_regime_id
        specs = {
            'R06': (
                'Nhập kho mua hàng', 'purchase_receipt', 40,
                [('debit', 'product_inventory', 'stock_value'),
                 ('credit', 'receipt_counterpart', 'stock_value')],
            ),
            'R07': (
                'Hóa đơn mua (thuế hàng)', 'purchase_invoice', 50,
                [('debit', 'tax_input', 'tax'),
                 ('credit', 'partner_payable', 'tax')],
            ),
            'R08': (
                'Chi phí mua ngoài', 'purchase_service', 48,
                [('debit', 'product_expense', 'untaxed'),
                 ('debit', 'tax_input', 'tax'),
                 ('credit', 'partner_payable', 'total')],
            ),
            'R25': (
                'Vốn hóa cước landed', 'landed_cost_adjust', 45,
                [('debit', 'product_inventory', 'landed_cost'),
                 ('credit', 'landed_counterpart', 'landed_cost')],
            ),
            'R26': (
                'Thuế GTGT hóa đơn cước', 'purchase_landed_tax', 49,
                [('debit', 'tax_input', 'tax'),
                 ('credit', 'partner_payable', 'tax')],
            ),
        }
        for code, (name, event_type, sequence, lines) in specs.items():
            existing = Rule.search(
                [('regime_id', '=', regime.id), ('code', '=', code)], limit=1,
            )
            if existing:
                if code == 'R25':
                    credit = existing.line_ids.filtered(lambda l: l.side == 'credit')[:1]
                    if credit and credit.account_selector == 'partner_payable':
                        credit.account_selector = 'landed_counterpart'
                if code == 'R06':
                    credit = existing.line_ids.filtered(lambda l: l.side == 'credit')[:1]
                    if credit and credit.account_selector == 'partner_payable':
                        credit.account_selector = 'receipt_counterpart'
                continue
            Rule.create({
                'code': code,
                'name': name,
                'regime_id': regime.id,
                'event_type': event_type,
                'sequence': sequence,
                'active': True,
                'line_ids': [
                    Command.create({
                        'sequence': (i + 1) * 10,
                        'side': side,
                        'account_selector': sel,
                        'amount_selector': amt,
                    })
                    for i, (side, sel, amt) in enumerate(lines)
                ],
            })

    @classmethod
    def _make_purchase_tax(cls, amount, name):
        Tax = cls.env['account.tax']
        existing = Tax.search([
            ('company_id', '=', cls.company.id),
            ('type_tax_use', '=', 'purchase'),
            ('amount', '=', amount),
            ('amount_type', '=', 'percent'),
            ('name', '=', name),
        ], limit=1)
        if existing:
            return existing
        return Tax.create({
            'name': name,
            'amount': amount,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
            'company_id': cls.company.id,
        })

    def _require_landed(self):
        if not getattr(self, '_landed_ready', False):
            self.skipTest('stock_landed_costs chưa có trên DB test')

    def _sync(self):
        return self.env['vas.sync'].sync_company(
            self.company, date_from='2099-01-01', date_to='2099-12-31',
        )

    def _net(self, moves):
        bal = defaultdict(float)
        for line in moves.mapped('line_ids'):
            bal[line.account_id.code] += (line.debit or 0.0) - (line.credit or 0.0)
        return dict(bal)

    def _vas_moves(self, source_model, source_id, move_kind=None):
        domain = [
            ('source_model', '=', source_model),
            ('source_res_id', '=', source_id),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ]
        if move_kind:
            domain.append(('move_kind', '=', move_kind))
        return self.env['vas.move'].search(domain)

    def _receive_goods(self):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner_goods.id,
            'company_id': self.company.id,
            'date_order': DATE,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'name': self.product.name,
                'product_qty': 1.0,
                'price_unit': GOODS_NET,
                'tax_ids': [Command.clear()],
            })],
        })
        po.button_confirm()
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')[:1]
        self.assertTrue(picking, 'PO phải tạo phiếu nhập')
        for move in picking.move_ids:
            move.quantity = 1.0
        picking.button_validate()
        receipt = picking.move_ids.filtered(lambda m: m.state == 'done')[:1]
        receipt.write({'date': fields.Datetime.to_datetime(DATE)})
        if float_compare(receipt.value or 0.0, 0.0, precision_digits=2) == 0:
            receipt.value = GOODS_NET
        return po, picking, receipt

    def _post_freight_bill(self, freight_product, tax, partner=None):
        partner = partner or self.partner_freight
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': DATE,
            'date': DATE,
            'journal_id': self.purchase_journal.id,
            'company_id': self.company.id,
            'invoice_line_ids': [Command.create({
                'product_id': freight_product.id,
                'name': freight_product.name,
                'quantity': 1.0,
                'price_unit': FREIGHT_NET,
                'tax_ids': [Command.set(tax.ids)],
                'is_landed_costs_line': True,
            })],
        })
        bill.action_post()
        return bill

    def _create_and_validate_lc(self, picking, freight_product, vendor_bill=None):
        accounts = freight_product.product_tmpl_id.get_product_accounts()
        expense = accounts.get('expense')
        self.assertTrue(expense, 'SP cước cần TK expense Odoo để validate LC')
        lc = self.env['stock.landed.cost'].create({
            'date': DATE,
            'company_id': self.company.id,
            'account_journal_id': self.lc_journal.id,
            'picking_ids': [Command.set(picking.ids)],
            'vendor_bill_id': vendor_bill.id if vendor_bill else False,
            'cost_lines': [Command.create({
                'product_id': freight_product.id,
                'name': freight_product.name,
                'price_unit': FREIGHT_NET,
                'split_method': 'equal',
                'account_id': expense.id,
            })],
        })
        lc.compute_landed_cost()
        lc.button_validate()
        self.assertEqual(lc.state, 'done', 'LC phải validate được')
        return lc

    def test_a_lc_with_bill_capitalizes_and_vat(self):
        self._require_landed()
        _po, picking, receipt = self._receive_goods()
        # Sync trước LC: R06 khóa giá hàng (không gồm cước — value còn GOODS_NET).
        self._sync()
        bill = self._post_freight_bill(self.freight, self.tax_10)
        lc = self._create_and_validate_lc(picking, self.freight, vendor_bill=bill)
        adj = lc.valuation_adjustment_lines[:1]
        self.assertTrue(adj, 'LC phải có adjustment line')
        self.assertAlmostEqual(
            adj.additional_landed_cost, FREIGHT_NET, delta=1,
            msg=f'additional={adj.additional_landed_cost}',
        )

        stats = self._sync()
        self.assertGreaterEqual(
            stats.get('landed_cost_adjust', {}).get('created', 0), 1,
            f'R25 phải tạo bút toán; stats={stats.get("landed_cost_adjust")}',
        )
        self.assertGreaterEqual(
            stats.get('purchase_landed_tax', {}).get('created', 0), 1,
            f'R26 phải tạo bút toán thuế; stats={stats.get("purchase_landed_tax")}',
        )

        r25 = self._vas_moves(
            'stock.valuation.adjustment.lines', adj.id, move_kind='landed',
        )
        self.assertEqual(len(r25), 1, f'R25 moves={r25}')
        bal25 = self._net(r25)
        self.assertAlmostEqual(bal25.get('156', 0.0), FREIGHT_NET, delta=1, msg=bal25)
        self.assertAlmostEqual(bal25.get('331', 0.0), -FREIGHT_NET, delta=1, msg=bal25)

        r26 = self._vas_moves('account.move', bill.id, move_kind='landed_tax')
        self.assertEqual(len(r26), 1, f'R26 moves={r26}')
        bal26 = self._net(r26)
        self.assertAlmostEqual(
            bal26.get('1331', 0.0), self.FREIGHT_TAX, delta=1, msg=bal26,
        )
        self.assertAlmostEqual(
            bal26.get('331', 0.0), -self.FREIGHT_TAX, delta=1, msg=bal26,
        )
        print(
            f'\n=== (a) LC+bill ===\n'
            f'  receipt.value={receipt.value}\n'
            f'  R25 {bal25}\n'
            f'  R26 {bal26}\n'
        )

    def test_b_lc_without_vendor_bill_flags_no_move(self):
        self._require_landed()
        _po, picking, _receipt = self._receive_goods()
        lc = self._create_and_validate_lc(picking, self.freight, vendor_bill=None)
        self.assertFalse(lc.vendor_bill_id)
        adj = lc.valuation_adjustment_lines[:1]
        self.assertTrue(adj)

        stats = self._sync()
        r25_stats = stats.get('landed_cost_adjust') or {}
        self.assertEqual(
            r25_stats.get('created', 0), 0,
            f'Không được sinh R25 khi thiếu bill; stats={r25_stats}',
        )
        self.assertGreaterEqual(
            r25_stats.get('flagged_no_bill', 0), 1,
            f'Phải gắn cờ thiếu bill; stats={r25_stats}',
        )
        self.assertFalse(
            self._vas_moves(
                'stock.valuation.adjustment.lines', adj.id, move_kind='landed',
            ),
            'Không có vas.move R25 khi thiếu vendor_bill',
        )
        self.assertGreaterEqual(
            (stats.get('default_account') or {}).get('landed_flags', 0), 1,
            f'landed_flags phải > 0; summary={stats.get("default_account")}',
        )
        print(f'\n=== (b) no vendor_bill ===\n  stats={r25_stats}\n')

    def test_c_zero_tax_freight_silent_r26(self):
        self._require_landed()
        _po, picking, _receipt = self._receive_goods()
        self._sync()
        bill = self._post_freight_bill(self.freight_0, self.tax_0)
        self.assertAlmostEqual(bill.amount_tax, 0.0, delta=0.01)
        lc = self._create_and_validate_lc(picking, self.freight_0, vendor_bill=bill)
        adj = lc.valuation_adjustment_lines[:1]

        stats = self._sync()
        r26_stats = stats.get('purchase_landed_tax') or {}
        self.assertEqual(
            r26_stats.get('created', 0), 0,
            f'R26 không được tạo khi thuế=0; stats={r26_stats}',
        )
        self.assertGreaterEqual(
            r26_stats.get('silent_zero_tax', 0), 1,
            f'Phải đếm silent_zero_tax; stats={r26_stats}',
        )
        self.assertFalse(
            self._vas_moves('account.move', bill.id, move_kind='landed_tax'),
            'Không có vas.move R26 khi thuế 0%',
        )
        r25 = self._vas_moves(
            'stock.valuation.adjustment.lines', adj.id, move_kind='landed',
        )
        self.assertEqual(len(r25), 1)
        bal25 = self._net(r25)
        self.assertAlmostEqual(bal25.get('156', 0.0), FREIGHT_NET, delta=1, msg=bal25)
        print(f'\n=== (c) 0% tax ===\n  R26={r26_stats}\n  R25={bal25}\n')

    def test_d_no_overlap_r08_r25_r26(self):
        """Mỗi tiền một lần: R06 hàng → R25 cước net → R26 thuế; R08 = 0.

        Luồng vận hành thật: sync sau nhập (R06 khóa GOODS_NET) rồi LC rồi sync
        lại (R25/R26). Sync một lần SAU LC sẽ làm R06 đọc value đã +cước — đó
        là hành vi Odoo đã đo, không phải chồng R25.
        """
        self._require_landed()
        _po, picking, receipt = self._receive_goods()
        self._sync()
        r06_before = self._vas_moves('stock.move', receipt.id, move_kind='stock')
        self.assertEqual(len(r06_before), 1)
        bal06 = self._net(r06_before)
        self.assertAlmostEqual(
            bal06.get('156', 0.0), GOODS_NET, delta=1,
            msg=f'R06 trước LC = giá hàng; {bal06}',
        )

        bill = self._post_freight_bill(self.freight, self.tax_10)
        lc = self._create_and_validate_lc(picking, self.freight, vendor_bill=bill)
        adj = lc.valuation_adjustment_lines[:1]

        self._sync()

        r08 = self._vas_moves('account.move', bill.id, move_kind='expense')
        r25 = self._vas_moves(
            'stock.valuation.adjustment.lines', adj.id, move_kind='landed',
        )
        r26 = self._vas_moves('account.move', bill.id, move_kind='landed_tax')
        r06_after = self._vas_moves('stock.move', receipt.id, move_kind='stock')

        self.assertFalse(
            r08,
            f'R08 phải loại dòng landed — không được ghi 642; moves={r08}',
        )
        self.assertEqual(len(r25), 1)
        self.assertEqual(len(r26), 1)
        # R06 không chạy lại (đã sync trước LC) dù sm.value đã +cước.
        self.assertEqual(len(r06_after), 1)
        self.assertAlmostEqual(
            self._net(r06_after).get('156', 0.0), GOODS_NET, delta=1,
        )

        bal25 = self._net(r25)
        bal26 = self._net(r26)

        self.assertAlmostEqual(bal25.get('156', 0.0), FREIGHT_NET, delta=1)
        self.assertNotIn('6421', bal25)
        self.assertNotIn('6422', bal25)
        self.assertAlmostEqual(bal26.get('1331', 0.0), self.FREIGHT_TAX, delta=1)
        self.assertAlmostEqual(bal26.get('156', 0.0), 0.0, delta=0.01)

        total_156 = bal06.get('156', 0.0) + bal25.get('156', 0.0)
        self.assertAlmostEqual(
            total_156, GOODS_NET + FREIGHT_NET, delta=1,
            msg='156 = hàng (R06) + cước (R25), mỗi phần một lần',
        )
        print(
            f'\n=== (d) no overlap ===\n'
            f'  R08 count={len(r08)}\n'
            f'  R06 {bal06}\n'
            f'  R25 {bal25}\n'
            f'  R26 {bal26}\n'
            f'  156 total={total_156}\n'
        )

    def test_orphan_landed_bill_without_lc_flags(self):
        self._require_landed()
        bill = self._post_freight_bill(self.freight, self.tax_10)
        stats = self._sync()
        orphan = stats.get('landed_orphan') or {}
        self.assertGreaterEqual(
            orphan.get('flagged', 0), 1,
            f'Phải gắn cờ orphan LC; stats={orphan}',
        )
        self.assertFalse(
            self._vas_moves('account.move', bill.id, move_kind='expense'),
            'R08 không ghi dòng landed orphan',
        )
        r26 = self._vas_moves('account.move', bill.id, move_kind='landed_tax')
        self.assertEqual(len(r26), 1, 'R26 vẫn ghi thuế dù chưa có LC')
        print(f'\n=== orphan ===\n  {orphan}\n  R26={self._net(r26)}\n')

    def test_t9_cancel_landed_cost_reverses(self):
        """Hủy phiếu LC (kỳ mở) → đảo bút toán R25 theo cơ chế cancel hiện có."""
        self._require_landed()
        _po, picking, _receipt = self._receive_goods()
        self._sync()
        bill = self._post_freight_bill(self.freight, self.tax_10)
        lc = self._create_and_validate_lc(picking, self.freight, vendor_bill=bill)
        self._sync()
        adj = lc.valuation_adjustment_lines[:1]
        r25 = self._vas_moves(
            'stock.valuation.adjustment.lines', adj.id, move_kind='landed',
        )
        self.assertEqual(len(r25), 1)
        orig = r25[:1]
        self.assertEqual(orig.state, 'posted')
        # LC done không có button_cancel; state draft = chết trong _source_is_dead.
        lc.write({'state': 'draft'})
        stats = self.env['vas.sync']._sync_cancel_regressions(self.company)
        orig.invalidate_recordset()
        self.assertGreaterEqual(stats['reversed'], 1, stats)
        self.assertEqual(orig.state, 'reversed')
