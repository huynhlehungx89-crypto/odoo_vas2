# -*- coding: utf-8 -*-
"""W12 Chặng 6 — vượt định mức / sai hỏng NVL."""
from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('connecta_vas', 'connecta_vas_w12_6')
class TestW12CostingStage6(TransactionCase):

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
        Acc = cls.env['vas.account']
        cls.acc_154 = Acc.search([('regime_id', '=', cls.regime.id), ('code', '=', '154')], limit=1)
        cls.acc_155 = Acc.search([('regime_id', '=', cls.regime.id), ('code', '=', '155')], limit=1)
        cls.acc_632 = Acc.search([('regime_id', '=', cls.regime.id), ('code', '=', '632')], limit=1)
        cls.acc_111 = Acc.search([('regime_id', '=', cls.regime.id), ('code', '=', '111')], limit=1)
        cls.acc_1381 = Acc.search([('regime_id', '=', cls.regime.id), ('code', '=', '1381')], limit=1)
        cls.acc_1388 = Acc.search([('regime_id', '=', cls.regime.id), ('code', '=', '1388')], limit=1)
        cls.acc_334 = Acc.search([('regime_id', '=', cls.regime.id), ('code', '=', '334')], limit=1)
        assert all([
            cls.acc_154, cls.acc_155, cls.acc_632, cls.acc_111,
            cls.acc_1381, cls.acc_1388, cls.acc_334,
        ]), 'Thiếu TK TT133 bắt buộc (1381/1388/334/632/154/155/111)'
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
            ('date_from', '<=', '2099-06-15'),
            ('date_to', '>=', '2099-06-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W12-6-2099', 'date_from': '2099-01-01',
                'date_to': '2099-12-31', 'company_id': cls.company.id,
                'state': 'open',
            })
        cls.fy = fy
        cls.period_acc = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', '2099-06-15'),
            ('date_end', '>=', '2099-06-15'),
        ], limit=1)
        if not cls.period_acc:
            cls.period_acc = cls.env['vas.period'].create({
                'name': '06/2099', 'date_start': '2099-06-01',
                'date_end': '2099-06-30', 'fiscalyear_id': fy.id, 'state': 'open',
            })
        cls.fg_categ = cls.env['product.category'].create({'name': 'W12-6 FG'})
        if not cls.env['vas.account.map'].search([
            ('regime_id', '=', cls.regime.id),
            ('category_id', '=', cls.fg_categ.id),
        ], limit=1):
            cls.env['vas.account.map'].create({
                'regime_id': cls.regime.id,
                'apply_to': 'category',
                'category_id': cls.fg_categ.id,
                'company_id': cls.company.id,
                'stock_account_id': cls.acc_155.id,
                'cogs_account_id': cls.acc_632.id,
            })
        cls.env['vas.variance.account.config']._seed_defaults_tt133()
        cfg = cls.env['vas.variance.account.config']._get_for(cls.company, cls.regime)
        if not cfg:
            cls.env['vas.variance.account.config'].create({
                'company_id': cls.company.id,
                'regime_id': cls.regime.id,
                'account_pending_id': cls.acc_1381.id,
                'account_claim_id': cls.acc_1388.id,
                'account_payroll_id': cls.acc_334.id,
                'account_writeoff_id': cls.acc_632.id,
            })
        cls.partner = cls.env['res.partner'].create({'name': 'NCC bồi thường W12-6'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'NV nội bộ W12-6',
            'company_id': cls.company.id,
        })

    # ------------------------------------------------------------------ helpers
    def _product(self, name):
        return self.env['product.product'].create({
            'name': name, 'is_storable': True,
            'categ_id': self.fg_categ.id,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
        })

    def _obj(self, code, product=None):
        vals = {
            'code': code, 'name': code, 'object_type': 'product',
            'company_id': self.company.id, 'wip_account_id': self.acc_154.id,
        }
        if product:
            vals.update({
                'source_model': 'product.product', 'source_res_id': product.id,
            })
        return self.env['vas.cost.object'].create(vals)

    def _source_move(self, amount, date='2099-06-15', object=None, ref='W12-6'):
        move = self.env['vas.move'].create({
            'date': date, 'journal_id': self.journal.id,
            'regime_id': self.regime.id, 'move_kind': 'manual',
            'ref': ref, 'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': [
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
            ],
        })
        move.action_post()
        return move

    def _period(self, objects, **extra):
        vals = {
            'name': 'Kỳ Ch6', 'date_from': '2099-06-01',
            'date_to': '2099-06-30', 'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [Command.set([o.id for o in objects])],
            'opening_wip': 0.0,
        }
        vals.update(extra)
        return self.env['vas.costing.period'].create(vals)

    def _closing(self, period, amounts_by_obj):
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

    def _warehouse(self, posting_mode='period_end'):
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
            'step_mode': 'one',
            'posting_mode': posting_mode,
            'fg_picking_type_id': pt.id,
            'fg_location_id': wh.lot_stock_id.id,
            'active': True,
        }
        if existing:
            existing.write(vals)
            return existing
        vals.update({
            'company_id': self.company.id,
            'warehouse_id': wh.id,
        })
        return self.env['vas.costing.warehouse.config'].create(vals)

    def _vml_source(self, amount, obj):
        move = self._source_move(amount, object=obj)
        return move.line_ids.filtered(lambda l: l.account_id == self.acc_154)[:1]

    def _sheet(self, period, **extra):
        vals = {
            'period_id': period.id,
            'company_id': self.company.id,
        }
        vals.update(extra)
        return self.env['vas.variance.sheet'].create(vals)

    def _excess_line(self, sheet, obj, amount, source_line=None, **extra):
        vals = {
            'sheet_id': sheet.id,
            'line_kind': 'excess',
            'suggestion_source': 'manual',
            'cost_object_id': obj.id,
            'cost_item_id': self.cpc.id,
            'amount_suggested': amount,
            'amount_confirmed': amount,
            'reason': extra.pop('reason', 'Vượt NVL thủ công'),
            'cause': extra.pop('cause', 'Hao hụt'),
        }
        if source_line:
            vals.update({
                'source_model': 'vas.move.line',
                'source_res_id': source_line.id,
                'source_label': source_line.display_name,
                'stock_value_actual': abs(source_line.debit - source_line.credit),
            })
        vals.update(extra)
        return self.env['vas.variance.line'].create(vals)

    def _treat(self, line, ttype, amount, **extra):
        vals = {
            'line_id': line.id,
            'treatment_type': ttype,
            'amount': amount,
            'name': ttype,
        }
        vals.update(extra)
        return self.env['vas.variance.treatment'].create(vals)

    def _confirm_post(self, sheet):
        sheet.action_confirm()
        sheet.action_post()
        return sheet

    def _compute_cost(self, period, obj, closing=0.0):
        self._closing(period, {obj: closing})
        period.action_compute_costing()
        return period.current_result_id

    # ------------------------------------------------------------------ UI / ACL
    def test_ui_views_actions_acl(self):
        self.assertTrue(self.env.ref('connecta_vas.view_vas_variance_sheet_form'))
        self.assertTrue(self.env.ref('connecta_vas.view_vas_variance_sheet_list'))
        self.assertTrue(self.env.ref('connecta_vas.action_vas_variance_sheet'))
        self.assertTrue(self.env.ref('connecta_vas.vas_ops_btn_cost_variance'))
        sheet = self._sheet(self._period([self._obj('UI1')]))
        wiz = self.env['vas.costing.reason.wizard'].create({
            'action_kind': 'variance_reverse',
            'variance_sheet_id': sheet.id,
            'period_id': sheet.period_id.id,
            'reason': 'thử',
        })
        self.assertEqual(wiz.action_kind, 'variance_reverse')
        # quyền đọc model
        self.env['vas.variance.sheet'].check_access('read')

    # ------------------------------------------------------------------ 12.1
    def test_121_exact_bom_no_sheet(self):
        """Xuất đúng định mức → toàn bộ vào GT, không cần phiếu vượt."""
        product = self._product('FG121')
        obj = self._obj('O121', product)
        self._source_move(900_000, object=obj)
        period = self._period([obj])
        ver = self._compute_cost(period, obj)
        self.assertEqual(ver.total_cost, 900_000)
        self.assertFalse(self.env['vas.variance.sheet'].search([
            ('period_id', '=', period.id), ('state', '=', 'posted'),
        ]))

    # ------------------------------------------------------------------ 12.2
    def test_122_excess_pending_post(self):
        product = self._product('FG122')
        obj = self._obj('O122', product)
        self._source_move(1_000_000, object=obj)
        src = self._vml_source(137_000, obj)  # trần nguồn riêng
        period = self._period([obj])
        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 137_000, source_line=src)
        self._treat(line, 'pending', 137_000)
        self._confirm_post(sheet)
        move = sheet.move_id
        self.assertEqual(move.state, 'posted')
        debit_pending = sum(
            move.line_ids.filtered(
                lambda l: l.account_id == self.acc_1381,
            ).mapped('debit')
        )
        credit_154 = sum(
            move.line_ids.filtered(
                lambda l: l.account_id == self.acc_154,
            ).mapped('credit')
        )
        self.assertEqual(debit_pending, 137_000)
        self.assertEqual(credit_154, 137_000)
        # không ghi thẳng từ 155/632
        self.assertFalse(move.line_ids.filtered(
            lambda l: l.account_id in (self.acc_155, self.acc_632) and l.credit,
        ))
        ver = self._compute_cost(period, obj)
        # 1_000_000 + 137_000 nguồn trần (cũng vào 154) - 137_000 reduction
        # Wait: _vml_source posts another 137k to 154. Total debit = 1_137_000
        # reduction treatment 137k → total = 1_000_000
        self.assertEqual(ver.total_cost, 1_000_000)
        # bất biến 1.3: thực tế = GT hợp lệ + vượt
        actual = 1_000_000 + 137_000
        self.assertEqual(ver.total_cost + 137_000, actual)

    # ------------------------------------------------------------------ 12.3
    def test_123_followup_claim(self):
        product = self._product('FG123')
        obj = self._obj('O123', product)
        self._source_move(800_000, object=obj)
        src = self._vml_source(120_000, obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 120_000, source_line=src)
        pending = self._treat(line, 'pending', 120_000)
        self._confirm_post(sheet)
        follow = self._sheet(period, is_followup=True, parent_treatment_id=pending.id)
        fline = self._excess_line(
            follow, obj, 120_000, source_line=src,
            reason='Xác định bồi thường',
        )
        self._treat(fline, 'claim', 120_000, partner_id=self.partner.id)
        self._confirm_post(follow)
        self.assertEqual(pending.amount_remaining, 0.0)
        self.assertEqual(pending.amount_processed, 120_000)
        # 7.4
        self.assertEqual(
            pending.amount_processed + pending.amount_remaining, pending.amount,
        )
        claim_lines = follow.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_1388,
        )
        self.assertEqual(sum(claim_lines.mapped('debit')), 120_000)
        self.assertEqual(claim_lines.partner_id, self.partner)

    # ------------------------------------------------------------------ 12.4
    def test_124_payroll_deduction(self):
        product = self._product('FG124')
        obj = self._obj('O124', product)
        src = self._vml_source(88_000, obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 88_000, source_line=src)
        self._treat(line, 'payroll', 88_000, employee_id=self.employee.id)
        self._confirm_post(sheet)
        self.assertEqual(
            sum(sheet.move_id.line_ids.filtered(
                lambda l: l.account_id == self.acc_334,
            ).mapped('debit')),
            88_000,
        )

    # ------------------------------------------------------------------ 12.5
    def test_125_split_two_treatments(self):
        product = self._product('FG125')
        obj = self._obj('O125', product)
        src = self._vml_source(10_000_000, obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 10_000_000, source_line=src)
        self._treat(line, 'claim', 6_000_000, partner_id=self.partner.id)
        self._treat(
            line, 'writeoff', 4_000_000, reason='Không thu hồi được phần còn lại',
        )
        # 2.3
        self.assertEqual(sum(line.treatment_ids.mapped('amount')), line.amount_confirmed)
        self._confirm_post(sheet)
        self.assertEqual(
            sum(sheet.move_id.line_ids.filtered(
                lambda l: l.account_id == self.acc_1388,
            ).mapped('debit')),
            6_000_000,
        )
        self.assertEqual(
            sum(sheet.move_id.line_ids.filtered(
                lambda l: l.account_id == self.acc_632 and l.debit,
            ).mapped('debit')),
            4_000_000,
        )

    # ------------------------------------------------------------------ 12.6
    def test_126_saving_admin_only(self):
        product = self._product('FG126')
        obj = self._obj('O126', product)
        self._source_move(750_000, object=obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        saving = self.env['vas.variance.line'].create({
            'sheet_id': sheet.id,
            'line_kind': 'saving',
            'suggestion_source': 'manual',
            'cost_object_id': obj.id,
            'amount_suggested': 0.0,
            'amount_confirmed': 0.0,
            'reason': 'Dùng ít hơn BOM',
            'qty_standard': 10, 'qty_actual': 8,
        })
        with self.assertRaises(UserError):
            self.env['vas.variance.treatment'].create({
                'line_id': saving.id,
                'treatment_type': 'writeoff',
                'amount': 1,
                'reason': 'x',
            })
        ver = self._compute_cost(period, obj)
        self.assertEqual(ver.total_cost, 750_000)
        self.assertFalse(sheet.move_id)

    # ------------------------------------------------------------------ 12.7
    def test_127_idempotent_and_reverse_order(self):
        product = self._product('FG127')
        obj = self._obj('O127', product)
        self._source_move(500_000, object=obj)
        src = self._vml_source(71_000, obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 71_000, source_line=src)
        pending = self._treat(line, 'pending', 71_000)
        self._confirm_post(sheet)
        follow = self._sheet(period, is_followup=True, parent_treatment_id=pending.id)
        fl = self._excess_line(follow, obj, 40_000, source_line=src, reason='một phần')
        self._treat(fl, 'claim', 40_000, partner_id=self.partner.id)
        self._confirm_post(follow)
        with self.assertRaises(UserError):
            sheet.action_reverse(reason='đảo gốc khi còn tiếp')
        follow.action_reverse(reason='đảo phiếu tiếp')
        self.assertEqual(pending.amount_remaining, 71_000)
        sheet.action_reverse(reason='đảo gốc sau khi hết tiếp')
        self.assertEqual(sheet.state, 'reversed')
        # tính lại được
        ver = self._compute_cost(period, obj)
        self.assertEqual(ver.total_cost, 500_000 + 71_000)

    # ------------------------------------------------------------------ 12.8
    def test_128_no_variance_unchanged_900k(self):
        product = self._product('FG128')
        obj = self._obj('O128', product)
        self._source_move(900_000, object=obj)
        self._warehouse('period_end')
        period = self._period([obj])
        ver = self._compute_cost(period, obj)
        self.assertEqual(ver.total_cost, 900_000)
        self.assertFalse(self.env['vas.variance.sheet'].search([
            ('period_id', '=', period.id),
        ]))

    # ------------------------------------------------------------------ 12.9
    def test_129_immediate_pullback_then_claim(self):
        """Đã ghi tạm → cuối kỳ ghi sổ vượt → kéo 155/632 về 154 rồi Nợ phải thu / Có 154."""
        cfg = self._warehouse('immediate')
        product = self._product('FG129')
        obj = self._obj('O129', product)
        # Chi phí NVL thực tế 1_000_000 (gồm vượt 173_000) — ghi vào 154
        self._source_move(1_000_000, object=obj)
        src = self._vml_source(173_000, obj)
        period = self._period([obj], name='Kỳ Ch6-129')
        # Phiếu nhập TP + ghi tạm (Dr 155 / Cr 154) qua engine Chặng 5
        StockLocation = self.env['stock.location']
        src_loc = StockLocation.search([
            ('usage', '=', 'production'),
            '|', ('company_id', '=', self.company.id), ('company_id', '=', False),
        ], limit=1) or StockLocation.search([
            ('usage', '=', 'supplier'),
            '|', ('company_id', '=', self.company.id), ('company_id', '=', False),
        ], limit=1)
        if not src_loc:
            self.skipTest('Thiếu location nguồn')
        sm = self.env['stock.move'].create({
            'origin': 'L129',
            'product_id': product.id,
            'product_uom_qty': 10.0,
            'product_uom': product.uom_id.id,
            'location_id': src_loc.id,
            'location_dest_id': cfg.fg_location_id.id,
            'picking_type_id': cfg.fg_picking_type_id.id,
            'company_id': self.company.id,
            'date': '2099-06-10 10:00:00',
        })
        self.env.cr.execute(
            "UPDATE stock_move SET state='done', quantity=%s, value=%s, date=%s WHERE id=%s",
            (10.0, 1_173_000.0, '2099-06-10 10:00:00', sm.id),
        )
        sm.invalidate_recordset()
        # Ghi tạm thủ công gắn lot (engine thật cần raw moves; đủ cho pullback)
        prov = self.env['vas.move'].create({
            'date': '2099-06-10', 'journal_id': self.journal.id,
            'regime_id': self.regime.id, 'move_kind': 'manual',
            'ref': 'prov-129', 'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'source_model': 'vas.costing.provisional.lot',
            'source_res_id': 0,
            'source_ref': 'provisional_fg',
            'line_ids': [
                Command.create({
                    'account_id': self.acc_155.id, 'name': 'tam',
                    'debit': 1_173_000, 'credit': 0.0,
                    'currency_id': self.company.currency_id.id,
                }),
                Command.create({
                    'account_id': self.acc_154.id, 'name': 'tam',
                    'debit': 0.0, 'credit': 1_173_000,
                    'currency_id': self.company.currency_id.id,
                    'cost_object_id': obj.id,
                }),
            ],
        })
        prov.action_post()
        self.env['vas.costing.provisional.lot'].create({
            'company_id': self.company.id,
            'warehouse_config_id': cfg.id,
            'period_id': period.id,
            'cost_object_id': obj.id,
            'product_id': product.id,
            'stock_move_id': sm.id,
            'lot_code': 'L129',
            'qty': 10.0,
            'unit_price_provisional': 117_300,
            'amount_provisional': 1_173_000,
            'receipt_date': '2099-06-10 10:00:00',
            'source_kind': 'nvl_stock_value',
            'state': 'posted',
            'move_id': prov.id,
        })
        # Bán 4/10 trước date_to → phần vượt kéo về từ 155 và 632
        cust = self.env['stock.location'].search([
            ('usage', '=', 'customer'),
            '|', ('company_id', '=', self.company.id), ('company_id', '=', False),
        ], limit=1)
        if not cust:
            self.skipTest('Thiếu location khách')
        out = self.env['stock.move'].create({
            'origin': 'OUT129',
            'product_id': product.id,
            'product_uom_qty': 4.0,
            'product_uom': product.uom_id.id,
            'location_id': cfg.fg_location_id.id,
            'location_dest_id': cust.id,
            'company_id': self.company.id,
            'date': '2099-06-20 10:00:00',
        })
        self.env.cr.execute(
            "UPDATE stock_move SET state='done', quantity=%s, date=%s WHERE id=%s",
            (4.0, '2099-06-20 10:00:00', out.id),
        )
        out.invalidate_recordset()

        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 173_000, source_line=src)
        self._treat(line, 'claim', 173_000, partner_id=self.partner.id)
        self._confirm_post(sheet)

        pb = sheet.pullback_move_id
        self.assertTrue(pb and pb.state == 'posted')
        pb_dr_154 = sum(pb.line_ids.filtered(
            lambda l: l.account_id == self.acc_154,
        ).mapped('debit'))
        pb_cr_155 = sum(pb.line_ids.filtered(
            lambda l: l.account_id == self.acc_155,
        ).mapped('credit'))
        pb_cr_632 = sum(pb.line_ids.filtered(
            lambda l: l.account_id == self.acc_632,
        ).mapped('credit'))
        self.assertEqual(pb_dr_154, 173_000)
        self.assertEqual(pb_cr_155 + pb_cr_632, 173_000)
        self.assertGreater(pb_cr_155, 0)
        self.assertGreater(pb_cr_632, 0)

        tr = sheet.move_id
        self.assertEqual(
            sum(tr.line_ids.filtered(lambda l: l.account_id == self.acc_1388).mapped('debit')),
            173_000,
        )
        self.assertEqual(
            sum(tr.line_ids.filtered(lambda l: l.account_id == self.acc_154).mapped('credit')),
            173_000,
        )
        self.assertFalse(tr.line_ids.filtered(
            lambda l: l.account_id in (self.acc_155, self.acc_632),
        ))
        self.assertEqual(tr.line_ids.filtered(
            lambda l: l.account_id == self.acc_1388,
        ).partner_id, self.partner)

        ver = self._compute_cost(period, obj)
        self.assertEqual(ver.total_cost, 1_000_000)
        actual = 1_000_000 + 173_000
        self.assertEqual(ver.total_cost + 173_000, actual)

    def test_1210_manual_without_mrp(self):
        product = self._product('FG1210')
        obj = self._obj('O1210', product)
        src = self._vml_source(64_000, obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        if 'mrp.bom' not in self.env:
            with self.assertRaises(UserError) as err:
                sheet.action_suggest_from_bom()
            self.assertIn('MRP', str(err.exception))
        line = self._excess_line(sheet, obj, 64_000, source_line=src)
        pending = self._treat(line, 'pending', 64_000)
        self._confirm_post(sheet)
        follow = self._sheet(period, is_followup=True, parent_treatment_id=pending.id)
        fl = self._excess_line(follow, obj, 64_000, source_line=src, reason='claim')
        self._treat(fl, 'claim', 64_000, partner_id=self.partner.id)
        self._confirm_post(follow)
        follow.action_reverse(reason='đảo tiếp')
        sheet.action_reverse(reason='đảo gốc')
        self.assertEqual(sheet.state, 'reversed')

    # ------------------------------------------------------------------ 4.5 ceiling
    def test_45_source_ceiling(self):
        obj = self._obj('O45')
        src = self._vml_source(50_000, obj)
        period = self._period([obj])
        s1 = self._sheet(period)
        l1 = self._excess_line(s1, obj, 40_000, source_line=src)
        self._treat(l1, 'pending', 40_000)
        self._confirm_post(s1)
        s2 = self._sheet(period)
        l2 = self._excess_line(s2, obj, 20_000, source_line=src)
        self._treat(l2, 'pending', 20_000)
        with self.assertRaises(UserError):
            s2.action_confirm()
        # đảo s1 → dùng lại
        s1.action_reverse(reason='nhả trần')
        s2.action_confirm()
        # số xác nhận > nguồn
        s3 = self._sheet(period)
        l3 = self._excess_line(s3, obj, 60_000, source_line=src)
        self._treat(l3, 'pending', 60_000)
        with self.assertRaises(UserError):
            s3.action_confirm()

    # ------------------------------------------------------------------ 5.12 accounts
    def test_512_accounts_and_partners(self):
        obj = self._obj('O512')
        period = self._period([obj])
        cfg = self.env['vas.variance.account.config']._get_for(self.company, self.regime)
        other_regime = self.env['vas.regime'].create({
            'code': 'TTX6', 'name': 'Fake',
        })
        bad = self.env['vas.account'].create({
            'code': '9999', 'name': 'Bad', 'regime_id': other_regime.id,
            'account_type': 'asset', 'ending_balance_policy': 'debit',
        })
        # sai regime
        src = self._vml_source(33_000, obj)
        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 33_000, source_line=src)
        t = self._treat(line, 'claim', 33_000, partner_id=self.partner.id)
        t.account_id = bad.id
        sheet.action_confirm()
        with self.assertRaises(UserError):
            sheet.action_post()
        # claim thiếu partner
        src_b = self._vml_source(34_000, obj)
        sheet_b = self._sheet(period)
        line_b = self._excess_line(sheet_b, obj, 34_000, source_line=src_b)
        self._treat(line_b, 'claim', 34_000)
        with self.assertRaises(UserError):
            sheet_b.action_confirm()
        # payroll không thuộc công ty
        src2 = self._vml_source(10_000, obj)
        sheet2 = self._sheet(period)
        line2 = self._excess_line(sheet2, obj, 10_000, source_line=src2)
        foreign_co = self.env['res.company'].create({'name': 'Công ty ngoài W12-6'})
        foreign_emp = self.env['hr.employee'].create({
            'name': 'NV khách',
            'company_id': foreign_co.id,
        })
        self._treat(line2, 'payroll', 10_000, employee_id=foreign_emp.id)
        with self.assertRaises(UserError):
            sheet2.action_confirm()
        # writeoff thiếu lý do
        sheet3 = self._sheet(period)
        src3 = self._vml_source(12_000, obj)
        line3 = self._excess_line(sheet3, obj, 12_000, source_line=src3)
        self._treat(line3, 'writeoff', 12_000, reason='')
        with self.assertRaises(UserError):
            sheet3.action_confirm()
        # đổi cấu hình sau ghi sổ không đổi account_used + partner xuống dòng
        sheet4 = self._sheet(period)
        src4 = self._vml_source(15_000, obj)
        line4 = self._excess_line(sheet4, obj, 15_000, source_line=src4)
        tr = self._treat(line4, 'claim', 15_000, partner_id=self.partner.id)
        self._confirm_post(sheet4)
        used = tr.account_used_id
        cfg.account_claim_id = self.acc_111
        self.assertEqual(tr.account_used_id, used)
        cfg.account_claim_id = self.acc_1388
        self.assertEqual(
            sheet4.move_id.line_ids.filtered(
                lambda l: l.account_id == self.acc_1388,
            ).partner_id,
            self.partner,
        )
    # ------------------------------------------------------------------ 7.8 followups
    def test_78_followup_rules(self):
        obj = self._obj('O78')
        src = self._vml_source(90_000, obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 90_000, source_line=src)
        pending = self._treat(line, 'pending', 90_000)
        self._confirm_post(sheet)
        f1 = self._sheet(period, is_followup=True, parent_treatment_id=pending.id)
        fl1 = self._excess_line(f1, obj, 50_000, source_line=src, reason='f1')
        self._treat(fl1, 'claim', 50_000, partner_id=self.partner.id)
        self._confirm_post(f1)
        f2 = self._sheet(period, is_followup=True, parent_treatment_id=pending.id)
        fl2 = self._excess_line(f2, obj, 50_000, source_line=src, reason='f2')
        self._treat(fl2, 'claim', 50_000, partner_id=self.partner.id)
        with self.assertRaises(UserError):
            f2.action_confirm()
        f2.line_ids.amount_confirmed = 40_000
        f2.line_ids.treatment_ids.amount = 40_000
        self._confirm_post(f2)
        self.assertEqual(pending.amount_remaining, 0.0)
        f2.action_reverse(reason='nhả')
        self.assertEqual(pending.amount_remaining, 40_000)
        # phần đã claim không làm nguồn
        claim_t = f1.line_ids.treatment_ids[:1]
        with self.assertRaises(UserError):
            bad = self._sheet(period, is_followup=True, parent_treatment_id=claim_t.id)
            bl = self._excess_line(bad, obj, 10_000, source_line=src, reason='bad')
            self._treat(bl, 'writeoff', 10_000, reason='x')
            bad.action_confirm()

    # ------------------------------------------------------------------ 9.5 saving
    def test_95_saving_data_layer_bans(self):
        obj = self._obj('O95')
        self._source_move(400_000, object=obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        saving = self.env['vas.variance.line'].create({
            'sheet_id': sheet.id,
            'line_kind': 'saving',
            'suggestion_source': 'manual',
            'cost_object_id': obj.id,
            'amount_suggested': 0, 'amount_confirmed': 0,
            'reason': 'tiết kiệm',
        })
        with self.assertRaises(UserError):
            self.env['vas.variance.treatment'].create({
                'line_id': saving.id,
                'treatment_type': 'pending',
                'amount': 1,
            })
        with self.assertRaises(UserError):
            sheet.action_confirm()
        # follow-up từ saving — không có pending
        with self.assertRaises(UserError):
            sheet.action_create_followup()
        ver = self._compute_cost(period, obj)
        self.assertEqual(ver.total_cost, 400_000)

    # ------------------------------------------------------------------ 11.7 lifecycle
    def test_117_costing_lifecycle(self):
        obj = self._obj('O117')
        self._source_move(600_000, object=obj)
        src = self._vml_source(45_000, obj)
        period = self._period([obj])
        sheet = self._sheet(period)
        line = self._excess_line(sheet, obj, 45_000, source_line=src)
        self._treat(line, 'pending', 45_000)
        # nháp không giảm GT — nhưng chặn compute nếu có excess chưa post
        with self.assertRaises(UserError):
            self._compute_cost(period, obj)
        sheet.action_confirm()
        with self.assertRaises(UserError) as err:
            period.action_compute_costing()
        self.assertIn('Ghi sổ phiếu xử lý vượt', str(err.exception))
        sheet.action_post()
        ver = self._compute_cost(period, obj)
        fp1 = ver.fingerprint
        self.assertEqual(ver.total_cost, 600_000)
        # đảo → vượt trở lại
        sheet.action_reverse(reason='đảo lifecycle')
        ver2 = self._compute_cost(period, obj)
        self.assertEqual(ver2.total_cost, 600_000 + 45_000)
        # fingerprint đổi khi có phiếu posted mới
        sheet2 = self._sheet(period)
        line2 = self._excess_line(sheet2, obj, 45_000, source_line=src)
        self._treat(line2, 'pending', 45_000)
        self._confirm_post(sheet2)
        ver3 = self._compute_cost(period, obj)
        self.assertNotEqual(ver3.fingerprint, fp1)
        # kỳ đã posted chặn sửa phiếu
        # giả lập period posted
        period.state = 'posted'
        with self.assertRaises(UserError):
            sheet2.action_reverse(reason='x')

    # ------------------------------------------------------------------ 12.11 BOM formulas
    def test_1211_bom_helper_formulas(self):
        Helper = self.env['vas.variance.bom.helper']
        # sản lượng thực tế (không theo kế hoạch)
        self.assertEqual(Helper._qty_standard(2.0, 7.0), 14.0)
        # xuất ròng sau hoàn trả
        self.assertEqual(Helper._qty_actual_net(10.0, 3.0), 7.0)
        # UoM: dozen → unit
        unit = self.env.ref('uom.product_uom_unit')
        dozen = self.env.ref('uom.product_uom_dozen')
        self.assertEqual(Helper._convert_qty(1.0, dozen, unit), 12.0)
        # tiền vượt theo giá lần xuất
        self.assertEqual(Helper._excess_amount(2.0, 1000.0, 10.0), 200.0)
        # không đủ dữ liệu → suggest báo / không tự đoán
        period = self._period([self._obj('O1211')])
        sheet = self._sheet(period)
        if 'mrp.bom' not in self.env:
            with self.assertRaises(UserError) as err:
                sheet.action_suggest_from_bom()
            self.assertIn('MRP', str(err.exception))
            # vẫn tạo thủ công
            line = self._excess_line(
                sheet, period.cost_object_ids[0], 21_000,
                source_line=self._vml_source(21_000, period.cost_object_ids[0]),
            )
            self.assertEqual(line.suggestion_source, 'manual')
        else:
            res = sheet.action_suggest_from_bom()
            self.assertIn('n_insufficient', res)

    def test_accounts_tt133_present(self):
        for code in ('1381', '1388', '334', '632'):
            self.assertTrue(
                self.env['vas.account'].search([
                    ('regime_id', '=', self.regime.id), ('code', '=', code),
                ], limit=1),
                'Thiếu TK %s trong TT133' % code,
            )
        cfg = self.env['vas.variance.account.config']._get_for(self.company, self.regime)
        self.assertTrue(cfg.account_pending_id)
        self.assertEqual(cfg.account_pending_id.code, '1381')
