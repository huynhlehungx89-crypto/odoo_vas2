# -*- coding: utf-8 -*-
"""W12 Chặng 1B — gắn khoản mục vào bốn đường sinh bút toán + CPD + HM2."""
from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase


@tagged('connecta_vas', 'connecta_vas_w12_1b')
class TestW12Costing1B(TransactionCase):

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
        assert cls.acc_154, 'Thiếu TK 154'
        cls.acc_334 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '334'),
        ], limit=1)
        cls.acc_111 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '111'),
        ], limit=1)
        cls.CostItem = cls.env['vas.cost.item']
        cls._ensure_system_items()
        cls.nvltt = cls._system('NVLTT')
        cls.nctt = cls._system('NCTT')
        cls.cpc = cls._system('CPC')
        cls.cpd = cls._system('CPD')
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
                'name': 'W12-1B-2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'company_id': cls.company.id,
                'state': 'open',
            })
        cls.period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', '2099-06-15'),
            ('date_end', '>=', '2099-06-15'),
        ], limit=1)
        if not cls.period:
            cls.period = cls.env['vas.period'].create({
                'name': '06/2099',
                'date_start': '2099-06-01',
                'date_end': '2099-06-30',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })

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
            item = cls.CostItem.create({
                'code': code,
                'name': name,
                'factor_group': factor,
                'account_id': cls.acc_154.id,
                'company_id': cls.company.id,
                'is_system': True,
            })
            cls.env['ir.model.data'].create({
                'name': 'test_1b_cost_%s_%s' % (code.lower(), cls.company.id),
                'module': 'connecta_vas',
                'model': 'vas.cost.item',
                'res_id': item.id,
                'noupdate': True,
            })

    @classmethod
    def _system(cls, code):
        return cls.CostItem.search([
            ('code', '=', code),
            ('company_id', '=', cls.company.id),
        ], limit=1)

    def _post_pair(self, amount, cost_item, debit_acc=None, credit_acc=None,
                   ref='W12-1B', move_kind='manual'):
        debit_acc = debit_acc or self.acc_154
        credit_acc = credit_acc or self.acc_111
        vals = {
            'date': '2099-06-15',
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': move_kind,
            'ref': ref,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': [
                Command.create({
                    'account_id': debit_acc.id,
                    'name': ref,
                    'debit': amount,
                    'credit': 0.0,
                    'currency_id': self.company.currency_id.id,
                    'cost_item_id': cost_item.id if cost_item else False,
                }),
                Command.create({
                    'account_id': credit_acc.id,
                    'name': ref,
                    'debit': 0.0,
                    'credit': amount,
                    'currency_id': self.company.currency_id.id,
                }),
            ],
        }
        if cost_item and cost_item._is_cpd_seed():
            vals['vas_has_unclassified_cost'] = True
        move = self.env['vas.move'].create(vals)
        move.action_post()
        return move

    def _amount_by_cost_item(self, codes=None):
        domain = [
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
            ('move_id.company_id', '=', self.company.id),
            ('cost_item_id', '!=', False),
            ('debit', '>', 0),
        ]
        if codes:
            domain.append(('cost_item_id.code', 'in', list(codes)))
        lines = self.env['vas.move.line'].search(domain)
        out = {}
        for line in lines:
            code = line.cost_item_id.code
            out[code] = out.get(code, 0.0) + line.debit
        return out

    # ------------------------------------------------------------------
    # 6a — ca nghiệm thu mục 1.1
    # ------------------------------------------------------------------

    def test_6a_acceptance_split_payroll_and_four_paths(self):
        """Xuất NVL + lương (tách NCTT/CPC) + KH + tiền điện — báo số từng khoản mục."""
        # Hai bộ phận → cùng 154, khác khoản mục
        dept_sx = self.env['hr.department'].create({
            'name': 'Tổ sản xuất W12', 'company_id': self.company.id,
        })
        dept_ql = self.env['hr.department'].create({
            'name': 'Quản lý xưởng W12', 'company_id': self.company.id,
        })
        Map = self.env['vas.payroll.department.map']
        Map.create({
            'company_id': self.company.id,
            'department_id': dept_sx.id,
            'expense_account_id': self.acc_154.id,
            'cost_item_id': self.nctt.id,
        })
        Map.create({
            'company_id': self.company.id,
            'department_id': dept_ql.id,
            'expense_account_id': self.acc_154.id,
            'cost_item_id': self.cpc.id,
        })
        self.assertEqual(
            Map.resolve_cost_item(self.company, dept_sx).code, 'NCTT',
        )
        self.assertEqual(
            Map.resolve_cost_item(self.company, dept_ql).code, 'CPC',
        )

        # Lương: 20tr công nhân + 4,7tr quản lý = 24,7tr (mục 1.1)
        self._post_pair(20_000_000, self.nctt, ref='W12-LUONG-SX', move_kind='payroll')
        self._post_pair(4_700_000, self.cpc, ref='W12-LUONG-QL', move_kind='payroll')

        # Khấu hao 548.387 — thẻ tài sản gắn CPC
        acc_214 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id), ('code', '=', '2141'),
        ], limit=1) or self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id), ('code', '=', '214'),
        ], limit=1)
        asset = self.env['vas.asset'].create({
            'name': 'Máy W12-1B',
            'code': 'W12-AS-1B',
            'asset_type': 'tscd',
            'method': 'straight_line',
            'original_value': 120_000_000,
            'date_start': date(2099, 3, 15),
            'useful_life_years': 10,
            'duration_months': 120,
            'prorata': True,
            'account_gross_id': self.env['vas.account'].search([
                ('regime_id', '=', self.regime.id), ('code', '=', '2111'),
            ], limit=1).id,
            'account_accum_id': acc_214.id,
            'account_expense_id': self.acc_154.id,
            'cost_item_id': self.cpc.id,
            'journal_id': self.journal.id,
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'source_mode': 'manual',
            'state': 'running',
        })
        line = self.env['vas.asset.line'].create({
            'asset_id': asset.id,
            'period_id': self.period.id,
            'date': self.period.date_end,
            'amount': 548_387.0,
            'state': 'planned',
            'sequence': 1,
        })
        move_kh = asset._post_line(line)
        self.assertTrue(move_kh)
        kh_debit = move_kh.line_ids.filtered(lambda l: l.debit)
        self.assertEqual(kh_debit.cost_item_id, self.cpc)
        self.assertEqual(kh_debit.debit, 548_387.0)

        # Tiền điện 5tr — map mua ngoài → CPC
        cat = self.env['product.category'].create({'name': 'W12 Điện'})
        self.env['vas.account.map'].create({
            'regime_id': self.regime.id,
            'apply_to': 'category',
            'category_id': cat.id,
            'expense_account_id': self.acc_154.id,
            'cost_item_id': self.cpc.id,
            'company_id': self.company.id,
        })
        product = self.env['product.product'].create({
            'name': 'Tiền điện nhà xưởng',
            'categ_id': cat.id,
            'type': 'service',
            'company_id': self.company.id,
        })
        resolved = self.env['vas.sync']._product_cost_item(product, self.company)
        self.assertEqual(resolved, self.cpc)
        self._post_pair(5_000_000, self.cpc, ref='W12-DIEN')

        # Xuất NVL 180.000 → NVLTT cố định (không cần khai)
        Sync = self.env['vas.sync']
        rule = self.env['vas.rule'].search([
            ('code', '=', 'R14'), ('regime_id', '=', self.regime.id),
        ], limit=1)
        self.assertTrue(rule)
        rline = rule.line_ids.filtered(lambda l: l.side == 'debit')[:1]
        splits = Sync._account_splits(
            rline, self.env['stock.move'], self.company, 180_000.0,
            event_type='stock_issue_production',
        )
        self.assertEqual(len(splits), 1)
        _acc, _amt, cost = splits[0]
        self.assertEqual(cost, self.nvltt)
        self._post_pair(180_000, self.nvltt, ref='W12-NVL')

        by_code = self._amount_by_cost_item(['NVLTT', 'NCTT', 'CPC'])
        # Báo số tiền từng khoản mục (nghiệm thu)
        self.assertEqual(by_code.get('NCTT'), 20_000_000.0)
        self.assertEqual(by_code.get('NVLTT'), 180_000.0)
        # CPC = lương QL 4.7tr + KH 548.387 + điện 5tr
        self.assertEqual(by_code.get('CPC'), 4_700_000.0 + 548_387.0 + 5_000_000.0)
        # Cùng TK 154 nhưng tách được NCTT vs phần lương trong CPC
        self.assertNotEqual(by_code['NCTT'], by_code['CPC'])

    # ------------------------------------------------------------------
    # 6b — các ca còn lại
    # ------------------------------------------------------------------

    def test_posted_line_cost_item_immutable(self):
        move = self._post_pair(1000, self.nctt, ref='IMM')
        line = move.line_ids.filtered('cost_item_id')
        with self.assertRaises(UserError):
            line.write({'cost_item_id': self.cpc.id})

    def test_unlink_cost_item_used_by_line_blocked_vi(self):
        item = self.CostItem.create({
            'code': 'TMP-DEL',
            'name': 'Xóa thử',
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        self._post_pair(500, item, ref='DEL-USE')
        with self.assertRaises(UserError) as err:
            item.unlink()
        self.assertIn('dòng bút toán', str(err.exception))
        self.assertIn('TMP-DEL', str(err.exception))

    def test_new_move_rejects_aggregate_accepts_leaf(self):
        parent = self.CostItem.create({
            'code': 'PAR-A',
            'name': 'Cha A',
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        self._post_pair(100, parent, ref='HIST-A')
        self.CostItem.create({
            'code': 'PAR-A1',
            'name': 'Con A1',
            'parent_id': parent.id,
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        parent.invalidate_recordset(['is_aggregate_node', 'child_ids'])
        self.assertTrue(parent.is_aggregate_node)
        with self.assertRaises(ValidationError):
            self._post_pair(10, parent, ref='NEW-AGG')
        # lá vẫn được
        leaf = self.CostItem.create({
            'code': 'LEAF-OK',
            'name': 'Lá OK',
            'factor_group': 'labor',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        move = self._post_pair(10, leaf, ref='NEW-LEAF')
        self.assertEqual(move.state, 'posted')

    def test_rollup_no_double_count(self):
        """A=100 lịch sử; thêm A1=30, A2=20 → A = 150 (không 250/50/100)."""
        parent = self.CostItem.create({
            'code': 'ROLL-A',
            'name': 'A',
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        self._post_pair(100, parent, ref='ROLL-100')
        a1 = self.CostItem.create({
            'code': 'ROLL-A1',
            'name': 'A1',
            'parent_id': parent.id,
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        a2 = self.CostItem.create({
            'code': 'ROLL-A2',
            'name': 'A2',
            'parent_id': parent.id,
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        self._post_pair(30, a1, ref='ROLL-30')
        self._post_pair(20, a2, ref='ROLL-20')
        parent.invalidate_recordset()
        self.assertEqual(parent.get_rollup_posted_amount(), 150.0)
        self.assertTrue(parent.has_direct_history)
        self.assertEqual(parent.direct_history_line_count, 1)
        self.assertEqual(parent.direct_history_amount, 100.0)

    def test_fallback_cpd_flag_and_filter(self):
        fallbacks = []
        item = self.env['vas.payroll.department.map'].resolve_cost_item(
            self.company, False, fallbacks=fallbacks,
        )
        self.assertEqual(item, self.cpd)
        self.assertTrue(fallbacks)
        flag = self.env['vas.sync']._unclassified_cost_flag_vals(fallbacks)
        self.assertTrue(flag.get('vas_has_unclassified_cost'))
        move = self._post_pair(777, self.cpd, ref='CPD-FLAG')
        self.assertTrue(move.vas_has_unclassified_cost)
        found = self.env['vas.move'].search([
            ('vas_has_unclassified_cost', '=', True),
            ('id', '=', move.id),
        ])
        self.assertEqual(found, move)

    def test_period_lock_blocked_by_cpd(self):
        self._post_pair(1_234_000, self.cpd, ref='CPD-LOCK')
        with self.assertRaises(UserError) as err:
            self.period.write({'state': 'closed'})
        msg = str(err.exception)
        self.assertIn('Chưa phân loại', msg)
        self.assertIn('1', msg)  # số dòng
        self.assertIn('1.234.000', msg)

    def test_config_change_does_not_rewrite_posted(self):
        dept = self.env['hr.department'].create({
            'name': 'Dept đổi map', 'company_id': self.company.id,
        })
        mapping = self.env['vas.payroll.department.map'].create({
            'company_id': self.company.id,
            'department_id': dept.id,
            'expense_account_id': self.acc_154.id,
            'cost_item_id': self.nctt.id,
        })
        move = self._post_pair(900, self.nctt, ref='CFG-STAY', move_kind='payroll')
        line = move.line_ids.filtered('cost_item_id')
        mapping.write({'cost_item_id': self.cpc.id})
        line.invalidate_recordset()
        self.assertEqual(line.cost_item_id, self.nctt)

    def test_stock_issue_fixed_nvltt_without_config(self):
        Sync = self.env['vas.sync']
        rule = self.env['vas.rule'].search([
            ('code', '=', 'R14'), ('regime_id', '=', self.regime.id),
        ], limit=1)
        rline = rule.line_ids.filtered(lambda l: l.side == 'debit')[:1]
        _acc, _amt, cost = Sync._account_splits(
            rline, self.env['stock.move'], self.company, 180_000.0,
            event_type='stock_issue_production',
        )[0]
        self.assertEqual(cost.code, 'NVLTT')

    def test_config_rejects_aggregate_and_cpd(self):
        parent = self.CostItem.create({
            'code': 'CFG-P',
            'name': 'Cha cfg',
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        self.CostItem.create({
            'code': 'CFG-C',
            'name': 'Con cfg',
            'parent_id': parent.id,
            'factor_group': 'other',
            'account_id': self.acc_154.id,
            'company_id': self.company.id,
        })
        parent.invalidate_recordset(['is_aggregate_node', 'child_ids'])
        dept = self.env['hr.department'].create({
            'name': 'Dept bad', 'company_id': self.company.id,
        })
        with self.assertRaises(ValidationError):
            self.env['vas.payroll.department.map'].create({
                'company_id': self.company.id,
                'department_id': dept.id,
                'expense_account_id': self.acc_154.id,
                'cost_item_id': parent.id,
            })
        with self.assertRaises(ValidationError):
            self.env['vas.payroll.department.map'].create({
                'company_id': self.company.id,
                'department_id': dept.id,
                'expense_account_id': self.acc_154.id,
                'cost_item_id': self.cpd.id,
            })
