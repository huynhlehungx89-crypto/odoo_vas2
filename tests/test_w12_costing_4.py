# -*- coding: utf-8 -*-
"""W12 Chặng 4 — bảng khai kho, ghép giá TP, dấu vân tay lượt PB, lưới đối tượng–TP."""
from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas', 'connecta_vas_w12_4')
class TestW12CostingStage4(TransactionCase):

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
        cls.acc_111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '111'),
        ], limit=1)
        assert cls.acc_154 and cls.acc_155 and cls.acc_111
        cls.CostItem = cls.env['vas.cost.item']
        cls.CostObject = cls.env['vas.cost.object']
        cls.cpc = cls.CostItem.search([
            ('code', '=', 'CPC'), ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.cpc:
            cls.cpc = cls.CostItem.create({
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
                'name': 'W12-4-2099', 'date_from': '2099-01-01',
                'date_to': '2099-12-31', 'company_id': cls.company.id,
                'state': 'open',
            })
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

    def _obj_product(self, code, product):
        return self.CostObject.create({
            'code': code, 'name': code, 'object_type': 'product',
            'company_id': self.company.id, 'wip_account_id': self.acc_154.id,
            'source_model': 'product.product', 'source_res_id': product.id,
        })

    def _obj_ws(self, code):
        return self.CostObject.create({
            'code': code, 'name': code, 'object_type': 'workshop',
            'company_id': self.company.id, 'wip_account_id': self.acc_154.id,
        })

    def _config(self, factors):
        cfg = self.env['vas.allocation.config'].create({
            'company_id': self.company.id,
            'cost_item_id': self.cpc.id,
            'scope_type': 'company',
            'criterion': 'manual_factor',
            'sequence': 1,
            'date_from': '2099-03-01',
            'date_to': '2099-03-31',
        })
        for obj, factor in factors:
            self.env['vas.allocation.config.factor'].create({
                'config_id': cfg.id, 'cost_object_id': obj.id, 'factor': factor,
            })
        return cfg

    def _source_move(self, amount, date='2099-03-15', cost_item=None, object=None):
        cost_item = cost_item or self.cpc
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
                    'cost_item_id': cost_item.id,
                    'cost_object_id': object.id if object else False,
                }),
            ]
        else:
            lines = [
                Command.create({
                    'account_id': self.acc_154.id, 'name': 'cp',
                    'debit': amount, 'credit': 0.0,
                    'currency_id': self.company.currency_id.id,
                    'cost_item_id': cost_item.id,
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
            'ref': 'W12-4', 'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': lines,
        })
        move.action_post()
        return move

    def _run(self, **extra):
        vals = {
            'name': 'PB4', 'company_id': self.company.id,
            'date_from': '2099-03-01', 'date_to': '2099-03-31',
            'cost_item_id': self.cpc.id, 'scope_type': 'company',
            'round_number': '1', 'money_source': 'pool_154', 'state': 'draft',
        }
        vals.update(extra)
        return self.env['vas.allocation.run'].create(vals)

    def _period(self, objects, **extra):
        vals = {
            'name': 'Kỳ 03/2099 Ch4', 'date_from': '2099-03-01',
            'date_to': '2099-03-31', 'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [Command.set([o.id for o in objects])],
            'opening_wip': 0.0,
        }
        vals.update(extra)
        return self.env['vas.costing.period'].create(vals)

    def _closing_confirm(self, period, amounts_by_obj):
        sheet = self.env['vas.closing.wip'].create({
            'name': 'DD cuối %s' % period.name,
            'kind': 'period_end',
            'period_id': period.id,
            'company_id': self.company.id,
        })
        for obj, amt in amounts_by_obj.items():
            self.env['vas.closing.wip.line'].create({
                'sheet_id': sheet.id,
                'cost_object_id': obj.id,
                'amount_suggested': amt,
                'amount_adjustment': 0.0,
            })
        sheet.state = 'pending_confirm'
        sheet.action_confirm()
        return sheet

    def _warehouse_config(self, step_mode='one'):
        wh = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        if not wh or not wh.lot_stock_id:
            self.skipTest('Thiếu kho công ty')
        pt = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', wh.id),
        ], limit=1)
        if not pt:
            self.skipTest('Thiếu loại phiếu')
        existing = self.env['vas.costing.warehouse.config'].search([
            ('company_id', '=', self.company.id),
            ('warehouse_id', '=', wh.id),
        ], limit=1)
        if existing:
            existing.write({
                'step_mode': step_mode,
                'fg_picking_type_id': pt.id,
                'fg_location_id': wh.lot_stock_id.id,
                'active': True,
            })
            return existing
        return self.env['vas.costing.warehouse.config'].create({
            'company_id': self.company.id,
            'warehouse_id': wh.id,
            'step_mode': step_mode,
            'fg_picking_type_id': pt.id,
            'fg_location_id': wh.lot_stock_id.id,
            'isolation_location_id': wh.lot_stock_id.id,
            'costing_sale_order': True,
        })

    def _fg_move_valued(self, product, cfg, value, qty=1.0, date='2099-03-15 12:00:00'):
        StockLocation = self.env['stock.location']
        src = StockLocation.search([
            ('usage', '=', 'production'),
            '|', ('company_id', '=', self.company.id), ('company_id', '=', False),
        ], limit=1) or StockLocation.search([
            ('usage', '=', 'supplier'),
            '|', ('company_id', '=', self.company.id), ('company_id', '=', False),
        ], limit=1)
        if not src:
            self.skipTest('Thiếu location nguồn phiếu TP')
        move = self.env['stock.move'].create({
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

    def test_step_mode_three_blocked(self):
        wh = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        pt = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', wh.id),
        ], limit=1) if wh else False
        if not wh or not pt:
            self.skipTest('Thiếu kho')
        with self.assertRaises(ValidationError) as err:
            self.env['vas.costing.warehouse.config'].create({
                'company_id': self.company.id,
                'warehouse_id': wh.id,
                'step_mode': 'three',
                'fg_picking_type_id': pt.id,
                'fg_location_id': wh.lot_stock_id.id,
            })
        self.assertIn('chưa mở', str(err.exception).lower())

    def test_post_blocked_without_warehouse_config(self):
        product = self.env['product.product'].create({
            'name': 'W12 no cfg', 'is_storable': True,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
        })
        obj = self._obj_product('NOCFG', product)
        self._source_move(10_000, object=obj)
        period = self._period([obj])
        self._closing_confirm(period, {obj: 0})
        period.action_compute_costing()
        period.action_submit_approval()
        period.action_approve()
        with self.assertRaises(UserError) as err:
            period.action_post_costing()
        msg = str(err.exception).lower()
        self.assertIn('cấu hình kho', msg)
        self.assertTrue(
            any(w.name.lower() in msg or w.code.lower() in msg
                for w in self.env['stock.warehouse'].search([
                    ('company_id', '=', self.company.id),
                ])),
            msg,
        )

    def test_e2e_warehouse_config_and_overhead_gap(self):
        """Xuyên suốt: khai kho → PB → kỳ → duyệt → 154→155; 155 − stock = CPC."""
        # Năm thành phần đôi một khác nhau; kết quả ≠ thành phần nào
        opening = 500_000.0
        direct = 400_000.0
        overhead = 300_000.0
        reduction = 200_000.0
        closing = 100_000.0
        expected_total = opening + direct + overhead - reduction - closing  # 900_000
        components = [opening, direct, overhead, reduction, closing, expected_total]
        self.assertEqual(len(set(components)), 6)

        cfg = self._warehouse_config('one')
        product = self.env['product.product'].create({
            'name': 'W12 FG E2E', 'is_storable': True,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
        })
        obj = self._obj_product('FGE2E', product)
        stock_fg = expected_total - overhead  # 600_000 — chênh đúng = overhead
        self._fg_move_valued(product, cfg, value=stock_fg)

        self._source_move(direct, object=obj)
        self._config([(obj, 1)])
        self._source_move(overhead)
        run = self._run(name='PB4-E2E')
        run.action_compute()
        run.action_confirm()
        self.assertEqual(run.amount_allocated, overhead)
        self.assertTrue(run.fingerprint)

        period = self._period([obj], opening_wip=opening, name='Kỳ Ch4 E2E')
        period.action_receive_allocation(result_ids=run.result_ids.ids)
        self._source_move(-reduction, object=obj)
        self._closing_confirm(period, {obj: closing})
        period.action_compute_costing()
        ver = period.current_result_id
        self.assertEqual(ver.total_cost, expected_total)
        line = ver.line_ids.filtered(lambda l: l.cost_object_id == obj)
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.stock_fg_receipt_value, stock_fg)
        self.assertAlmostEqual(line.amount_overhead, overhead)

        period.action_submit_approval()
        period.action_approve()
        period.action_post_costing()
        self.assertEqual(period.state, 'posted')
        move = period.posting_move_id
        self.assertTrue(move)
        bal_155 = sum(
            l.debit - l.credit for l in move.line_ids
            if l.account_id == self.acc_155
        )
        self.assertAlmostEqual(bal_155, expected_total)
        gap = bal_155 - line.stock_fg_receipt_value
        self.assertAlmostEqual(gap, overhead)
        # Hai bước tách: bút toán 154→155 không gắn stock.move TP
        self.assertNotEqual(move.source_model, 'stock.move')

    def test_grid_mismatch_blocks_post(self):
        """Lệch tổng đối tượng vs giao TP + chưa giao → chặn, nêu số lệch."""
        cfg = self._warehouse_config('two')
        product = self.env['product.product'].create({
            'name': 'W12 mismatch', 'is_storable': True,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
        })
        obj = self._obj_product('MIS', product)
        self._fg_move_valued(product, cfg, value=1_000.0)
        self._source_move(50_000, object=obj)
        period = self._period([obj])
        self._closing_confirm(period, {obj: 0})
        period.action_compute_costing()
        ver = period.current_result_id
        line = ver.line_ids[:1]
        # Cố ý lệch lưới: giảm amount_delivered, không bù undelivered
        line.write({'amount_delivered': line.total_cost - 7_121_930.0})
        period.action_submit_approval()
        period.action_approve()
        with self.assertRaises(UserError) as err:
            period.action_post_costing()
        msg = str(err.exception)
        self.assertIn('Lệch', msg)
        self.assertIn('7121930', msg)

    def test_allocation_late_source_needs_recompute(self):
        """Hóa đơn CPC phát sinh muộn trong khoảng lượt → dấu vân tay lệch."""
        a = self._obj_ws('LATE1')
        self._config([(a, 1)])
        self._source_move(80_000, date='2099-03-05')
        run = self._run(name='PB4-LATE')
        run.action_compute()
        run.action_confirm()
        fp_before = run.fingerprint
        self.assertTrue(fp_before)
        # Phát sinh muộn — cùng khoảng ngày lượt, sau khi xác nhận
        self._source_move(15_000, date='2099-03-20')
        run.action_check_source_fingerprint()
        self.assertTrue(run.needs_recompute)
        self.assertIn('lệch', (run.recompute_reason or '').lower())
        period = self._period([a])
        with self.assertRaises(UserError) as err:
            period.action_receive_allocation(result_ids=run.result_ids.ids)
        self.assertIn('chạy lại', str(err.exception).lower())
