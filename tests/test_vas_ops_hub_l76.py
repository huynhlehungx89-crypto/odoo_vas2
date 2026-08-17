# -*- coding: utf-8 -*-
"""Hub l76 — bốn nhóm Tài sản / Thuế / Vay / Vốn."""
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas', 'connecta_vas_ops', 'connecta_vas_l76')
class TestVasOpsHubL76(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Group = cls.env['vas.ops.group']

    def test_l76_hub_tiles_vay_von_separate(self):
        tiles = self.Group.get_hub_tiles()
        by_code = {t['code']: t for t in tiles}
        self.assertIn('vay', by_code)
        self.assertIn('von', by_code)
        self.assertNotIn('loan', by_code)
        self.assertEqual(by_code['vay']['state'], 'ready')
        self.assertEqual(by_code['von']['state'], 'ready')
        self.assertEqual(by_code['asset']['state'], 'ready')
        self.assertEqual(by_code['tax']['state'], 'ready')

    def test_l76_asset_chain_plus_prepaid_detached(self):
        group = self.env.ref('connecta_vas.vas_ops_group_asset')
        self.assertEqual(group.screen_kind, 'workflow')
        payload = self.Group.get_workflow_payload('asset')
        self.assertEqual(payload['layout'], 'chain')
        self.assertEqual([p['label'] for p in payload['process']], [
            'Ghi tăng tài sản',
            'Tính khấu hao định kỳ',
            'Điều chuyển',
            'Ghi giảm',
        ])
        self.assertEqual([d['label'] for d in payload['detached']], [
            'Chi phí trả trước (242)',
        ])
        self.assertFalse(payload['report'])
        dep = next(p for p in payload['process'] if p['label'] == 'Tính khấu hao định kỳ')
        self.assertEqual(dep['action_xmlid'], 'connecta_vas.action_vas_move_depreciation')

    def test_l76_tax_chain_plus_import_vat_detached(self):
        payload = self.Group.get_workflow_payload('tax')
        labels_process = [p['label'] for p in payload['process']]
        labels_detached = [d['label'] for d in payload['detached']]
        self.assertIn('Khấu trừ GTGT (L06)', labels_process + labels_detached)
        self.assertIn('GTGT hàng nhập khẩu', labels_process + labels_detached)
        self.assertNotIn('Nộp thuế GTGT', labels_process)
        self.assertNotIn('Nộp thuế GTGT', labels_detached)
        l06 = next(
            p for p in (payload['process'] + payload['detached'])
            if p['label'] == 'Khấu trừ GTGT (L06)'
        )
        self.assertEqual(l06['action_xmlid'], 'connecta_vas.action_vas_closing_entry')

    def test_l76_vay_five_step_chain(self):
        payload = self.Group.get_workflow_payload('vay')
        self.assertEqual(payload['layout'], 'chain')
        self.assertEqual([p['label'] for p in payload['process']], [
            'Khế ước vay',
            'Ghi lãi định kỳ',
            'Trả lãi',
            'Trả gốc',
            'Tất toán',
        ])
        by_label = {p['label']: p for p in payload['process']}
        self.assertEqual(
            by_label['Ghi lãi định kỳ']['action_xmlid'],
            'connecta_vas.action_vas_move_loan_interest',
        )
        self.assertEqual(
            by_label['Trả lãi']['action_xmlid'],
            'connecta_vas.action_vas_payment_loan_interest',
        )
        self.assertEqual(
            by_label['Trả gốc']['action_xmlid'],
            'connecta_vas.action_vas_payment_loan_repay',
        )
        for label in ('Khế ước vay', 'Tất toán'):
            self.assertEqual(
                by_label[label]['action_xmlid'],
                'connecta_vas.action_vas_loan',
            )

    def test_l76_von_hub_two_tiles_no_chain(self):
        group = self.env.ref('connecta_vas.vas_ops_group_von')
        self.assertEqual(group.screen_kind, 'hub')
        payload = self.Group.get_workflow_payload('von')
        self.assertEqual(payload['layout'], 'tiles')
        labels = [p['label'] for p in payload['process']]
        self.assertEqual(labels, ['Phân phối LN / quỹ', 'Góp vốn hiện vật'])
        self.assertFalse(payload['detached'])

    def test_l76_group_menus_and_legacy_menus(self):
        ops = self.env.ref('connecta_vas.menu_vas_ops')
        names = set(ops.child_id.filtered(lambda m: m.active).mapped('name'))
        for label in (
            'Tài sản / Phân bổ', 'Thuế', 'Vay', 'Vốn',
            'Khoản vay', 'Phân phối LN / quỹ', 'Góp vốn hiện vật',
            'GTGT hàng nhập khẩu',
        ):
            self.assertIn(label, names)

        asset_menu = self.env.ref('connecta_vas.menu_vas_asset')
        self.assertEqual(
            asset_menu.action.id,
            self.env.ref('connecta_vas.action_vas_ops_workflow_asset').id,
        )

    def test_l76_step_actions_resolve(self):
        """Mọi nút seed l76 tra được action — không bị ẩn."""
        for code in ('asset', 'tax', 'vay', 'von'):
            payload = self.Group.get_workflow_payload(code)
            self.assertTrue(payload['process'], code)
            for btn in payload['process']:
                self.assertTrue(btn.get('has_action'), btn['label'])
            for btn in payload.get('detached') or []:
                self.assertTrue(btn.get('has_action'), btn['label'])
