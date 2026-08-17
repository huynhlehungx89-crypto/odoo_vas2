# -*- coding: utf-8 -*-
"""W12 Chặng 1A — khoản mục, đối tượng, kỳ tính giá thành."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas', 'connecta_vas_w12_1a')
class TestW12Costing1A(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'Thông tư 133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.acc_154 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id),
            ('code', '=', '154'),
        ], limit=1)
        assert cls.acc_154, 'Thiếu vas.account 154'

        cls.CostItem = cls.env['vas.cost.item']
        cls.CostObject = cls.env['vas.cost.object']
        cls.Period = cls.env['vas.costing.period']

        # Seed có thể thuộc main_company khác env.company — bảo đảm có bản ghi hệ thống.
        cls._ensure_system_items()

    @classmethod
    def _ensure_system_items(cls):
        seeds = [
            ('NVLTT', 'Nguyên vật liệu trực tiếp', 'material'),
            ('NCTT', 'Nhân công trực tiếp', 'labor'),
            ('CPC', 'Chi phí sản xuất chung', 'other'),
            ('CPD', 'Chưa phân loại', 'other'),
        ]
        for code, name, factor in seeds:
            item = cls.CostItem.search([
                ('code', '=', code),
                ('company_id', '=', cls.company.id),
            ], limit=1)
            if item:
                continue
            # Tạo bản ghi + gắn ir.model.data để đi đúng khuôn bảo vệ seed.
            item = cls.CostItem.create({
                'code': code,
                'name': name,
                'factor_group': factor,
                'account_id': cls.acc_154.id,
                'company_id': cls.company.id,
                'is_system': True,
            })
            cls.env['ir.model.data'].create({
                'name': 'test_vas_cost_item_%s_%s' % (code.lower(), cls.company.id),
                'module': 'connecta_vas',
                'model': 'vas.cost.item',
                'res_id': item.id,
                'noupdate': True,
            })

    def _system_item(self, code):
        return self.CostItem.search([
            ('code', '=', code),
            ('company_id', '=', self.company.id),
        ], limit=1)

    def _make_product(self, name='SP GT', company=None):
        company = company or self.company
        return self.env['product.product'].create({
            'name': name,
            'default_code': 'GT-%s' % name[:8],
            'company_id': company.id,
            'is_storable': True,
        })

    def _make_object(self, code, object_type='workshop', **extra):
        vals = {
            'code': code,
            'name': extra.pop('name', code),
            'object_type': object_type,
            'wip_account_id': self.acc_154.id,
            'company_id': self.company.id,
        }
        vals.update(extra)
        return self.CostObject.create(vals)

    # ---- khoản mục ------------------------------------------------------

    def test_cost_item_parent_cycle_blocked(self):
        a = self.CostItem.create({
            'code': 'CI-A', 'name': 'A',
            'factor_group': 'material',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        b = self.CostItem.create({
            'code': 'CI-B', 'name': 'B',
            'factor_group': 'material',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
            'parent_id': a.id,
        })
        with self.assertRaises(ValidationError):
            a.parent_id = b

    def test_factor_group_required_on_leaf_optional_on_aggregate(self):
        with self.assertRaises(ValidationError):
            self.CostItem.create({
                'code': 'CI-LEAF', 'name': 'Lá thiếu yếu tố',
                'account_id': self.acc_154.id,
                'company_id': self.company.id,
            })
        parent = self.CostItem.create({
            'code': 'CI-P', 'name': 'Cha',
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        self.CostItem.create({
            'code': 'CI-C', 'name': 'Con',
            'factor_group': 'material',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
            'parent_id': parent.id,
        })
        parent.invalidate_recordset()
        self.assertTrue(parent.is_aggregate_node)
        parent.factor_group = False  # nút tổng hợp để trống được

    def test_system_seed_protect_rename_ok(self):
        nvltt = self._system_item('NVLTT')
        self.assertTrue(nvltt)
        nvltt.name = 'NVLTT đổi tên'
        self.assertEqual(nvltt.name, 'NVLTT đổi tên')
        with self.assertRaises(UserError):
            nvltt.code = 'NVLTT2'
        with self.assertRaises(UserError):
            nvltt.is_system = False
        with self.assertRaises(UserError):
            nvltt.unlink()

    def test_customer_item_edit_unlink_ok(self):
        item = self.CostItem.create({
            'code': 'CI-CUST', 'name': 'Khách',
            'factor_group': 'outsourced',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        item.name = 'Khách sửa'
        item.unlink()

    def test_unlink_cost_item_with_child_vietnamese(self):
        parent = self.CostItem.create({
            'code': 'CI-UP', 'name': 'Cha xóa',
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        self.CostItem.create({
            'code': 'CI-UC', 'name': 'Con',
            'factor_group': 'material',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
            'parent_id': parent.id,
        })
        with self.assertRaises(UserError) as err:
            parent.unlink()
        self.assertIn('Không xóa được khoản mục', str(err.exception))
        self.assertNotIn('ForeignKeyViolation', str(err.exception))

    # ---- đối tượng / nguồn nối -----------------------------------------

    def test_cost_object_parent_cycle_blocked(self):
        a = self._make_object('OBJ-A')
        b = self._make_object('OBJ-B')
        # Cặp workshop–workshop không nằm trong ma trận → chặn trước vòng lặp.
        with self.assertRaises(ValidationError):
            b.parent_id = a
        # Vòng lặp tường minh trên cặp được mở (nếu có mrp).
        if not self.CostObject._mrp_available():
            return
        process = self._make_object('PR-A', object_type='process')
        op1 = self._make_object(
            'OP-A', object_type='operation', parent_id=process.id,
        )
        with self.assertRaises(ValidationError):
            process.parent_id = op1

    def test_parent_matrix_process_operation_only(self):
        ws1 = self._make_object('WS-1')
        ws2 = self._make_object('WS-2')
        with self.assertRaises(ValidationError):
            ws2.parent_id = ws1
        prod = self._make_object('TP-1', object_type='product')
        with self.assertRaises(ValidationError):
            ws1.parent_id = prod
        if not self.CostObject._mrp_available():
            return
        process = self._make_object('QT-1', object_type='process')
        op = self._make_object(
            'CD-1', object_type='operation', parent_id=process.id,
        )
        self.assertEqual(op.parent_id, process)

    def test_source_wrong_company_blocked(self):
        other = self.env['res.company'].search([
            ('id', '!=', self.company.id),
        ], limit=1)
        if not other:
            vnd = self.env.ref('base.VND')
            other = self.env['res.company'].create({
                'name': 'Công ty GT khác',
                'currency_id': vnd.id,
            })
        product = self._make_product('SP khác CT', company=other)
        with self.assertRaises(ValidationError):
            self._make_object(
                'TP-CO',
                object_type='product',
                source_model='product.product',
                source_res_id=product.id,
            )

    def test_source_wrong_model_blocked(self):
        partner = self.env['res.partner'].create({'name': 'Nguồn sai bảng'})
        with self.assertRaises(ValidationError):
            self._make_object(
                'TP-WM',
                object_type='product',
                source_model='res.partner',
                source_res_id=partner.id,
            )

    def test_source_duplicate_blocked(self):
        product = self._make_product('SP trùng')
        self._make_object(
            'TP-D1',
            object_type='product',
            source_model='product.product',
            source_res_id=product.id,
        )
        with self.assertRaises(ValidationError):
            self._make_object(
                'TP-D2',
                object_type='product',
                source_model='product.product',
                source_res_id=product.id,
            )

    def test_source_orphan_keeps_snapshot_and_filterable(self):
        product = self._make_product('SP mồ côi')
        obj = self._make_object(
            'TP-OR',
            object_type='product',
            source_model='product.product',
            source_res_id=product.id,
        )
        snapshot = obj.source_label_snapshot
        self.assertTrue(snapshot)
        self.assertEqual(obj.source_status, 'alive')
        # Xóa nguồn ở tầng SQL để tránh cascade nghiệp vụ product.
        self.env.cr.execute(
            'DELETE FROM product_product WHERE id = %s',
            [product.id],
        )
        self.env.invalidate_all()
        obj.action_sync_catalog_check()
        self.assertEqual(obj.source_status, 'orphan')
        self.assertEqual(obj.source_label_snapshot, snapshot)
        found = self.CostObject.search([
            ('source_status', '=', 'orphan'),
            ('id', '=', obj.id),
        ])
        self.assertEqual(found, obj)
        self.assertTrue(found.source_label_snapshot)

    def test_mrp_types_hidden_when_unavailable(self):
        selection = dict(self.CostObject._selection_object_type())
        if self.CostObject._mrp_available():
            self.assertIn('operation', selection)
            self.assertIn('process', selection)
        else:
            self.assertNotIn('operation', selection)
            self.assertNotIn('process', selection)

    # ---- kỳ tính giá thành ---------------------------------------------

    def test_period_overlap_same_object_blocked(self):
        obj = self._make_object('WS-OV')
        self.Period.create({
            'name': 'Kỳ A',
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [(6, 0, obj.ids)],
        })
        with self.assertRaises(ValidationError):
            self.Period.create({
                'name': 'Kỳ B',
                'date_from': '2026-01-15',
                'date_to': '2026-02-15',
                'method': 'simple',
                'company_id': self.company.id,
                'cost_object_ids': [(6, 0, obj.ids)],
            })

    def test_period_overlap_different_objects_allowed(self):
        a = self._make_object('WS-OA')
        b = self._make_object('WS-OB')
        self.Period.create({
            'name': 'Kỳ A',
            'date_from': '2026-03-01',
            'date_to': '2026-03-31',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [(6, 0, a.ids)],
        })
        other = self.Period.create({
            'name': 'Kỳ B',
            'date_from': '2026-03-15',
            'date_to': '2026-04-15',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [(6, 0, b.ids)],
        })
        self.assertTrue(other)

    def test_period_overlap_different_method_still_blocked(self):
        """Chồng kỳ khác phương pháp vẫn bị chặn (quyết định 19)."""
        obj = self._make_object('WS-OM')
        p1 = self.Period.create({
            'name': 'Kỳ M1',
            'date_from': '2026-05-01',
            'date_to': '2026-05-31',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [(6, 0, obj.ids)],
        })
        # Tạo kỳ thứ hai giản đơn rồi ép method=stepwise ở SQL (app chặn tạo phân bước).
        p2 = self.Period.create({
            'name': 'Kỳ M2',
            'date_from': '2026-06-01',
            'date_to': '2026-06-30',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [(6, 0, obj.ids)],
        })
        self.env.cr.execute(
            "UPDATE vas_costing_period SET method = 'stepwise' WHERE id = %s",
            [p2.id],
        )
        self.env.invalidate_all()
        # Đưa khoảng ngày chồng nhau → ràng buộc phải chặn dù khác phương pháp.
        with self.assertRaises(ValidationError):
            p1.write({
                'date_to': '2026-06-15',
            })
        # Tạo kỳ phân bước chạy thật vẫn bị chặn ở tầng app.
        with self.assertRaises(UserError):
            self.Period.create({
                'name': 'Kỳ M3 phân bước',
                'date_from': '2026-07-01',
                'date_to': '2026-07-31',
                'method': 'stepwise',
                'company_id': self.company.id,
                'cost_object_ids': [(6, 0, obj.ids)],
            })

    def test_stepwise_period_blocked(self):
        with self.assertRaises(UserError):
            self.Period.create({
                'name': 'Phân bước',
                'date_from': '2026-06-01',
                'date_to': '2026-06-30',
                'method': 'stepwise',
                'company_id': self.company.id,
            })

    def test_edit_objects_only_in_draft(self):
        obj = self._make_object('WS-ED')
        period = self.Period.create({
            'name': 'Kỳ sửa',
            'date_from': '2026-07-01',
            'date_to': '2026-07-31',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [(6, 0, obj.ids)],
        })
        other = self._make_object('WS-ED2')
        period.cost_object_ids = [(4, other.id)]
        period.state = 'computed'
        with self.assertRaises(UserError) as err:
            period.cost_object_ids = [(3, other.id)]
        self.assertIn('Nháp', str(err.exception))
        self.assertIn('Đã tính', str(err.exception))

    def test_unlink_object_used_in_period_vietnamese(self):
        obj = self._make_object('WS-DEL')
        self.Period.create({
            'name': 'Kỳ giữ đối tượng',
            'date_from': '2026-08-01',
            'date_to': '2026-08-31',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [(6, 0, obj.ids)],
        })
        with self.assertRaises(UserError) as err:
            obj.unlink()
        msg = str(err.exception)
        self.assertIn('Không xóa được đối tượng', msg)
        self.assertIn('kỳ tính giá thành', msg.lower())
        self.assertNotIn('ForeignKeyViolation', msg)
