# -*- coding: utf-8 -*-
"""W12 Chặng 2 — cấu hình phân bổ, lượt, engine chia, truy vết, số học."""
from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('connecta_vas', 'connecta_vas_w12_2')
class TestW12AllocationStage2(TransactionCase):

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
        cls.acc_111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '111'),
        ], limit=1)
        assert cls.acc_154 and cls.acc_111
        cls.CostItem = cls.env['vas.cost.item']
        cls.CostObject = cls.env['vas.cost.object']
        cls._ensure_cpc()
        cls.cpc = cls.CostItem.search([
            ('code', '=', 'CPC'), ('company_id', '=', cls.company.id),
        ], limit=1)
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
            ('date_from', '<=', '2099-01-15'),
            ('date_to', '>=', '2099-01-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W12-2-2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'company_id': cls.company.id,
                'state': 'open',
            })
        cls.period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', '2099-01-15'),
            ('date_end', '>=', '2099-01-15'),
        ], limit=1)
        if not cls.period:
            cls.period = cls.env['vas.period'].create({
                'name': '01/2099',
                'date_start': '2099-01-01',
                'date_end': '2099-01-31',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })

    @classmethod
    def _ensure_cpc(cls):
        item = cls.CostItem.search([
            ('code', '=', 'CPC'), ('company_id', '=', cls.company.id),
        ], limit=1)
        if item:
            return
        item = cls.CostItem.create({
            'code': 'CPC',
            'name': 'Chi phí sản xuất chung',
            'factor_group': 'other',
            'account_id': cls.acc_154.id,
            'company_id': cls.company.id,
            'is_system': True,
        })
        cls.env['ir.model.data'].create({
            'name': 'test_w12_2_cpc_%s' % cls.company.id,
            'module': 'connecta_vas',
            'model': 'vas.cost.item',
            'res_id': item.id,
            'noupdate': True,
        })

    def _obj(self, code, name=None):
        return self.CostObject.create({
            'code': code,
            'name': name or code,
            'object_type': 'workshop',
            'company_id': self.company.id,
            'wip_account_id': self.acc_154.id,
        })

    def _config(self, factors, sequence=1, date_from='2099-01-01',
                date_to='2099-01-31', cost_item=None):
        cost_item = cost_item or self.cpc
        cfg = self.env['vas.allocation.config'].create({
            'company_id': self.company.id,
            'cost_item_id': cost_item.id,
            'scope_type': 'company',
            'criterion': 'manual_factor',
            'sequence': sequence,
            'date_from': date_from,
            'date_to': date_to,
        })
        for obj, factor in factors:
            self.env['vas.allocation.config.factor'].create({
                'config_id': cfg.id,
                'cost_object_id': obj.id,
                'factor': factor,
            })
        return cfg

    def _source_move(self, amount, date='2099-01-15', cost_item=None):
        cost_item = cost_item or self.cpc
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'ref': 'W12-2-SRC',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': [
                Command.create({
                    'account_id': self.acc_154.id,
                    'name': 'chung',
                    'debit': amount if amount > 0 else 0.0,
                    'credit': -amount if amount < 0 else 0.0,
                    'currency_id': self.company.currency_id.id,
                    'cost_item_id': cost_item.id,
                }),
                Command.create({
                    'account_id': self.acc_111.id,
                    'name': 'dt',
                    'debit': -amount if amount < 0 else 0.0,
                    'credit': amount if amount > 0 else 0.0,
                    'currency_id': self.company.currency_id.id,
                }),
            ],
        })
        # Âm nguồn: Nợ 111 / Có 154
        if amount < 0:
            move.unlink()
            move = self.env['vas.move'].create({
                'date': date,
                'journal_id': self.journal.id,
                'regime_id': self.regime.id,
                'move_kind': 'manual',
                'ref': 'W12-2-SRC-NEG',
                'company_id': self.company.id,
                'currency_id': self.company.currency_id.id,
                'line_ids': [
                    Command.create({
                        'account_id': self.acc_111.id,
                        'name': 'hoan',
                        'debit': abs(amount),
                        'credit': 0.0,
                        'currency_id': self.company.currency_id.id,
                    }),
                    Command.create({
                        'account_id': self.acc_154.id,
                        'name': 'chung',
                        'debit': 0.0,
                        'credit': abs(amount),
                        'currency_id': self.company.currency_id.id,
                        'cost_item_id': cost_item.id,
                    }),
                ],
            })
        move.action_post()
        return move

    def _run(self, **extra):
        vals = {
            'name': 'PB test',
            'company_id': self.company.id,
            'date_from': '2099-01-01',
            'date_to': '2099-01-31',
            'cost_item_id': self.cpc.id,
            'scope_type': 'company',
            'round_number': '1',
            'money_source': 'pool_154',
            'state': 'draft',
        }
        vals.update(extra)
        return self.env['vas.allocation.run'].create(vals)

    # ------------------------------------------------------------------
    # Số học
    # ------------------------------------------------------------------

    def test_split_100_three_equal(self):
        a = self._obj('A1')
        b = self._obj('B1')
        c = self._obj('C1')
        self._config([(a, 1), (b, 1), (c, 1)])
        self._source_move(100)
        run = self._run()
        run.action_compute()
        amounts = {
            r.cost_object_id.code: r.amount for r in run.result_ids
        }
        self.assertEqual(sorted(amounts.values()), [33.0, 33.0, 34.0])
        self.assertEqual(sum(amounts.values()), 100.0)
        self.assertEqual(run.amount_source, 100.0)
        self.assertEqual(run.amount_allocated, 100.0)
        self.assertEqual(run.amount_unallocated, 0.0)
        self.assertEqual(
            run.amount_allocated + run.amount_unallocated - run.amount_source, 0.0,
        )

    def test_remainder_to_largest_fraction(self):
        # 10 / weights 2,3,5 → exact 2,3,5 — no remainder
        # 10 / 3 equal already covered; use 1000/7≈142.857
        objs = [self._obj('R%s' % i) for i in range(3)]
        self._config([(o, 1) for o in objs])
        self._source_move(10)
        run = self._run()
        run.action_compute()
        # 10/3 → 4,3,3 — đối tượng mã nhỏ nhất nhận phần dư khi frac bằng nhau
        by_code = {r.cost_object_id.code: r.amount for r in run.result_ids}
        self.assertEqual(sum(by_code.values()), 10.0)
        self.assertEqual(by_code['R0'], 4.0)  # mã nhỏ nhất khi frac bằng

    def test_tie_break_by_object_code_deterministic(self):
        z = self._obj('Z9')
        a = self._obj('A9')
        self._config([(z, 1), (a, 1)])
        self._source_move(1)
        run = self._run()
        run.action_compute()
        by_code = {r.cost_object_id.code: r.amount for r in run.result_ids}
        # 1 đồng → một đối tượng 1, một 0; mã A9 nhận vì sắp xếp code
        self.assertEqual(by_code['A9'], 1.0)
        self.assertEqual(by_code['Z9'], 0.0)

    def test_rerun_three_times_identical(self):
        objs = [self._obj('T%s' % i) for i in 'ABC']
        self._config([(o, 1) for o in objs])
        self._source_move(100)
        run = self._run()
        snapshots = []
        for _ in range(3):
            run.action_compute()
            snap = [
                (r.cost_object_id.code, r.amount, round(r.ratio, 12), r.sequence)
                for r in run.result_ids.sorted(
                    lambda r: (r.cost_object_id.code, r.cost_object_id.id),
                )
            ]
            snapshots.append(snap)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[1], snapshots[2])

    def test_negative_source_amount(self):
        objs = [self._obj('N%s' % i) for i in 'AB']
        self._config([(o, 1) for o in objs])
        self._source_move(-100)
        run = self._run()
        run.action_compute()
        self.assertEqual(run.amount_source, -100.0)
        self.assertEqual(run.amount_allocated, -100.0)
        self.assertEqual(
            run.amount_allocated + run.amount_unallocated, run.amount_source,
        )

    def test_negative_factor_blocked(self):
        obj = self._obj('NEG')
        cfg = self._config([(obj, 1)])
        with self.assertRaises(ValidationError):
            cfg.factor_ids.write({'factor': -1})

    def test_zero_factor_excluded_from_denominator(self):
        a = self._obj('Z1')
        b = self._obj('Z2')
        self._config([(a, 1), (b, 0)])
        self._source_move(50)
        run = self._run()
        run.action_compute()
        by_code = {r.cost_object_id.code: r.amount for r in run.result_ids}
        self.assertEqual(by_code.get('Z1'), 50.0)
        self.assertNotIn('Z2', by_code)

    def test_zero_denominator_full_not_success(self):
        a = self._obj('D0')
        self._config([(a, 0)])
        self._source_move(77)
        run = self._run()
        run.action_compute()
        self.assertFalse(run.compute_ok)
        self.assertEqual(run.amount_source, 77.0)
        self.assertEqual(run.amount_allocated, 0.0)
        self.assertEqual(run.amount_unallocated, 77.0)
        self.assertTrue(run.unallocated_reason)
        self.assertIn('77', run.unallocated_reason.replace('.', ''))

    def test_over_hundred_objects_exact_balance(self):
        objs = [self._obj('H%03d' % i) for i in range(120)]
        self._config([(o, 1) for o in objs])
        self._source_move(1_000_000)
        run = self._run()
        run.action_compute()
        self.assertEqual(run.amount_source, 1_000_000.0)
        self.assertEqual(run.amount_allocated, 1_000_000.0)
        self.assertEqual(run.amount_unallocated, 0.0)
        self.assertEqual(
            run.amount_allocated + run.amount_unallocated - run.amount_source, 0.0,
        )
        self.assertEqual(sum(run.result_ids.mapped('amount')), 1_000_000.0)

    # ------------------------------------------------------------------
    # Truy vết
    # ------------------------------------------------------------------

    def test_trace_source_line_sums_to_line_amount(self):
        objs = [self._obj('V%s' % i) for i in 'AB']
        self._config([(o, 1) for o in objs])
        move = self._source_move(90)
        src = move.line_ids.filtered(lambda l: l.cost_item_id)
        run = self._run()
        run.action_compute()
        traces = run.trace_ids.filtered(
            lambda t: t.source_move_line_id == src,
        )
        self.assertEqual(sum(traces.mapped('amount')), src.debit)

    def test_trace_reverse_from_object(self):
        objs = [self._obj('W%s' % i) for i in 'AB']
        self._config([(o, 1) for o in objs])
        move = self._source_move(80)
        run = self._run()
        run.action_compute()
        res_a = run.result_ids.filtered(lambda r: r.cost_object_id == objs[0])
        traces = res_a.trace_ids
        self.assertTrue(traces)
        self.assertTrue(traces.mapped('source_move_line_id'))
        self.assertIn(move.line_ids.filtered('cost_item_id'), traces.mapped('source_move_line_id'))

    # ------------------------------------------------------------------
    # Ràng buộc
    # ------------------------------------------------------------------

    def test_confirm_blocked_on_seven_key_conflict(self):
        a = self._obj('K1')
        self._config([(a, 1)])
        self._source_move(10)
        run1 = self._run(name='PB1')
        run1.action_compute()
        run1.action_confirm()
        run2 = self._run(name='PB2')  # nháp trùng khóa
        run2.action_compute()
        with self.assertRaises(UserError) as err:
            run2.action_confirm()
        self.assertIn('PB1', str(err.exception))

    def test_round_two_not_blocked_as_round_one(self):
        """Vòng 2 khác nguồn tiền + vòng → không bị khóa bảy thành phần chặn oan."""
        a = self._obj('R2A')
        self._config([(a, 1)], sequence=1)
        self._config([(a, 1)], sequence=2)
        self._source_move(100)
        run1 = self._run(name='V1', round_number='1', money_source='pool_154')
        run1.action_compute()
        run1.action_confirm()
        run2 = self._run(
            name='V2', round_number='2', money_source='prior_round',
            parent_run_id=run1.id,
        )
        run2.action_compute()
        run2.action_confirm()
        self.assertEqual(run2.state, 'confirmed')

    def test_config_overlap_blocked(self):
        a = self._obj('O1')
        self._config([(a, 1)], date_from='2099-01-01', date_to='2099-01-31')
        with self.assertRaises(ValidationError):
            self._config([(a, 1)], date_from='2099-01-15', date_to='2099-02-15')

    def test_config_parent_child_same_window_blocked(self):
        # Khai cha khi còn là lá; tạo con sau → cha thành nút tổng hợp.
        parent = self.CostItem.create({
            'code': 'PAR2',
            'name': 'Cha KM',
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        obj = self._obj('PC1')
        self.env['vas.allocation.config'].create({
            'company_id': self.company.id,
            'cost_item_id': parent.id,
            'scope_type': 'company',
            'criterion': 'manual_factor',
            'sequence': 1,
            'date_from': '2099-02-01',
            'date_to': '2099-02-28',
            'factor_ids': [Command.create({
                'cost_object_id': obj.id, 'factor': 1,
            })],
        })
        child = self.CostItem.create({
            'code': 'CH2',
            'name': 'Con KM',
            'parent_id': parent.id,
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        with self.assertRaises(ValidationError):
            self.env['vas.allocation.config'].create({
                'company_id': self.company.id,
                'cost_item_id': child.id,
                'scope_type': 'company',
                'criterion': 'manual_factor',
                'sequence': 1,
                'date_from': '2099-02-01',
                'date_to': '2099-02-28',
                'factor_ids': [Command.create({
                    'cost_object_id': obj.id, 'factor': 1,
                })],
            })

    def test_sequence_gt_2_blocked(self):
        with self.assertRaises(ValidationError):
            self.env['vas.allocation.config'].create({
                'company_id': self.company.id,
                'cost_item_id': self.cpc.id,
                'scope_type': 'company',
                'criterion': 'manual_factor',
                'sequence': 3,
                'date_from': '2099-03-01',
            })

    def test_orphan_source_blocks_compute_without_sync(self):
        """Xóa nguồn, KHÔNG sync — engine vẫn chặn (yêu cầu 7)."""
        product = self.env['product.product'].create({
            'name': 'Nguồn sẽ xóa W12-2',
        })
        obj = self.CostObject.create({
            'code': 'ORPH',
            'name': 'Mồ côi',
            'object_type': 'product',
            'company_id': self.company.id,
            'wip_account_id': self.acc_154.id,
            'ui_product_id': product.id,
        })
        self.assertEqual(obj.source_status, 'alive')
        product_id = product.id
        # Xóa thẳng nguồn; giữ trạng thái đã lưu = alive (không sync)
        self.env.cr.execute(
            'DELETE FROM product_product WHERE id = %s', (product_id,),
        )
        self.env.cr.execute(
            "UPDATE vas_cost_object SET source_status = 'alive' WHERE id = %s",
            (obj.id,),
        )
        obj.invalidate_recordset()
        self.assertEqual(obj.source_status, 'alive')
        self.assertFalse(
            self.env['product.product'].browse(product_id).exists(),
        )
        self._config([(obj, 1)])
        self._source_move(10)
        run = self._run()
        with self.assertRaises(UserError) as err:
            run.action_compute()
        self.assertIn('ORPH', str(err.exception))
        self.assertIn('mồ côi', str(err.exception).lower())

    def test_received_by_period_blocks_recompute(self):
        a = self._obj('RECV1')
        self._config([(a, 1)])
        self._source_move(20)
        run = self._run()
        run.action_compute()
        period = self.env['vas.costing.period'].create({
            'name': 'Kỳ nhận test',
            'date_from': '2099-01-01',
            'date_to': '2099-01-31',
            'method': 'simple',
            'company_id': self.company.id,
            'cost_object_ids': [Command.set([a.id])],
        })
        run.result_ids.write({'receiving_period_ids': [Command.set([period.id])]})
        with self.assertRaises(UserError) as err:
            run.action_compute()
        self.assertIn(period.display_name, str(err.exception))
