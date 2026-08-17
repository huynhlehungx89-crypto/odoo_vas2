# -*- coding: utf-8 -*-
"""W12 Chặng 3 — trọn luồng tính giá thành (CP1–CP7)."""
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_is_zero


@tagged('connecta_vas', 'connecta_vas_w12_3')
class TestW12CostingStage3(TransactionCase):

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
                'name': 'W12-3-2099', 'date_from': '2099-01-01',
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

    def _obj(self, code, **extra):
        vals = {
            'code': code, 'name': code, 'object_type': 'workshop',
            'company_id': self.company.id, 'wip_account_id': self.acc_154.id,
        }
        vals.update(extra)
        return self.CostObject.create(vals)

    def _config(self, factors, sequence=1, scope_type='company',
                scope_object=None, date_from='2099-03-01', date_to='2099-03-31'):
        cfg = self.env['vas.allocation.config'].create({
            'company_id': self.company.id,
            'cost_item_id': self.cpc.id,
            'scope_type': scope_type,
            'scope_object_id': scope_object.id if scope_object else False,
            'criterion': 'manual_factor',
            'sequence': sequence,
            'date_from': date_from,
            'date_to': date_to,
        })
        for obj, factor in factors:
            self.env['vas.allocation.config.factor'].create({
                'config_id': cfg.id, 'cost_object_id': obj.id, 'factor': factor,
            })
        return cfg

    def _source_move(self, amount, date='2099-03-15', cost_item=None, object=None):
        cost_item = cost_item or self.cpc
        debit = amount if amount > 0 else 0.0
        credit = -amount if amount < 0 else 0.0
        if amount < 0:
            debit, credit = 0.0, abs(amount)
            lines = [
                Command.create({
                    'account_id': self.acc_111.id, 'name': 'hoan',
                    'debit': abs(amount), 'credit': 0.0,
                    'currency_id': self.company.currency_id.id,
                }),
                Command.create({
                    'account_id': self.acc_154.id, 'name': 'chung',
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
            'ref': 'W12-3', 'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': lines,
        })
        move.action_post()
        return move

    def _run(self, **extra):
        vals = {
            'name': 'PB3', 'company_id': self.company.id,
            'date_from': '2099-03-01', 'date_to': '2099-03-31',
            'cost_item_id': self.cpc.id, 'scope_type': 'company',
            'round_number': '1', 'money_source': 'pool_154', 'state': 'draft',
        }
        vals.update(extra)
        return self.env['vas.allocation.run'].create(vals)

    def _period(self, objects, **extra):
        vals = {
            'name': 'Kỳ 03/2099', 'date_from': '2099-03-01',
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

    def _balance_154(self):
        lines = self.env['vas.move.line'].search([
            ('company_id', '=', self.company.id),
            ('account_id', '=', self.acc_154.id),
            ('move_id.state', '=', 'posted'),
        ])
        return sum(l.debit - l.credit for l in lines)

    def _wizard_from_action(self, action, reason):
        """Mô phỏng nút UI: mở wizard rồi xác nhận với lý do."""
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertEqual(action.get('res_model'), 'vas.costing.reason.wizard')
        wiz = self.env['vas.costing.reason.wizard'].with_context(
            **action.get('context', {}),
        ).create({'reason': reason})
        return wiz.action_confirm()

    def _system_item(self, code, name, factor_group):
        item = self.CostItem.search([
            ('code', '=', code), ('company_id', '=', self.company.id),
        ], limit=1)
        if not item:
            item = self.CostItem.create({
                'code': code, 'name': name, 'factor_group': factor_group,
                'account_id': self.acc_154.id, 'company_id': self.company.id,
                'is_system': True,
            })
        return item

    # ===================== CP1 B1 / B2 =====================

    def test_b1_two_scopes_second_confirm_blocked(self):
        a = self._obj('B1A')
        proc = self._obj('PROC', object_type='process')
        self._config([(a, 1)], scope_type='company')
        # Phạm vi process phải có đối tượng nhận trong phạm vi (chính proc)
        self._config(
            [(proc, 1)], scope_type='process', scope_object=proc,
        )
        self._source_move(100)
        run1 = self._run(name='R-company', scope_type='company')
        run1.action_compute()
        run1.action_confirm()
        run2 = self._run(
            name='R-process', scope_type='process', scope_object_id=proc.id,
        )
        run2.action_compute()
        self.assertTrue(run2.compute_ok)
        with self.assertRaises(UserError) as err:
            run2.action_confirm()
        self.assertIn('B1', str(err.exception))

    def test_b1_negative_full_allocation(self):
        a = self._obj('NEG1')
        self._config([(a, 1)])
        self._source_move(-90)
        run = self._run(name='NEG-full')
        run.action_compute()
        run.action_confirm()
        self.assertEqual(run.amount_allocated, -90.0)

    def test_b1_negative_partial_allocation(self):
        """Nguồn âm — phân bổ một phần: |allocated| < |source|, xác nhận OK."""
        a = self._obj('NEGPART')
        self._config([(a, 1)])
        self._source_move(-90)
        run = self._run(name='NEG-part')
        run.action_compute()
        self.assertEqual(run.amount_allocated, -90.0)
        run.trace_ids.write({'amount': -40.0})
        run.result_ids.write({'amount': -40.0})
        run.write({
            'amount_allocated': -40.0,
            'amount_unallocated': -50.0,
            'compute_ok': True,
        })
        run.action_confirm()
        self.assertEqual(run.state, 'confirmed')
        self.assertEqual(sum(run.trace_ids.mapped('amount')), -40.0)
        self.assertEqual(run.amount_allocated, -40.0)

    def test_b1_negative_over_ceiling_blocked(self):
        a = self._obj('NEG2')
        proc = self._obj('NEGP', object_type='process')
        self._config([(a, 1)])
        self._config([(proc, 1)], scope_type='process', scope_object=proc)
        self._source_move(-50)
        run1 = self._run(name='N1')
        run1.action_compute()
        run1.action_confirm()
        run2 = self._run(
            name='N2', scope_type='process', scope_object_id=proc.id,
        )
        run2.action_compute()
        with self.assertRaises(UserError):
            run2.action_confirm()

    def test_b1_opposite_sign_blocked(self):
        a = self._obj('SIGN')
        self._config([(a, 1)])
        self._source_move(100)
        run = self._run(name='S1')
        run.action_compute()
        # Đảo dấu đóng góp truy vết
        run.trace_ids.write({'amount': -10})
        with self.assertRaises(UserError) as err:
            run.action_confirm()
        self.assertIn('dấu', str(err.exception).lower())

    def test_partial_allocation_trace_grid_passes(self):
        a = self._obj('PART')
        self._config([(a, 1)])
        move = self._source_move(100)
        src = move.line_ids.filtered('cost_item_id')[:1]
        run = self._run(name='PARTIAL')
        run.action_compute()
        # Giả lập phân bổ một phần: giảm trace
        for tr in run.trace_ids:
            tr.amount = 40.0
        run.amount_unallocated = 60.0
        run.compute_ok = True
        run._assert_trace_balance(
            [(src, 100.0)], run.currency_id.rounding, full_allocation=False,
        )

    def test_zero_denom_trace_grid_passes(self):
        a = self._obj('ZD')
        self._config([(a, 0)])
        self._source_move(55)
        run = self._run(name='ZD')
        run.action_compute()
        self.assertFalse(run.compute_ok)
        self.assertEqual(run.amount_unallocated, 55.0)
        # Không có trace — đẳng thức ở mức run
        self.assertEqual(
            run.amount_allocated + run.amount_unallocated, run.amount_source,
        )

    def test_draft_version_does_not_release_ceiling(self):
        a = self._obj('VER1')
        proc = self._obj('VERP', object_type='process')
        self._config([(a, 1)])
        self._config([(proc, 1)], scope_type='process', scope_object=proc)
        self._source_move(100)
        run1 = self._run(name='VOLD')
        run1.action_compute()
        run1.action_confirm()
        action = run1.action_new_version()
        draft = self.env['vas.allocation.run'].browse(action['res_id'])
        self.assertEqual(draft.state, 'draft')
        self.assertEqual(run1.state, 'confirmed')
        run_other = self._run(
            name='OTHER', scope_type='process', scope_object_id=proc.id,
        )
        run_other.action_compute()
        with self.assertRaises(UserError):
            run_other.action_confirm()

    def test_version_replace_failed_keeps_old_ceiling(self):
        a = self._obj('ATOM')
        proc = self._obj('ATOMP', object_type='process')
        self._config([(a, 1)])
        self._config([(proc, 1)], scope_type='process', scope_object=proc)
        self._source_move(100)
        run1 = self._run(name='ATOM1')
        run1.action_compute()
        run1.action_confirm()
        action = run1.action_new_version()
        draft = self.env['vas.allocation.run'].browse(action['res_id'])
        draft.action_compute()
        draft.trace_ids.write({'amount': -1})
        with self.assertRaises(UserError):
            draft.action_confirm()
        self.assertEqual(run1.state, 'confirmed')
        run_x = self._run(
            name='X', scope_type='process', scope_object_id=proc.id,
        )
        run_x.action_compute()
        with self.assertRaises(UserError):
            run_x.action_confirm()

    def test_unreceive_does_not_release_ceiling(self):
        a = self._obj('UR1')
        proc = self._obj('URP', object_type='process')
        self._config([(a, 1)])
        self._config([(proc, 1)], scope_type='process', scope_object=proc)
        self._source_move(80)
        run = self._run(name='UR')
        run.action_compute()
        run.action_confirm()
        period = self._period([a])
        period.action_receive_allocation(result_ids=run.result_ids.ids)
        period.action_unreceive_allocation(reason='test')
        self.assertFalse(run.result_ids.receiving_period_ids)
        run2 = self._run(
            name='UR2', scope_type='process', scope_object_id=proc.id,
        )
        run2.action_compute()
        with self.assertRaises(UserError):
            run2.action_confirm()

    def test_b2_parent_params_and_happy(self):
        a = self._obj('B2A')
        self._config([(a, 1)], sequence=1)
        self._config([(a, 1)], sequence=2)
        self._source_move(100)
        run1 = self._run(name='B2R1')
        run1.action_compute()
        run1.action_confirm()
        # Happy
        run2 = self._run(
            name='B2R2', round_number='2', money_source='prior_round',
            parent_run_id=run1.id,
        )
        run2.action_compute()
        run2.action_confirm()
        # Sai công ty
        other_co = self.env['res.company'].create({'name': 'OtherCo W12'})
        with self.assertRaises(ValidationError):
            self._run(
                name='bad-co', round_number='2', money_source='prior_round',
                parent_run_id=run1.id, company_id=other_co.id,
            )
        # Vòng 2 + pool_154
        with self.assertRaises(ValidationError):
            self._run(
                name='bad-src', round_number='2', money_source='pool_154',
                parent_run_id=run1.id,
            )

    def test_b2_parent_not_immediate_round(self):
        a = self._obj('B2X')
        self._config([(a, 1)], sequence=1)
        self._config([(a, 1)], sequence=2)
        self._source_move(10)
        run1 = self._run(name='R1x')
        run1.action_compute()
        run1.action_confirm()
        r2 = self._run(
            name='R2x', round_number='2', money_source='prior_round',
            parent_run_id=run1.id,
        )
        r2.action_compute()
        r2.action_confirm()
        with self.assertRaises(ValidationError):
            self._run(
                name='R3bad', round_number='2', money_source='prior_round',
                parent_run_id=r2.id,
            )

    def test_b1_3_lock_order_code_present(self):
        """Bằng chứng kỹ thuật: có khóa FOR UPDATE theo id tăng dần."""
        import inspect
        from odoo.addons.connecta_vas.models.vas_allocation_run import VasAllocationRun
        src = inspect.getsource(VasAllocationRun._lock_source_rows)
        self.assertIn('FOR UPDATE', src)
        self.assertIn('ORDER BY id', src)

    def test_receive_only_draft_and_one_period(self):
        a = self._obj('RECV')
        self._config([(a, 1)])
        self._source_move(50)
        run = self._run(name='RECV')
        run.action_compute()
        run.action_confirm()
        p1 = self._period([a], name='P1')
        p2 = self._period([a], name='P2', date_from='2099-04-01', date_to='2099-04-30')
        p1.action_receive_allocation(result_ids=run.result_ids.ids)
        with self.assertRaises(UserError):
            p2.action_receive_allocation(result_ids=run.result_ids.ids)
        # Nhận khi đã tính
        self._closing_confirm(p1, {a: 0})
        p1.action_compute_costing()
        with self.assertRaises(UserError) as err:
            p1.action_receive_allocation()
        self.assertIn('Nháp', str(err.exception))

    # ===================== CP2 =====================

    def test_opening_four_groups_and_excel(self):
        a = self._obj('OW1')
        # Trực tiếp nhóm A → nhóm 1
        self._source_move(100, object=a, cost_item=self.cpc)
        # Chung chưa đối tượng + phân bổ → nhóm 4
        self._config([(a, 1)])
        self._source_move(40)
        run = self._run(name='OW')
        run.action_compute()
        run.action_confirm()
        # Unallocated → nhóm 3
        b_obj = self._obj('OW0')
        nvl = self._system_item('NVLTT', 'NVL', 'material')
        self.env['vas.allocation.config'].create({
            'company_id': self.company.id, 'cost_item_id': nvl.id,
            'scope_type': 'company', 'criterion': 'manual_factor',
            'sequence': 1, 'date_from': '2099-03-01', 'date_to': '2099-03-31',
            'factor_ids': [Command.create({'cost_object_id': b_obj.id, 'factor': 0})],
        })
        self._source_move(25, cost_item=nvl)
        run_u = self._run(name='OWU', cost_item_id=nvl.id)
        run_u.action_compute()
        run_u.action_confirm()
        # Nhóm B trên 154 (không vào g1) → khớp g2 khai tay
        proj = self._obj('OWB', object_type='project')
        self._source_move(10, object=proj, cost_item=self.cpc)

        sheet = self.env['vas.opening.wip'].create({
            'name': 'OW test', 'date': '2099-03-31',
            'company_id': self.company.id, 'group_b_manual_amount': 10.0,
            'detail_level': 'total',
        })
        rows = ['object_code,cost_item_code,amount']
        for i in range(200):
            o = self._obj('E%03d' % i)
            rows.append('%s,,1' % o.code)
        n = sheet.action_import_csv('\n'.join(rows))
        self.assertEqual(n, 200)
        self.assertEqual(sum(sheet.line_ids.mapped('amount')), 200.0)

        g1, g2, g3, g4, bal, diff = sheet._compute_four_groups()
        self.assertNotEqual(g1, 0.0)
        self.assertEqual(g2, 10.0)
        self.assertEqual(g3, 25.0)
        self.assertEqual(g4, 40.0)
        self.assertEqual(diff, 0.0, 'g1=%s g2=%s g3=%s g4=%s bal=%s' % (
            g1, g2, g3, g4, bal,
        ))
        period = self._period([a])
        period.action_receive_allocation(result_ids=run.result_ids.ids)
        g4_before = sheet._compute_four_groups()[3]
        action = period.action_unreceive_allocation()
        self._wizard_from_action(action, 'mở nhóm 4')
        g4_after = sheet._compute_four_groups()[3]
        self.assertAlmostEqual(
            g4_after - g4_before, sum(run.result_ids.mapped('amount')),
        )

    # ===================== CP3–CP7 e2e =====================

    def test_e2e_costing_flow_and_s18(self):
        """Ca nghiệm thu xuyên suốt 7b — báo số từng bước."""
        steps = {}
        a = self._obj('E2E1')
        b = self._obj('E2E2')
        # 1. Dở dang đầu kỳ
        steps['opening'] = 200_000.0
        # 2. Trực tiếp
        self._source_move(300_000, object=a)
        steps['direct'] = 300_000.0
        # 3. Chung + phân bổ
        self._config([(a, 1), (b, 1)])
        self._source_move(100_000)
        run = self._run(name='E2E-PB')
        run.action_compute()
        run.action_confirm()
        steps['allocated'] = run.amount_allocated
        # 4. Kỳ nhận
        period = self._period([a, b], opening_wip=steps['opening'])
        period.action_receive_allocation(result_ids=run.result_ids.ids)
        steps['received'] = sum(run.result_ids.mapped('amount_received'))
        # Phần chưa nhận = 0 vì nhận hết
        # 5. Giảm 500k
        self._source_move(-500_000, object=a)  # credit 154
        # Wait - negative helper posts credit on 154 — good reduction
        steps['reduction'] = 500_000.0
        # Fix: _source_move(-500000) creates credit 500000 on 154 — yes
        # 6. Closing confirm
        # Chi phí còn lại tạm closing = 50k mỗi đối tượng
        sheet = self._closing_confirm(period, {a: 30_000.0, b: 20_000.0})
        steps['closing'] = sheet.total_confirmed()
        # 7. Tính
        period.action_compute_costing()
        ver = period.current_result_id
        steps['total'] = ver.total_cost
        # Công thức: opening + direct_debit + overhead - reduction - closing
        # direct_debit includes only debits; reduction separate
        expected = (
            steps['opening'] + 300_000 + steps['allocated']
            - steps['reduction'] - steps['closing']
        )
        self.assertEqual(ver.total_cost, expected)
        # 8. Duyệt + ghi sổ
        period.action_submit_approval()
        period.action_approve()
        period.action_post_costing()
        self.assertEqual(period.state, 'posted')
        move = period.posting_move_id
        line_155 = move.line_ids.filtered(lambda l: l.account_id == self.acc_155)
        self.assertEqual(line_155.debit, expected)
        # S18
        self.assertEqual(ver.opening_wip, steps['opening'])
        self.assertEqual(ver.closing_wip, steps['closing'])
        # B3 double post
        with self.assertRaises(UserError) as err:
            period.action_post_costing()
        self.assertIn('B3', str(err.exception))
        # Phân bổ 3 lần — số dư 154 không đổi một đồng
        bal_before = self._balance_154()
        for i in range(3):
            r = self._run(name='E2E-PB-RERUN-%s' % i)
            r.action_compute()
            self.assertEqual(r.amount_source, 100_000)
        bal_after = self._balance_154()
        self.assertEqual(bal_before, bal_after)
        self.assertEqual(run.amount_source, 100_000)
        # Store for report
        self.env['ir.config_parameter'].sudo().set_param(
            'connecta_vas.w12_3_e2e_steps', str(steps),
        )
        # Mở thẻ S18 đúng đường nút
        action_s18 = period.action_open_s18()
        self.assertEqual(action_s18.get('res_model'), 'vas.costing.result.version')
        self.assertEqual(action_s18.get('res_id'), ver.id)

    def test_closing_adjustment_and_regen(self):
        a = self._obj('CL1')
        period = self._period([a])
        sheet = self.env['vas.closing.wip'].create({
            'name': 'CL', 'kind': 'period_end', 'period_id': period.id,
            'company_id': self.company.id,
        })
        line = self.env['vas.closing.wip.line'].create({
            'sheet_id': sheet.id, 'cost_object_id': a.id,
            'amount_suggested': 100, 'amount_adjustment': 0,
        })
        line.write({'amount_adjustment': 20, 'reason_adjustment': 'điều chỉnh'})
        self.assertEqual(line.amount_confirmed, 120)
        with self.assertRaises(ValidationError):
            line.write({'amount_adjustment': 5, 'reason_adjustment': False})
        sheet.state = 'pending_confirm'
        sheet.action_confirm()
        confirmed = line.amount_confirmed
        sheet.action_regen_suggestion()
        self.assertEqual(line.amount_confirmed, confirmed)
        self.assertEqual(sheet.state, 'needs_review')

    def test_compute_blocked_when_closing_pending(self):
        a = self._obj('CP')
        period = self._period([a])
        sheet = self.env['vas.closing.wip'].create({
            'name': 'pending', 'kind': 'period_end', 'period_id': period.id,
            'company_id': self.company.id, 'state': 'pending_confirm',
        })
        with self.assertRaises(UserError) as err:
            period.action_compute_costing()
        self.assertIn(sheet.name, str(err.exception))

    def test_fingerprint_stable_and_name_ignored(self):
        a = self._obj('FP1')
        self._source_move(10, object=a)
        period = self._period([a], opening_wip=0)
        self._closing_confirm(period, {a: 0})
        period.action_compute_costing()
        fp1 = period.current_result_id.fingerprint
        # Đổi tên đối tượng — không đổi dấu vân tay
        a.name = 'Tên mới đẹp'
        fp2, _ = period._compute_fingerprint()
        self.assertEqual(fp1, fp2)
        # Đảo thứ tự bản ghi thật — hash hai lần phải bằng nhau
        rows = period._fingerprint_payload_rows()
        d1, _ = period._fingerprint_digest_from_rows(list(rows))
        d2, _ = period._fingerprint_digest_from_rows(list(reversed(list(rows))))
        self.assertEqual(d1, d2)
        self.assertEqual(d1, fp1)

    def test_fingerprint_changes_on_amount(self):
        a = self._obj('FP2')
        move = self._source_move(10, object=a)
        period = self._period([a])
        self._closing_confirm(period, {a: 0})
        period.action_compute_costing()
        fp1 = period.current_result_id.fingerprint
        # Thêm bút toán mới đổi số
        self._source_move(5, object=a)
        fp2, _ = period._compute_fingerprint()
        self.assertNotEqual(fp1, fp2)

    def test_post_conditions_and_reject_reason(self):
        a = self._obj('PC1')
        self._source_move(100, object=a)
        period = self._period([a], opening_wip=0)
        self._closing_confirm(period, {a: 0})
        period.action_compute_costing()
        period.action_submit_approval()
        # Nút Từ chối → wizard; lý do trống bị chặn
        action = period.action_reject()
        wiz = self.env['vas.costing.reason.wizard'].with_context(
            **action['context'],
        ).create({'reason': ''})
        with self.assertRaises(UserError):
            wiz.action_confirm()
        self._wizard_from_action(action, 'sai số')
        self.assertEqual(period.state, 'computed')

        # Lưới đối tượng–thành phẩm: cố tình lệch → chặn ghi sổ
        period.action_submit_approval()
        period.action_approve()
        line = period.current_result_id.line_ids[:1]
        line.write({'amount_delivered': line.total_cost - 7.0, 'amount_undelivered': 0.0})
        with self.assertRaises(UserError) as err:
            period.action_post_costing()
        self.assertIn('7', str(err.exception))
        self.assertIn('điều kiện 2', str(err.exception).lower())

    def test_object_list_blocked_when_computed(self):
        a = self._obj('OL1')
        b = self._obj('OL2')
        period = self._period([a])
        self._closing_confirm(period, {a: 0})
        period.action_compute_costing()
        with self.assertRaises(UserError):
            period.write({'cost_object_ids': [Command.link(b.id)]})

    def test_opening_detail_levels_three(self):
        a = self._obj('DL1')
        nvl = self._system_item('NVLTT', 'NVL', 'material')
        nc = self._system_item('NCTT', 'NC', 'labor')
        cpc = self.cpc
        # total
        sheet_t = self.env['vas.opening.wip'].create({
            'name': 'DL-total', 'date': '2099-03-31',
            'company_id': self.company.id, 'detail_level': 'total',
            'line_ids': [Command.create({
                'cost_object_id': a.id, 'amount': 100.0,
            })],
        })
        sheet_t.action_validate_detail_level()
        self.assertEqual(sheet_t.amount_total_by_object()[a], 100.0)
        # root3
        sheet_r = self.env['vas.opening.wip'].create({
            'name': 'DL-root3', 'date': '2099-03-31',
            'company_id': self.company.id, 'detail_level': 'root3',
            'line_ids': [
                Command.create({
                    'cost_object_id': a.id, 'cost_item_id': nvl.id, 'amount': 40.0,
                }),
                Command.create({
                    'cost_object_id': a.id, 'cost_item_id': nc.id, 'amount': 35.0,
                }),
                Command.create({
                    'cost_object_id': a.id, 'cost_item_id': cpc.id, 'amount': 25.0,
                }),
            ],
        })
        sheet_r.action_validate_detail_level()
        self.assertEqual(sheet_r.amount_total_by_object()[a], 100.0)
        # full — leaf item
        sheet_f = self.env['vas.opening.wip'].create({
            'name': 'DL-full', 'date': '2099-03-31',
            'company_id': self.company.id, 'detail_level': 'full',
            'line_ids': [
                Command.create({
                    'cost_object_id': a.id, 'cost_item_id': nvl.id, 'amount': 70.0,
                }),
                Command.create({
                    'cost_object_id': a.id, 'cost_item_id': cpc.id, 'amount': 30.0,
                }),
            ],
        })
        sheet_f.action_validate_detail_level()
        self.assertEqual(sheet_f.amount_total_by_object()[a], 100.0)
        # total sai: gắn khoản mục → chặn
        sheet_bad = self.env['vas.opening.wip'].create({
            'name': 'DL-bad', 'date': '2099-03-31',
            'company_id': self.company.id, 'detail_level': 'total',
            'line_ids': [Command.create({
                'cost_object_id': a.id, 'cost_item_id': nvl.id, 'amount': 1.0,
            })],
        })
        with self.assertRaises(UserError):
            sheet_bad.action_validate_detail_level()

    def test_e2e_costing_flow_distinct_inputs(self):
        """Ca xuyên suốt thứ hai — năm đầu vào đôi một khác nhau, kết quả không trùng."""
        steps = {}
        a = self._obj('E2E2A')
        b = self._obj('E2E2B')
        steps['opening'] = 110_000.0
        self._source_move(230_000, object=a)
        steps['direct'] = 230_000.0
        self._config([(a, 1), (b, 1)])
        self._source_move(70_000)
        run = self._run(name='E2E2-PB')
        run.action_compute()
        run.action_confirm()
        steps['allocated'] = run.amount_allocated
        period = self._period([a, b], opening_wip=steps['opening'])
        period.action_receive_allocation(result_ids=run.result_ids.ids)
        steps['received'] = sum(run.result_ids.mapped('amount_received'))
        self._source_move(-40_000, object=a)
        steps['reduction'] = 40_000.0
        sheet = self._closing_confirm(period, {a: 20_000.0, b: 15_000.0})
        steps['closing'] = sheet.total_confirmed()
        inputs = [
            steps['opening'], steps['direct'], steps['allocated'],
            steps['reduction'], steps['closing'],
        ]
        self.assertEqual(len(set(inputs)), 5, inputs)
        period.action_compute_costing()
        ver = period.current_result_id
        expected = (
            steps['opening'] + steps['direct'] + steps['allocated']
            - steps['reduction'] - steps['closing']
        )
        steps['total'] = ver.total_cost
        self.assertEqual(ver.total_cost, expected)
        self.assertNotIn(ver.total_cost, inputs)
        period.action_submit_approval()
        period.action_approve()
        period.action_post_costing()
        self.assertEqual(period.state, 'posted')
        line_155 = period.posting_move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_155,
        )
        self.assertEqual(line_155.debit, expected)
        action_s18 = period.action_open_s18()
        self.assertEqual(action_s18['res_id'], ver.id)
        self.env['ir.config_parameter'].sudo().set_param(
            'connecta_vas.w12_3_e2e2_steps', str(steps),
        )

    def test_approve_permission_group(self):
        a = self._obj('AP1')
        self._source_move(50, object=a)
        period = self._period([a])
        self._closing_confirm(period, {a: 0})
        period.action_compute_costing()
        period.action_submit_approval()
        User = self.env['res.users'].with_context(no_reset_password=True)
        # Cấp ACL tối thiểu để gọi được method (kiểm quyền nằm trong action_approve)
        for model_name in self.env.registry:
            if not model_name.startswith('vas.'):
                continue
            self.env['ir.model.access'].create({
                'name': 'w12.tmp.%s' % model_name.replace('.', '_'),
                'model_id': self.env['ir.model']._get(model_name).id,
                'group_id': self.env.ref('base.group_user').id,
                'perm_read': True,
                'perm_write': True,
                'perm_create': True,
                'perm_unlink': False,
            })
        # Fingerprint có thể đọc stock/product
        for model_name in ('product.product', 'stock.move', 'res.company'):
            self.env['ir.model.access'].create({
                'name': 'w12.tmp.%s' % model_name.replace('.', '_'),
                'model_id': self.env['ir.model']._get(model_name).id,
                'group_id': self.env.ref('base.group_user').id,
                'perm_read': True,
                'perm_write': False,
                'perm_create': False,
                'perm_unlink': False,
            })
        plain = User.create({
            'name': 'W12 No Approve',
            'login': 'w12_no_approve_%s' % a.id,
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            period.with_user(plain).action_approve()
        approver = User.create({
            'name': 'W12 Approver',
            'login': 'w12_approver_%s' % a.id,
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('connecta_vas.group_vas_costing_approver').id,
            ])],
        })
        period.with_user(approver).action_approve()
        self.assertEqual(period.state, 'approved')

    def test_unvalued_stock_blocks_compute(self):
        """Điều kiện 1: phiếu nhập TP theo bảng khai kho chưa định giá → chặn tính."""
        product = self.env['product.product'].create({
            'name': 'W12 FG unvalued',
            'is_storable': True,
            'uom_id': self.env.ref('uom.product_uom_unit').id,
            'standard_price': 0.0,
        })
        obj = self.env['vas.cost.object'].create({
            'code': 'FGUV', 'name': 'FGUV', 'object_type': 'product',
            'company_id': self.company.id,
            'wip_account_id': self.acc_154.id,
            'source_model': 'product.product',
            'source_res_id': product.id,
        })
        wh = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        if not wh or not wh.lot_stock_id:
            self.skipTest('Thiếu kho / khu vực tồn')
        pt = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', wh.id),
        ], limit=1)
        if not pt:
            self.skipTest('Thiếu loại phiếu kho')
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
        cfg = self.env['vas.costing.warehouse.config'].search([
            ('company_id', '=', self.company.id),
            ('warehouse_id', '=', wh.id),
        ], limit=1)
        if not cfg:
            cfg = self.env['vas.costing.warehouse.config'].create({
                'company_id': self.company.id,
                'warehouse_id': wh.id,
                'step_mode': 'one',
                'fg_picking_type_id': pt.id,
                'fg_location_id': wh.lot_stock_id.id,
            })
        # Nhận diện theo bảng khai (picking type / khu vực TP) — không đoán production→internal
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': product.uom_id.id,
            'location_id': src_loc.id,
            'location_dest_id': cfg.fg_location_id.id,
            'picking_type_id': cfg.fg_picking_type_id.id,
            'company_id': self.company.id,
            'date': '2099-03-15 10:00:00',
        })
        self.env.cr.execute(
            "UPDATE stock_move SET state='done', quantity=1, value=0, date=%s "
            "WHERE id=%s",
            ('2099-03-15 10:00:00', move.id),
        )
        move.invalidate_recordset()
        PV = self.env.get('product.value')
        if PV is not None and 'move_id' in PV._fields:
            PV.search([('move_id', '=', move.id)]).unlink()
        self.assertTrue(
            self.env['vas.costing.period']._is_stock_move_unvalued(move),
        )
        period = self._period([obj])
        found = period._related_stock_moves_for_costing()
        self.assertIn(move.id, found.ids)
        self._closing_confirm(period, {obj: 0})
        with self.assertRaises(UserError) as err:
            period.action_compute_costing()
        self.assertIn('định giá', str(err.exception).lower())

    def test_criterion_warning_real(self):
        """Điều kiện 4: tiêu thức không có nguồn số → cảnh báo, vẫn tính được."""
        a = self._obj('CW1')
        self.env['vas.allocation.config'].create({
            'company_id': self.company.id, 'cost_item_id': self.cpc.id,
            'scope_type': 'company', 'criterion': 'output_qty',
            'sequence': 1, 'date_from': '2099-03-01', 'date_to': '2099-03-31',
        })
        self._source_move(10, object=a)
        period = self._period([a])
        self._closing_confirm(period, {a: 0})
        period.action_compute_costing()
        self.assertTrue(period.compute_warnings)
        self.assertIn('tiêu thức', period.compute_warnings.lower())
        self.assertEqual(period.state, 'computed')
