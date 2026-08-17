# -*- coding: utf-8 -*-
"""W12 Chặng 5 — ghi ngay giá tạm (NVL) + ghi bù 155/632."""
from datetime import datetime

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('connecta_vas', 'connecta_vas_w12_5')
class TestW12CostingStage5(TransactionCase):

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
                'code': 'TT133', 'name': 'Thông tư 133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.acc_154 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '154'),
        ], limit=1)
        cls.acc_155 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '155'),
        ], limit=1)
        cls.acc_632 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '632'),
        ], limit=1)
        cls.acc_111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '111'),
        ], limit=1)
        assert cls.acc_154 and cls.acc_155 and cls.acc_632 and cls.acc_111
        cls.cpc = cls.env['vas.cost.item'].search([
            ('code', '=', 'CPC'), ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.cpc:
            cls.cpc = cls.env['vas.cost.item'].create({
                'code': 'CPC', 'name': 'Chi phí SX chung',
                'factor_group': 'other', 'account_id': cls.acc_154.id,
                'company_id': cls.company.id, 'is_system': True,
            })
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['vas.journal'].create({
                'code': 'TH', 'name': 'Tổng hợp', 'type': 'general',
                'company_id': cls.company.id, 'regime_id': cls.regime.id,
            })
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-03-15'),
            ('date_to', '>=', '2099-03-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W12-5-2099', 'date_from': '2099-01-01',
                'date_to': '2099-12-31', 'company_id': cls.company.id,
                'state': 'open',
            })
        cls.fy = fy
        cls.period_acc = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', '2099-03-15'),
            ('date_end', '>=', '2099-03-15'),
        ], limit=1)
        if not cls.period_acc:
            cls.period_acc = cls.env['vas.period'].create({
                'name': '03/2099', 'date_start': '2099-03-01',
                'date_end': '2099-03-31', 'fiscalyear_id': fy.id, 'state': 'open',
            })
        # Nhóm SP thành phẩm → TK 155 / 632 từ ánh xạ (không viết cứng trong engine)
        cls.fg_categ = cls.env['product.category'].create({'name': 'W12 FG Cat'})
        existing = cls.env['vas.account.map'].search([
            ('regime_id', '=', cls.regime.id),
            ('apply_to', '=', 'category'),
            ('category_id', '=', cls.fg_categ.id),
            ('company_id', 'in', (cls.company.id, False)),
        ], limit=1)
        if not existing:
            cls.env['vas.account.map'].create({
                'regime_id': cls.regime.id,
                'apply_to': 'category',
                'category_id': cls.fg_categ.id,
                'company_id': cls.company.id,
                'stock_account_id': cls.acc_155.id,
                'cogs_account_id': cls.acc_632.id,
            })

    def _product(self, name):
        return self.env['product.product'].create({
            'name': name, 'is_storable': True,
            'categ_id': self.fg_categ.id,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
        })

    def _obj_product(self, code, product):
        return self.env['vas.cost.object'].create({
            'code': code, 'name': code, 'object_type': 'product',
            'company_id': self.company.id, 'wip_account_id': self.acc_154.id,
            'source_model': 'product.product', 'source_res_id': product.id,
        })

    def _config_alloc(self, factors):
        cfg = self.env['vas.allocation.config'].create({
            'company_id': self.company.id, 'cost_item_id': self.cpc.id,
            'scope_type': 'company', 'criterion': 'manual_factor',
            'sequence': 1, 'date_from': '2099-03-01', 'date_to': '2099-03-31',
        })
        for obj, factor in factors:
            self.env['vas.allocation.config.factor'].create({
                'config_id': cfg.id, 'cost_object_id': obj.id, 'factor': factor,
            })
        return cfg

    def _source_move(self, amount, date='2099-03-15', object=None):
        if amount < 0:
            lines = [
                Command.create({
                    'account_id': self.acc_111.id, 'name': 'hoan',
                    'debit': abs(amount), 'credit': 0.0,
                    'currency_id': self.company.currency_id.id,
                }),
                Command.create({
                    'account_id': self.acc_154.id, 'name': 'giam',
                    'debit': 0.0, 'credit': abs(amount),
                    'currency_id': self.company.currency_id.id,
                    'cost_item_id': self.cpc.id,
                    'cost_object_id': object.id if object else False,
                }),
            ]
        else:
            lines = [
                Command.create({
                    'account_id': self.acc_154.id, 'name': 'cp',
                    'debit': amount, 'credit': 0.0,
                    'currency_id': self.company.currency_id.id,
                    'cost_item_id': self.cpc.id,
                    'cost_object_id': object.id if object else False,
                }),
                Command.create({
                    'account_id': self.acc_111.id, 'name': 'dt',
                    'debit': 0.0, 'credit': amount,
                    'currency_id': self.company.currency_id.id,
                }),
            ]
        move = self.env['vas.move'].create({
            'date': date, 'journal_id': self.journal.id,
            'regime_id': self.regime.id, 'move_kind': 'manual',
            'ref': 'W12-5', 'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': lines,
        })
        move.action_post()
        return move

    def _run(self, **extra):
        vals = {
            'name': 'PB5', 'company_id': self.company.id,
            'date_from': '2099-03-01', 'date_to': '2099-03-31',
            'cost_item_id': self.cpc.id, 'scope_type': 'company',
            'round_number': '1', 'money_source': 'pool_154', 'state': 'draft',
        }
        vals.update(extra)
        return self.env['vas.allocation.run'].create(vals)

    def _period(self, objects, **extra):
        vals = {
            'name': 'Kỳ Ch5', 'date_from': '2099-03-01',
            'date_to': '2099-03-31', 'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [Command.set([o.id for o in objects])],
            'opening_wip': 0.0,
        }
        vals.update(extra)
        return self.env['vas.costing.period'].create(vals)

    def _closing_confirm(self, period, amounts_by_obj):
        sheet = self.env['vas.closing.wip'].create({
            'name': 'DD %s' % period.name, 'kind': 'period_end',
            'period_id': period.id, 'company_id': self.company.id,
        })
        for obj, amt in amounts_by_obj.items():
            self.env['vas.closing.wip.line'].create({
                'sheet_id': sheet.id, 'cost_object_id': obj.id,
                'amount_suggested': amt, 'amount_adjustment': 0.0,
            })
        sheet.state = 'pending_confirm'
        sheet.action_confirm()
        return sheet

    def _warehouse_config(self, posting_mode='immediate', step_mode='one'):
        wh = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        if not wh or not wh.lot_stock_id:
            self.skipTest('Thiếu kho')
        pt = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', wh.id),
        ], limit=1)
        if not pt:
            self.skipTest('Thiếu loại phiếu')
        existing = self.env['vas.costing.warehouse.config'].search([
            ('company_id', '=', self.company.id),
            ('warehouse_id', '=', wh.id),
        ], limit=1)
        vals = {
            'step_mode': step_mode,
            'posting_mode': posting_mode,
            'fg_picking_type_id': pt.id,
            'fg_location_id': wh.lot_stock_id.id,
            'active': True,
        }
        if existing:
            # Đảo tạm nếu cần trước khi đổi chế độ
            if existing.posting_mode != posting_mode:
                lots = self.env['vas.costing.provisional.lot'].search([
                    ('warehouse_config_id', '=', existing.id),
                    ('state', '=', 'posted'),
                ])
                if lots:
                    lots.action_reverse_provisional()
            existing.write(vals)
            return existing
        vals.update({
            'company_id': self.company.id,
            'warehouse_id': wh.id,
            'isolation_location_id': wh.lot_stock_id.id,
        })
        return self.env['vas.costing.warehouse.config'].create(vals)

    def _fg_move(self, product, cfg, qty, value, date='2099-03-10 10:00:00',
                 lot_code=None):
        StockLocation = self.env['stock.location']
        src = StockLocation.search([
            ('usage', '=', 'production'),
            '|', ('company_id', '=', self.company.id), ('company_id', '=', False),
        ], limit=1) or StockLocation.search([
            ('usage', '=', 'supplier'),
            '|', ('company_id', '=', self.company.id), ('company_id', '=', False),
        ], limit=1)
        if not src:
            self.skipTest('Thiếu location nguồn')
        move = self.env['stock.move'].create({
            'origin': lot_code or False,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': src.id,
            'location_dest_id': cfg.fg_location_id.id,
            'picking_type_id': cfg.fg_picking_type_id.id,
            'company_id': self.company.id,
            'date': date,
        })
        self.env.cr.execute(
            "UPDATE stock_move SET state='done', quantity=%s, value=%s, date=%s "
            "WHERE id=%s",
            (qty, value, date, move.id),
        )
        move.invalidate_recordset()
        return move

    def _sale_out(self, product, cfg, qty, date):
        cust = self.env['stock.location'].search([
            ('usage', '=', 'customer'),
            '|', ('company_id', '=', self.company.id), ('company_id', '=', False),
        ], limit=1)
        if not cust:
            self.skipTest('Thiếu location khách')
        move = self.env['stock.move'].create({
            'origin': 'OUT',
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': cfg.fg_location_id.id,
            'location_dest_id': cust.id,
            'company_id': self.company.id,
            'date': date,
        })
        self.env.cr.execute(
            "UPDATE stock_move SET state='done', quantity=%s, date=%s WHERE id=%s",
            (qty, date, move.id),
        )
        move.invalidate_recordset()
        return move

    def _approve_ready(self, period, obj, opening, direct, overhead, reduction, closing):
        self._source_move(direct, object=obj)
        self._config_alloc([(obj, 1)])
        self._source_move(overhead)
        run = self._run(name='PB-%s' % period.name)
        run.action_compute()
        run.action_confirm()
        period.action_receive_allocation(result_ids=run.result_ids.ids)
        self._source_move(-reduction, object=obj)
        self._closing_confirm(period, {obj: closing})
        period.write({'opening_wip': opening})
        period.action_compute_costing()
        period.action_submit_approval()
        period.action_approve()
        return run

    def _bal(self, move, account):
        return sum(
            l.debit - l.credit for l in move.line_ids
            if l.account_id == account
        )

    # ------------------------------------------------------------------
    # 7.1 official > provisional
    # ------------------------------------------------------------------

    def test_71_official_gt_provisional_stock_and_cogs(self):
        opening, direct, overhead, reduction, closing = (
            110_000.0, 220_000.0, 330_000.0, 40_000.0, 50_000.0,
        )
        official = opening + direct + overhead - reduction - closing  # 570_000
        self.assertEqual(len({
            opening, direct, overhead, reduction, closing, official,
        }), 6)

        cfg = self._warehouse_config('immediate')
        product = self._product('FG71')
        obj = self._obj_product('O71', product)
        # Hai lô qty 2 và 3 — tạm 100k + 150k
        self._fg_move(product, cfg, 2, 100_000, date='2099-03-05 10:00:00', lot_code='L-A')
        self._fg_move(product, cfg, 3, 150_000, date='2099-03-08 10:00:00', lot_code='L-B')
        # Bán 2 trong kỳ → FIFO hết lô A
        self._sale_out(product, cfg, 2, '2099-03-20 12:00:00')

        period = self._period([obj], opening_wip=opening, name='Kỳ 7.1')
        # Đường bấm nút trên kỳ
        action = period.action_post_provisional_fg()
        self.assertEqual(action.get('res_model'), 'vas.costing.provisional.lot')
        lots = period.provisional_lot_ids.filtered(lambda l: l.state == 'posted')
        self.assertEqual(len(lots), 2)
        prov_sum = sum(lots.mapped('amount_provisional'))
        self.assertAlmostEqual(prov_sum, 250_000.0)

        # Ghi tạm lại → bỏ qua, không trùng
        period.action_post_provisional_fg()
        self.assertEqual(
            len(period.provisional_lot_ids.filtered(lambda l: l.state == 'posted')), 2,
        )

        self._approve_ready(
            period, obj, opening, direct, overhead, reduction, closing,
        )
        self.assertAlmostEqual(period.current_result_id.total_cost, official)
        period.action_post_costing()

        lots = period.provisional_lot_ids.filtered(lambda l: l.state == 'posted')
        lot_a = lots.filtered(lambda l: l.lot_code == 'L-A')
        lot_b = lots.filtered(lambda l: l.lot_code == 'L-B')
        self.assertAlmostEqual(lot_a.amount_official, 228_000.0)
        self.assertAlmostEqual(lot_b.amount_official, 342_000.0)
        self.assertAlmostEqual(
            sum(lots.mapped('amount_official')), official,
        )  # 4.6
        self.assertAlmostEqual(lot_a.amount_diff, 128_000.0)
        self.assertAlmostEqual(lot_b.amount_diff, 192_000.0)
        self.assertAlmostEqual(lot_a.qty_sold, 2.0)
        self.assertAlmostEqual(lot_a.qty_remaining, 0.0)
        self.assertAlmostEqual(lot_b.qty_sold, 0.0)
        self.assertAlmostEqual(lot_b.qty_remaining, 3.0)
        self.assertAlmostEqual(lot_a.amount_trueup_cogs, 128_000.0)
        self.assertAlmostEqual(lot_a.amount_trueup_stock, 0.0)
        self.assertAlmostEqual(lot_b.amount_trueup_stock, 192_000.0)
        self.assertAlmostEqual(lot_b.amount_trueup_cogs, 0.0)
        # 5.5
        self.assertAlmostEqual(
            prov_sum + sum(lots.mapped('amount_trueup_stock'))
            + sum(lots.mapped('amount_trueup_cogs')),
            official,
        )
        move = period.posting_move_id
        self.assertAlmostEqual(self._bal(move, self.acc_155), 192_000.0)
        self.assertAlmostEqual(self._bal(move, self.acc_632), 128_000.0)
        self.assertAlmostEqual(self._bal(move, self.acc_154), -(192_000 + 128_000))
        # Tài khoản từ map — đúng 155/632 đã khai
        self.assertTrue(all(
            l.account_id in (self.acc_155, self.acc_632, self.acc_154)
            for l in move.line_ids
        ))

    # ------------------------------------------------------------------
    # 7.2 official < provisional
    # ------------------------------------------------------------------

    def test_72_official_lt_provisional_reverse_trueup(self):
        opening, direct, overhead, reduction, closing = (
            110_000.0, 220_000.0, 330_000.0, 40_000.0, 50_000.0,
        )
        official = 570_000.0
        cfg = self._warehouse_config('immediate')
        product = self._product('FG72')
        obj = self._obj_product('O72', product)
        # Tạm cao hơn official: 400k + 300k = 700k
        self._fg_move(product, cfg, 2, 400_000, date='2099-03-05 10:00:00', lot_code='H-A')
        self._fg_move(product, cfg, 3, 300_000, date='2099-03-08 10:00:00', lot_code='H-B')
        self._sale_out(product, cfg, 2, '2099-03-20 12:00:00')

        period = self._period([obj], opening_wip=opening, name='Kỳ 7.2')
        period.action_post_provisional_fg()
        lots = period.provisional_lot_ids.filtered(lambda l: l.state == 'posted')
        prov_sum = sum(lots.mapped('amount_provisional'))
        self.assertAlmostEqual(prov_sum, 700_000.0)

        self._approve_ready(
            period, obj, opening, direct, overhead, reduction, closing,
        )
        period.action_post_costing()
        lots = period.provisional_lot_ids.filtered(lambda l: l.state == 'posted')
        # official shares same 228k / 342k; diffs âm
        lot_a = lots.filtered(lambda l: l.lot_code == 'H-A')
        lot_b = lots.filtered(lambda l: l.lot_code == 'H-B')
        self.assertAlmostEqual(lot_a.amount_diff, 228_000 - 400_000)
        self.assertAlmostEqual(lot_b.amount_diff, 342_000 - 300_000)
        self.assertAlmostEqual(
            prov_sum + sum(lots.mapped('amount_trueup_stock'))
            + sum(lots.mapped('amount_trueup_cogs')),
            official,
        )
        move = period.posting_move_id
        # Hỗn hợp chiều: lô A bán (bù âm 632), lô B tồn (bù dương 155)
        self.assertAlmostEqual(self._bal(move, self.acc_155), 42_000.0)
        self.assertAlmostEqual(self._bal(move, self.acc_632), -172_000.0)
        self.assertAlmostEqual(
            self._bal(move, self.acc_154),
            -(42_000.0 - 172_000.0),
        )

    # ------------------------------------------------------------------
    # 7.3 idempotent
    # ------------------------------------------------------------------

    def test_73_idempotent_provisional_and_trueup(self):
        cfg = self._warehouse_config('immediate')
        product = self._product('FG73')
        obj = self._obj_product('O73', product)
        self._fg_move(product, cfg, 1, 50_000, lot_code='ID1')
        period = self._period([obj], name='Kỳ 7.3')
        period.action_post_provisional_fg()
        period.action_post_provisional_fg()
        period.action_post_provisional_fg()
        self.assertEqual(
            len(period.provisional_lot_ids.filtered(lambda l: l.state == 'posted')), 1,
        )
        self._approve_ready(
            period, obj, 10_000, 20_000, 30_000, 5_000, 4_000,
        )
        period.action_post_costing()
        move = period.posting_move_id
        bal155 = self._bal(move, self.acc_155)
        bal632 = self._bal(move, self.acc_632)
        with self.assertRaises(UserError) as err:
            period.action_post_costing()
        self.assertIn('B3', str(err.exception))
        self.assertAlmostEqual(self._bal(period.posting_move_id, self.acc_155), bal155)
        self.assertAlmostEqual(self._bal(period.posting_move_id, self.acc_632), bal632)

    # ------------------------------------------------------------------
    # 7.4 period_end unchanged (Chặng 4 numbers)
    # ------------------------------------------------------------------

    def test_74_period_end_unchanged_no_provisional_no_632(self):
        opening, direct, overhead, reduction, closing = (
            500_000.0, 400_000.0, 300_000.0, 200_000.0, 100_000.0,
        )
        expected = 900_000.0
        cfg = self._warehouse_config('period_end')
        product = self._product('FG74')
        obj = self._obj_product('O74', product)
        self._fg_move(product, cfg, 1, expected - overhead)
        period = self._period([obj], opening_wip=opening, name='Kỳ 7.4')
        with self.assertRaises(UserError):
            period.action_post_provisional_fg()
        self._approve_ready(
            period, obj, opening, direct, overhead, reduction, closing,
        )
        period.action_post_costing()
        self.assertFalse(period.provisional_lot_ids)
        move = period.posting_move_id
        self.assertAlmostEqual(self._bal(move, self.acc_155), expected)
        self.assertAlmostEqual(self._bal(move, self.acc_632), 0.0)
        self.assertFalse(move.line_ids.filtered(lambda l: l.account_id == self.acc_632))

    # ------------------------------------------------------------------
    # 7.5 unvalued blocks provisional
    # ------------------------------------------------------------------

    def test_75_unvalued_blocks_provisional(self):
        cfg = self._warehouse_config('immediate')
        product = self._product('FG75')
        obj = self._obj_product('O75', product)
        move = self._fg_move(product, cfg, 1, 0, lot_code='UV')
        # Ép chưa định giá: value=0 + xóa product.value
        PV = self.env.get('product.value')
        if PV is not None and 'move_id' in PV._fields:
            PV.search([('move_id', '=', move.id)]).unlink()
        period = self._period([obj], name='Kỳ 7.5')
        action = period.action_post_provisional_fg()
        # Notification hoặc list trống — không tạo lô
        self.assertFalse(period.provisional_lot_ids)
        if action.get('params'):
            self.assertIn('chặn', (action['params'].get('message') or '').lower())

    # ------------------------------------------------------------------
    # 7.6 cutoff date — sale after date_to before approve
    # ------------------------------------------------------------------

    def test_76_cutoff_ignores_sale_after_period_end(self):
        opening, direct, overhead, reduction, closing = (
            110_000.0, 220_000.0, 330_000.0, 40_000.0, 50_000.0,
        )
        official = 570_000.0
        cfg = self._warehouse_config('immediate')
        product = self._product('FG76')
        obj = self._obj_product('O76', product)
        self._fg_move(product, cfg, 5, 250_000, date='2099-03-10 10:00:00', lot_code='C76')
        period = self._period([obj], opening_wip=opening, name='Kỳ 7.6')
        period.action_post_provisional_fg()
        self._approve_ready(
            period, obj, opening, direct, overhead, reduction, closing,
        )
        # Bán SAU date_to, TRƯỚC duyệt (đã duyệt rồi — bán trước ghi bù)
        # Quay lại: bán trước approve nhưng sau date_to
        # period đã approved — bán rồi ghi bù
        self._sale_out(product, cfg, 5, '2099-04-02 10:00:00')
        period.action_post_costing()
        lot = period.provisional_lot_ids.filtered(lambda l: l.state == 'posted')
        # Toàn bộ còn tồn tại ngày cắt 31/3 — bù hết vào 155
        self.assertAlmostEqual(lot.qty_sold, 0.0)
        self.assertAlmostEqual(lot.qty_remaining, 5.0)
        self.assertAlmostEqual(lot.amount_trueup_cogs, 0.0)
        self.assertAlmostEqual(
            lot.amount_trueup_stock, official - 250_000.0,
        )
        move = period.posting_move_id
        self.assertAlmostEqual(self._bal(move, self.acc_632), 0.0)
        self.assertAlmostEqual(
            self._bal(move, self.acc_155), official - 250_000.0,
        )

    def test_47_one_lot_cannot_take_all_official(self):
        """Bất biến 4.7 — có >1 lô thì không lô nào nhận hết tổng kỳ."""
        cfg = self._warehouse_config('immediate')
        product = self._product('FG47')
        obj = self._obj_product('O47', product)
        self._fg_move(product, cfg, 1, 10_000, date='2099-03-05 10:00:00', lot_code='A47')
        self._fg_move(product, cfg, 1, 10_000, date='2099-03-06 10:00:00', lot_code='B47')
        period = self._period([obj], name='Kỳ 4.7')
        period.action_post_provisional_fg()
        lots = period.provisional_lot_ids.filtered(lambda l: l.state == 'posted')
        self.assertEqual(len(lots), 2)
        lots[0].qty = 1.0
        lots[1].qty = 0.0
        with self.assertRaises(UserError) as err:
            period._allocate_official_to_lots(lots, 100_000.0)
        self.assertIn('toàn bộ', str(err.exception).lower())

    # ------------------------------------------------------------------
    # 7.7 block immediate: span two AP / closed AP
    # ------------------------------------------------------------------

    def test_77_block_immediate_span_and_closed(self):
        # (a) kỳ giá thành kéo hai kỳ kế toán
        if not self.env['vas.period'].search([
            ('fiscalyear_id', '=', self.fy.id), ('date_start', '=', '2099-01-01'),
        ], limit=1):
            self.env['vas.period'].create({
                'name': '01/2099', 'date_start': '2099-01-01',
                'date_end': '2099-01-31', 'fiscalyear_id': self.fy.id,
                'state': 'open',
            })
        if not self.env['vas.period'].search([
            ('fiscalyear_id', '=', self.fy.id), ('date_start', '=', '2099-02-01'),
        ], limit=1):
            self.env['vas.period'].create({
                'name': '02/2099', 'date_start': '2099-02-01',
                'date_end': '2099-02-28', 'fiscalyear_id': self.fy.id,
                'state': 'open',
            })
        span = self._period(
            [], name='Kéo hai kỳ', date_from='2099-01-15', date_to='2099-02-15',
        )
        with self.assertRaises(UserError) as err_a:
            span._assert_immediate_mode_allowed()
        msg_a = str(err_a.exception).lower()
        self.assertIn('hai kỳ', msg_a)

        wh = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        pt = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', wh.id),
        ], limit=1)
        existing = self.env['vas.costing.warehouse.config'].search([
            ('company_id', '=', self.company.id),
            ('warehouse_id', '=', wh.id),
        ], limit=1)
        with self.assertRaises(ValidationError) as err_sel:
            if existing:
                existing.write({'posting_mode': 'immediate'})
            else:
                self.env['vas.costing.warehouse.config'].create({
                    'company_id': self.company.id,
                    'warehouse_id': wh.id,
                    'step_mode': 'one',
                    'posting_mode': 'immediate',
                    'fg_picking_type_id': pt.id,
                    'fg_location_id': wh.lot_stock_id.id,
                })
        self.assertIn('ghi ngay', str(err_sel.exception).lower())

        # (b) kỳ ghi bù đã khóa
        span.unlink()
        if existing and existing.posting_mode == 'immediate':
            existing.posting_mode = 'period_end'
        closed = self._period(
            [], name='Trong kỳ khóa', date_from='2099-03-01', date_to='2099-03-31',
        )
        self.period_acc.state = 'closed'
        try:
            with self.assertRaises(UserError) as err_b:
                closed._assert_immediate_mode_allowed()
            self.assertIn('khóa', str(err_b.exception).lower())
            with self.assertRaises(ValidationError):
                if existing:
                    existing.write({'posting_mode': 'immediate'})
                else:
                    self.env['vas.costing.warehouse.config'].create({
                        'company_id': self.company.id,
                        'warehouse_id': wh.id,
                        'step_mode': 'one',
                        'posting_mode': 'immediate',
                        'fg_picking_type_id': pt.id,
                        'fg_location_id': wh.lot_stock_id.id,
                    })
        finally:
            self.period_acc.state = 'open'

    # ------------------------------------------------------------------
    # Fingerprint gates + reverse provisional blocked after trueup
    # ------------------------------------------------------------------

    def test_fingerprint_gates_and_reverse_block(self):
        a = self.env['vas.cost.object'].create({
            'code': 'FP5', 'name': 'FP5', 'object_type': 'workshop',
            'company_id': self.company.id, 'wip_account_id': self.acc_154.id,
        })
        self._config_alloc([(a, 1)])
        self._source_move(50_000, date='2099-03-05')
        run = self._run(name='FP-GATE')
        run.action_compute()
        run.action_confirm()
        self._source_move(10_000, date='2099-03-20')
        # Cổng 2 — mở lại lượt
        run.action_set_draft()
        self.assertTrue(run.needs_recompute)
        run.write({'state': 'confirmed'})
        # Cổng 1 — nhận kết quả
        period = self._period([a], name='FP kỳ')
        with self.assertRaises(UserError) as err:
            period.action_receive_allocation(result_ids=run.result_ids.ids)
        self.assertIn('chạy lại', str(err.exception).lower())
        run.state = 'cancelled'
        period.unlink()

        # Cổng 3 — tính giá thành sau nhận, nguồn lệch (cùng đối tượng a, run mới)
        self._source_move(25_000, date='2099-03-07')
        run2 = self._run(name='FP-GATE2')
        run2.action_compute()
        run2.action_confirm()
        p2 = self._period([a], name='FP kỳ 2')
        p2.action_receive_allocation(result_ids=run2.result_ids.ids)
        self._source_move(8_000, date='2099-03-25')
        self._closing_confirm(p2, {a: 0})
        with self.assertRaises(UserError) as err3:
            p2.action_compute_costing()
        self.assertIn('chạy lại', str(err3.exception).lower())

    def test_reverse_provisional_blocked_after_trueup(self):
        cfg = self._warehouse_config('immediate')
        product = self._product('FG-REV')
        obj = self._obj_product('OREV', product)
        self._fg_move(product, cfg, 1, 50_000, lot_code='RV1')
        period = self._period([obj], name='Kỳ REV')
        period.action_post_provisional_fg()
        self._approve_ready(period, obj, 10_000, 20_000, 30_000, 5_000, 4_000)
        period.action_post_costing()
        lot = period.provisional_lot_ids[:1]
        with self.assertRaises(UserError) as err:
            lot.action_reverse_provisional()
        self.assertIn('ghi bù', str(err.exception).lower())
