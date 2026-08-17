# -*- coding: utf-8 -*-
"""M5 — kết quả kỳ tính giá thành (chỉ đọc kết quả đã lưu)."""
from odoo import Command
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_is_zero


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_l78')
class TestVasCostingM5L78(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.acc_154 = cls.env.ref('connecta_vas.vas_account_tt133_154')
        cls.acc_111 = cls.env.ref('connecta_vas.vas_account_tt133_1111')
        cls.env['vas.journal']._ensure_journals_for_company(cls.company)
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        fy = cls.env['vas.fiscalyear'].create({
            'name': 'M5-2096',
            'date_from': '2096-01-01',
            'date_to': '2096-12-31',
            'company_id': cls.company.id,
            'state': 'open',
        })
        cls.env['vas.period'].create({
            'name': '05/2096',
            'date_start': '2096-05-01',
            'date_end': '2096-05-31',
            'fiscalyear_id': fy.id,
            'state': 'open',
        })
        cls.CostItem = cls.env['vas.cost.item']
        cls.CostObject = cls.env['vas.cost.object']
        cls.leaf_a = cls.CostItem.search([
            ('company_id', '=', cls.company.id),
            ('code', '=', 'NVLTT'),
            ('active', '=', True),
        ], limit=1)
        if not cls.leaf_a:
            cls.leaf_a = cls.CostItem.create({
                'code': 'NVLTT', 'name': 'NVL trực tiếp',
                'factor_group': 'material', 'account_id': cls.acc_154.id,
                'company_id': cls.company.id,
            })
        cls.obj = cls.CostObject.create({
            'code': 'M5-OBJ', 'name': 'Đối tượng M5',
            'object_type': 'workshop',
            'company_id': cls.company.id,
            'wip_account_id': cls.acc_154.id,
        })

    def _post_direct(self, amount, cost_item, obj, date='2096-05-10'):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'move_kind': 'manual',
            'ref': 'M5-DIR',
            'line_ids': [
                Command.create({
                    'account_id': self.acc_154.id,
                    'name': 'cp',
                    'debit': amount,
                    'credit': 0.0,
                    'cost_item_id': cost_item.id,
                    'cost_object_id': obj.id,
                }),
                Command.create({
                    'account_id': self.acc_111.id,
                    'name': 'dt',
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _period(self, objects, **extra):
        vals = {
            'name': 'Kỳ M5 05/2096',
            'date_from': '2096-05-01',
            'date_to': '2096-05-31',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [Command.set([o.id for o in objects])],
            'opening_wip': 0.0,
        }
        vals.update(extra)
        return self.env['vas.costing.period'].create(vals)

    def _closing_zero(self, period, objects):
        sheet = self.env['vas.closing.wip'].create({
            'name': 'DD cuối %s' % period.name,
            'kind': 'period_end',
            'period_id': period.id,
            'company_id': self.company.id,
        })
        for obj in objects:
            self.env['vas.closing.wip.line'].create({
                'sheet_id': sheet.id,
                'cost_object_id': obj.id,
                'amount_suggested': 0.0,
                'amount_adjustment': 0.0,
            })
        sheet.state = 'pending_confirm'
        sheet.action_confirm()
        return sheet

    def test_l78_list_columns_empty_and_filled(self):
        period = self._period([self.obj])
        self.assertFalse(period.m5_has_result)
        self.assertFalse(period.m5_total_cost)
        self.assertFalse(period.m5_opening_wip)

        self._post_direct(500_000, self.leaf_a, self.obj)
        self._closing_zero(period, [self.obj])
        period.action_compute_costing()
        period.invalidate_recordset()
        self.assertTrue(period.m5_has_result)
        self.assertEqual(
            float_compare(period.m5_total_cost, period.current_result_id.total_cost, 2),
            0,
        )
        self.assertEqual(
            float_compare(
                period.m5_period_incurred,
                period.current_result_id.amount_direct
                + period.current_result_id.amount_overhead,
                2,
            ),
            0,
        )

    def test_l78_m5_totals_match_across_header_and_tabs(self):
        period = self._period([self.obj])
        self._post_direct(800_000, self.leaf_a, self.obj)
        self._closing_zero(period, [self.obj])
        period.action_compute_costing()

        cmp_ = self.env['vas.costing.period'].get_m5_totals_compare(period.id)
        self.assertTrue(cmp_['ok'], cmp_)
        self.assertEqual(
            float_compare(cmp_['header_total'], cmp_['summary_total'], 2), 0,
        )
        self.assertEqual(
            float_compare(cmp_['header_total'], cmp_['sheet_total'], 2), 0,
        )

        data = self.env['vas.costing.period'].get_m5_payload(period.id)
        self.assertTrue(data['has_result'])
        self.assertEqual(
            float_compare(data['header']['total_cost'], period.m5_total_cost, 2),
            0,
        )
        keys = [t['key'] for t in data['tabs']]
        self.assertIn('summary', keys)
        self.assertIn('cost_sheet', keys)
        self.assertIn('direct', keys)
        # Phân bổ: không nhận → không khai tab
        self.assertNotIn('allocation', keys)

        sheet = next(t for t in data['tabs'] if t['key'] == 'cost_sheet')
        col_ids = {c['id'] for c in sheet['columns']}
        self.assertIn(self.leaf_a.id, col_ids)

    def test_l78_m5_dynamic_cost_item_columns(self):
        period = self._period([self.obj])
        self._post_direct(100_000, self.leaf_a, self.obj)
        self._closing_zero(period, [self.obj])
        period.action_compute_costing()

        data1 = self.env['vas.costing.period'].get_m5_payload(period.id)
        sheet1 = next(t for t in data1['tabs'] if t['key'] == 'cost_sheet')
        n1 = len(sheet1['columns'])

        extra = self.CostItem.create({
            'code': 'M5EXTRA',
            'name': 'Khoản mục M5 thêm',
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        data2 = self.env['vas.costing.period'].get_m5_payload(period.id)
        sheet2 = next(t for t in data2['tabs'] if t['key'] == 'cost_sheet')
        self.assertEqual(len(sheet2['columns']), n1 + 1)
        self.assertIn(extra.id, {c['id'] for c in sheet2['columns']})

        extra.active = False
        data3 = self.env['vas.costing.period'].get_m5_payload(period.id)
        sheet3 = next(t for t in data3['tabs'] if t['key'] == 'cost_sheet')
        self.assertEqual(len(sheet3['columns']), n1)
        self.assertNotIn(extra.id, {c['id'] for c in sheet3['columns']})

    def test_l78_m5_empty_period_and_s18_path(self):
        period = self._period([self.obj])
        data = self.env['vas.costing.period'].get_m5_payload(period.id)
        self.assertFalse(data['has_result'])
        self.assertTrue(data['empty_message'])
        self.assertFalse(data['tabs'])
        self.assertFalse(data['header']['total_cost'])

        act = period.action_open_m5()
        self.assertEqual(act['tag'], 'vas_costing_m5')

        # Chưa tính → S18 báo
        note = period.action_open_s18_report_for_object(self.obj.id)
        self.assertEqual(note.get('tag'), 'display_notification')

        self._post_direct(200_000, self.leaf_a, self.obj)
        self._closing_zero(period, [self.obj])
        period.action_compute_costing()
        s18 = period.action_open_s18_report_for_object(self.obj.id)
        self.assertEqual(s18['tag'], 'vas_report_client')
        line_id = s18['context']['snapshot_id']
        report = self.env['vas.costing.result.line'].get_report_data({
            'snapshot_id': line_id,
        })
        self.assertEqual(report['meta']['form_code'], 'S18-DNN')
        self.assertTrue(report['lines'])

    def test_l78_ops_compute_action_unchanged(self):
        btn = self.env.ref('connecta_vas.vas_ops_btn_cost_compute')
        self.assertEqual(
            btn.action_xmlid, 'connecta_vas.action_vas_costing_period',
        )
        act = self.env.ref('connecta_vas.action_vas_costing_period')
        self.assertEqual(act.res_model, 'vas.costing.period')
        self.assertIn('list', act.view_mode)
        list_arch = self.env.ref('connecta_vas.view_vas_costing_period_list').arch
        self.assertIn('action_open_m5', list_arch)
        self.assertIn('type="object"', list_arch)
