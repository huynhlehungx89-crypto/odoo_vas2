# -*- coding: utf-8 -*-
"""W10 chặng 2 — phiếu kết chuyển lớp A (kqkd + year_start)."""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w10')
class TestW10ClosingEntry(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        if not cls.company.vas_regime_id:
            cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2090-01-01'
        cls.company.fiscalyear_last_day = 31
        cls.company.fiscalyear_last_month = '12'
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2090-06-15'),
            ('date_to', '>=', '2090-06-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W10E-2090',
                'date_from': '2090-01-01',
                'date_to': '2090-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.fy = fy
        for month, start, end in (
            (6, '2090-06-01', '2090-06-30'),
            (12, '2090-12-01', '2090-12-31'),
            (1, '2091-01-01', '2091-01-31'),
        ):
            period = cls.env['vas.period'].search([
                ('fiscalyear_id.company_id', '=', cls.company.id),
                ('date_start', '=', start),
            ], limit=1)
            if not period:
                # 2091 cần FY riêng
                fy_for = fy
                if start.startswith('2091'):
                    fy_for = cls.env['vas.fiscalyear'].search([
                        ('company_id', '=', cls.company.id),
                        ('date_from', '=', '2091-01-01'),
                    ], limit=1)
                    if not fy_for:
                        fy_for = cls.env['vas.fiscalyear'].create({
                            'name': 'W10E-2091',
                            'date_from': '2091-01-01',
                            'date_to': '2091-12-31',
                            'state': 'open',
                            'company_id': cls.company.id,
                        })
                period = cls.env['vas.period'].create({
                    'name': '%02d/%s' % (month, start[:4]),
                    'date_start': start,
                    'date_end': end,
                    'fiscalyear_id': fy_for.id,
                    'state': 'open',
                })
            if month == 6:
                cls.period_jun = period
            elif month == 12:
                cls.period_dec = period
            else:
                cls.period_jan91 = period

        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id),
            ('code', '=', 'KC'),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['vas.journal'].search([
                ('company_id', '=', cls.company.id),
            ], limit=1)
        cls.Entry = cls.env['vas.closing.entry']
        cls.Rule = cls.env['vas.closing.rule']

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post_pair(self, day, debit_acc, credit_acc, amount, name='W10E'):
        move = self.env['vas.move'].create({
            'date': day,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'ref': name,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_acc.id,
                    'name': name,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': credit_acc.id,
                    'name': name,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _make_entry(self, date_from, date_to, **kwargs):
        vals = {
            'company_id': self.company.id,
            'date_from': date_from,
            'date_to': date_to,
            'run_kqkd': True,
            'run_year_start': False,
            'run_fx': False,
        }
        vals.update(kwargs)
        return self.Entry.create(vals)

    def _line_pairs(self, entry):
        """[(debit_code, credit_code, amount), ...] sorted by sequence."""
        rows = []
        for line in entry.line_ids.sorted(lambda l: (l.sequence, l.id)):
            if line.excluded:
                continue
            rows.append((
                line.account_debit_id.code,
                line.account_credit_id.code,
                line.amount,
            ))
        return rows

    def _has_pair(self, entry, debit, credit):
        return any(
            d == debit and c == credit
            for d, c, _a in self._line_pairs(entry)
        )

    def _amount_pair(self, entry, debit, credit):
        for d, c, a in self._line_pairs(entry):
            if d == debit and c == credit:
                return a
        return None

    def _seed_profit_june(self):
        """DT 1tr − GV 400k = lãi 600k; thêm 515/711/chi phí nhỏ để đủ dòng."""
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 1_000_000, 'DT')
        self._post_pair('2090-06-11', self._acc('111'), self._acc('515'), 50_000, 'DTTC')
        self._post_pair('2090-06-12', self._acc('111'), self._acc('711'), 20_000, 'TN')
        self._post_pair('2090-06-13', self._acc('632'), self._acc('156'), 400_000, 'GV')
        self._post_pair('2090-06-14', self._acc('635'), self._acc('111'), 10_000, 'CPtc')
        self._post_pair('2090-06-15', self._acc('6421'), self._acc('111'), 15_000, 'BH')
        self._post_pair('2090-06-16', self._acc('6422'), self._acc('111'), 25_000, 'QL')
        self._post_pair('2090-06-17', self._acc('811'), self._acc('111'), 5_000, 'CPk')
        # Lãi trước thuế = 1_000k+50+20 − 400−10−15−25−5 = 615_000

    # ----- 1 mid-year -----

    def test_01_mid_year_kqkd_no_821(self):
        self._seed_profit_june()
        entry = self._make_entry('2090-06-01', '2090-06-30')
        self.assertFalse(entry.is_year_end)
        self.assertTrue(entry.warning_html)
        entry.action_fetch_data()
        pairs = self._line_pairs(entry)
        self.assertTrue(self._has_pair(entry, '511', '911'))
        self.assertTrue(self._has_pair(entry, '515', '911'))
        self.assertTrue(self._has_pair(entry, '711', '911'))
        self.assertTrue(self._has_pair(entry, '911', '632'))
        self.assertTrue(self._has_pair(entry, '911', '635'))
        self.assertTrue(self._has_pair(entry, '911', '6421'))
        self.assertTrue(self._has_pair(entry, '911', '6422'))
        self.assertTrue(self._has_pair(entry, '911', '811'))
        self.assertTrue(self._has_pair(entry, '911', '4212'))
        self.assertFalse(any(d == '821' or c == '821' for d, c, _ in pairs))
        self.assertFalse(any(d == '911' and c == '821' for d, c, _ in pairs))
        self.assertFalse(any(d == '821' and c == '911' for d, c, _ in pairs))

    # ----- 2 year-end 821 before 4212 -----

    def test_02_year_end_has_821_before_4212(self):
        self._post_pair('2090-12-10', self._acc('111'), self._acc('511'), 500_000, 'DT12')
        self._post_pair('2090-12-15', self._acc('821'), self._acc('3334'), 50_000, 'TNDN')
        entry = self._make_entry('2090-12-01', '2090-12-31')
        self.assertTrue(entry.is_year_end)
        self.assertFalse(entry.warning_html)
        entry.action_fetch_data()
        seq_821 = min(
            (l.sequence for l in entry.line_ids
             if '821' in (l.account_debit_id.code, l.account_credit_id.code)),
            default=None,
        )
        seq_4212 = min(
            (l.sequence for l in entry.line_ids
             if l.account_debit_id.code == '911' and l.account_credit_id.code == '4212'
             or l.account_debit_id.code == '4212' and l.account_credit_id.code == '911'),
            default=None,
        )
        self.assertIsNotNone(seq_821)
        self.assertIsNotNone(seq_4212)
        self.assertLess(seq_821, seq_4212)
        self.assertTrue(
            self._has_pair(entry, '911', '821') or self._has_pair(entry, '821', '911')
        )

    # ----- 3 profit / loss direction -----

    def test_03_profit_and_loss_direction(self):
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 800_000, 'DT+')
        self._post_pair('2090-06-11', self._acc('632'), self._acc('156'), 200_000, 'GV+')
        e_profit = self._make_entry('2090-06-01', '2090-06-30')
        e_profit.action_fetch_data()
        self.assertTrue(self._has_pair(e_profit, '911', '4212'))
        self.assertEqual(
            float_compare(self._amount_pair(e_profit, '911', '4212'), 600_000.0, 2),
            0,
        )

        self._post_pair('2090-06-20', self._acc('632'), self._acc('156'), 900_000, 'GV-')
        # Net: 800 − 200 − 900 = −300k lỗ (cộng thêm trên cùng khoảng)
        e_loss = self._make_entry('2090-06-01', '2090-06-30')
        e_loss.action_fetch_data()
        self.assertTrue(self._has_pair(e_loss, '4212', '911'))
        self.assertEqual(
            float_compare(self._amount_pair(e_loss, '4212', '911'), 300_000.0, 2),
            0,
        )

    # ----- 4 mixed 511 → one net line -----

    def test_04_511_mixed_one_net_line(self):
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 1_000_000, 'DT')
        self._post_pair('2090-06-12', self._acc('511'), self._acc('111'), 100_000, 'Giam')
        entry = self._make_entry('2090-06-01', '2090-06-30')
        entry.action_fetch_data()
        lines_511 = entry.line_ids.filtered(
            lambda l: l.account_debit_id.code == '511' or l.account_credit_id.code == '511'
        )
        self.assertEqual(len(lines_511), 1)
        self.assertEqual(lines_511.account_debit_id.code, '511')
        self.assertEqual(lines_511.account_credit_id.code, '911')
        self.assertEqual(float_compare(lines_511.amount, 900_000.0, 2), 0)

    # ----- 5–6 date_from chain + reverse -----

    def test_05_date_from_second_is_prior_to_plus_one(self):
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 100_000, 'DT')
        e1 = self._make_entry('2090-06-01', '2090-06-30')
        e1.action_fetch_data()
        e1.action_post()
        suggested = self.Entry._suggest_date_from(self.company, fields.Date.to_date('2090-07-31'))
        self.assertEqual(suggested, fields.Date.to_date('2090-07-01'))

    def test_06_reverse_first_resets_date_from(self):
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 100_000, 'DT')
        e1 = self._make_entry('2090-06-01', '2090-06-30')
        e1.action_fetch_data()
        e1.action_post()
        e1.action_reverse_entry()
        self.assertEqual(e1.state, 'cancelled')
        suggested = self.Entry._suggest_date_from(self.company, fields.Date.to_date('2090-06-30'))
        self.assertEqual(suggested, fields.Date.to_date('2090-01-01'))

    # ----- 7 overlap block -----

    def test_07_overlap_blocked_until_reverse(self):
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 100_000, 'DT')
        e1 = self._make_entry('2090-06-01', '2090-06-30')
        e1.action_fetch_data()
        e1.action_post()
        e2 = self._make_entry('2090-06-15', '2090-06-30')
        e2.action_fetch_data()
        with self.assertRaises(UserError) as err:
            e2.action_post()
        msg = err.exception.args[0]
        self.assertIn(e1.name, msg)
        self.assertIn('Đảo', msg)

    # ----- 8 reverse cluster delta -----

    def test_08_reverse_cluster_no_orphan_delta(self):
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 200_000, 'DT')
        entry = self._make_entry('2090-06-01', '2090-06-30')
        entry.action_fetch_data()
        entry.action_post()
        Move = self.env['vas.move']
        Line = self.env['vas.move.line']
        moves_before = Move.search_count([('company_id', '=', self.company.id)])
        lines_before = Line.search_count([('company_id', '=', self.company.id)])
        batch = entry._batch_active_moves()
        n_moves = len(batch)
        n_lines = sum(len(m.line_ids) for m in batch)
        sample_name = batch[:1].name
        entry.action_reverse_entry()
        # Đảo thành công: +N move đảo (đủ cả lô) + cùng số dòng; không orphan draft
        self.assertEqual(
            Move.search_count([('company_id', '=', self.company.id)]),
            moves_before + n_moves,
        )
        self.assertEqual(
            Line.search_count([('company_id', '=', self.company.id)]),
            lines_before + n_lines,
        )
        orphans = Move.search([
            ('company_id', '=', self.company.id),
            ('state', '=', 'draft'),
            ('is_reversal', '=', True),
            ('ref', 'ilike', sample_name),
        ])
        self.assertFalse(orphans)
        self.assertEqual(entry.state, 'cancelled')

    # ----- 9 closed period -----

    def test_09_closed_period_blocks_fetch(self):
        self.period_jun.with_context(vas_skip_asset_lock_check=True).write({
            'state': 'closed',
        })
        entry = self._make_entry('2090-06-01', '2090-06-30')
        with self.assertRaises(UserError) as err:
            entry.action_fetch_data()
        self.assertIn('khóa', err.exception.args[0].lower())
        self.period_jun.with_context(vas_skip_asset_lock_check=True).write({
            'state': 'open',
        })

    # ----- 10 pending asset -----

    def test_10_pending_asset_blocks_fetch(self):
        # FY phủ lịch ngắn
        asset = self.env['vas.asset'].create({
            'code': 'W10E-AST',
            'name': 'TS chặn KC',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'prepaid',
            'asset_kind': 'prepaid_service',
            'original_value': 1_200_000,
            'date_start': date(2090, 6, 1),
            'method': 'straight_line',
            'duration_months': 2,
            'prorata': False,
            'account_gross_id': self._acc('242').id,
            'account_accum_id': self._acc('242').id,
            'account_expense_id': self._acc('6422').id,
            'journal_id': self.journal.id,
            'source_mode': 'manual',
        })
        asset.action_confirm()
        planned = asset.line_ids.filtered(lambda l: l.state == 'planned')
        self.assertTrue(planned)
        entry = self._make_entry('2090-06-01', '2090-06-30')
        with self.assertRaises(UserError) as err:
            entry.action_fetch_data()
        msg = err.exception.args[0].lower()
        self.assertTrue(
            'khấu hao' in msg or 'phân bổ' in msg or 'chưa ghi' in msg,
            msg,
        )
        # Dọn nhẹ (TransactionCase rollback vẫn đủ; tránh để state invalid)
        planned.write({'state': 'skipped'})
        asset.action_cancel()

    # ----- 11 zero amount no empty line -----

    def test_11_zero_amount_skips_line(self):
        # Chỉ có DT 511 — không phát sinh 515 → không dòng 515
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 50_000, 'DT')
        entry = self._make_entry('2090-06-01', '2090-06-30')
        entry.action_fetch_data()
        self.assertFalse(self._has_pair(entry, '515', '911'))
        self.assertFalse(self._has_pair(entry, '711', '911'))
        self.assertTrue(self._has_pair(entry, '511', '911'))

    # ----- 12 P&L none accounts zero after close (CRITICAL) -----

    def test_12_pnl_none_balances_cleared(self):
        """QUAN TRỌNG NHẤT W10: sau KC lớp A, TK P&L ending_balance_policy=none về 0."""
        self._seed_profit_june()
        entry = self._make_entry('2090-06-01', '2090-06-30')
        entry.action_fetch_data()
        entry.action_post()
        # Mọi TK none thuộc P&L đã có PS trong khoảng + 911 phải về 0
        pnl_none = self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id),
            ('ending_balance_policy', '=', 'none'),
            ('account_type', 'in', ('income', 'expense', 'equity')),
            ('code', 'in', (
                '511', '515', '711', '632', '635', '6421', '6422', '811', '911',
            )),
        ])
        self.assertTrue(pnl_none)
        for acc in pnl_none:
            amount, side = self.Rule.compute_closing_amount(
                acc, self.company, '2090-06-01', '2090-06-30', 'both',
            )
            self.assertFalse(
                side,
                'TK %s còn số dư sau KC: amount=%s side=%s' % (acc.code, amount, side),
            )
            self.assertTrue(float_is_zero(amount, precision_digits=2), acc.code)

    # ----- 13 year_start 4212→4211 -----

    def test_13_year_start_4212_to_4211(self):
        # Dư Có 4212
        self._post_pair('2091-01-05', self._acc('111'), self._acc('4212'), 70_000, 'LN')
        e_credit = self._make_entry(
            '2091-01-01', '2091-01-31',
            run_kqkd=False, run_year_start=True,
        )
        e_credit.action_fetch_data()
        self.assertTrue(self._has_pair(e_credit, '4212', '4211'))
        self.assertEqual(
            float_compare(self._amount_pair(e_credit, '4212', '4211'), 70_000.0, 2),
            0,
        )

        # Dư Nợ 4212 (lỗ)
        self._post_pair('2091-01-10', self._acc('4212'), self._acc('111'), 40_000, 'LO')
        # Net 4212: Có 70k − Nợ 40k = dư Có 30k vẫn
        # Thêm lỗ lớn hơn
        self._post_pair('2091-01-12', self._acc('4212'), self._acc('111'), 100_000, 'LO2')
        # Net = 70 − 40 − 100 = −70 dư Nợ
        e_debit = self._make_entry(
            '2091-01-01', '2091-01-31',
            run_kqkd=False, run_year_start=True,
        )
        e_debit.action_fetch_data()
        self.assertTrue(self._has_pair(e_debit, '4211', '4212'))
        self.assertEqual(
            float_compare(self._amount_pair(e_debit, '4211', '4212'), 70_000.0, 2),
            0,
        )

    def test_14_fx_group_not_supported(self):
        """Giữ tương thích: chỉ bật fx không còn báo «chưa hỗ trợ» — bỏ qua ở chặng 3."""
        # Có thể không có số dư NT → phiếu ready với 0 dòng FX vẫn OK nếu chỉ fx
        entry = self._make_entry(
            '2090-06-01', '2090-06-30',
            run_kqkd=False, run_fx=True,
        )
        # Không có tỷ giá/ngoại tệ → fetch không nổ vì không có nhóm FC
        entry.action_fetch_data()
        self.assertEqual(entry.state, 'ready')

    # ----- Lô 1 Nợ–1 Có (thay QĐ #6) -----

    def _make_prepaid_june(self):
        asset = self.env['vas.asset'].create({
            'code': 'W10E-PP',
            'name': 'PP batch test',
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'asset_type': 'prepaid',
            'asset_kind': 'prepaid_service',
            'original_value': 1_200_000,
            'date_start': date(2090, 6, 1),
            'method': 'straight_line',
            'duration_months': 2,
            'prorata': False,
            'account_gross_id': self._acc('242').id,
            'account_accum_id': self._acc('242').id,
            'account_expense_id': self._acc('6422').id,
            'journal_id': self.journal.id,
            'source_mode': 'manual',
        })
        asset.action_confirm()
        return asset

    def test_15_batch_no_account_both_sides(self):
        """Sau ghi sổ: không chứng từ nào có cùng TK ở cả hai vế (911 và 6422)."""
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 500_000, 'DT')
        self._post_pair('2090-06-11', self._acc('6422'), self._acc('111'), 80_000, 'CP')
        self._make_prepaid_june()
        entry = self._make_entry(
            '2090-06-01', '2090-06-30',
            run_kqkd=True, run_prepaid=True,
        )
        entry.action_fetch_data()
        entry.action_post()
        batch = entry._batch_active_moves()
        self.assertGreaterEqual(len(batch), 2)
        for move in batch:
            self.assertEqual(
                len(move.line_ids), 2,
                'Mỗi chứng từ lô phải đúng 1 Nợ + 1 Có: %s' % move.name,
            )
            by_acc = {}
            for line in move.line_ids:
                code = line.account_id.code
                by_acc.setdefault(code, [0.0, 0.0])
                by_acc[code][0] += line.debit
                by_acc[code][1] += line.credit
            for code, (dr, cr) in by_acc.items():
                self.assertFalse(
                    dr > 0.0001 and cr > 0.0001,
                    'TK %s đứng cả hai vế trên %s' % (code, move.name),
                )
            # Nhấn mạnh 911 / 6422
            for code in ('911', '6422'):
                if code in by_acc:
                    dr, cr = by_acc[code]
                    self.assertFalse(dr > 0.0001 and cr > 0.0001)

    def test_16_ledger_911_and_6422_after_close(self):
        """Sổ chi tiết 911 và 6422 mở được sau KC — có TK đối ứng, không raise."""
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 500_000, 'DT')
        self._post_pair('2090-06-11', self._acc('6422'), self._acc('111'), 80_000, 'CP')
        self._make_prepaid_june()
        entry = self._make_entry(
            '2090-06-01', '2090-06-30',
            run_kqkd=True, run_prepaid=True,
        )
        entry.action_fetch_data()
        entry.action_post()
        Led = self.env['vas.account.ledger.wizard']
        for code in ('911', '6422'):
            wiz = Led.create({
                'company_id': self.company.id,
                'account_id': self._acc(code).id,
                'period_from_id': self.period_jun.id,
                'period_to_id': self.period_jun.id,
                'hide_reversed': True,
            })
            wiz.action_compute()
            move_rows = wiz.line_ids.filtered(lambda l: l.row_type == 'move')
            self.assertTrue(move_rows, 'Sổ %s không có dòng phát sinh' % code)
            self.assertTrue(
                all(r.counterpart_code for r in move_rows),
                'Sổ %s thiếu TK đối ứng: %s' % (
                    code, move_rows.mapped('counterpart_code'),
                ),
            )

    def test_17_reverse_entry_reverses_entire_batch(self):
        """Đảo phiếu → mọi chứng từ gốc trong lô đều reversed; không đảo lẻ."""
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 300_000, 'DT')
        self._post_pair('2090-06-12', self._acc('632'), self._acc('156'), 100_000, 'GV')
        entry = self._make_entry('2090-06-01', '2090-06-30')
        entry.action_fetch_data()
        entry.action_post()
        batch = entry._batch_active_moves()
        self.assertGreaterEqual(len(batch), 2)
        sample = batch[:1]
        with self.assertRaises(UserError) as err:
            sample.action_reverse()
        self.assertIn('lô kết chuyển', err.exception.args[0].lower())
        entry.action_reverse_entry()
        self.assertEqual(entry.state, 'cancelled')
        for move in batch:
            self.assertEqual(move.state, 'reversed')
            self.assertTrue(move.reversal_move_id)
            self.assertEqual(move.reversal_move_id.state, 'posted')
            self.assertTrue(move.reversal_move_id.is_reversal)
        self.assertFalse(entry._batch_active_moves())

    def _ps_closing_pair(self, entry, debit_code, credit_code):
        """Tổng amount các dòng đề xuất (hoặc move lô) đúng cặp Nợ–Có."""
        lines = entry.line_ids.filtered(
            lambda l: (
                not l.excluded
                and l.account_debit_id.code == debit_code
                and l.account_credit_id.code == credit_code
            )
        )
        return float_round(sum(lines.mapped('amount')), precision_digits=2)

    def test_18_reverse_reclose_no_double_amounts(self):
        """Hồi quy: KC lần 1 → đảo trọn lô → lấy dữ liệu + ghi sổ lại = đúng lần 1.

        Bug cũ: compute chỉ lọc state=posted → giữ bản đảo → 911/511 gấp đôi.
        """
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 720_000, 'DT511')
        self._post_pair('2090-06-11', self._acc('111'), self._acc('5111'), 280_000, 'DT5111')
        e1 = self._make_entry('2090-06-01', '2090-06-30')
        e1.action_fetch_data()
        amt_511_1 = self._ps_closing_pair(e1, '511', '911')
        amt_5111_1 = self._ps_closing_pair(e1, '5111', '911')
        amt_911_cr_1 = float_round(amt_511_1 + amt_5111_1, precision_digits=2)
        self.assertEqual(float_compare(amt_511_1, 720_000.0, 2), 0)
        self.assertEqual(float_compare(amt_5111_1, 280_000.0, 2), 0)
        e1.action_post()
        # PS trên lô đã ghi (911 bên Có từ các cặp DT)
        batch1 = e1._batch_active_moves()
        posted_911_cr = sum(
            l.credit for m in batch1 for l in m.line_ids
            if l.account_id.code == '911'
        )
        self.assertEqual(float_compare(posted_911_cr, amt_911_cr_1, 2), 0)

        e1.action_reverse_entry()
        self.assertEqual(e1.state, 'cancelled')

        e2 = self._make_entry('2090-06-01', '2090-06-30')
        e2.action_fetch_data()
        amt_511_2 = self._ps_closing_pair(e2, '511', '911')
        amt_5111_2 = self._ps_closing_pair(e2, '5111', '911')
        self.assertEqual(
            float_compare(amt_511_2, amt_511_1, 2), 0,
            '511 sau đảo+lấy lại: %s ≠ lần 1 %s (gấp đôi?)' % (amt_511_2, amt_511_1),
        )
        self.assertEqual(
            float_compare(amt_5111_2, amt_5111_1, 2), 0,
            '5111 sau đảo+lấy lại: %s ≠ lần 1 %s' % (amt_5111_2, amt_5111_1),
        )
        e2.action_post()
        batch2 = e2._batch_active_moves()
        posted_911_cr_2 = sum(
            l.credit for m in batch2 for l in m.line_ids
            if l.account_id.code == '911'
        )
        self.assertEqual(
            float_compare(posted_911_cr_2, posted_911_cr, 2), 0,
            'PS Có 911 lần 2 %s ≠ lần 1 %s' % (posted_911_cr_2, posted_911_cr),
        )

    def test_19_safety_net_after_reverse_not_doubled(self):
        """Lưới an toàn P3: sau đảo lô, số dư TK orphan vẫn đúng (không gấp đôi)."""
        orphan = self.env['vas.account'].create({
            'code': '5198',
            'name': 'DT orphan reverse-reclose',
            'regime_id': self.regime.id,
            'account_type': 'income',
            'ending_balance_policy': 'none',
            'parent_id': self._acc('511').id,
        })
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 100_000, 'DT')
        self._post_pair('2090-06-11', self._acc('111'), orphan, 55_000, 'ORPH')
        e1 = self._make_entry('2090-06-01', '2090-06-30')
        e1.action_fetch_data()
        uncovered1 = {
            a.code: amt for a, amt, _s in e1._find_uncovered_pl_none_balances()
        }
        self.assertIn('5198', uncovered1)
        self.assertEqual(float_compare(uncovered1['5198'], 55_000.0, 2), 0)
        e1.action_post()
        e1.action_reverse_entry()

        e2 = self._make_entry('2090-06-01', '2090-06-30')
        e2.action_fetch_data()
        uncovered2 = {
            a.code: amt for a, amt, _s in e2._find_uncovered_pl_none_balances()
        }
        self.assertEqual(
            float_compare(uncovered2.get('5198', 0.0), 55_000.0, 2), 0,
            'orphan sau đảo: %s (kỳ vọng 55000, không 110000)' % uncovered2.get('5198'),
        )

