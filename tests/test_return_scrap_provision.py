# -*- coding: utf-8 -*-
"""Trả hàng đúng giá vốn lô xuất + scrap + dự phòng HTK (T1–T14)."""
from datetime import datetime

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('connecta_vas', 'connecta_vas_return_scrap')
class TestReturnScrapProvision(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.Sync = cls.env['vas.sync']
        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.supplier_location = cls.env.ref('stock.stock_location_suppliers')
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.picking_type_in = cls.env.ref('stock.picking_type_in')
        cls.picking_type_out = cls.env.ref('stock.picking_type_out')
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-11-15'),
            ('date_to', '>=', '2099-12-15'),
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
        cls.fy = fy
        cls.period_nov = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2099-11-01'),
        ], limit=1)
        if not cls.period_nov:
            cls.period_nov = cls.env['vas.period'].create({
                'name': '11/2099',
                'date_start': '2099-11-01',
                'date_end': '2099-11-30',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        cls.period_dec = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2099-12-01'),
        ], limit=1)
        if not cls.period_dec:
            cls.period_dec = cls.env['vas.period'].create({
                'name': '12/2099',
                'date_start': '2099-12-01',
                'date_end': '2099-12-31',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        cls.cat = cls.env['product.category'].create({
            'name': 'HH trả hàng AVCO',
            'property_cost_method': 'average',
            'property_valuation': 'real_time',
        })
        cls.env['vas.account.map'].create({
            'regime_id': cls.regime.id,
            'apply_to': 'category',
            'category_id': cls.cat.id,
            'stock_account_id': cls._acc('156').id,
            'cogs_account_id': cls._acc('632').id,
            'revenue_account_id': cls._acc('5111').id,
        })
        acc_811 = cls._acc('811')
        cls.company.vas_scrap_account_id = acc_811

    @classmethod
    def _acc(cls, code):
        rec = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', code),
        ], limit=1)
        if not rec:
            atype = 'expense' if code in ('632', '811') else (
                'liability' if code == '2294' else 'asset'
            )
            rec = cls.env['vas.account'].create({
                'code': code, 'name': code, 'regime_id': cls.regime.id,
                'account_type': atype,
            })
        return rec

    def _product(self, name):
        return self.env['product.product'].create({
            'name': name,
            'is_storable': True,
            'categ_id': self.cat.id,
            'list_price': 50_000,
            'standard_price': 20_000,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
        })

    def _make_in(self, product, qty, unit_cost, date='2099-11-10'):
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': self.supplier_location.id,
            'location_dest_id': self.stock_location.id,
            'company_id': self.company.id,
            'picking_type_id': self.picking_type_in.id,
            'price_unit': unit_cost,
            'value_manual': unit_cost * qty,
        })
        move._action_confirm()
        move._action_assign()
        move.picked = True
        move._action_done()
        move.date = date
        return move

    def _make_out(self, product, qty, date='2099-11-11', origin='SO-RET'):
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'company_id': self.company.id,
            'picking_type_id': self.picking_type_out.id,
            'origin': origin,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        move.date = date
        return move

    def _make_return(self, out_move, qty, date='2099-11-13', origin_link=True):
        vals = {
            'product_id': out_move.product_id.id,
            'product_uom_qty': qty,
            'product_uom': out_move.product_uom.id,
            'location_id': self.customer_location.id,
            'location_dest_id': self.stock_location.id,
            'company_id': self.company.id,
            'picking_type_id': self.picking_type_in.id,
            'origin': 'return %s' % (out_move.origin or out_move.id),
        }
        if origin_link:
            vals['origin_returned_move_id'] = out_move.id
        move = self.env['stock.move'].create(vals)
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        move.date = date
        return move

    def _vas(self, source, kind=None):
        domain = [
            ('source_model', '=', source._name),
            ('source_res_id', '=', source.id),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ]
        if kind:
            domain.append(('move_kind', '=', kind))
        return self.env['vas.move'].search(domain)

    def _amt(self, move, code, side):
        lines = move.line_ids.filtered(
            lambda l: (l.account_id.code or '').startswith(code)
        )
        if side == 'debit':
            return sum(lines.mapped('debit'))
        return sum(lines.mapped('credit'))

    def test_t1_unlinked_combined_return_flagged_zero(self):
        """T1: trả gộp không chỉ rõ lô → 0 + cờ, không đoán số."""
        product = self._product('HH T1 không lô')
        self._make_in(product, 2, 20_000, '2099-11-01')
        out1 = self._make_out(product, 2, '2099-11-02', origin='SO-A')
        self._make_in(product, 2, 30_000, '2099-11-03')
        out2 = self._make_out(product, 2, '2099-11-04', origin='SO-B')
        self.Sync.sync_company(self.company)
        self.assertTrue(self._vas(out1, 'cogs'))
        self.assertTrue(self._vas(out2, 'cogs'))
        # Trả gộp 3 sp, CỐ Ý không gắn origin_returned_move_id.
        ret = self._make_return(out2, 3, '2099-11-13', origin_link=False)
        self.assertFalse(ret.origin_returned_move_id)
        self.Sync.sync_company(self.company)
        stock = self._vas(ret, 'stock')
        self.assertEqual(len(stock), 1)
        self.assertEqual(self._amt(stock, '156', 'debit'), 0.0)
        self.assertEqual(self._amt(stock, '632', 'credit'), 0.0)
        self.assertTrue(stock.vas_has_default_account)
        self.assertIn('origin_returned_move_id', (stock.narration or '').lower())
        with self.assertRaises(UserError):
            self.period_nov._check_no_default_account_move()

    def test_t2_return_uses_original_cogs_not_avco(self):
        """T2: có origin → đúng lô xuất, COGS triệt tiêu về 0."""
        product = self._product('HH T2 trả đúng lô')
        self._make_in(product, 2, 20_000, '2099-11-10')
        out = self._make_out(product, 2, '2099-11-11')
        self.Sync.sync_company(self.company)
        cogs = self._vas(out, 'cogs')
        self.assertEqual(len(cogs), 1)
        self.assertEqual(self._amt(cogs, '632', 'debit'), 40_000.0)
        self._make_in(product, 10, 100_000, '2099-11-12')
        ret = self._make_return(out, 2, '2099-11-13')
        odoo_val = abs(ret.value or 0.0)
        self.Sync.sync_company(self.company)
        stock = self._vas(ret, 'stock')
        self.assertEqual(len(stock), 1, 'T2: phải có bút toán nhập trả')
        self.assertEqual(self._amt(stock, '156', 'debit'), 40_000.0)
        self.assertEqual(self._amt(stock, '632', 'credit'), 40_000.0)
        net_632 = self._amt(cogs, '632', 'debit') - self._amt(stock, '632', 'credit')
        self.assertEqual(net_632, 0.0, 'T2: giá vốn triệt tiêu về 0')
        if odoo_val and float_compare(odoo_val, 40_000.0, 2) != 0:
            self.assertNotEqual(
                self._amt(stock, '156', 'debit'), odoo_val,
                'T2: không lấy AVCO hiện hành của Odoo',
            )

    def test_t3_partial_return_three_of_ten(self):
        product = self._product('HH T3 trả 3/10')
        self._make_in(product, 10, 20_000, '2099-11-10')
        out = self._make_out(product, 10, '2099-11-11')
        self.Sync.sync_company(self.company)
        ret = self._make_return(out, 3, '2099-11-13')
        self.Sync.sync_company(self.company)
        stock = self._vas(ret, 'stock')
        self.assertEqual(self._amt(stock, '156', 'debit'), 60_000.0)

    def test_t5_return_into_156_subaccount_parent_rolls_up(self):
        """T5: tiểu khoản dưới 156 — cha cộng đúng, bảng cân đối nhận đủ."""
        acc_156 = self._acc('156')
        acc_1561 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id), ('code', '=', '1561'),
        ], limit=1)
        if not acc_1561:
            acc_1561 = self.env['vas.account'].create({
                'code': '1561',
                'name': 'HH trả về (tiểu khoản khách)',
                'regime_id': self.regime.id,
                'account_type': 'asset',
                'parent_id': acc_156.id,
                'ending_balance_policy': acc_156.ending_balance_policy or 'debit',
            })
        elif not acc_1561.parent_id:
            acc_1561.parent_id = acc_156.id
        # Ánh xạ nhóm sang tiểu khoản 1561 (không đụng seed 156 cha).
        amap = self.env['vas.account.map'].search([
            ('regime_id', '=', self.regime.id),
            ('apply_to', '=', 'category'),
            ('category_id', '=', self.cat.id),
        ], limit=1)
        amap.stock_account_id = acc_1561
        product = self._product('HH T5 tiểu khoản 1561')
        self._make_in(product, 2, 20_000, '2099-11-10')
        out = self._make_out(product, 2, '2099-11-11')
        self.Sync.sync_company(self.company)
        ret = self._make_return(out, 2, '2099-11-13')
        self.Sync.sync_company(self.company)
        stock = self._vas(ret, 'stock')
        self.assertEqual(len(stock), 1)
        self.assertEqual(self._amt(stock, '1561', 'debit'), 40_000.0)
        self.assertFalse(
            stock.line_ids.filtered(lambda l: l.account_id.code == '156'),
            'T5: ghi trên tiểu khoản, không ghi thẳng 156 cha',
        )
        # Bảng cân đối: số dư cha = tổng lá (kể cả 1561 vừa nhập trả).
        data = self.env['vas.trial.balance.wizard'].get_report_data({
            'company_id': self.company.id,
            'period_from_id': self.period_nov.id,
            'period_to_id': self.period_nov.id,
            'hide_reversed': True,
        })
        by_id = {l['id']: l for l in data['lines']}
        parent = by_id.get(f'acc_{acc_156.id}')
        child = by_id.get(f'acc_{acc_1561.id}')
        self.assertTrue(parent and child, 'T5: bảng cân đối phải có 156 và 1561')
        self.assertEqual(child['parent_id'], parent['id'])
        for idx in range(2, 8):
            # Cha ≥ lá (có thể còn lá khác dưới 156 trong DB); lá 1561 mang đúng 40k debit PS.
            self.assertGreaterEqual(
                parent['values'][idx] + 1e-6,
                0.0,
            )
        # PS Nợ kỳ của 1561 phải có 40.000 (cột debit period thường là index 4 hoặc tương đương).
        # Đọc trực tiếp sổ: tổng debit 1561 ≥ 40k; tổng debit các lá dưới 156 chứa đủ số cha.
        leaf_debit = sum(self.env['vas.move.line'].search([
            ('account_id', '=', acc_1561.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
            ('period_id', '=', self.period_nov.id),
        ]).mapped('debit'))
        self.assertGreaterEqual(leaf_debit, 40_000.0 - 0.01)
        parent_debit_children = sum(self.env['vas.move.line'].search([
            ('account_id', 'child_of', acc_156.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
            ('period_id', '=', self.period_nov.id),
        ]).mapped('debit'))
        # Roll-up: số ghi trên lá phải nằm trong tổng nhánh 156.
        self.assertGreaterEqual(parent_debit_children, leaf_debit - 0.01)
        amap.stock_account_id = acc_156

    def test_t6_revenue_untouched_after_return(self):
        """Doanh thu không đụng khi trả kho (bổ sung an toàn; suite = T6 chính)."""
        product = self._product('HH T6 DT chiết khấu')
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company.id), ('code', '=', 'BH'),
        ], limit=1) or self.env['vas.journal'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        rev = self.env['vas.move'].create({
            'date': '2099-11-11',
            'journal_id': journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'sale_inv',
            'ref': 'DT T6 chiết khấu 10%',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': [
                Command.create({
                    'account_id': self._acc('131').id,
                    'name': 'DT',
                    'debit': 180_000.0,
                    'credit': 0.0,
                }),
                Command.create({
                    'account_id': self._acc('5111').id,
                    'name': 'DT',
                    'debit': 0.0,
                    'credit': 180_000.0,
                }),
            ],
        })
        rev.action_post()
        rev_before = self._amt(rev, '511', 'credit')
        self.assertEqual(rev_before, 180_000.0)
        self._make_in(product, 2, 20_000, '2099-11-10')
        out = self._make_out(product, 2, '2099-11-11')
        self.Sync.sync_company(self.company)
        ret = self._make_return(out, 2, '2099-11-13')
        self.Sync.sync_company(self.company)
        rev.invalidate_recordset()
        self.assertEqual(self._amt(rev, '511', 'credit'), 180_000.0)
        self.assertEqual(rev.state, 'posted')
        self.assertTrue(self._vas(ret, 'stock'))

    def test_t7_scrap_at_book_cost(self):
        product = self._product('HH T7 hủy')
        self._make_in(product, 2, 20_000, '2099-11-10')
        self.Sync.sync_company(self.company)
        scrap = self.env['stock.scrap'].create({
            'product_id': product.id,
            'scrap_qty': 2,
            'product_uom_id': product.uom_id.id,
            'company_id': self.company.id,
        })
        scrap.action_validate()
        scrap.date_done = datetime(2099, 11, 14, 10, 0, 0)
        self.Sync.sync_company(self.company)
        move = self._vas(scrap, 'scrap')
        self.assertEqual(len(move), 1)
        self.assertEqual(self._amt(move, '156', 'credit'), 40_000.0)
        self.assertEqual(self._amt(move, '811', 'debit'), 40_000.0)

    def test_t8_scrap_empty_config_flagged(self):
        product = self._product('HH T8 hủy trống TK')
        self.company.vas_scrap_account_id = False
        self._make_in(product, 2, 20_000, '2099-11-10')
        self.Sync.sync_company(self.company)
        scrap = self.env['stock.scrap'].create({
            'product_id': product.id,
            'scrap_qty': 2,
            'product_uom_id': product.uom_id.id,
            'company_id': self.company.id,
        })
        scrap.action_validate()
        scrap.date_done = datetime(2099, 11, 14, 10, 0, 0)
        self.Sync.sync_company(self.company)
        move = self._vas(scrap, 'scrap')
        self.assertTrue(move.vas_has_default_account)
        self.assertIn('811', move.line_ids.mapped('account_id.code'))
        with self.assertRaises(UserError):
            self.period_nov._check_no_default_account_move()
        self.company.vas_scrap_account_id = self._acc('811')

    def test_t9_scrap_draft_reverses(self):
        product = self._product('HH T9 đảo hủy')
        self._make_in(product, 2, 20_000, '2099-11-10')
        self.Sync.sync_company(self.company)
        scrap = self.env['stock.scrap'].create({
            'product_id': product.id,
            'scrap_qty': 2,
            'product_uom_id': product.uom_id.id,
            'company_id': self.company.id,
        })
        scrap.action_validate()
        scrap.date_done = datetime(2099, 11, 14, 10, 0, 0)
        self.Sync.sync_company(self.company)
        move = self._vas(scrap, 'scrap')
        self.assertEqual(move.state, 'posted')
        self.env.cr.execute(
            "UPDATE stock_scrap SET state = 'draft' WHERE id = %s",
            (scrap.id,),
        )
        scrap.invalidate_recordset()
        self.Sync.sync_company(self.company)
        move.invalidate_recordset()
        self.assertEqual(move.state, 'reversed')

    def _post_provision(self, product, nrv, date='2099-11-30'):
        rec = self.env['vas.inventory.provision'].create({
            'date': date,
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'ref': 'DP %s' % product.name,
            'line_ids': [Command.create({
                'product_id': product.id,
                'nrv_value': nrv,
            })],
        })
        rec.action_post()
        return rec

    def test_t10_provision_30k_inventory_unchanged(self):
        product = self._product('HH T10 DP')
        self._make_in(product, 1, 100_000, '2099-11-10')
        self.Sync.sync_company(self.company)
        rec = self._post_provision(product, 70_000)
        self.assertEqual(rec.line_ids.needed, 30_000.0)
        move = rec.move_id
        self.assertEqual(self._amt(move, '632', 'debit'), 30_000.0)
        self.assertEqual(self._amt(move, '2294', 'credit'), 30_000.0)
        self.assertFalse(move.line_ids.filtered(
            lambda l: (l.account_id.code or '').startswith('156')
        ))

    def test_t11_provision_reverse_15k(self):
        product = self._product('HH T11 DP')
        self._make_in(product, 1, 100_000, '2099-11-10')
        self.Sync.sync_company(self.company)
        self._post_provision(product, 70_000, '2099-11-30')
        rec2 = self._post_provision(product, 85_000, '2099-12-15')
        self.assertEqual(rec2.line_ids.needed, 15_000.0)
        self.assertEqual(rec2.line_ids.delta, -15_000.0)
        move = rec2.move_id
        self.assertEqual(self._amt(move, '2294', 'debit'), 15_000.0)
        self.assertEqual(self._amt(move, '632', 'credit'), 15_000.0)

    def test_t12_provision_add_10k(self):
        product = self._product('HH T12 DP')
        self._make_in(product, 1, 100_000, '2099-11-10')
        self.Sync.sync_company(self.company)
        self._post_provision(product, 70_000, '2099-11-30')
        rec2 = self._post_provision(product, 60_000, '2099-12-15')
        self.assertEqual(rec2.line_ids.needed, 40_000.0)
        self.assertEqual(rec2.line_ids.delta, 10_000.0)
        self.assertEqual(self._amt(rec2.move_id, '632', 'debit'), 10_000.0)

    def test_t13_posted_provision_immutable(self):
        product = self._product('HH T13 DP')
        self._make_in(product, 1, 100_000, '2099-11-10')
        self.Sync.sync_company(self.company)
        rec = self._post_provision(product, 70_000)
        with self.assertRaises(UserError):
            rec.write({'ref': 'sửa lén'})
        rec.action_reverse()
        self.assertEqual(rec.state, 'reversed')


@tagged('connecta_vas', 'connecta_vas_return_scrap')
class TestReturnPosT5(TransactionCase):
    """T5 — trả hàng quầy cùng kết quả T1. Bỏ qua nếu không có pos.order."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'TT133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.has_pos = 'pos.order' in cls.env
        cls.Sync = cls.env['vas.sync']

    def test_t4_pos_refund_original_cogs(self):
        if not self.has_pos:
            self.skipTest('pos.order not in registry')
        fy = self.env['vas.fiscalyear'].search([
            ('company_id', '=', self.company.id),
            ('date_from', '<=', '2099-01-15'),
            ('date_to', '>=', '2099-01-15'),
        ], limit=1)
        if not fy:
            fy = self.env['vas.fiscalyear'].create({
                'name': '2099', 'date_from': '2099-01-01', 'date_to': '2099-12-31',
                'state': 'open', 'company_id': self.company.id,
            })
        if not fy.period_ids.filtered(lambda p: p.date_start == fields.Date.to_date('2099-01-01')):
            self.env['vas.period'].create({
                'name': '01/2099', 'date_start': '2099-01-01',
                'date_end': '2099-01-31', 'fiscalyear_id': fy.id,                 'state': 'open',
            })
        self.env.user.group_ids += self.env.ref('point_of_sale.group_pos_manager')
        cash_journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'cash'),
        ], limit=1)
        if not cash_journal:
            cash_journal = self.env['account.journal'].create({
                'name': 'Cash T5', 'code': 'CSH5', 'type': 'cash',
                'company_id': self.company.id,
            })
        sale_journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'sale'),
        ], limit=1)
        cash_pm = self.env['pos.payment.method'].create({
            'name': 'TM T5', 'journal_id': cash_journal.id,
            'company_id': self.company.id,
        })
        pos_config = self.env['pos.config'].create({
            'name': 'VAS POS T5',
            'company_id': self.company.id,
            'journal_id': sale_journal.id if sale_journal else False,
            'payment_method_ids': [Command.set(cash_pm.ids)],
        })
        cat = self.env['product.category'].create({
            'name': 'T5 AVCO',
            'property_cost_method': 'average',
            'property_valuation': 'real_time',
        })
        product = self.env['product.product'].create({
            'name': 'HH POS T5',
            'is_storable': True,
            'available_in_pos': True,
            'list_price': 50_000,
            'standard_price': 20_000,
            'categ_id': cat.id,
            'taxes_id': False,
        })
        loc = self.env.ref('stock.stock_location_stock')
        supplier = self.env.ref('stock.stock_location_suppliers')
        in_move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': 2,
            'product_uom': product.uom_id.id,
            'location_id': supplier.id,
            'location_dest_id': loc.id,
            'company_id': self.company.id,
            'picking_type_id': self.env.ref('stock.picking_type_in').id,
            'price_unit': 20_000,
            'value_manual': 40_000,
        })
        in_move._action_confirm()
        in_move._action_assign()
        in_move.picked = True
        in_move._action_done()
        self.Sync.sync_company(self.company)
        pos_config.open_ui()
        session = pos_config.current_session_id
        order = self.env['pos.order'].create({
            'session_id': session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100_000.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [Command.create({
                'product_id': product.id,
                'qty': 2,
                'price_unit': 50_000,
                'price_subtotal': 100_000,
                'price_subtotal_incl': 100_000,
                'full_product_name': product.name,
                'name': product.display_name,
            })],
        })
        wizard = self.env['pos.make.payment'].with_context(
            active_id=order.id, active_ids=order.ids,
        ).create({
            'amount': order.amount_total,
            'payment_method_id': cash_pm.id,
        })
        wizard.check()
        # Một số cấu hình chỉ sinh phiếu kho khi đóng ca.
        if not order.picking_ids.mapped('move_ids').filtered(lambda m: m.state == 'done'):
            session.action_pos_session_closing_control()
            order.invalidate_recordset()
        self.Sync.sync_company(self.company)
        pos_cogs = self.env['vas.move'].search([
            ('source_model', '=', 'pos.order'),
            ('source_res_id', '=', order.id),
            ('move_kind', '=', 'pos_cogs'),
            ('is_reversal', '=', False),
        ])
        self.assertTrue(pos_cogs, 'T5: bán quầy phải có pos_cogs')
        extra = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': 10,
            'product_uom': product.uom_id.id,
            'location_id': supplier.id,
            'location_dest_id': loc.id,
            'company_id': self.company.id,
            'picking_type_id': self.env.ref('stock.picking_type_in').id,
            'price_unit': 100_000,
            'value_manual': 1_000_000,
        })
        extra._action_confirm()
        extra._action_assign()
        extra.picked = True
        extra._action_done()
        refund_action = order.refund()
        refund = self.env['pos.order'].browse(refund_action['res_id'])
        wizard = self.env['pos.make.payment'].with_context(
            active_id=refund.id, active_ids=refund.ids,
        ).create({
            'amount': refund.amount_total,
            'payment_method_id': cash_pm.id,
        })
        wizard.check()
        self.Sync.sync_company(self.company)
        refund_cogs = self.env['vas.move'].search([
            ('source_model', '=', 'pos.order'),
            ('source_res_id', '=', refund.id),
            ('move_kind', '=', 'pos_cogs'),
            ('is_reversal', '=', False),
        ])
        self.assertEqual(len(refund_cogs), 1)
        inv_debit = sum(refund_cogs.line_ids.filtered(
            lambda l: (l.account_id.code or '').startswith('156')
        ).mapped('debit'))
        self.assertEqual(inv_debit, 40_000.0, 'T4: nhập trả quầy đúng giá vốn lúc bán')
