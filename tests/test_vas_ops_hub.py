# -*- coding: utf-8 -*-
"""Hub / lưu đồ nghiệp vụ — ca kiểm tự động (không đụng sổ)."""
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas', 'connecta_vas_ops')
class TestVasOpsHub(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Group = cls.env['vas.ops.group']
        cls.Button = cls.env['vas.ops.button']
        # Seed noupdate phải có mặt
        cls.cash = cls.env.ref('connecta_vas.vas_ops_group_cash')
        cls.general = cls.env.ref('connecta_vas.vas_ops_group_general')

    def test_09_m2m_next_bidirectional(self):
        """Một nút nối tới HAI nút tiếp — đọc đúng cả hai chiều."""
        a = self.Button.with_context(vas_ops_allow_write=True).create({
            'group_id': self.cash.id,
            'zone': 'process',
            'label': 'A-test',
            'sequence': 900,
        })
        b = self.Button.with_context(vas_ops_allow_write=True).create({
            'group_id': self.cash.id,
            'zone': 'process',
            'label': 'B-test',
            'sequence': 901,
        })
        c = self.Button.with_context(vas_ops_allow_write=True).create({
            'group_id': self.cash.id,
            'zone': 'process',
            'label': 'C-test',
            'sequence': 902,
        })
        a.with_context(vas_ops_allow_write=True).write({
            'next_ids': [(6, 0, [b.id, c.id])],
        })
        self.assertEqual(set(a.next_ids.ids), {b.id, c.id})
        self.assertIn(a, b.prev_ids)
        self.assertIn(a, c.prev_ids)
        # Dọn — chỉ trong ca kiểm
        (a | b | c).with_context(vas_ops_allow_write=True).unlink()

    def test_10_bad_action_hides_button_screen_runs(self):
        btn = self.Button.with_context(vas_ops_allow_write=True).create({
            'group_id': self.cash.id,
            'zone': 'process',
            'label': 'Nút sai XML',
            'sequence': 950,
            'action_xmlid': 'connecta_vas.action_does_not_exist_xyz',
        })
        payload = self.Group.get_workflow_payload('cash')
        self.assertTrue(payload.get('group'))
        labels = [p['label'] for p in payload['process']]
        self.assertNotIn('Nút sai XML', labels)
        self.assertTrue(payload['process'], 'Các nút hợp lệ vẫn hiện')
        btn.with_context(vas_ops_allow_write=True).unlink()

    def test_11_all_buttons_hidden_polite_message(self):
        group = self.Group.with_context(vas_ops_allow_write=True).create({
            'code': 'empty_test_%s' % fields.Datetime.now().strftime('%H%M%S'),
            'name': 'Nhóm trống test',
            'sequence': 999,
            'screen_kind': 'hub',
            'state': 'ready',
        })
        self.Button.with_context(vas_ops_allow_write=True).create({
            'group_id': group.id,
            'zone': 'process',
            'label': 'Toàn sai',
            'action_xmlid': 'connecta_vas.no_such_action_abc',
        })
        payload = self.Group.get_workflow_payload(group.code)
        self.assertEqual(payload['layout'], 'empty')
        self.assertTrue(payload['message'])
        self.assertFalse(payload['process'])
        group.with_context(vas_ops_allow_write=True).unlink()

    def test_12_business_user_cannot_mutate(self):
        """Chặn create/write/unlink ở tầng máy chủ — cả ba đường."""
        from odoo import Command
        user = self.env['res.users'].create({
            'name': 'VAS Ops Reader',
            'login': 'vas_ops_reader_%s' % fields.Datetime.now().strftime('%f'),
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        Group = self.Group.with_user(user)
        with self.assertRaises(AccessError):
            Group.create({
                'code': 'hack',
                'name': 'Hack',
                'screen_kind': 'hub',
                'state': 'temp',
            })
        with self.assertRaises(AccessError):
            self.cash.with_user(user).write({'name': 'Đổi tên'})
        with self.assertRaises(AccessError):
            self.env.ref('connecta_vas.vas_ops_btn_cash_in').with_user(user).unlink()

    def test_13_seed_stable_no_dup(self):
        """Nâng cấp / đọc lại seed: đúng 1 bản ghi theo xml id, không nhân đôi."""
        codes = self.Group.search([]).mapped('code')
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(self.env.ref('connecta_vas.vas_ops_group_cash'))
        self.assertTrue(self.env.ref('connecta_vas.vas_ops_btn_gen_b01a'))
        # Bốn lựa chọn BCTC là bốn bản ghi con
        parent = self.env.ref('connecta_vas.vas_ops_btn_gen_fs_parent')
        self.assertEqual(len(parent.child_ids), 4)
        # Chuỗi tổng hợp
        move = self.env.ref('connecta_vas.vas_ops_btn_gen_move')
        closing = self.env.ref('connecta_vas.vas_ops_btn_gen_closing')
        lock = self.env.ref('connecta_vas.vas_ops_btn_gen_lock')
        self.assertIn(closing, move.next_ids)
        self.assertIn(lock, closing.next_ids)
        self.assertIn(parent, lock.next_ids)

    def test_hub_tiles_hide_payroll_without_module(self):
        tiles = self.Group.get_hub_tiles()
        codes = {t['code'] for t in tiles}
        self.assertIn('cash', codes)
        self.assertIn('costing', codes)
        if not self.Group._module_installed('hr_payroll'):
            self.assertNotIn('payroll', codes)

    def test_current_period_filter_on_move_action(self):
        action = self.env.ref('connecta_vas.action_vas_move')
        self.assertTrue(action.context)
        self.assertIn('search_default_filter_current_period', action.context)

    def test_menu_four_roots(self):
        root = self.env.ref('connecta_vas.menu_connecta_vas_root')
        children = root.child_id.filtered(lambda m: m.active)
        names = set(children.mapped('name'))
        self.assertIn('Nghiệp vụ', names)
        self.assertIn('Sổ & Báo cáo', names)
        self.assertIn('Danh mục & Số dư đầu kỳ', names)
        self.assertIn('Cấu hình', names)
        self.assertNotIn('Cuối kỳ', names)
        # Folder Giá thành vẫn dưới Cấu hình
        costing = self.env.ref('connecta_vas.menu_vas_costing_root')
        self.assertEqual(costing.parent_id, self.env.ref('connecta_vas.menu_vas_config'))

    def test_l2_seven_ops_workflow_menus(self):
        ops = self.env.ref('connecta_vas.menu_vas_ops')
        names = set(ops.child_id.filtered(lambda m: m.active).mapped('name'))
        for label in (
            'Tiền mặt', 'Tiền gửi', 'Mua hàng', 'Bán hàng',
            'Kho', 'Tổng hợp', 'Sản xuất & Giá thành',
        ):
            self.assertIn(label, names)

    def test_l2_costing_config_only_three(self):
        root = self.env.ref('connecta_vas.menu_vas_costing_root')
        names = set(root.child_id.filtered(lambda m: m.active).mapped('name'))
        self.assertEqual(names, {
            'Cấu hình phân bổ',
            'TK xử lý vượt định mức',
            'Cấu hình kho giá thành',
        })
        for gone in (
            'menu_vas_opening_wip', 'menu_vas_closing_wip',
            'menu_vas_costing_period', 'menu_vas_allocation_run',
            'menu_vas_variance_sheet', 'menu_vas_cost_item',
            'menu_vas_cost_object',
        ):
            rec = self.env.ref('connecta_vas.%s' % gone, raise_if_not_found=False)
            self.assertFalse(rec and rec.active, gone)

    def test_l2_costing_eight_steps_variance_before_compute(self):
        group = self.env.ref('connecta_vas.vas_ops_group_costing')
        self.assertEqual(group.state, 'ready')
        self.assertEqual(group.screen_kind, 'workflow')
        payload = self.Group.get_workflow_payload('costing')
        self.assertEqual(payload['layout'], 'chain')
        labels = [p['label'] for p in payload['process']]
        self.assertEqual(labels, [
            'Dở dang đầu kỳ',
            'Tạo kỳ tính giá thành',
            'Lượt phân bổ chi phí chung',
            'Dở dang cuối kỳ',
            'Xử lý vượt định mức',
            'Tính giá thành',
            'Nhập kho thành phẩm',
            'Thẻ tính giá thành S18-DNN',
        ])
        self.assertFalse(payload['detached'])
        self.assertFalse(payload['report'])
        cat = [c['label'] for c in payload['catalog']]
        self.assertEqual(cat, ['Khoản mục chi phí', 'Đối tượng tập hợp chi phí'])
        for step in ('Tính giá thành', 'Nhập kho thành phẩm', 'Thẻ tính giá thành S18-DNN'):
            btn = next(p for p in payload['process'] if p['label'] == step)
            self.assertEqual(btn['action_xmlid'], 'connecta_vas.action_vas_costing_period')

    def test_l2_sale_chain_plus_detached_return(self):
        payload = self.Group.get_workflow_payload('sale')
        self.assertEqual(payload['layout'], 'chain')
        self.assertEqual([p['label'] for p in payload['process']], [
            'Báo giá', 'Đơn bán hàng', 'Xuất kho', 'Hóa đơn bán', 'Thu tiền',
        ])
        self.assertEqual([d['label'] for d in payload['detached']], ['Trả lại hàng bán'])
        inv = next(p for p in payload['process'] if p['label'] == 'Hóa đơn bán')
        self.assertEqual(inv['action_xmlid'], 'account.action_move_out_invoice_type')

    def test_l2_purchase_four_steps_no_return_tile(self):
        payload = self.Group.get_workflow_payload('purchase')
        self.assertEqual(payload['layout'], 'chain')
        self.assertEqual([p['label'] for p in payload['process']], [
            'Đơn mua hàng', 'Nhận hàng', 'Nhận hóa đơn', 'Trả tiền',
        ])
        self.assertFalse(payload['detached'])
        all_labels = (
            [p['label'] for p in payload['process']]
            + [d['label'] for d in payload['detached']]
        )
        self.assertTrue(all('Trả lại' not in lab for lab in all_labels))

    def test_l2_stock_and_bank_hub_no_chain(self):
        stock = self.Group.get_workflow_payload('stock')
        self.assertEqual(stock['layout'], 'tiles')
        self.assertIn('Nhập kho', [p['label'] for p in stock['process']])
        self.assertIn('Xuất kho', [p['label'] for p in stock['process']])
        self.assertIn('Chuyển kho', [p['label'] for p in stock['process']])
        bank = self.Group.get_workflow_payload('bank')
        self.assertEqual(bank['layout'], 'tiles')
        labels = [p['label'] for p in bank['process']]
        self.assertIn('Thu tiền', labels)
        self.assertIn('Chi tiền', labels)
        self.assertIn('Chuyển quỹ nội bộ', labels)
        # Đối chiếu NH: ẩn nếu chưa cài accountant
        if not self.Group._module_installed('account_accountant'):
            self.assertNotIn('Đối chiếu ngân hàng', labels)

    def test_l2_ready_groups_hub_tiles(self):
        tiles = self.Group.get_hub_tiles()
        by_code = {t['code']: t for t in tiles}
        for code in ('bank', 'purchase', 'sale', 'stock', 'costing'):
            self.assertEqual(by_code[code]['state'], 'ready')

    def test_l2_detached_does_not_break_chain(self):
        """Ô rời + chuỗi thẳng → layout chain, không unsupported."""
        payload = self.Group.get_workflow_payload('sale')
        self.assertNotEqual(payload['layout'], 'unsupported')
        self.assertTrue(payload['process'])
        self.assertTrue(payload['detached'])

    def test_l3_bank_reconcile_hidden_when_action_unregistered(self):
        """Lỗ 1: thiếu action accountant → ẩn Đối chiếu NH; nút khác vẫn hiện; VAS vẫn cài được."""
        vas = self.env['ir.module.module'].search(
            [('name', '=', 'connecta_vas')], limit=1,
        )
        self.assertEqual(vas.state, 'installed')
        self.assertNotIn(
            'account_accountant',
            vas.dependencies_id.mapped('depend_id.name'),
            'connecta_vas không được hard-depend account_accountant',
        )

        imd = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'account_accountant'),
            ('name', '=', 'action_bank_statement_line_transactions'),
        ], limit=1)
        if imd:
            # Giả lập accountant chưa cài: gỡ xmlid khỏi sổ đăng ký + xóa cache ref.
            imd.sudo().unlink()
            self.env.registry.clear_cache()

        self.assertFalse(
            self.Group._resolve_action_xmlid(
                'account_accountant.action_bank_statement_line_transactions',
            ),
            'Sau khi bỏ xmlid, action không còn tra được',
        )
        payload = self.Group.get_workflow_payload('bank')
        self.assertEqual(payload['layout'], 'tiles')
        labels = [p['label'] for p in payload['process']]
        self.assertNotIn('Đối chiếu ngân hàng', labels)
        self.assertIn('Thu tiền', labels)
        self.assertIn('Chi tiền', labels)
        self.assertIn('Chuyển quỹ nội bộ', labels)
        self.assertEqual(vas.state, 'installed')
